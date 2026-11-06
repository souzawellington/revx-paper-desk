import type { Metadata } from "next";
import { ReportsView } from "@/components/Pages";

export const metadata: Metadata = {
  title: "Relatório do auditor",
  description: "Relatório semanal de paper de 2026-11-02. Veredito NO-GO, finding NO_EDGE.",
};

export default function Page() {
  return <ReportsView />;
}
