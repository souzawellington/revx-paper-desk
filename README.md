# RevX Paper Desk

Paper-first crypto desk for people learning Revolut X. Simulated money. Public market data. No API key to begin.

**Teaching site (Portuguese by default, English toggle):** [https://revx-paper-desk.vercel.app](https://revx-paper-desk.vercel.app)

[![Paper / dry-run](https://img.shields.io/badge/mode-paper%20%2F%20dry--run-orange)](https://revx-paper-desk.vercel.app)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## Em português

O **RevX Paper Desk** é um projeto educativo independente para quem está a começar em cripto na Revolut X. O modo normal é **paper / simulado**: o programa lê candles públicos e escreve um diário de operações fictícias. Não é um produto oficial da Revolut. Não é conselho financeiro. Não levanta dinheiro e não envia ordens reais, a menos que mais tarde você mesmo configure isso, depois de entender o risco.

Para experimentar sem chave de API:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m bot --demo
```

`python -m bot` (sem `--demo`) usa os candles **públicos** da Revolut X, ainda em paper. O site de ensino:

```bash
cd web && npm install && npm run dev
```

Abre em [http://127.0.0.1:43123](http://127.0.0.1:43123).

O auditor só marca **GO** quando um livro paper cumpre, ao mesmo tempo, quatro limiares congelados: pelo menos 40 trades fechados, win rate de pelo menos 33%, expectancy de pelo menos +0.4R e drawdown máximo de no máximo 20%. O relatório de 2026-11-02 não chega lá: **34 trades, win rate 17,6%, −0,518R, drawdown máximo 4,9%, veredito NO-GO / NO_EDGE**. O Bot C está desligado. Cada número deste repositório é simulado.

---

## What this is

RevX Paper Desk is an open educational monorepo. It studies spot crypto on Revolut X with a paper desk: public candles, a simulated book, and a written audit trail.

You can read the idea in a browser, or run the Python desk on your own machine. Both paths stay on simulated results. The published sample has not earned a GO.

| Piece | Role |
|---|---|
| [`bot/`](bot/) | Paper bot. `--demo` uses synthetic prices. The default run uses public Revolut X candles and the paper broker. |
| [`desk/`](desk/) | Research desk: zones, risk notes, strategies, and the weekly auditor. Rules live in [`desk/DESK_RULES.md`](desk/DESK_RULES.md). |
| [`web/`](web/) | Next.js teaching site. Portuguese is the default. An EN control switches the whole site. |
| [`examples/reports/weekly_2026-11-02.md`](examples/reports/weekly_2026-11-02.md) | Frozen auditor report used by the site. |
| [`vercel_dashboard/`](vercel_dashboard/) | Optional read-only dashboard template. Auth comes from environment variables you set yourself. This repo does not ship a private URL, a password, or an ingest token. |

Revolut X, in this project, means spot only. The paper broker models a 0% maker fee, a 0.09% taker fee, slippage, and the book spread. An optional language-model layer may only veto or shrink a proposal. It does not invent a buy.

## Start with no API key

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m bot --demo     # paper book, synthetic candles
python -m bot            # paper book, public Revolut X candles
```

`BOT_DRY_RUN` defaults to paper. `BOT_BROKER` defaults to `paper`. You do not need `REVX_API_KEY` for either command.

Teaching site, from a second terminal:

```bash
cd web
npm install
npm run dev    # http://127.0.0.1:43123
```

The Vercel project uses the Next.js preset with root directory `web`, install `npm install`, and build `npm run build`. It needs no environment variables. It is a normal Next.js build, with no `output: 'export'`.

## The auditor, in one page

A book stays on paper until every line below is true on closed paper trades:

- at least 40 trades
- win rate at least 33%
- expectancy at least +0.4R
- max drawdown at most 20%

Fail one line and the verdict is **NO-GO**. The finding **NO_EDGE** means the sample did not show an edge. The thresholds stay frozen. Missing a GO is a result, and the desk keeps simulating.

The weekly report dated 2026-11-02, copied in [`examples/reports/weekly_2026-11-02.md`](examples/reports/weekly_2026-11-02.md), reads:

| Metric | Value | Bar | Result |
|---|---|---|---|
| Paper trades | 34 | ≥ 40 | Fail |
| Win rate | 17.6% | ≥ 33% | Fail |
| Expectancy | −0.518R | ≥ +0.4R | Fail |
| Max drawdown | 4.9% | ≤ 20% | Pass |

**Verdict: NO-GO. Finding: NO_EDGE.** Paper equity in that report is 9,703.14 USD. That figure is simulated. The same file is what the teaching site quotes. The site also shows other frozen paper books from the same study (desk, scalpers, EMS, news). Those numbers are simulated too, and they are not a live track record.

**Bot C is off.** There is no hidden mode that turns it on.

## What you will find on the desk

- **Bot D** walks zone-style paper entries on Revolut X pairs, with a small risk budget per trade.
- **Bot A** runs the same daily idea twice on paper, once with a per-coin cap and once without, so you can see the difference.
- **Bot B** just holds BTC on paper. It is the boring baseline: did the strategy beat sitting in bitcoin?
- **Bot C** is off.
- **Scalpers, EMS, and news books** are shorter-horizon paper studies. They can refuse a trade when volume is thin, the spread is wide, or a headline is a poor reason to click buy.

Charts for four illiquid paper stops (FORT, BEAM, MORPHO, FAI) live under [`examples/charts/`](examples/charts/) and on the teaching site. They are case studies in why a filter might have skipped the trade. They are not winners.

## Layout

```
bot/                 paper bot, public Revolut X client, local read-only dashboard
desk/                screener, zones, auditor, strategy notes
live/                execution code, shipped with live mode off
tests/               pytest suite (HTTP is mocked)
tools/               local helpers
examples/reports/    the 2026-11-02 auditor report
web/                 teaching site
vercel_dashboard/    optional private-deploy template (you bring the env vars)
```

Deeper notes: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`desk/README.md`](desk/README.md), [`desk/DESK_RULES.md`](desk/DESK_RULES.md), [`web/README.md`](web/README.md).

## Secrets stay on your machine

This repository has no API keys, no `.env` files, no private keys, and no dashboard password. Environment-variable **names** such as `REVX_API_KEY`, `DASH_USER`, `DASH_PASSWORD`, and `INGEST_TOKEN` appear in code and docs so you know what a later setup would read. Values do not.

If you run the local dashboard and want a password, set `DASHBOARD_PASSWORD` yourself or let the local helper create a gitignored file. The default basic-auth user name in the public code is the generic word `paper`. Change it with `DASHBOARD_USER`.

Ignored on purpose: `.env*`, `*.pem`, password files, ingest-token files, `data/`, `logs/`, `desk/state/`, `node_modules/`, and `.next/`.

## Real orders are a later decision, and they are off

The quick start above stays on paper. Placing real orders means you create your own Revolut X API key, you keep withdrawal and transfer permissions off, and you accept the risk yourself. The code also expects an auditor **GO** and an explicit confirmation phrase before a live path will run. That path is described for study in [`GO_LIVE.md`](GO_LIVE.md). It is not a one-line switch, and this README will not give you one. The sample in this repo would not pass the auditor.

The project cannot withdraw funds. Revolut X API usage here is limited to market data and, only in a configuration you build yourself, spot orders.

## Disclaimer

RevX Paper Desk is an independent educational project by Wellington Vieira De Souza. It is not an official Revolut product. It is not financial advice. Results in the site and in `examples/reports/` are simulated. Past paper numbers are not a prediction. You can lose money if you later choose to trade with real funds.

## License

[MIT](LICENSE) © 2026 Wellington Vieira De Souza.

TradingView Lightweight Charts™ is vendored under `bot/dashboard_static/vendor/` for the local dashboard and stays under its own Apache-2.0 license. See `LICENSE-lightweight-charts.txt` and `NOTICE-lightweight-charts.txt` in that folder.
