"""Análise (só leitura) de todos os livros paper. Não altera nenhum livro. Usa só velas PÚBLICAS da Revolut X (throttle partilhado).
Uso: python -m desk.research.trade_analysis --report  -> desk/state/trade_analysis_<data>.md + .json"""
import json, math, os, sys, datetime as dt
import pandas as pd, numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ST = os.path.join(ROOT, "desk", "state")
LON = "Europe/London"
CACHE = os.path.join(ST, "cache", "analysis_5m")


def candles5(sym, since, until):
    from desk.scalp.feed import http_get, RX1
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{sym}_{since}_{until}.json")
    if os.path.exists(p): return pd.read_json(p)
    out, a, M5 = {}, since, 300_000
    while a <= until:
        b = min(until, a + 990 * M5)
        j = http_get(f"{RX1}/public/candles/{sym}", {"interval": 5, "since": a, "until": b + M5 - 1})
        for r in (j or {}).get("data", []):
            s = int(r["start"]); out[s] = dict(ts=s, o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"]), v=float(r["volume"]))
        a = b + M5
    df = pd.DataFrame(sorted(out.values(), key=lambda x: x["ts"]))
    df.to_json(p); return df


def adx_atr(df, n=14):
    h, l, c = df.h, df.l, df.c; pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), atr / c


def regimes(t0, t1, syms):
    feats = {}
    for s in syms:
        df = candles5(s, t0, t1)
        if df.empty: continue
        df["adx"], df["atrp"] = adx_atr(df)
        h = df.set_index(pd.to_datetime(df.ts, unit="ms")).c.resample("1h").last().dropna()
        e50 = h.ewm(span=50, adjust=False).mean(); ch24 = h.pct_change(24)
        hh = pd.DataFrame({"trend1h": np.where(h > e50, "acima EMA50 1h", "abaixo EMA50 1h"), "ch24": ch24})
        hh.index = (hh.index - pd.Timestamp(0)) // pd.Timedelta(milliseconds=1) + 3_600_000      # só disponível no fecho da hora
        feats[s] = (df[["ts", "adx", "atrp"]].copy(), hh)
    return feats


def attach(t, feats, ts_col, sym_col):
    rows = []
    for _, r in t.iterrows():
        f = feats.get(r[sym_col]); b = feats.get("BTC-USD")
        adx = atrp = np.nan; tr = mtr = None
        if f is not None:
            d = f[0][f[0].ts <= r[ts_col] - 300_000]
            if len(d): adx, atrp = d.adx.iloc[-1], d.atrp.iloc[-1]
            hh = f[1][f[1].index <= r[ts_col]]
            if len(hh): tr = hh.trend1h.iloc[-1]
        if b is not None:
            hb = b[1][b[1].index <= r[ts_col]]
            if len(hb): mtr = hb.trend1h.iloc[-1]; bch = hb.ch24.iloc[-1]
        rows.append((adx, atrp, tr, mtr, bch if b is not None and len(hb) else np.nan))
    t[["adx5m", "atr5m_pct", "trend_coin", "trend_btc", "btc_ch24"]] = pd.DataFrame(rows, index=t.index)
    t["btc24_b"] = pd.cut(t.btc_ch24, [-1, -0.02, 0, 0.02, 1], labels=["BTC 24h < -2%", "-2% a 0", "0 a +2%", "> +2%"])
    t["adx_b"] = pd.cut(t.adx5m, [0, 20, 25, 35, 200], labels=["<20", "20-25", "25-35", ">35"])
    return t


def summ(g):
    n = len(g); w = (g.pnl > 0).sum()
    gross = g.pnl.sum() + g.cost.sum()
    return pd.Series({"n": n, "win%": round(100 * w / n, 0) if n else np.nan, "R_med": round(g.r.mean(), 3), "R_tot": round(g.r.sum(), 2),
                      "R_se": round(g.r.std(ddof=1) / math.sqrt(n), 3) if n > 1 else np.nan, "pnl$": round(g.pnl.sum(), 3),
                      "bruto$": round(gross, 3), "custo$": round(g.cost.sum(), 3)})


def tbl(df, by, minn=1):
    x = df.groupby(by, observed=True).apply(summ, include_groups=False).reset_index()
    x = x[x.n >= minn]
    return x.to_markdown(index=False)


