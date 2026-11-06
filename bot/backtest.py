"""Backtest -> ledger de estatísticas de sinal (p, avg_win, avg_loss, n) por símbolo.

Uso:  python -m bot.backtest [--symbols BTC,ETH,SOL] [--quote USD] [--max-pages N] [--refresh]

- Dados: APENAS candles públicos Revolut X (GET /api/1.0/public/candles/{symbol}), sem credenciais.
  Paginação para trás em janelas de 100 candles, 1 pedido/s (limite público dos docs), até a API
  devolver páginas vazias (fim do histórico). Cache em data/candles_<SYM>_<iv>.json.
- Regras: as MESMAS do bot ao vivo (signals.technical_state): SMA20>SMA50 com preço acima, stop ATR
  (3x por defeito) fixado na entrada, hard-stop -8% da entrada/pico local, taxa taker + slippage.
- Sem look-ahead: sinal no FECHO do candle i usando só candles <= i; entrada na ABERTURA de i+1;
  stops avaliados com o pico conhecido ANTES de cada candle; gap abaixo do stop sai na abertura.
- R: R = (saída - entrada)/entrada / risco_inicial, risco_inicial = (entrada - stop_ATR)/entrada,
  igual à definição usada pelo engine (r_l = distância ao stop ATR; b = avg_win/avg_loss).
  p/avg_win/avg_loss publicados em R BRUTO (antes de custos), porque o engine já desconta C na fórmula EV
  (EV = p*R_w - q*R_l - C). R líquido também é guardado para auditoria.
- Validação: holdout cronológico. Primeiros (1-h) = in-sample (IS), últimos h = out-of-sample (OOS).
  As regras não são otimizadas; publica-se SÓ a estatística OOS. alpha = clip(1 - EV_oos/EV_is, 0, max_alpha)
  quando EV_is > 0 (degradação IS->OOS, variante (1-alpha) do PDF).
"""
from __future__ import annotations
import argparse, json, os, time
from dataclasses import asdict, dataclass
from typing import Optional
from .config import Config, load_config
from .signals import technical_state

WARMUP = 51  # SMA50 + 1


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    stop_atr: float
    risk_frac: float
    r_gross: float
    r_net: float
    reason: str
    volume_confirmed: bool


# ---------------- dados ----------------
def fetch_history(client, symbol: str, cfg: Config, max_pages: int = 2000, cache_dir: str = "data",
                  refresh: bool = False, now_ms: Optional[int] = None, empty_stop: int = 3, log=print) -> list[dict]:
    iv_ms = cfg.candle_interval_min * 60_000
    path = os.path.join(cache_dir, f"candles_{symbol}_{cfg.candle_interval_min}.json")
    cached = {}
    if os.path.exists(path) and not refresh:
        cached = {r["start"]: r for r in json.load(open(path))}
    now_ms = now_ms or int(time.time() * 1000)
    until, empties, pages = now_ms, 0, 0
    oldest_cached = min(cached) if cached else None
    newest_cached = max(cached) if cached else None
    rows = dict(cached)
    while pages < max_pages:
        if newest_cached is not None and until - 100 * iv_ms <= newest_cached:
            until = oldest_cached       # intervalo já em cache: salta para antes do candle mais antigo
            newest_cached = None
        since = until - 100 * iv_ms
        data = client.public_candles(symbol, cfg.candle_interval_min, since, until, cfg.region)  # rate limit 1/s no cliente
        pages += 1
        if not data:
            empties += 1
            if empties >= empty_stop:
                break
        else:
            empties = 0
            for r in data:
                rows[int(r["start"])] = {"start": int(r["start"]), **{k: float(r[k]) for k in ("open", "high", "low", "close", "volume")}}
        until = since
        if pages % 25 == 0:
            log(f"  {symbol}: {pages} páginas, {len(rows)} candles")
    out = [rows[k] for k in sorted(rows) if k + iv_ms <= now_ms]  # só candles FECHADOS
    os.makedirs(cache_dir, exist_ok=True)
    json.dump(out, open(path, "w"))
    return out


# ---------------- simulação ----------------
def simulate(candles: list[dict], cfg: Config) -> list[Trade]:
    o = [c["open"] for c in candles]; h = [c["high"] for c in candles]
    l = [c["low"] for c in candles]; cl = [c["close"] for c in candles]; v = [c["volume"] for c in candles]
    cost = cfg.taker_fee + cfg.slippage_est
    trades, i, n = [], WARMUP, len(candles)
    while i < n - 1:
        active, _, volc, _, a, stop_atr = technical_state(h[:i + 1], l[:i + 1], cl[:i + 1], v[:i + 1], cfg)
        if not active:
            i += 1; continue
        j = i + 1
        entry = o[j]
        if entry <= stop_atr:
            i += 1; continue
        risk = (entry - stop_atr) / entry
        peak, exit_px, reason = entry, None, ""
        while j < n:
            level = max(stop_atr, max(entry, peak) * (1 - cfg.position_hard_stop_pct))
            why = "ATR_STOP" if stop_atr >= max(entry, peak) * (1 - cfg.position_hard_stop_pct) else "HARD_STOP_8PCT"
            if o[j] <= level and j > i + 1:
                exit_px, reason = o[j], why + "_GAP"; break
            if l[j] <= level:
                exit_px, reason = min(level, o[j]) if j > i + 1 else level, why; break
            peak = max(peak, cl[j])
            j += 1
        if exit_px is None:
            break  # posição aberta no fim dos dados: excluída (sem resultado)
        r_g = (exit_px - entry) / entry / risk
        r_n = ((exit_px * (1 - cost)) / (entry * (1 + cost)) - 1) / risk
        trades.append(Trade(candles[i + 1]["start"], candles[j]["start"], entry, exit_px, stop_atr, risk, r_g, r_n, reason, volc))
        i = j  # reavalia sinal no fecho do candle de saída
    return trades


