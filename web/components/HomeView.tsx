"use client";

import Link from "next/link";
import { ArticleView } from "./ArticleView";
import { DashboardDemo } from "./DashboardDemo";
import { articles } from "@/lib/articles";
import { tx, useI18n } from "@/lib/i18n";
import { auditorReport, GITHUB_URL } from "@/lib/sample";

const facts = [
  { pt: "Spot, sem alavancagem", en: "Spot, no leverage" },
  { pt: "Maker 0%", en: "Maker 0%" },
  { pt: "Taker 0,09%", en: "Taker 0.09%" },
  { pt: "Sem chave para dados públicos", en: "No key for public data" },
];

export function HomeView() {
  const { lang, t } = useI18n();
  const featured = ["como-comecar", "moedas-pouco-negociadas", "relatorio-do-auditor", "por-que-no-go"]
    .map((slug) => articles.find((article) => article.slug === slug))
    .filter((article) => article != null);

  return (
    <div>
      <section className="mx-auto grid max-w-6xl items-end gap-10 px-4 pb-6 pt-16 md:grid-cols-12 md:px-6 md:pt-24">
        <div className="md:col-span-7">
          <p className="text-[11px] uppercase tracking-[0.2em] text-cy">
            {tx(lang, "Mesa de estudo · Revolut X · só paper", "Study desk · Revolut X · paper only")}
          </p>
          <h1 className="mt-4 text-[2.7rem] leading-[1.02] tracking-tight md:text-7xl">
            {tx(lang, "Estude o mercado. Não lhe entregue o saldo.", "Study the market. Do not hand it your balance.")}
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-8 text-mut">
            {tx(
              lang,
              "Uma mesa em paper para quem está a começar em cripto na Revolut X. Dados públicos, dinheiro simulado, e um auditor que diz NO-GO quando a estratégia não tem edge.",
              "A paper desk for people starting in crypto on Revolut X. Public data, simulated money, and an auditor that says NO-GO when a strategy has no edge.",
            )}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/start" className="rounded-full bg-acc px-5 py-2.5 text-sm font-medium text-white hover:bg-acc2">
              {tx(lang, "Começar em paper", "Start on paper")}
            </Link>
            <Link href="/learn/por-que-no-go" className="rounded-full border border-line px-5 py-2.5 text-sm text-tx hover:border-cy">
              {tx(lang, "Ler por que é NO-GO", "Read why it is NO-GO")}
            </Link>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm text-mut">
            {facts.map((fact) => (
              <li key={fact.en} className="num">{tx(lang, fact.pt, fact.en)}</li>
            ))}
          </ul>
        </div>
        <aside className="cardx md:col-span-5">
          <div className="p-5 md:p-6">
            <p className="text-[11px] uppercase tracking-[0.18em] text-mut">
              {tx(lang, "Relatório 2026-11-02 · livro do desk", "Report 2026-11-02 · desk book")}
            </p>
            <p className="num mt-5 text-6xl tracking-tight text-ask">NO-GO</p>
            <p className="mt-2 text-sm text-gold">NO_EDGE</p>
            <dl className="mt-6 grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-mut">{tx(lang, "Trades", "Trades")}</dt>
                <dd className="num mt-1 text-xl">{auditorReport.trades} <span className="text-xs text-ask">/ 40</span></dd>
              </div>
              <div>
                <dt className="text-mut">Win rate</dt>
                <dd className="num mt-1 text-xl">{auditorReport.win}</dd>
              </div>
              <div>
                <dt className="text-mut">Expectancy</dt>
                <dd className="num mt-1 text-xl text-ask">{auditorReport.expectancy}</dd>
              </div>
              <div>
                <dt className="text-mut">Max DD</dt>
                <dd className="num mt-1 text-xl text-bid">{auditorReport.maxDd}</dd>
              </div>
            </dl>
            <p className="mt-5 text-xs leading-5 text-mut">
              {tx(
                lang,
                "Três limiares falham. O drawdown passa e não salva o veredito. Equity deste ficheiro: 9.703,14 USD paper — outro retrato, não o livro de ~65 dólares.",
                "Three thresholds fail. Drawdown passes and does not save the verdict. Equity in this file: 9,703.14 USD paper — a different picture, not the ~$65 book.",
              )}
            </p>
          </div>
        </aside>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-10 md:px-6">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Demonstração", "Demonstration")}</p>
            <h2 className="mt-2 text-3xl tracking-tight">{tx(lang, "A mesa, com a amostra publicada.", "The desk, with the published sample.")}</h2>
          </div>
          <p className="hidden max-w-xs text-right text-sm text-mut md:block">
            {tx(lang, "Nada aqui está ligado a uma conta. Os separadores só mudam o recorte.", "Nothing here is tied to an account. The tabs only change the slice.")}
          </p>
        </div>
        <DashboardDemo />
      </section>

      <section className="mx-auto grid max-w-6xl gap-4 px-4 py-12 md:grid-cols-3 md:px-6">
        {[
          {
            k: "01",
            pt: "Dados públicos",
            en: "Public data",
            body: {
              pt: "Velas, tickers e regras dos pares vêm dos endpoints públicos da Revolut X. O ciclo `python -m bot` não pede chave.",
              en: "Candles, tickers, and pair rules come from Revolut X public endpoints. The `python -m bot` cycle does not ask for a key.",
            },
          },
          {
            k: "02",
            pt: "Broker de paper",
            en: "Paper broker",
            body: {
              pt: "O dry-run começa ligado. Taxas maker 0% e taker 0,09%, slippage de 5–15 bps, e o spread entram na conta antes da ordem simulada.",
              en: "Dry-run starts on. Maker 0% and taker 0.09%, 5–15 bps of slippage, and the spread are counted before the simulated order.",
            },
          },
          {
            k: "03",
            pt: "Auditor frio",
            en: "A cold auditor",
            body: {
              pt: "Quatro limiares congelados. Se falhar depois de 40 trades, o nome da coisa é NO-GO. Não se afina para perseguir o selo.",
              en: "Four frozen thresholds. If it fails after 40 trades, the name of the thing is NO-GO. You do not retune to chase the stamp.",
            },
          },
        ].map((item) => (
          <article key={item.k} className="cardx p-5">
            <p className="num text-xs text-cy">{item.k}</p>
            <h3 className="mt-4 text-xl tracking-tight">{tx(lang, item.pt, item.en)}</h3>
            <p className="mt-3 text-sm leading-6 text-mut">{t(item.body)}</p>
          </article>
        ))}
      </section>

      <section className="mx-auto max-w-6xl px-4 py-8 md:px-6">
        <div className="flex items-end justify-between gap-4">
          <h2 className="text-3xl tracking-tight">{tx(lang, "Os bots, em uma grelha.", "The bots, in one grid.")}</h2>
          <Link href="/bots" className="text-sm text-cy hover:text-white">{tx(lang, "Ver o mapa", "See the map")}</Link>
        </div>
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[
            ["D", tx(lang, "Zonas na Revolut X", "Zones on Revolut X"), tx(lang, "1% por trade, teto 15%, limites de preferência. Equity de amostra ~$62,07.", "1% per trade, 15% cap, prefers limits. Sample equity ~$62.07.")],
            ["A", tx(lang, "Sombra C3, dois livros", "C3 shadow, two books"), tx(lang, "Com teto 12,5%: ~$63,13. Sem teto: ~$57,72. Não validado.", "With a 12.5% cap: ~$63.13. Without: ~$57.72. Not validated.")],
            ["B", tx(lang, "Segurar BTC", "Hold BTC"), tx(lang, "A baseline. Amostra ~$60,31. A pergunta é se o resto bate isto.", "The baseline. Sample ~$60.31. The question is whether the rest beats it.")],
            ["C", tx(lang, "Desligado", "Off"), tx(lang, "Não está disponível. Não há modo secreto.", "Not available. There is no secret mode.")],
            ["S", tx(lang, "Seis scalpers", "Six scalpers"), tx(lang, "1m–5m em BTC, ETH e SOL. Os que já têm amostra estão NO-GO.", "1m–5m on BTC, ETH, and SOL. The ones with a sample are NO-GO.")],
            ["N", tx(lang, "Notícias e EMS", "News and EMS"), tx(lang, "Manchetes públicas e microestrutura curta. Também em paper, também sem GO.", "Public headlines and short-horizon microstructure. Also paper, also no GO.")],
          ].map(([mark, title, body]) => (
            <article key={mark} className="rounded-2xl border border-line bg-card/80 p-5">
              <p className="num text-xs text-cy">{mark}</p>
              <h3 className="mt-3 text-lg">{title}</h3>
              <p className="mt-2 text-sm leading-6 text-mut">{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-8 px-4 py-14 md:grid-cols-2 md:px-6">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Como o paper trabalha", "How paper works")}</p>
          <h2 className="mt-3 text-3xl tracking-tight">{tx(lang, "Quatro travões antes de qualquer história bonita.", "Four brakes before any pretty story.")}</h2>
          <ol className="mt-6 grid gap-4">
            {[
              [tx(lang, "Valor esperado", "Expected value"), tx(lang, "Se taxas e slippage comem o trade, o trade não existe.", "If fees and slippage eat the trade, the trade does not exist.")],
              [tx(lang, "Tamanho pequeno", "Small size"), tx(lang, "Um quarto de Kelly, teto de 15% por moeda, cerca de 1% de risco no Bot D.", "Quarter-Kelly, a 15% cap per coin, about 1% risk on Bot D.")],
              [tx(lang, "Stop duro", "Hard stop"), tx(lang, "−8% desde a entrada ou o pico, mais um stop por ATR. Sem dados, HOLD.", "−8% from entry or peak, plus an ATR stop. No data, HOLD.")],
              [tx(lang, "Linguagem só veta", "Language only vetoes"), tx(lang, "Um modelo, se existir, reduz ou recusa. Nunca inventa a compra.", "A model, if present, reduces or refuses. It never invents the buy.")],
            ].map(([title, body], index) => (
              <li key={title} className="grid grid-cols-[auto_1fr] gap-4">
                <span className="num text-sm text-cy">0{index + 1}</span>
                <div>
                  <p className="font-medium">{title}</p>
                  <p className="mt-1 text-sm leading-6 text-mut">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div className="cardx p-6">
          <p className="text-[11px] uppercase tracking-[0.18em] text-gold">{tx(lang, "Régua congelada", "Frozen ruler")}</p>
          <h2 className="mt-3 text-3xl tracking-tight">{tx(lang, "GO pede as quatro, juntas.", "GO asks for all four, together.")}</h2>
          <ul className="mt-6 grid gap-3 text-sm">
            {[
              ["≥ 40", tx(lang, "trades fechados em paper", "closed paper trades")],
              ["≥ 33%", tx(lang, "de acerto", "win rate")],
              ["≥ +0.4R", tx(lang, "de média por trade", "average per trade")],
              ["≤ 20%", tx(lang, "de drawdown máximo", "maximum drawdown")],
            ].map(([value, label]) => (
              <li key={value} className="flex items-baseline justify-between gap-4 border-b border-line pb-3">
                <span className="num text-xl">{value}</span>
                <span className="text-mut">{label}</span>
              </li>
            ))}
          </ul>
          <p className="mt-5 text-sm leading-6 text-mut">
            {tx(
              lang,
              "Falhou depois dos 40? NO-GO. Fica em paper. O relatório de 2 de novembro nem chegou aos 40, e a expectancy já era −0,518R.",
              "Failed after 40? NO-GO. It stays on paper. The 2 November report did not even reach 40, and expectancy was already −0.518R.",
            )}
          </p>
          <Link href="/reports" className="mt-5 inline-block text-sm text-cy hover:text-white">
            {tx(lang, "Abrir o relatório", "Open the report")}
          </Link>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-6 md:px-6">
        <div className="cardx grid gap-6 p-6 md:grid-cols-[1.1fr_0.9fr] md:p-8">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Cinco minutos", "Five minutes")}</p>
            <h2 className="mt-3 text-3xl tracking-tight">{tx(lang, "Comece sem chave e sem depósito.", "Start with no key and no deposit.")}</h2>
            <p className="mt-3 text-sm leading-6 text-mut">
              {tx(
                lang,
                "O primeiro ciclo com dados reais públicos continua em paper. Se a resposta for INSUFFICIENT_DATA, o bot está a recusar inventar edge. Isso é o comportamento certo.",
                "The first cycle on real public data stays on paper. If the answer is INSUFFICIENT_DATA, the bot is refusing to invent an edge. That is the right behavior.",
              )}
            </p>
            <Link href="/start" className="mt-5 inline-block text-sm text-cy hover:text-white">
              {tx(lang, "Passo a passo", "Step by step")}
            </Link>
          </div>
          <pre className="num overflow-x-auto rounded-xl border border-line bg-bg p-4 text-[13px] leading-6 text-cy">{`python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m bot --demo
python -m bot`}</pre>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 md:px-6">
        <h2 className="text-3xl tracking-tight">{tx(lang, "Para ler a seguir", "Read next")}</h2>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {featured.map((article) => (
            <Link key={article.slug} href={`/learn/${article.slug}`} className="rounded-2xl border border-line p-5 hover:border-cy/50">
              <p className="text-[11px] uppercase tracking-[0.16em] text-mut">{t(article.kicker)}</p>
              <h3 className="mt-3 text-xl tracking-tight">{t(article.title)}</h3>
              <p className="mt-2 text-sm leading-6 text-mut">{t(article.description)}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-8 md:px-6">
        <div className="flex flex-col items-start justify-between gap-6 border-t border-line pt-10 md:flex-row md:items-end">
          <div>
            <h2 className="text-3xl tracking-tight">{tx(lang, "Código aberto. Veredito aberto.", "Open code. Open verdict.")}</h2>
            <p className="mt-3 max-w-xl text-sm leading-6 text-mut">
              {tx(
                lang,
                "O nome sugerido no GitHub é revx-paper-desk. A licença é MIT. O modo por defeito continua a ser paper.",
                "The suggested GitHub name is revx-paper-desk. The license is MIT. The default mode remains paper.",
              )}
            </p>
          </div>
          <a href={GITHUB_URL} className="rounded-full bg-white px-5 py-2.5 text-sm font-medium text-bg">
            {tx(lang, "Ver o repositório", "View the repository")}
          </a>
        </div>
      </section>
    </div>
  );
}

export function StartView() {
  return <ArticleView slug="como-comecar" />;
}
