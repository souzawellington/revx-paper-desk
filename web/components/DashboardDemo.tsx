"use client";

import { useState } from "react";
import { tx, useI18n, type Copy } from "@/lib/i18n";
import {
  auditorReport,
  botA,
  botB,
  botD,
  ems,
  news,
  sampleNote,
  scalpers,
  stops,
  verdictCopy,
  type BookRow,
  type Verdict,
} from "@/lib/sample";

type Tab = "desk" | "scalp" | "ems" | "news" | "auditor";

const tabs: { id: Tab; label: Copy }[] = [
  { id: "desk", label: { pt: "Mesa", en: "Desk" } },
  { id: "scalp", label: { pt: "Scalpers", en: "Scalpers" } },
  { id: "ems", label: { pt: "EMS", en: "EMS" } },
  { id: "news", label: { pt: "Notícias", en: "News" } },
  { id: "auditor", label: { pt: "Auditor", en: "Auditor" } },
];

function Pill({ verdict }: { verdict: Verdict }) {
  const { lang } = useI18n();
  const tone =
    verdict === "nogo"
      ? "border-ask/40 text-ask"
      : verdict === "thin" || verdict === "training"
        ? "border-gold/40 text-gold"
        : "border-line text-mut";
  return <span className={`num rounded-full border px-2 py-0.5 text-[11px] ${tone}`}>{tx(lang, verdictCopy[verdict].pt, verdictCopy[verdict].en)}</span>;
}

function BookTable({ rows }: { rows: BookRow[] }) {
  const { lang } = useI18n();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-left text-sm">
        <thead className="text-[11px] uppercase tracking-[0.14em] text-mut">
          <tr>
            <th className="py-2 pr-3 font-medium">{tx(lang, "Livro", "Book")}</th>
            <th className="py-2 pr-3 font-medium">{tx(lang, "Trades", "Trades")}</th>
            <th className="py-2 pr-3 font-medium">{tx(lang, "Acerto", "Win rate")}</th>
            <th className="py-2 pr-3 font-medium">R</th>
            <th className="py-2 pr-3 font-medium">Equity</th>
            <th className="py-2 font-medium">{tx(lang, "Estado", "State")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-line">
              <td className="py-2.5 pr-3">{row.name}</td>
              <td className="num py-2.5 pr-3 text-mut">{row.trades}</td>
              <td className="num py-2.5 pr-3">{row.win}</td>
              <td className={`num py-2.5 pr-3 ${row.exp.startsWith("−") || row.exp.startsWith("-") ? "text-ask" : ""}`}>{row.exp}</td>
              <td className="num py-2.5 pr-3">{row.equity}</td>
              <td className="py-2.5"><Pill verdict={row.verdict} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel px-4 py-3">
      <p className="text-[11px] uppercase tracking-[0.16em] text-mut">{label}</p>
      <p className="num mt-2 text-2xl tracking-tight">{value}</p>
      {hint ? <p className="mt-1 text-xs text-mut">{hint}</p> : null}
    </div>
  );
}

