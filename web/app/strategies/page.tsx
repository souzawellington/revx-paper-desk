import type { Metadata } from "next";
import { StrategiesView } from "@/components/Pages";

export const metadata: Metadata = {
  title: "Estratégias",
  description: "Cadernos de pesquisa da mesa. Nenhum tem um GO público.",
};

export default function Page() {
  return <StrategiesView />;
}
