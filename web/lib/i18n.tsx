"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "pt" | "en";

export type Copy = { pt: string; en: string };

type Ctx = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (copy: Copy) => string;
};

const LanguageContext = createContext<Ctx | null>(null);

export function tx(lang: Lang, pt: string, en: string) {
  return lang === "pt" ? pt : en;
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("pt");

  useEffect(() => {
    const saved = window.localStorage.getItem("revx-lang");
    if (saved === "en" || saved === "pt") setLangState(saved);
  }, []);

  const setLang = (next: Lang) => {
    setLangState(next);
    window.localStorage.setItem("revx-lang", next);
    document.documentElement.lang = next === "pt" ? "pt" : "en";
  };

  useEffect(() => {
    document.documentElement.lang = lang === "pt" ? "pt" : "en";
  }, [lang]);

  const value = useMemo<Ctx>(
    () => ({
      lang,
      setLang,
      t: (copy) => (lang === "pt" ? copy.pt : copy.en),
    }),
    [lang],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useI18n outside LanguageProvider");
  return ctx;
}
