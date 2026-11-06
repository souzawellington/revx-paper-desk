"use client";

import Link from "next/link";
import { tx, useI18n } from "@/lib/i18n";
import { auditorReport, botA, botB, botD, ems, news, scalpers } from "@/lib/sample";
import { strategies } from "@/lib/strategies";

export function BotsView() {
  const { lang } = useI18n();
  return (
    <div className="mx-auto max-w-6xl px-4 py-14 md:px-6 md:py-20">
      <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Bots", "Bots")}</p>
      <h1 className="mt-3 max-w-3xl text-4xl tracking-tight md:text-6xl">
        {tx(lang, "Cada livro faz uma pergunta pequena.", "Each book asks a small question.")}
      </h1>
      <p className="mt-5 max-w-2xl text-lg leading-8 text-mut">
        {tx(
          lang,
          "Todos correm em paper. Nenhum tem GO. O Bot C não faz parte da lista de coisas que se podem ligar.",
          "They all run on paper. None has a GO. Bot C is not on the list of things you can switch on.",
        )}
      </p>
      <div className="mt-10 grid gap-4">
        <article className="cardx p-5 md:p-6">
          <p className="num text-xs text-cy">D</p>
          <h2 className="mt-2 text-2xl tracking-tight">{tx(lang, "Executor da mesa", "Desk executor")}</h2>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-mut">
            {tx(
              lang,
              `Zonas em pares da Revolut X. Risco ~1% por trade, teto de 15% por moeda, preferência por limites. Livro de amostra: equity ${botD.equity}, drawdown ${botD.dd}, sem posição depois do último stop. Volume abaixo de $50k, spread acima de 0,50%, tendência fraca e macro CAUTION eram filtros observados, não bloqueios.`,
              `Zones on Revolut X pairs. Risk ~1% per trade, 15% cap per coin, preference for limits. Sample book: equity ${botD.equity}, drawdown ${botD.dd}, no position after the last stop. Volume below $50k, spread above 0.50%, a weak trend, and macro CAUTION were watched filters, not blocks.`,
            )}
          </p>
          <Link href="/learn/moedas-pouco-negociadas" className="mt-4 inline-block text-sm text-cy">
            {tx(lang, "Estudo FORT, BEAM, MORPHO, FAI", "FORT, BEAM, MORPHO, FAI study")}
          </Link>
        </article>
        <div className="grid gap-4 md:grid-cols-2">
          <article className="cardx p-5">
            <p className="num text-xs text-cy">A</p>
            <h2 className="mt-2 text-2xl">{tx(lang, "Sombra C3", "C3 shadow")}</h2>
            <p className="mt-3 text-sm leading-7 text-mut">
              {tx(
                lang,
                `Dois livros da mesma estratégia diária. Com teto de 12,5%: ${botA.cappedEquity} (DD ${botA.cappedDd}, kill ${botA.cappedKill}). Sem teto: ${botA.openEquity} (DD ${botA.openDd}, kill ${botA.openKill}). Na noite de 5–6 nov, stops paper de −8% em BTC e ETH.`,
                `Two books of the same daily strategy. With a 12.5% cap: ${botA.cappedEquity} (DD ${botA.cappedDd}, kill ${botA.cappedKill}). Without: ${botA.openEquity} (DD ${botA.openDd}, kill ${botA.openKill}). On the night of 5–6 Nov, paper −8% stops on BTC and ETH.`,
              )}
            </p>
          </article>
          <article className="cardx p-5">
            <p className="num text-xs text-cy">B</p>
            <h2 className="mt-2 text-2xl">{tx(lang, "Segurar BTC", "Hold BTC")}</h2>
            <p className="mt-3 text-sm leading-7 text-mut">
              {tx(
                lang,
                `Baseline. Amostra ${botB.equity}. Serve para perguntar se a estratégia bate o gesto simples. Não é um produto para promover.`,
                `Baseline. Sample ${botB.equity}. It exists to ask whether a strategy beats the simple act. It is not a product to promote.`,
              )}
            </p>
          </article>
        </div>
        <article className="rounded-2xl border border-dashed border-line p-5">
          <p className="num text-xs text-mut">C · {tx(lang, "DESLIGADO", "OFF")}</p>
          <h2 className="mt-2 text-2xl text-mut">{tx(lang, "Não disponível", "Not available")}</h2>
          <p className="mt-3 text-sm leading-7 text-mut">
            {tx(lang, "Não há livro, não há equity, não há flag. O projeto não o anuncia.", "There is no book, no equity, no flag. The project does not advertise it.")}
          </p>
        </article>
        <div className="grid gap-4 lg:grid-cols-3">
          <article className="rounded-2xl border border-line p-5">
            <h2 className="text-xl">{tx(lang, "Scalpers", "Scalpers")}</h2>
            <ul className="mt-3 grid gap-2 text-sm text-mut">
              {scalpers.map((row) => (
                <li key={row.id} className="flex justify-between gap-3">
                  <span>{row.name}</span>
                  <span className="num">{row.exp}</span>
                </li>
              ))}
            </ul>
            <Link href="/learn/os-bots" className="mt-4 inline-block text-sm text-cy">{tx(lang, "Regras e tabela", "Rules and table")}</Link>
          </article>
          <article className="rounded-2xl border border-line p-5">
            <h2 className="text-xl">EMS</h2>
            <ul className="mt-3 grid gap-2 text-sm text-mut">
              {ems.map((row) => (
                <li key={row.id} className="flex justify-between gap-3">
                  <span>{row.name}</span>
                  <span className="num">{row.exp}</span>
                </li>
              ))}
            </ul>
          </article>
          <article className="rounded-2xl border border-line p-5">
            <h2 className="text-xl">{tx(lang, "Notícias", "News")}</h2>
            <p className="mt-3 text-sm leading-6 text-mut">
              news_momo {news.momo.trades} · {news.momo.exp} · {news.momo.equity}
            </p>
            <p className="mt-2 text-sm leading-6 text-mut">
              news_pullback {news.pullback.trades} · {news.pullback.equity}
            </p>
            <Link href="/learn/bot-de-noticias" className="mt-4 inline-block text-sm text-cy">
              {tx(lang, "O caso do XRP", "The XRP case")}
            </Link>
          </article>
        </div>
      </div>
    </div>
  );
}

