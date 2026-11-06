"""Versão cripto (24/7, sem horário de mercado). Ciclo: Propor -> Recuperar -> Verificar -> Simular -> Executar (PDF)."""
from __future__ import annotations
import time
from .brokers.base import Order
from .circuit import CircuitBreaker
from .logutil import audit, setup
from .risk import DrawdownMonitor, RiskMode, position_stop_hit
from .signals import compute_signal
from .sizing import InsufficientData, expected_value, size_position


class Engine:
    def __init__(self, cfg, broker, market, sentiment, stats, llm=None):
        self.cfg, self.broker, self.market, self.sentiment, self.stats, self.llm = cfg, broker, market, sentiment, stats, llm
        self.dd = DrawdownMonitor(cfg)
        self.cb = CircuitBreaker(cfg.max_consecutive_errors)
        self.log = setup(cfg.log_dir)

    def _exec(self, order: Order, price: float):
        res = self.broker.submit(order, price)
        audit(self.cfg.log_dir, {"event": "order", "order": order.__dict__, "result": res})
        return res

    def cycle(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        decisions = []
        if self.cb.tripped:
            self.log.error("CIRCUIT BREAKER ativo: %s", self.cb.reason); return decisions
        try:
            prices = {t: self.market.last_price(t) for t in set(self.cfg.symbols) | set(self.broker.positions())}
        except Exception as e:
            self.cb.record_error(f"prices: {e}"); return decisions
        equity = self.broker.equity(prices)
        mode = self.dd.update(equity)
        audit(self.cfg.log_dir, {"event": "equity", "equity": equity, "dd": self.dd.current_dd, "max_dd": self.dd.max_dd, "mode": mode,
                                 "circuit": {"tripped": self.cb.tripped, "reason": self.cb.reason, "errors": self.cb.errors}, "prices": prices})

        # 1) Stops por posição (prioridade CRÍTICA, sem narrativa)
        for t, pos in list(self.broker.positions().items()):
            px = prices[t]; pos.local_peak = max(pos.local_peak, px)
            if hasattr(self.broker, "update_peak"): self.broker.update_peak(t, px)
            atr_stop = pos.atr_stop
            why = position_stop_hit(pos.entry, pos.local_peak, px, atr_stop, self.cfg)
            if why or mode == RiskMode.SUSPEND:
                self._exec(Order(t, "SELL", pos.qty, "MARKET", reason=why or "PORTFOLIO_DD_SUSPEND"), px)
                decisions.append({"ticker": t, "action": "SELL", "reason": why or "SUSPEND"})
        if mode == RiskMode.SUSPEND:
            self.cb.trip(f"drawdown {self.dd.current_dd:.2%} >= {self.cfg.portfolio_dd_suspend:.0%}")
            audit(self.cfg.log_dir, {"event": "circuit", "tripped": True, "reason": self.cb.reason})
            return decisions

        # 2) Novas entradas
        n_orders = 0
        for t in self.cfg.symbols:
            if n_orders >= self.cfg.max_orders_per_cycle: break
            try:
                bars = self.market.bars(t)
                hist = self.stats.get(t)
                sig = compute_signal(t, bars, hist, self.sentiment.score(t), self.sentiment.macro(), self.cfg, now)
                if not sig.active:
                    decisions.append({"ticker": t, "action": "HOLD", "reason": sig.reason}); continue
                # b derivado da distância ATR (passo 3): R_l = distância ao stop em fração do preço
                r_l = (prices[t] - sig.stop_price) / prices[t]
                r_w = r_l * (sig.avg_win / sig.avg_loss)
                ev = expected_value(sig.p, r_w, r_l, self.cfg.transaction_cost_frac)
                sz = size_position(sig.p, r_w, r_l, self.cfg, self.dd.risk_multiplier(), getattr(hist, "alpha", 0.0))
                if ev <= 0 or sz.allocation <= 0:
                    decisions.append({"ticker": t, "action": "HOLD", "reason": f"EV={ev:.4f} f*={sz.full_kelly:.4f}"}); continue
                # Verificar: LLM (opcional) só pode reduzir/vetar
                alloc = sz.allocation
                if self.llm is not None:
                    d = self.llm(self.cfg, {"ticker": t, "p": sig.p, "b": sz.b, "f_star": sz.full_kelly, "quarter": sz.quarter_kelly,
                                            "atr": sig.atr, "stop": sig.stop_price, "price": prices[t]}, [])
                    ed = d["execution_directive"]
                    if ed["action_type"] != "BUY" or d["system_compliance_audit"]["drawdown_safeguard_status"] != "PASS":
                        decisions.append({"ticker": t, "action": "HOLD", "reason": "LLM veto"}); continue
                    alloc = min(alloc, ed["capital_allocation_fraction"])
                held = self.broker.positions().get(t)
                cur = (held.qty * prices[t] / equity) if held else 0.0
                add = min(alloc, self.cfg.max_position_fraction) - cur
                if add <= 0:
                    decisions.append({"ticker": t, "action": "HOLD", "reason": "já no alvo/teto 15%"}); continue
                qty = add * equity / prices[t]
                # Simular: caixa (com taxa) + incrementos/mínimos do par
                max_aff = self.broker.cash() / (prices[t] * (1 + self.cfg.taker_fee + self.cfg.slippage_est))
                qty = self.broker.quantize(t, min(qty, max_aff), prices[t])
                if qty <= 0:
                    decisions.append({"ticker": t, "action": "HOLD", "reason": "abaixo do mínimo do par/caixa"}); continue
                res = self._exec(Order(t, "BUY", qty, "MARKET", stop_price=sig.stop_price, reason=sig.reason), prices[t])
                p = self.broker.positions().get(t)
                if p and p.atr_stop is None: p.atr_stop = sig.stop_price
                n_orders += 1
                decisions.append({"ticker": t, "action": "BUY", "qty": qty, "alloc": alloc, "p": sig.p, "b": sz.b,
                                  "f_star": sz.full_kelly, "quarter_kelly": sz.quarter_kelly, "ev": ev, "result": res["status"]})
                self.cb.record_ok()
            except InsufficientData as e:
                decisions.append({"ticker": t, "action": "HOLD", "reason": f"INSUFFICIENT_DATA: {e}"})
            except Exception as e:
                self.log.exception("erro %s", t); self.cb.record_error(str(e))
        audit(self.cfg.log_dir, {"event": "cycle", "decisions": decisions, "circuit": {"tripped": self.cb.tripped, "reason": self.cb.reason, "errors": self.cb.errors}})
        return decisions