def load_scalp():
    t = pd.read_csv(os.path.join(ST, "scalp_paper", "forward", "trades.csv"))
    t["family"] = "scalp"; t["cost"] = t.fee + t.slip_cost
    t["exit_kind"] = np.where(t.reason.str.startswith("alvo"), "alvo (maker)", np.where(t.reason.str.startswith("stop"), "stop (taker)",
                     np.where(t.reason.str.startswith("tempo"), "tempo", "sinal de saída")))
    t["fill_kind"] = np.where(t.fee <= 1e-12, "maker→maker", "com taker")
    t["same_bar_stop"] = t.reason.str.contains("mesma vela")
    return t


def load_ems():
    t = pd.read_csv(os.path.join(ST, "ems_paper", "forward", "trades.csv"))
    t["family"] = "ems"; t["cost"] = t.fee + t.slip_cost
    t["exit_kind"] = np.where(t.reason.str.startswith("alvo"), "alvo (maker)", np.where(t.reason.str.startswith("stop"), "stop (taker)",
                     np.where(t.reason.str.startswith("tempo"), "tempo", "outro")))
    t["fill_kind"] = t.entry_kind
    return t


def load_d():
    j = pd.read_csv(os.path.join(ST, "exec_paper_autonomous", "exec_journal.csv"))
    e = j[j.event == "ENTRY"].set_index("pid"); x = j[j.event == "EXIT"].set_index("pid")
    rows = []
    for pid, r in x.iterrows():
        if pid not in e.index: continue
        a = e.loc[pid]; qty = float(a.qty); ent = float(a.price); ex = float(r.price)
        gross = (ex - ent) * qty; fee = 0.0009 * qty * (ent + ex)     # taker dos dois lados (paper exchange do Bot D)
        rows.append(dict(book="D_exec", symbol=pid.split("-USD")[0].replace("P-", "") + "-USD", fill_ts=int(pd.Timestamp(a.ts).value // 10**6),
                         exit_ts=int(pd.Timestamp(r.ts).value // 10**6), entry=ent, exit=ex, qty=qty, notional=ent * qty, r=float(r.r),
                         pnl=gross - fee, cost=fee, reason=r.note, exit_kind="alvo" if "TAKE" in str(r.note) else "stop"))
    t = pd.DataFrame(rows); t["family"] = "D"; t["fill_kind"] = "taker"
    open_ = [p for p in e.index if p not in x.index]
    return t, open_


def equity_last(path, cols):
    if not os.path.exists(path): return {}
    q = pd.read_csv(path); last = q.iloc[-1]
    return {c: float(last[c]) for c in cols if c in q.columns}


def main():
    today = dt.date.today().isoformat()
    S = load_scalp(); E = load_ems(); D, d_open = load_d()
    t0 = int(min(S.fill_ts.min(), E.fill_ts.min() if len(E) else 1e15)) - 3 * 86_400_000
    t1 = int(max(S.exit_ts.max(), E.exit_ts.max() if len(E) else 0))
    feats = regimes(t0, t1, ["BTC-USD", "ETH-USD", "SOL-USD"])
    S = attach(S, feats, "signal_ts", "symbol"); E = attach(E, feats, "signal_ts", "symbol")
    for t in (S, E, D):
        if not len(t): continue
        f = pd.to_datetime(t.fill_ts, unit="ms", utc=True).dt.tz_convert(LON)
        t["hora_lon"] = f.dt.hour; t["dia"] = f.dt.day_name().str[:3]
        t["hold_min"] = (t.exit_ts - t.fill_ts) / 60000
        t["hold_b"] = pd.cut(t.hold_min, [-1, 0.5, 5, 15, 60, 240, 1e9], labels=["0 (mesma vela)", "1-5", "5-15", "15-60", "60-240", ">240"])
        t["blk"] = pd.cut(t.hora_lon, [-1, 6, 12, 17, 23], labels=["00-06", "07-12", "13-17", "18-23"])
    S["vol_b"] = pd.qcut(S.atr5m_pct, 3, labels=["vol baixa", "vol média", "vol alta"])
    # macro gate snapshot (atual) e equity de A/B
    shadow = json.load(open(os.path.join(ST, "shadow_c3", "state.json")))
    AB = {k: v.get("mark", v.get("equity")) for k, v in shadow["books"].items()}
    out = dict(scalp=S, ems=E, d=D, d_open=d_open, AB=AB, shadow_created=shadow.get("created_at"))
    return out


if __name__ == "__main__" and "--report" not in sys.argv:
    o = main()
    for k in ("scalp", "ems", "d"):
        print(k, len(o[k]))


# ----------------------------------------------------------------------------------------- relatório
def md(df):
    df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
    cols = [str(c) for c in df.columns]
    f = lambda v: "" if (isinstance(v, float) and np.isnan(v)) else (f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
    return "\n".join(["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(f(v) for v in r) + " |" for r in df.itertuples(index=False)])


def G(df, by, minn=1):
    x = df.groupby(by, observed=True).apply(summ, include_groups=False)
    x = x[x.n >= minn]; x["n"] = x.n.astype(int); return x


def gross_r(t):
    cr = t.cost / t.r_unit; g = t.r + cr
    return dict(n=len(t), R=t.r.mean(), R_se=t.r.std(ddof=1) / math.sqrt(len(t)), grossR=g.mean(), grossR_se=g.std(ddof=1) / math.sqrt(len(t)), costR=cr.mean())


def report(o, path):
    S, E, D = o["scalp"], o["ems"], o["d"]
    R = pd.read_csv(os.path.join(ST, "scalp_paper", "replay", "trades.csv")); R["cost"] = R.fee + R.slip_cost
    gf, gr = gross_r(S), gross_r(R)
    W = []; w = W.append
    w(f"# Análise dos trades acumulados (paper) — {dt.date.today().isoformat()}\n")
    w("_Só leitura. Nenhum livro existente foi alterado. Horas em Londres. Regimes calculados com velas 5m PÚBLICAS da Revolut X (ADX14/ATR14 5m do próprio par no fecho anterior ao sinal; tendência = fecho 1h vs EMA50 1h; macro = variação 24 h do BTC). Gerado por `python -m desk.research.trade_analysis`._\n")
    w("## 1. Resumo honesto\n")
    w(f"- **Scalpers (6 livros, {len(S)} trades fechados em ~7,5 dias)**: média **{gf['R']:+.2f} R/trade** (erro-padrão {gf['R_se']:.2f}) — negativo com muita certeza estatística (t≈{gf['R']/gf['R_se']:.0f}). "
      f"PnL **${S.pnl.sum():+.2f}**, dos quais **${S.cost.sum():.2f} são custos** (taxa taker + slippage + spread). Antes de custos: **${(S.pnl.sum()+S.cost.sum()):+.2f}** "
      f"(= {gf['grossR']:+.2f} R/trade ± {gf['grossR_se']:.2f}) → **edge bruto ≈ zero**; o custo médio é **{gf['costR']:.2f} R por trade** porque os stops são minúsculos (mediana 0,07–0,20% do preço).")
    w(f"- O **replay histórico** (23/09–20/10, {len(R)} trades, mesmas regras) dá exatamente o mesmo quadro: {gr['R']:+.2f} R/trade, bruto {gr['grossR']:+.2f} R, custo {gr['costR']:.2f} R. Ou seja, não é azar desta semana: **a família scalp 1m/5m não tem vantagem e os custos garantem perda**.")
    if len(D):
        w(f"- **Bot D (executor, {len(D)} trades fechados desde 20/10)**: 1 ganho (VVV +3,9 R) e 16 perdas; total **{D.r.sum():+.1f} R**, ${D.pnl.sum():+.2f}. Stops cheios executados entre −1,0 e −1,6 R (pior que −1 R = slippage em altcoins pouco líquidas); média de todas as saídas por stop {D[D.exit_kind=='stop'].r.mean():+.2f} R. "
          f"Amostra pequena (erro-padrão {D.r.std(ddof=1)/math.sqrt(len(D)):.2f} R) — inconclusivo, mas nada sugere vantagem. Abertas agora: {', '.join(p.split('-USD')[0].replace('P-','') for p in o['d_open'])}.")
    ab = o["AB"]
    w(f"- **Bot A (C3, BTC+ETH diário)** e **Bot B (segurar BTC)**: sem trades fechados desde {str(o['shadow_created'])[:10]} (só as entradas de 19/10). Equity c3 ${ab.get('c3',0):.2f}, c3_raw ${ab.get('c3_raw',0):.2f}, BTC-hold ${ab.get('bh_btc',0):.2f} → são basicamente o movimento de BTC/ETH; 8 dias de uma estratégia diária não dizem nada (precisa de meses).")
    w(f"- **EMS (4 livros, desde 27/10)**: {len(E)} trades, todos saída por tempo, {E.r.sum():+.2f} R no total; custo médio ${E.cost.mean():.3f}/trade > |PnL|. Amostra demasiado pequena para qualquer conclusão.")
    w("- **Conclusão prática**: nenhum livro está perto do critério GO (≥40 trades com expectância positiva e DD < 20%). Os dados acumulados dizem sobretudo **onde NÃO há dinheiro**: trades curtos cujo stop é do tamanho do custo. Qualquer variante nova tem de ter **custo ≤ 0,2 R por trade** por construção.\n")

    w("## 2. Scalpers — por livro\n"); w(md(G(S, "book")))
    w("\n`bruto$` = PnL antes de taxas e slippage; `custo$` = taxas + slippage (inclui meio spread). R_se = erro-padrão da média de R.\n")
    t = S.copy(); t["custo_R"] = t.cost / t.r_unit
    w("### Custo em R por livro (forward vs replay)\n")
    rr = R.copy(); rr["custo_R"] = rr.cost / rr.r_unit; rr["gR"] = rr.r + rr.custo_R; t["gR"] = t.r + t.custo_R
    cmp_ = pd.DataFrame({"n_fwd": t.groupby("book").size(), "R_fwd": t.groupby("book").r.mean(), "brutoR_fwd": t.groupby("book").gR.mean(), "custoR_fwd": t.groupby("book").custo_R.mean(),
                         "stop%_mediana": 100 * t.groupby("book").stop_pct.median(),
                         "n_replay": rr.groupby("book").size(), "R_replay": rr.groupby("book").r.mean(), "brutoR_replay": rr.groupby("book").gR.mean()}).round(3)
    w(md(cmp_))
    w("\n## 3. Scalpers — por moeda\n"); w(md(G(S, "symbol")))
    w("\n## 4. Por hora de Londres (entrada)\n"); w(md(G(S, "blk"))); w("\nHora a hora:\n"); w(md(G(S, "hora_lon")))
    w("\nNota: as diferenças entre blocos (−0,46 a −0,76 R) estão dentro de ~2 erros-padrão → **ruído**, não um padrão explorável. Todas as horas são negativas.\n")
    w("## 5. Por dia da semana\n"); w(md(G(S, "dia"))); w("\nTodos os dias negativos; ~7 dias de dados = 1 observação por dia da semana → sem conclusão.\n")
    w("## 6. Maker vs taker / motivo de saída\n"); w(md(G(S, "fill_kind"))); w(""); w(md(G(S, "exit_kind")))
    w(f"\nOs únicos trades sem custo são os que saem no alvo com ordem maker. **{int(S.same_bar_stop.sum())} trades ({100*S.same_bar_stop.mean():.0f}%) foram parados na mesma vela de 1m em que entraram** (−1,0 R cada, {S[S.same_bar_stop].r.sum():.0f} R no total) → a entrada a mercado no fim de um movimento curto é apanhada pelo próprio ruído da vela.\n")
    w("### Saída por livro\n"); w(md(G(S, ["book", "exit_kind"])))
    w("\n## 7. Tempo em posição\n"); w(md(G(S, "hold_b")))
    w("\nTrades que sobrevivem >15 min ficam ~neutros (seleção pela sobrevivência — não é uma regra utilizável sozinha).\n")
    w("## 8. Regime\n### ADX14 (5m) no sinal\n"); w(md(G(S, "adx_b"))); w("\nPor livro:\n"); w(md(G(S, ["book", "adx_b"])))
    w("\nOs livros com filtro ADX (`*_adx`) não melhoraram: bb_rsi_adx −0,85 R (n=12) vs bb_rsi −0,61 R; ema_pb_adx −0,50 R (n=22) vs ema_pb −0,56 R. Diferenças = ruído.\n")
    w("### Volatilidade (ATR14 5m, tercis)\n"); w(md(G(S, "vol_b")))
    w("\n### Tendência da moeda (1h vs EMA50) e macro (BTC)\n"); w(md(G(S, "trend_coin"))); w(""); w(md(G(S, "trend_btc"))); w(""); w(md(G(S, "btc24_b")))
    w("\nCom BTC a subir >2% em 24 h os scalps de reversão foram ligeiramente piores (−0,71 R, n=43) — coerente com 'comprar fraqueza contra tendência curta', mas ainda dentro do ruído.\n")
    w("### Largura do stop (o fator que mais pesa)\n")
    for nm, tt in (("forward", S), ("replay", R)):
        tt = tt.copy(); tt["stop%"] = pd.cut(tt.stop_pct, [0, 0.001, 0.0015, 0.0025, 0.005, 1], labels=["≤0,10%", "0,10–0,15%", "0,15–0,25%", "0,25–0,50%", ">0,50%"])
        w(f"\n{nm}:\n"); w(md(G(tt, "stop%")))
    w("\nStops ≤0,10% são os piores (−0,75 R). Mesmo os mais largos continuam negativos **antes** de custos no replay → alargar o stop sozinho não cria edge; só deixa de o destruir.\n")
    if len(D):
        w("## 9. Bot D (executor) — detalhe\n")
        d = D[["symbol", "r", "pnl", "cost", "hold_min", "hora_lon", "dia", "exit_kind"]].copy(); d["hold_h"] = (d.hold_min / 60).round(1); d = d.drop(columns="hold_min")
        w(md(d.round(3))); w(""); w(md(G(D, "blk"))); w("")
        w(f"Custo (estimado, taker 0,09% nos dois lados): ${D.cost.sum():.2f} de ${D.pnl.sum():.2f} → aqui o problema não é custo, é **direção**: 16/17 stops. {int((D.hora_lon<=6).sum())} de {len(D)} entradas foram entre 00h e 06h de Londres (madrugada, livro fino), todas perdedoras; {int((~D.symbol.isin(LIQUID)).sum())} de {len(D)} em moedas fora do grupo líquido (volume ≥$10k/24h e spread ≤40 bps).\n")
    w("## 10. EMS\n"); w(md(E[["book", "symbol", "entry_kind", "r", "pnl", "cost", "reason"]].round(4))); w("\n3 trades. Nada a concluir; manter a correr.\n")
    w("## 11. Bot A / Bot B\n"); w(md(pd.DataFrame([{"livro": k, "equity_$": round(v, 2), "vs_$65": f"{100*(v/65-1):+.2f}%"} for k, v in o["AB"].items()])))
    w("\nSem trades fechados; estratégia diária — avaliar só depois de várias semanas.\n")
    w("## 12. Tamanho de amostra e ruído\n")
    w("- Scalp: 285 trades forward + 949 replay → a **perda** é estatisticamente sólida; os **cortes** (hora, dia, moeda, ADX) têm 10–100 trades cada e erros-padrão de 0,1–0,3 R → nenhum corte mostra um subgrupo positivo de forma fiável. Procurar 'a melhor hora' nestes dados seria sobreajuste.\n"
      "- Bot D: 17 trades; um único trade (+3,9 R) muda o total em 30%.\n- EMS: 3 trades. A/B: 0 trades fechados.\n"
      "- Todas as tabelas acima são **descritivas**. As variantes abaixo têm de provar-se em paper novo, com regras congeladas antes do 1.º trade.\n")
    w("## 13. Variantes NOVAS propostas (pré-registo, paper, não mexem nos livros atuais)\n")
    w("""| id proposto | regra (congelada antes do 1.º trade) | porquê (dado) | critério GO |
|---|---|---|---|
| `scalp_costgate_15m` | Sinais BB-RSI e EMA-pullback recalculados em velas **15m**; só entra se `custo_estimado (taxa+slip+½spread ida e volta) ≤ 0,2 R` ⇒ stop ≥ ~0,6%; entrada **maker** (limite no preço do sinal, válida 2 velas), alvo maker 1,5 R, time-stop 16 velas; BTC/ETH/SOL. | custo atual 0,4–0,6 R/trade come todo o PnL; bruto ≈ 0 | ≥40 trades, expectância > +0,10 R líquida, DD < 20% |
| `scalp_maker_confirm` | Mesmo sinal 1m de bb_rsi, mas **só ordem maker** 1 tick abaixo, e só se a vela seguinte não fizer novo mínimo; nunca entra a mercado | 26% dos trades parados na mesma vela; taker é sempre o lado perdedor | idem |
| `d_liquid_day` | Mesmas regras de sinal do Bot D, mas só no universo líquido (27 moedas) e só entradas 07h–22h Londres; stop executado como ordem stop-limite simulada com slippage medido | 12/17 entradas entre 00h–06h (todas perdedoras) e 15/17 fora do grupo líquido; stops cheios até −1,6 R | ≥40 trades, expectância > 0 |
| `news_v1` (já a correr) | Notícia positiva + confirmação de volume/momento na Revolut X; 2 livros (momo taker, pullback maker) | estratégia de evento, não de ruído de 1m | ≥40 trades/livro |
""")
    w("Recomendação: **não** ajustar os 6 scalpers (seria tuning de resultado); deixá-los correr como controlo até ao fim da janela e **não** os considerar para dinheiro real. Prioridade de teste: news_v1 (já ativo) → scalp_costgate_15m → d_liquid_day.\n")
    open(path, "w").write("\n".join(W))
    return path


LIQUID = {s + "-USD" for s in "AAVE ADA AERO BCH BERA BTC DOGE ENA ETH FET HBAR HYPE INJ LINK LTC ONDO PENGU PEPE QNT RAY RENDER SOL SUI TIA TRB XLM XRP".split()}

if __name__ == "__main__" and "--report" in sys.argv:
    print(report(main(), os.path.join(ST, f"trade_analysis_{dt.date.today().isoformat()}.md")))