export function StrategiesView() {
  const { lang, t } = useI18n();
  return (
    <div className="mx-auto max-w-6xl px-4 py-14 md:px-6 md:py-20">
      <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Estratégias", "Strategies")}</p>
      <h1 className="mt-3 max-w-3xl text-4xl tracking-tight md:text-6xl">
        {tx(lang, "Cadernos de pesquisa. Nenhum com GO.", "Research notes. None with a GO.")}
      </h1>
      <p className="mt-5 max-w-2xl text-lg leading-8 text-mut">
        {tx(
          lang,
          "Os ficheiros em desk/strategies descrevem hipóteses. A régua do auditor é que decide, e até agora a resposta pública é NO-GO ou “ainda não há amostra”.",
          "The files in desk/strategies describe hypotheses. The auditor’s ruler decides, and so far the public answer is NO-GO or “there is no sample yet.”",
        )}
      </p>
      <Link href="/learn/estrategias" className="mt-4 inline-block text-sm text-cy">
        {tx(lang, "Ler as regras sem jargão", "Read the rules without jargon")}
      </Link>
      <div className="mt-10 grid gap-4 md:grid-cols-2">
        {strategies.map((note) => (
          <article key={note.id} className="rounded-2xl border border-line bg-card/70 p-5">
            <p className="num text-xs text-mut">{note.id} · {note.file}</p>
            <h2 className="mt-3 text-xl tracking-tight">{t(note.title)}</h2>
            <p className="mt-2 text-sm leading-6 text-mut">{t(note.body)}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

export function ReportsView() {
  const { lang } = useI18n();
  const rows = [
    [tx(lang, "Trades (paper)", "Trades (paper)"), auditorReport.trades, "≥ 40", tx(lang, "FALHA", "FAIL")],
    ["Win rate", auditorReport.win, "≥ 33%", tx(lang, "FALHA", "FAIL")],
    ["Expectancy", auditorReport.expectancy, "≥ +0.4R", tx(lang, "FALHA", "FAIL")],
    ["Max DD", auditorReport.maxDd, "≤ 20%", tx(lang, "PASSA", "PASS")],
  ];
  return (
    <div className="mx-auto max-w-3xl px-4 py-14 md:px-6 md:py-20">
      <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Relatório", "Report")}</p>
      <h1 className="mt-3 text-4xl tracking-tight md:text-6xl">
        {tx(lang, "Semanal do desk, 2026-11-02.", "Desk weekly, 2026-11-02.")}
      </h1>
      <p className="mt-5 text-lg leading-8 text-mut">
        {tx(
          lang,
          "Limiares congelados. O auditor não sugere alterá-los. O ficheiro no repositório é examples/reports/weekly_2026-11-02.md.",
          "Frozen thresholds. The auditor does not suggest changing them. The file in the repository is examples/reports/weekly_2026-11-02.md.",
        )}
      </p>
      <div className="cardx mt-8 p-2">
        <table className="w-full text-left text-sm">
          <thead className="text-[11px] uppercase tracking-[0.14em] text-mut">
            <tr>
              <th className="px-3 py-3 font-medium">{tx(lang, "Métrica", "Metric")}</th>
              <th className="px-3 py-3 font-medium">{tx(lang, "Valor", "Value")}</th>
              <th className="px-3 py-3 font-medium">{tx(lang, "Limiar", "Threshold")}</th>
              <th className="px-3 py-3 font-medium">{tx(lang, "Estado", "State")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row[0]} className="border-t border-line">
                {row.map((cell, index) => (
                  <td key={index} className={`px-3 py-3 ${index === 0 ? "" : "num"} ${cell === "FALHA" || cell === "FAIL" ? "text-ask" : ""} ${cell === "PASSA" || cell === "PASS" ? "text-bid" : ""}`}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="num mt-6 text-lg text-ask">NO-GO · NO_EDGE</p>
      <p className="mt-4 text-sm leading-7 text-mut">
        {tx(
          lang,
          `Ensaio acelerado: ${auditorReport.accelerated.trades} trades, acerto ${auditorReport.accelerated.win}, ${auditorReport.accelerated.exp}. Normais: ${auditorReport.normal.trades} trades, acerto ${auditorReport.normal.win}, ${auditorReport.normal.exp}. O veredito junta os dois; só com os normais também seria NO-GO. SKIPPED hipotético: ${auditorReport.skipped.trades} trade, ${auditorReport.skipped.exp}.`,
          `Accelerated trial: ${auditorReport.accelerated.trades} trades, win rate ${auditorReport.accelerated.win}, ${auditorReport.accelerated.exp}. Normals: ${auditorReport.normal.trades} trades, win rate ${auditorReport.normal.win}, ${auditorReport.normal.exp}. The verdict counts both; normals alone would still be NO-GO. Hypothetical SKIPPED: ${auditorReport.skipped.trades} trade, ${auditorReport.skipped.exp}.`,
        )}
      </p>
      <p className="mt-3 text-sm leading-7 text-mut">
        {tx(
          lang,
          `Métricas descritivas, que não mudam o GO: PF ${auditorReport.descriptive.pf} · SQN ${auditorReport.descriptive.sqn} · Sortino(R) ${auditorReport.descriptive.sortino} · CVaR95 ${auditorReport.descriptive.cvar} · Omega ${auditorReport.descriptive.omega}. Equity paper deste ficheiro: ${auditorReport.equity}.`,
          `Descriptive metrics, which do not change the GO: PF ${auditorReport.descriptive.pf} · SQN ${auditorReport.descriptive.sqn} · Sortino(R) ${auditorReport.descriptive.sortino} · CVaR95 ${auditorReport.descriptive.cvar} · Omega ${auditorReport.descriptive.omega}. Paper equity in this file: ${auditorReport.equity}.`,
        )}
      </p>
      <Link href="/learn/relatorio-do-auditor" className="mt-6 inline-block text-sm text-cy">
        {tx(lang, "Como ler esta tabela", "How to read this table")}
      </Link>
    </div>
  );
}

export function NotFoundView() {
  const { lang } = useI18n();
  return (
    <div className="mx-auto max-w-3xl px-4 py-24">
      <p className="num text-sm text-ask">404</p>
      <h1 className="mt-3 text-4xl tracking-tight">{tx(lang, "Esta página não está na mesa.", "This page is not on the desk.")}</h1>
      <Link href="/" className="mt-6 inline-block text-cy">{tx(lang, "Voltar ao início", "Back to the start")}</Link>
    </div>
  );
}
