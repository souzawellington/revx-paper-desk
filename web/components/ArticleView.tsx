"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect } from "react";
import { articles, getArticle, kindLabel, type Block } from "@/lib/articles";
import { tx, useI18n, type Copy } from "@/lib/i18n";

function cellText(cell: string | Copy, t: (copy: Copy) => string) {
  return typeof cell === "string" ? cell : t(cell);
}

function Blocks({ blocks }: { blocks: Block[] }) {
  const { t } = useI18n();
  return (
    <div className="prose-desk">
      {blocks.map((block, index) => {
        if (block.kind === "p") return <p key={index} className="mt-4">{t(block.text)}</p>;
        if (block.kind === "h2") return <h2 key={index}>{t(block.text)}</h2>;
        if (block.kind === "h3") return <h3 key={index}>{t(block.text)}</h3>;
        if (block.kind === "ul" || block.kind === "ol") {
          const Tag = block.kind;
          return (
            <Tag key={index}>
              {block.items.map((item) => (
                <li key={item.pt}>{t(item)}</li>
              ))}
            </Tag>
          );
        }
        if (block.kind === "callout") {
          const tone =
            block.tone === "nogo"
              ? "border-ask/40"
              : block.tone === "good"
                ? "border-vault/40"
                : block.tone === "sim"
                  ? "border-gold/50"
                  : "border-cy/30";
          return (
            <aside key={index} className={`mt-6 rounded-2xl border bg-panel px-4 py-4 ${tone}`}>
              <p className="text-[11px] uppercase tracking-[0.16em] text-gold">{t(block.title)}</p>
              <p className="mt-2 text-[15px] leading-7 text-tx">{t(block.text)}</p>
            </aside>
          );
        }
        if (block.kind === "quote") {
          return (
            <blockquote key={index} className="mt-6 border-l-2 border-acc pl-4">
              <p className="text-xl leading-snug tracking-tight">{t(block.text)}</p>
              <p className="num mt-2 text-xs text-mut">{t(block.cite)}</p>
            </blockquote>
          );
        }
        if (block.kind === "code") {
          return (
            <figure key={index} className="mt-6">
              <figcaption className="mb-2 text-[11px] uppercase tracking-[0.16em] text-mut">{t(block.caption)}</figcaption>
              <pre className="num overflow-x-auto rounded-2xl border border-line bg-panel p-4 text-[13px] leading-6 text-cy">
                <code>{block.code}</code>
              </pre>
            </figure>
          );
        }
        if (block.kind === "figure") {
          return (
            <figure key={index} className="cardx mt-6">
              {/* The attached paper-entry charts are the source images. */}
              <Image src={block.src} alt={t(block.alt)} width={1100} height={572} className="h-auto w-full bg-bg" />
              <figcaption className="px-4 py-3 text-sm leading-6 text-mut">{t(block.caption)}</figcaption>
            </figure>
          );
        }
        return (
          <figure key={index} className="mt-6">
            <figcaption className="mb-2 text-sm text-mut">{t(block.caption)}</figcaption>
            <div className="overflow-x-auto rounded-2xl border border-line">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="bg-panel text-[11px] uppercase tracking-[0.14em] text-mut">
                  <tr>
                    {block.headers.map((header) => (
                      <th key={header.pt} className="px-3 py-2 font-medium">{t(header)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row) => (
                    <tr key={row.map((cell) => (typeof cell === "string" ? cell : cell.pt)).join("|")} className="border-t border-line">
                      {row.map((cell, cellIndex) => {
                        const text = cellText(cell, t);
                        const raw = typeof cell === "string" ? cell : cell.pt;
                        return (
                          <td key={cellIndex} className={`px-3 py-2.5 ${cellIndex === 0 ? "" : "num"} ${raw === "NO-GO" || raw === "FALHA" ? "text-ask" : ""} ${raw === "PASSA" ? "text-bid" : ""}`}>
                            {text}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </figure>
        );
      })}
    </div>
  );
}

export function ArticleView({ slug }: { slug: string }) {
  const { lang, t } = useI18n();
  const article = getArticle(slug);
  useEffect(() => {
    if (!article) return;
    document.title = `${tx(lang, article.title.pt, article.title.en)} · RevX Paper Desk`;
  }, [article, lang]);
  if (!article) return null;
  const related = article.related.map((id) => articles.find((item) => item.slug === id)).filter((item) => item != null);

  return (
    <article className="mx-auto max-w-3xl px-4 py-14 md:px-6 md:py-20">
      <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{t(article.kicker)}</p>
      <h1 className="mt-3 text-4xl tracking-tight md:text-5xl">{t(article.title)}</h1>
      <p className="mt-4 text-lg leading-8 text-mut">{t(article.description)}</p>
      <p className="num mt-4 text-xs text-mut">
        {t(kindLabel[article.kind])} · {article.minutes} min · SIMULADO
      </p>
      <Blocks blocks={article.blocks} />
      <aside className="mt-12 border-t border-line pt-6">
        <p className="text-[11px] uppercase tracking-[0.16em] text-mut">{tx(lang, "Continuar a ler", "Keep reading")}</p>
        <div className="mt-3 grid gap-2">
          {related.map((item) => (
            <Link key={item.slug} href={`/learn/${item.slug}`} className="text-cy hover:text-white">
              {t(item.title)}
            </Link>
          ))}
        </div>
      </aside>
    </article>
  );
}

export function LearnIndex() {
  const { t, lang } = useI18n();
  return (
    <div className="mx-auto max-w-6xl px-4 py-14 md:px-6 md:py-20">
      <p className="text-[11px] uppercase tracking-[0.18em] text-cy">{tx(lang, "Aprender", "Learn")}</p>
      <h1 className="mt-3 max-w-3xl text-4xl tracking-tight md:text-6xl">
        {tx(lang, "Um blog para aprender a ler a mesa, não para copiar um trade.", "A blog for learning to read the desk, not for copying a trade.")}
      </h1>
      <p className="mt-5 max-w-2xl text-lg leading-8 text-mut">
        {tx(
          lang,
          "Textos curtos, em português, com tradução no botão EN. Todos os números são paper e vêm da amostra publicada e do relatório de 2 de novembro.",
          "Short pieces, in Portuguese first, with an EN toggle. Every number is paper and comes from the published sample and the 2 November report.",
        )}
      </p>
      <div className="mt-10 grid gap-4 md:grid-cols-2">
        {articles.map((article) => (
          <Link key={article.slug} href={`/learn/${article.slug}`} className="cardx group block p-5 transition hover:-translate-y-0.5">
            <div className="flex items-center justify-between gap-3 text-[11px] uppercase tracking-[0.16em] text-mut">
              <span>{t(kindLabel[article.kind])}</span>
              <span className="num">{article.minutes} min</span>
            </div>
            <h2 className="mt-4 text-2xl tracking-tight group-hover:text-white">{t(article.title)}</h2>
            <p className="mt-3 text-sm leading-6 text-mut">{t(article.description)}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
