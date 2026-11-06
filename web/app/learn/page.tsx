import type { Metadata } from "next";
import { LearnIndex } from "@/components/ArticleView";

export const metadata: Metadata = {
  title: "Aprender",
  description: "Artigos para aprender paper trading na Revolut X: bots, custos, auditor e estudos de caso.",
};

export default function Page() {
  return <LearnIndex />;
}
