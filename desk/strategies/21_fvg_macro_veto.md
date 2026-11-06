# 21 — 01 + veto macro (≥2 flags) (OpenBB/yfinance macro, pré-registado 2026-10-19 antes de descarregar dados macro)
- Base: spec 01 sem nenhuma alteração; overrides: macro_mode: enforce, macro_veto_flags: 2.
- Séries: ^GSPC, ^VIX, DX-Y.NYB, ^TNX (yfinance, diário); vela D usável só a partir de D+1 00:00 UTC + 1h.
- Flags: EQ_DOWN (SPX<SMA50), VOL_STRESS (VIX>25), USD_UP (DXY 20d>+2%), RATES_UP (10y 20d>+0.30pp). <3 séries → sem efeito.
- O macro só VETA novos ENTRY; nunca aumenta, nunca toca em stops/TP/saídas. Holdout 60/40. Limiares congelados decidem; sem auto-promoção.
