import type { Metadata } from "next";
import { HomeView } from "@/components/HomeView";

export const metadata: Metadata = {
  description:
    "Mesa de paper para quem começa em cripto na Revolut X. Amostra simulada, dados públicos, sem ordens reais.",
};

export default function Page() {
  return <HomeView />;
}
