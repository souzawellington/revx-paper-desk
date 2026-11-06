import type { Metadata } from "next";
import { StartView } from "@/components/HomeView";

export const metadata: Metadata = {
  title: "Começar em paper",
  description: "Passo a passo para correr o desk em paper com dados públicos da Revolut X, sem chave de API.",
};

export default function Page() {
  return <StartView />;
}
