import type { Copy } from "./i18n";

export type StrategyNote = {
  id: string;
  file: string;
  title: Copy;
  body: Copy;
};

/** Research notes shipped with the engine. None of these carry a public GO. */
export const strategies: StrategyNote[] = [
  {
    id: "01",
    file: "desk/strategies/01_desk_fvg_long.md",
    title: { pt: "FVG longo da mesa", en: "Desk long FVG" },
    body: {
      pt: "A ideia principal da mesa: viragem de alta no diário, zona de fair value gap em 4h, confirmação em 1h, stop no pavio, alvo a 4R e hard stop de −8%.",
      en: "The desk’s main idea: a daily up-flip, a 4h fair-value-gap zone, a 1h confirmation, a stop at the wick, a 4R target, and the −8% hard stop.",
    },
  },
  {
    id: "02",
    file: "desk/strategies/02_sma_momentum.md",
    title: { pt: "Momentum por médias", en: "Moving-average momentum" },
    body: {
      pt: "Uma variante mais simples: seguir a direção quando médias móveis se alinham. Continua em paper.",
      en: "A simpler variant: follow direction when moving averages line up. Still paper.",
    },
  },
  {
    id: "03",
    file: "desk/strategies/03_4h_momentum_end.md",
    title: { pt: "Saída no fim do momentum 4h", en: "Exit when 4h momentum ends" },
    body: {
      pt: "Experimenta sair quando o momentum de 4 horas acaba, em vez de esperar só pelo alvo.",
      en: "Tries leaving when the 4-hour momentum ends, instead of waiting only for the target.",
    },
  },
  {
    id: "04",
    file: "desk/strategies/04_tp2r.md",
    title: { pt: "Alvo a 2R", en: "2R target" },
    body: {
      pt: "A mesma família de entrada, com a tomada de lucro mais perto: duas vezes o risco.",
      en: "The same entry family, with a closer take-profit: two times the risk.",
    },
  },
  {
    id: "05",
    file: "desk/strategies/05_tp4r.md",
    title: { pt: "Alvo a 4R", en: "4R target" },
    body: {
      pt: "Tomada de lucro mais longe, a quatro vezes o risco. Mais espaço, mais tempo exposto.",
      en: "A farther take-profit, at four times risk. More room, more time exposed.",
    },
  },
  {
    id: "06",
    file: "desk/strategies/06_fvg_panel_veto.md",
    title: { pt: "FVG com veto do painel", en: "FVG with panel veto" },
    body: {
      pt: "O plano de fair value gap passa por um painel de leituras. O painel só pode vetar ou reduzir.",
      en: "The fair-value-gap plan goes through a panel of readings. The panel may only veto or reduce.",
    },
  },
  {
    id: "07",
    file: "desk/strategies/07_fvg_panel_full.md",
    title: { pt: "FVG com painel completo", en: "FVG with the full panel" },
    body: {
      pt: "Mais votos do painel sobre o mesmo tipo de zona. Nenhum voto pode inventar uma compra.",
      en: "More panel votes on the same kind of zone. No vote is allowed to invent a buy.",
    },
  },
  {
    id: "08",
    file: "desk/strategies/08_fvg_protections.md",
    title: { pt: "FVG com proteções", en: "FVG with protections" },
    body: {
      pt: "Acrescenta a camada de proteções (limites de posições, custo, halt) por cima do plano.",
      en: "Adds the protection layer (position limits, cost, halt) on top of the plan.",
    },
  },
  {
    id: "09",
    file: "desk/strategies/09_bbandrsi.md",
    title: { pt: "Bandas de Bollinger e RSI", en: "Bollinger bands and RSI" },
    body: {
      pt: "Uma leitura de excesso: preço nas bandas e RSI esticado. É parente lento da ideia dos scalpers.",
      en: "A stretch reading: price at the bands and RSI extended. A slower cousin of the scalper idea.",
    },
  },
  {
    id: "10",
    file: "desk/strategies/10_adxmomentum.md",
    title: { pt: "Momentum com ADX", en: "Momentum with ADX" },
    body: {
      pt: "Só considera momentum quando o ADX diz que o mercado está em tendência, não em ruído.",
      en: "Only considers momentum when ADX says the market is trending, not chopping.",
    },
  },
  {
    id: "11",
    file: "desk/strategies/11_mm_as.md",
    title: { pt: "Simulação de market making", en: "Market-making simulation" },
    body: {
      pt: "Um esboço simulado no estilo Avellaneda–Stoikov. Não é um motor de cotações ao vivo.",
      en: "A simulated Avellaneda–Stoikov-style sketch. Not a live quoting engine.",
    },
  },
  {
    id: "12",
    file: "desk/strategies/12_mm_wide.md",
    title: { pt: "Market making com spread largo", en: "Wide-spread market making" },
    body: {
      pt: "A mesma família, com um spread mais largo na simulação.",
      en: "The same family, with a wider spread in the simulation.",
    },
  },
  {
    id: "13",
    file: "desk/strategies/13_sweep_best.md",
    title: { pt: "Candidato de uma varredura", en: "A sweep candidate" },
    body: {
      pt: "O nome do ficheiro guarda um candidato de uma varredura de parâmetros. O registo público não lhe dá GO.",
      en: "The filename keeps a candidate from a parameter sweep. The public record does not give it a GO.",
    },
  },
  {
    id: "14",
    file: "desk/strategies/14_xsec_lgbm_top3.md",
    title: { pt: "Ranking transversal (LightGBM)", en: "Cross-sectional rank (LightGBM)" },
    body: {
      pt: "Experiência de ordenar moedas com um modelo. Investigação, não uma estratégia validada.",
      en: "An experiment that ranks coins with a model. Research, not a validated strategy.",
    },
  },
  {
    id: "15",
    file: "desk/strategies/15_tsmom60d_presample.md",
    title: { pt: "Momentum de 60 dias (pré-amostra)", en: "60-day momentum (pre-sample)" },
    body: {
      pt: "Momentum de série temporal a 60 dias, marcado como pré-amostra. Ainda não é um teste limpo.",
      en: "Sixty-day time-series momentum, marked pre-sample. Not a clean test yet.",
    },
  },
  {
    id: "21",
    file: "desk/strategies/21_fvg_macro_veto.md",
    title: { pt: "FVG com veto macro", en: "FVG with a macro veto" },
    body: {
      pt: "O estado macro pode vetar o plano. Não pode forçar uma entrada.",
      en: "Macro state may veto the plan. It cannot force an entry.",
    },
  },
  {
    id: "22",
    file: "desk/strategies/22_fvg_macro_strict.md",
    title: { pt: "FVG com macro estrito", en: "FVG with a strict macro filter" },
    body: {
      pt: "Um filtro macro mais apertado sobre a mesma ideia de zona.",
      en: "A tighter macro filter on the same zone idea.",
    },
  },
  {
    id: "23",
    file: "desk/strategies/23_bbandrsi_macro.md",
    title: { pt: "Bollinger, RSI e macro", en: "Bollinger, RSI, and macro" },
    body: {
      pt: "Junta a leitura de bandas ao contexto macro. O macro continua a ser um travão, não um acelerador.",
      en: "Joins the band reading to macro context. Macro stays a brake, not an accelerator.",
    },
  },
  {
    id: "24",
    file: "desk/strategies/24_fvg_hrp_mv.md",
    title: { pt: "FVG com carteira HRP (média-variância)", en: "FVG with HRP portfolio (mean-variance)" },
    body: {
      pt: "Pesquisa de construção de carteira por cima dos planos. Não muda o veredito do auditor.",
      en: "Portfolio-construction research on top of the plans. It does not change the auditor’s verdict.",
    },
  },
  {
    id: "25",
    file: "desk/strategies/25_fvg_hrp_cvar.md",
    title: { pt: "FVG com carteira HRP (CVaR)", en: "FVG with HRP portfolio (CVaR)" },
    body: {
      pt: "A mesma família, com uma medida de perda de cauda (CVaR) em vez de variância.",
      en: "The same family, using a tail-loss measure (CVaR) instead of variance.",
    },
  },
  {
    id: "26",
    file: "desk/strategies/26_c3_trend_vt_unvalidated.md",
    title: { pt: "Tendência C3 — não validada", en: "C3 trend — unvalidated" },
    body: {
      pt: "O próprio ficheiro se chama unvalidated. O Bot A observa esta família em paper. Não há GO.",
      en: "The file itself is named unvalidated. Bot A watches this family on paper. There is no GO.",
    },
  },
];