export function DashboardDemo() {
  const { lang } = useI18n();
  const [tab, setTab] = useState<Tab>("desk");

  return (
    <section id="mesa" className="scroll-mt-28">
      <div className="cardx">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 md:px-5">
          <div className="flex gap-1.5" aria-hidden>
            <span className="h-2.5 w-2.5 rounded-full bg-ask/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-gold/80" />
            <span className="h-2.5 w-2.5 rounded-full bg-bid/80" />
          </div>
          <p className="text-sm font-medium">Paper desk</p>
          <span className="rounded-full border border-gold/40 px-2 py-0.5 text-[11px] uppercase tracking-[0.14em] text-gold">
            {tx(lang, "Amostra congelada", "Frozen sample")}
          </span>
          <span className="text-xs text-mut">{tx(lang, "Não está ao vivo", "Not live")}</span>
        </div>
        <div className="flex gap-1 overflow-x-auto border-b border-line px-3 py-2" role="tablist">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              onClick={() => setTab(item.id)}
              className={`shrink-0 rounded-full px-3 py-1.5 text-[13px] ${tab === item.id ? "bg-acc text-white" : "text-mut hover:text-tx"}`}
            >
              {tx(lang, item.label.pt, item.label.en)}
            </button>
          ))}
        </div>
        <div className="p-4 md:p-5" role="tabpanel">
          {tab === "desk" ? (
            <div className="grid gap-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <Stat label="Bot D" value={botD.equity} hint={tx(lang, `DD ${botD.dd} · sem posição aberta`, `DD ${botD.dd} · no open position`)} />
                <Stat label={tx(lang, "Bot A com teto", "Bot A capped")} value={botA.cappedEquity} hint={`DD ${botA.cappedDd} · kill ${botA.cappedKill}`} />
                <Stat label={tx(lang, "Bot A sem teto", "Bot A uncapped")} value={botA.openEquity} hint={`DD ${botA.openDd} · kill ${botA.openKill}`} />
                <Stat label={tx(lang, "Bot B · BTC", "Bot B · BTC")} value={botB.equity} hint={tx(lang, "Baseline: só segurar bitcoin", "Baseline: just hold bitcoin")} />
              </div>
              <div>
                <p className="mb-2 text-[11px] uppercase tracking-[0.16em] text-mut">
                  {tx(lang, "Stops recentes do Bot D", "Recent Bot D stops")}
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead className="text-[11px] uppercase tracking-[0.14em] text-mut">
                      <tr>
                        <th className="py-2 font-medium">{tx(lang, "Par", "Pair")}</th>
                        <th className="py-2 font-medium">{tx(lang, "Entrada", "Entry")}</th>
                        <th className="py-2 font-medium">Stop</th>
                        <th className="py-2 font-medium">R</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stops.map((stop) => (
                        <tr key={stop.pair} className="border-t border-line">
                          <td className="py-2.5">{stop.pair}</td>
                          <td className="num py-2.5 text-mut">{stop.entry}</td>
                          <td className="num py-2.5 text-mut">{stop.exit}</td>
                          <td className="num py-2.5 text-ask">{stop.r}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <p className="text-sm text-mut">
                {tx(
                  lang,
                  "Bot C está desligado e não aparece como livro. Os filtros de volume e spread, nesta amostra, observavam e ainda não bloqueavam.",
                  "Bot C is off and does not appear as a book. Volume and spread filters, in this sample, were watching and not yet blocking.",
                )}
              </p>
            </div>
          ) : null}
          {tab === "scalp" ? <BookTable rows={scalpers} /> : null}
          {tab === "ems" ? <BookTable rows={ems} /> : null}
          {tab === "news" ? (
            <BookTable
              rows={[
                { id: "momo", name: "news_momo", trades: news.momo.trades, win: news.momo.win, exp: news.momo.exp, equity: news.momo.equity, verdict: news.momo.verdict },
                { id: "pull", name: "news_pullback", trades: news.pullback.trades, win: news.pullback.win, exp: news.pullback.exp, equity: news.pullback.equity, verdict: news.pullback.verdict },
              ]}
            />
          ) : null}
          {tab === "auditor" ? (
            <div className="grid gap-4">
              <p className="text-sm text-mut">
                {tx(
                  lang,
                  "Relatório semanal de 2026-11-02, livro do desk. Equity deste ficheiro: 9.703,14 USD. Não é o livro de ~65 dólares dos outros separadores.",
                  "Weekly report dated 2026-11-02, desk book. Equity in that file: 9,703.14 USD. It is not the ~$65 book on the other tabs.",
                )}
              </p>
              <div className="grid gap-3 sm:grid-cols-4">
                <Stat label={tx(lang, "Trades", "Trades")} value={auditorReport.trades} hint="≥ 40 · FALHA" />
                <Stat label="Win rate" value={auditorReport.win} hint="≥ 33% · FALHA" />
                <Stat label="Expectancy" value={auditorReport.expectancy} hint="≥ +0.4R · FALHA" />
                <Stat label="Max DD" value={auditorReport.maxDd} hint="≤ 20% · PASSA" />
              </div>
              <p className="num text-sm text-ask">NO-GO · NO_EDGE</p>
            </div>
          ) : null}
        </div>
        <p className="border-t border-line px-4 py-3 text-xs leading-5 text-mut md:px-5">{tx(lang, sampleNote.pt, sampleNote.en)}</p>
      </div>
    </section>
  );
}
