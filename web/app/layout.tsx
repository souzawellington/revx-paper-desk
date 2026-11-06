import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { LanguageProvider } from "@/lib/i18n";
import { SiteShell } from "@/components/SiteShell";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: {
    default: "RevX Paper Desk — mesa de paper para a Revolut X",
    template: "%s · RevX Paper Desk",
  },
  description:
    "Mesa de estudo em paper para quem está a começar em cripto na Revolut X. Dados públicos, dinheiro simulado, sem ordens reais. Não é um produto oficial da Revolut e não é conselho financeiro.",
  applicationName: "RevX Paper Desk",
  keywords: ["paper trading", "Revolut X", "crypto education", "RevX Paper Desk"],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt" className={`${inter.variable} ${mono.variable}`}>
      <body className="font-sans antialiased">
        <LanguageProvider>
          <SiteShell>{children}</SiteShell>
        </LanguageProvider>
      </body>
    </html>
  );
}
