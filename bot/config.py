"""Configuração exposta (versão cripto / Revolut X).
[PDF] = valor literal do PDF; [GAP] = PDF omisso, ver GAPS.md; [RX] = Revolut X docs/tarifário."""
from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    # --- Sizing (PDF: position_sizing_engine) ---
    kelly_fraction: float = 0.25            # [PDF] Quarter-Kelly. NÃO alterar.
    max_position_fraction: float = 0.15     # [PDF] Capital Constraint Limit 15%
    overfit_alpha: float = 0.0              # [PDF] (1-alpha); valor [GAP]
    # --- Stops ---
    position_hard_stop_pct: float = 0.08    # [PDF] -8% entrada OU pico local
    atr_period: int = 14                    # [GAP]
    atr_stop_multiplier: float = 3.0        # [GAP] cripto: 3xATR (ações: 2x)
    # --- Drawdown de carteira (PDF Tabela 2, faixa Momentum 15-30%) ---
    portfolio_dd_reduce: float = 0.15       # [GAP]
    portfolio_dd_suspend: float = 0.30      # [GAP]
    reduce_size_multiplier: float = 0.5     # [GAP]
    # --- Sinal ---
    min_signal_samples: int = 30            # [GAP]
    social_unconfirmed_discount: float = 0.5  # [PDF] "penalizador severo"; valor [GAP]
    volume_confirm_ratio: float = 1.5       # [GAP]
    candle_interval_min: int = 60           # [RX] valores permitidos: 1,5,15,30,60,240,1440,...
    candle_count: int = 100                 # [GAP] >= 51 (SMA50 + 1)
    ledger_path: str = "data/signal_stats.json"   # ledger do backtest
    ledger_max_age_days: float = 7.0        # [GAP] ledger mais antigo -> INSUFFICIENT_DATA
    holdout_fraction: float = 0.4           # [GAP] último 40% do histórico = fora-da-amostra (publicado)
    max_alpha: float = 0.9                  # [GAP] teto do alpha estimado
    # --- Custos C (EV) ---
    maker_fee: float = 0.0                  # [RX] revolut.com/legal/crypto-exchange-fees: 0%
    taker_fee: float = 0.0009               # [RX] 0.09%
    slippage_est: float = 0.001             # [GAP] estimativa de slippage+spread por lado
    # --- Mercado ---
    quote_currency: str = "USD"             # [RX] pares BASE-QUOTE, ex. BTC-USD
    universe: tuple = field(default_factory=lambda: ("BTC", "ETH", "SOL"))  # bases [GAP]
    region: str | None = None               # [RX] parâmetro 'region' dos endpoints públicos (ex. EEA, UK)
    # --- LLM ---
    llm_enabled: bool = False
    llm_model: str = "grok-4.7"             # [PDF] não verificado
    llm_temperature: float = 0.1            # [PDF]
    llm_reasoning_effort: str = "xhigh"     # [PDF]
    llm_prompt_cache_key: str = "grok_quant_alpha_crypto_v1"
    # --- Circuit breakers / operação ---
    max_consecutive_errors: int = 3         # [GAP]
    max_orders_per_cycle: int = 5           # [GAP]
    max_data_staleness_s: int = 7200        # [GAP] 2 candles de 60 min
    broker: str = "paper"                   # paper | revolutx
    dry_run: bool = True
    log_dir: str = "logs"

    def __post_init__(self):
        if self.kelly_fraction != 0.25:
            raise ValueError("PDF: apenas Quarter-Kelly (0.25) é permitido")
        if not 0 < self.max_position_fraction <= 0.15:
            raise ValueError("PDF: concentração máxima 15%")
        if not 0.1 <= self.llm_temperature <= 0.2:
            raise ValueError("PDF: temperatura 0.1-0.2")
        if not 0 <= self.overfit_alpha < 1:
            raise ValueError("alpha deve estar em [0,1)")
        if self.candle_interval_min not in (1, 5, 15, 30, 60, 240, 1440, 2880, 5760, 10080, 20160, 40320):
            raise ValueError("Revolut X: intervalo de candle inválido")

    @property
    def symbols(self) -> tuple:
        return tuple(f"{b}-{self.quote_currency}" for b in self.universe)

    @property
    def transaction_cost_frac(self) -> float:
        """C da fórmula EV: ida+volta com ordens a mercado (taker) + slippage."""
        return 2 * (self.taker_fee + self.slippage_est)


def load_config() -> Config:
    env = os.environ
    uni = env.get("BOT_UNIVERSE")
    kw = dict(
        overfit_alpha=float(env.get("BOT_OVERFIT_ALPHA", 0.0)),
        broker=env.get("BOT_BROKER", "paper"),
        dry_run=env.get("BOT_DRY_RUN", "1") != "0",
        llm_enabled=env.get("BOT_LLM_ENABLED", "0") == "1",
        quote_currency=env.get("BOT_QUOTE", "USD"),
        region=env.get("BOT_REGION") or None,
    )
    if uni:
        kw["universe"] = tuple(x.strip().upper() for x in uni.split(","))
    return Config(**kw)
