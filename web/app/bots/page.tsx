import type { Metadata } from "next";
import { BotsView } from "@/components/Pages";

export const metadata: Metadata = {
  title: "Bots",
  description: "Bot D, A, B, scalpers, EMS e notícias. Tudo em paper. O Bot C está desligado.",
};

export default function Page() {
  return <BotsView />;
}
