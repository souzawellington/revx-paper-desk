import type { Copy } from "./i18n";

/**
 * Frozen teaching sample.
 * Sources: PUBLIC brief figures for 5–6 Nov 2026, and
 * examples/reports/weekly_2026-11-02.md.
 * Do not add performance numbers anywhere else.
 */

export const GITHUB_URL = "https://github.com/souzawellington/revx-paper-desk";

export type Verdict = "nogo" | "thin" | "training" | "baseline" | "off";

export type BookRow = {
  id: string;
  name: string;
  trades: string;
  win: string;
  exp: string;
  equity: string;
  verdict: Verdict;
};

export const auditorReport = {
  date: "2026-11-02",
  trades: "34",
  win: "17.6%",
  expectancy: "−0.518R",
  maxDd: "4.9%",
  equity: "9,703.14 USD",
  accelerated: { trades: "30", win: "16.7%", exp: "−0.634R" },
  normal: { trades: "4", win: "25.0%", exp: "+0.357R" },
  skipped: { trades: "1", exp: "−0.049R" },
  descriptive: {
    pf: "0.48",
    sqn: "−1.41",
    sortino: "−0.32",
    cvar: "−4.51R",
    omega: "0.48",
  },
};

export const botD = {
  equity: "$62.07",
  dd: "5.1%",
  start: "$65",
};

export const botA = {
  cappedEquity: "$63.13",
  cappedDd: "2.0%",
  cappedKill: "14%",
  openEquity: "$57.72",
  openDd: "7.7%",
  openKill: "20%",
};

export const botB = { equity: "$60.31" };

export const stops = [
  {
    pair: "FORT-USD",
    bought: "2 Nov ~22:13",
    entry: "0.0276977",
    stopped: "3 Nov ~05:08",
    exit: "0.02767",
    r: "−0.03R",
    chart: "/charts/ENTRY_P-FORT-USD-1793505600000.png",
  },
  {
    pair: "BEAM-USD",
    bought: "3 Nov ~16:16",
    entry: "0.00419148",
    stopped: "4 Nov ~02:13",
    exit: "0.00392282",
    r: "−1.03R",
    chart: "/charts/ENTRY_P-BEAM-USD-1793332800000.png",
  },
  {
    pair: "MORPHO-USD",
    bought: "4 Nov ~13:16",
    entry: "2.21511",
    stopped: "4 Nov ~14:17",
    exit: "2.1966",
    r: "−1.26R",
    chart: "/charts/ENTRY_P-MORPHO-USD-1793764800000.png",
  },
  {
    pair: "FAI-USD",
    bought: "limit 4 Nov ~22:14 · fill 5 Nov ~00:13",
    entry: "0.00209434",
    stopped: "5 Nov ~13:09",
    exit: "0.00204795",
    r: "−1.31R",
    chart: "/charts/ENTRY_P-FAI-USD-1793793600000.png",
  },
] as const;

export const scalpers: BookRow[] = [
  { id: "bb_rsi", name: "bb_rsi", trades: "311", win: "14%", exp: "−0.69R", equity: "$57.25", verdict: "nogo" },
  { id: "ema_pb", name: "ema_pb", trades: "208", win: "18%", exp: "−0.53R", equity: "$59.31", verdict: "nogo" },
  { id: "ema_pb_adx", name: "ema_pb_adx", trades: "67", win: "31%", exp: "−0.36R", equity: "$63.62", verdict: "nogo" },
  { id: "brk", name: "brk", trades: "25", win: "24%", exp: "−0.66R", equity: "$64.25", verdict: "thin" },
  { id: "bb_rsi_adx", name: "bb_rsi_adx", trades: "16", win: "12%", exp: "−0.76R", equity: "$64.57", verdict: "thin" },
  { id: "brk_adx", name: "brk_adx", trades: "2", win: "50%", exp: "−0.19R", equity: "$64.99", verdict: "thin" },
];

export const ems: BookRow[] = [
  { id: "ems_vwap_mr", name: "ems_vwap_mr", trades: "62", win: "23%", exp: "−0.43R", equity: "$62.06", verdict: "nogo" },
  { id: "ems_rsi_div", name: "ems_rsi_div", trades: "70", win: "24%", exp: "−0.43R", equity: "$61.77", verdict: "nogo" },
  { id: "ems_squeeze_bo", name: "ems_squeeze_bo", trades: "48", win: "17%", exp: "−0.54R", equity: "$62.27", verdict: "nogo" },
  { id: "ems_vwap_obi", name: "ems_vwap_obi", trades: "4/40", win: "0%", exp: "−1.00R", equity: "$64.53", verdict: "training" },
];

export const news = {
  momo: { trades: "6/40", win: "33%", exp: "−0.20R", equity: "$65.16", verdict: "training" as Verdict },
  pullback: { trades: "0/40", win: "—", exp: "—", equity: "$65.00", verdict: "training" as Verdict },
};

export const verdictCopy: Record<Verdict, Copy> = {
  nogo: { pt: "NO-GO", en: "NO-GO" },
  thin: { pt: "Poucos dados", en: "Not enough data" },
  training: { pt: "Ainda a treinar", en: "Still training" },
  baseline: { pt: "Baseline", en: "Baseline" },
  off: { pt: "Desligado", en: "Off" },
};

export const sampleNote: Copy = {
  pt: "Amostra de ensino congelada (cerca de 5–6 nov 2026, hora de Londres). Dinheiro simulado. Não atualiza e não é o seu saldo.",
  en: "Frozen teaching sample (around 5–6 Nov 2026, London time). Simulated money. It does not update, and it is not your balance.",
};
