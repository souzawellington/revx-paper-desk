"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useI18n, tx } from "@/lib/i18n";
import { GITHUB_URL } from "@/lib/sample";

const links = [
  { href: "/#mesa", pt: "Mesa", en: "Desk" },
  { href: "/learn", pt: "Aprender", en: "Learn" },
  { href: "/bots", pt: "Bots", en: "Bots" },
  { href: "/strategies", pt: "Estratégias", en: "Strategies" },
  { href: "/reports", pt: "Auditor", en: "Auditor" },
  { href: "/start", pt: "Começar", en: "Start" },
];

export function SiteShell({ children }: { children: React.ReactNode }) {
  const { lang, setLang } = useI18n();
  const path = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <>
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[80] focus:bg-card focus:px-3 focus:py-2"
      >
        {tx(lang, "Saltar para o conteúdo", "Skip to content")}
      </a>
      <div className="sticky top-0 z-50">
        <div className="banner-sim px-4 py-2 text-center text-[12px] font-semibold tracking-[0.14em] uppercase">
          {tx(
            lang,
            "Simulado · só paper · sem ordens reais · não é a Revolut",
            "Simulated · paper only · no real orders · not Revolut",
          )}
        </div>
        <header className="border-b border-line bg-panel">
          <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 md:px-6">
            <Link href="/" className="flex items-baseline gap-2" onClick={() => setOpen(false)}>
              <span className="text-[15px] font-semibold tracking-tight">RevX</span>
              <span className="text-[13px] text-mut">Paper Desk</span>
            </Link>
            <nav className="ml-auto hidden items-center gap-1 lg:flex" aria-label="Primary">
              {links.map((item) => {
                const active = item.href === "/learn" ? path.startsWith("/learn") : path === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`rounded-full px-3 py-1.5 text-[13px] ${active ? "bg-card text-tx" : "text-mut hover:text-tx"}`}
                  >
                    {tx(lang, item.pt, item.en)}
                  </Link>
                );
              })}
            </nav>
            <div className="ml-auto flex items-center gap-2 lg:ml-2">
              <div className="flex rounded-full border border-line p-0.5 text-[12px]" role="group" aria-label={tx(lang, "Idioma", "Language")}>
                {(["pt", "en"] as const).map((code) => (
                  <button
                    key={code}
                    type="button"
                    onClick={() => setLang(code)}
                    aria-pressed={lang === code}
                    className={`rounded-full px-2.5 py-1 uppercase ${lang === code ? "bg-acc text-white" : "text-mut"}`}
                  >
                    {code}
                  </button>
                ))}
              </div>
              <a
                href={GITHUB_URL}
                className="hidden rounded-full border border-line px-3 py-1.5 text-[12px] text-cy hover:text-white sm:inline"
              >
                GitHub
              </a>
              <button
                type="button"
                className="rounded-full border border-line px-3 py-1.5 text-[12px] text-mut lg:hidden"
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
              >
                {open ? tx(lang, "Fechar", "Close") : tx(lang, "Menu", "Menu")}
              </button>
            </div>
          </div>
          {open ? (
            <nav className="border-t border-line px-4 py-3 lg:hidden" aria-label="Mobile">
              <div className="grid gap-1">
                {links.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className="rounded-lg px-2 py-2 text-sm text-tx hover:bg-card"
                  >
                    {tx(lang, item.pt, item.en)}
                  </Link>
                ))}
                <a href={GITHUB_URL} className="rounded-lg px-2 py-2 text-sm text-cy">
                  GitHub
                </a>
              </div>
            </nav>
          ) : null}
        </header>
      </div>
      <main id="conteudo">{children}</main>
      <footer className="mt-20 border-t border-line bg-panel">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 md:grid-cols-3 md:px-6">
          <div>
            <p className="text-sm font-semibold">RevX Paper Desk</p>
            <p className="mt-2 text-sm leading-6 text-mut">
              {tx(
                lang,
                "Projeto independente de estudo. Não é um produto oficial da Revolut. Não é conselho financeiro. Por defeito não coloca ordens.",
                "An independent study project. Not an official Revolut product. Not financial advice. It places no orders by default.",
              )}
            </p>
          </div>
          <div className="text-sm leading-7">
            <p className="text-mut">{tx(lang, "Ler", "Read")}</p>
            <div className="mt-2 grid">
              <Link href="/start" className="hover:text-cy">{tx(lang, "Começar em paper", "Start on paper")}</Link>
              <Link href="/learn" className="hover:text-cy">{tx(lang, "Blog de aprendizagem", "Learning blog")}</Link>
              <Link href="/learn/por-que-no-go" className="hover:text-cy">NO-GO</Link>
              <Link href="/learn/moedas-pouco-negociadas" className="hover:text-cy">
                {tx(lang, "FORT, BEAM, MORPHO, FAI", "FORT, BEAM, MORPHO, FAI")}
              </Link>
            </div>
          </div>
          <div className="text-sm leading-7 text-mut">
            <p>MIT</p>
            <p>{tx(lang, "Spot apenas. Sem alavancagem neste código.", "Spot only. No leverage in this code.")}</p>
            <p>{tx(lang, "Maker 0% · taker 0,09% na Revolut X.", "Maker 0% · taker 0.09% on Revolut X.")}</p>
            <a href={GITHUB_URL} className="text-cy hover:text-white">
              souzawellington/revx-paper-desk
            </a>
          </div>
        </div>
      </footer>
    </>
  );
}