def stats(trades: list[Trade], key: str = "r_gross") -> dict:
    rs = [getattr(t, key) for t in trades]
    wins = [r for r in rs if r > 0]; losses = [-r for r in rs if r <= 0]
    n = len(rs)
    p = len(wins) / n if n else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    return {"n": n, "wins": len(wins), "p": p, "avg_win": aw, "avg_loss": al,
            "b": (aw / al) if al > 0 else None, "ev_r": p * aw - (1 - p) * al,
            "mean_r_net": (sum(t.r_net for t in trades) / n) if n else 0.0}


def evaluate(candles: list[dict], cfg: Config) -> dict:
    trades = simulate(candles, cfg)
    if not candles:
        return {"n": 0, "wins": 0, "avg_win": 0.0, "avg_loss": 0.0, "alpha": 0.0, "candles": 0}
    split_ts = candles[int(len(candles) * (1 - cfg.holdout_fraction))]["start"]
    is_t = [t for t in trades if t.exit_ts < split_ts]          # IS: trade fechado antes do corte
    oos_t = [t for t in trades if t.entry_ts >= split_ts]       # OOS: trade aberto depois do corte
    s_is, s_oos, s_all = stats(is_t), stats(oos_t), stats(trades)
    alpha = 0.0
    if s_is["ev_r"] > 0:
        alpha = min(cfg.max_alpha, max(0.0, 1 - s_oos["ev_r"] / s_is["ev_r"]))
    return {
        # campos consumidos pelo bot (OOS apenas)
        "n": s_oos["n"], "wins": s_oos["wins"], "avg_win": s_oos["avg_win"], "avg_loss": s_oos["avg_loss"], "alpha": alpha,
        # auditoria
        "in_sample": s_is, "out_of_sample": s_oos, "full_sample": s_all,
        "net_out_of_sample": stats(oos_t, "r_net"),
        "candles": len(candles), "first_candle": candles[0]["start"], "last_candle": candles[-1]["start"],
        "split_ts": split_ts, "exit_reasons": {r: sum(t.reason == r for t in trades) for r in sorted({t.reason for t in trades})},
        "trades_oos": [asdict(t) for t in oos_t],
    }


def fingerprint(cfg: Config) -> dict:
    """Parâmetros que, se mudarem, invalidam o ledger."""
    return {k: getattr(cfg, k) for k in ("candle_interval_min", "atr_period", "atr_stop_multiplier",
            "position_hard_stop_pct", "volume_confirm_ratio", "taker_fee", "slippage_est", "quote_currency", "holdout_fraction")}


def run(cfg: Config, client=None, symbols=None, max_pages=2000, refresh=False, out_path=None, log=print) -> dict:
    from .revolutx import RevolutXClient
    client = client or RevolutXClient()
    ledger = {"generated_at": time.time(), "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "source": "Revolut X public candles", "region": cfg.region, "config": fingerprint(cfg), "symbols": {}}
    for sym in symbols or cfg.symbols:
        log(f"[{sym}] a descarregar histórico…")
        candles = fetch_history(client, sym, cfg, max_pages=max_pages, refresh=refresh,
                                cache_dir=os.path.dirname(out_path or cfg.ledger_path) or "data", log=log)
        ledger["symbols"][sym] = evaluate(candles, cfg)
    path = out_path or cfg.ledger_path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(ledger, open(path, "w"), indent=2)
    return ledger


def summary_rows(ledger: dict, cfg: Config) -> list[dict]:
    from .sizing import full_kelly
    rows = []
    for sym, s in ledger["symbols"].items():
        o = s.get("out_of_sample", {})
        p, aw, al = o.get("p", 0), o.get("avg_win", 0), o.get("avg_loss", 0)
        b = aw / al if al > 0 else None
        fk = full_kelly(p, b) if b else None
        qk = max(0.0, fk / 4) * (1 - max(cfg.overfit_alpha, s.get("alpha", 0))) if fk is not None else 0.0
        rows.append({"symbol": sym, "candles": s.get("candles"), "n_oos": o.get("n"), "p": p, "avg_win_R": aw, "avg_loss_R": al,
                     "b": b, "ev_R_gross": o.get("ev_r"), "mean_R_net": s.get("net_out_of_sample", {}).get("mean_r_net"),
                     "alpha": s.get("alpha"), "full_kelly": fk, "quarter_kelly_after_alpha": min(qk, cfg.max_position_fraction),
                     "n_in_sample": s.get("in_sample", {}).get("n"), "p_in_sample": s.get("in_sample", {}).get("p"),
                     "usable": (o.get("n") or 0) >= cfg.min_signal_samples})
    return rows


def main():
    ap = argparse.ArgumentParser(description="Backtest com candles públicos Revolut X -> data/signal_stats.json")
    ap.add_argument("--symbols", help="bases separadas por vírgula (ex. BTC,ETH,SOL)")
    ap.add_argument("--quote")
    ap.add_argument("--max-pages", type=int, default=2000)
    ap.add_argument("--refresh", action="store_true", help="ignora cache de candles")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = load_config()
    if a.quote:
        from dataclasses import replace
        cfg = replace(cfg, quote_currency=a.quote.upper())
    syms = [f"{b.strip().upper()}-{cfg.quote_currency}" for b in a.symbols.split(",")] if a.symbols else None
    ledger = run(cfg, symbols=syms, max_pages=a.max_pages, refresh=a.refresh, out_path=a.out)
    print(json.dumps(summary_rows(ledger, cfg), indent=2, default=str))


if __name__ == "__main__":
    main()
