import type { Copy } from "./i18n";

export type Block =
  | { kind: "p"; text: Copy }
  | { kind: "h2"; text: Copy }
  | { kind: "h3"; text: Copy }
  | { kind: "ul"; items: Copy[] }
  | { kind: "ol"; items: Copy[] }
  | { kind: "callout"; tone: "sim" | "nogo" | "note" | "good"; title: Copy; text: Copy }
  | { kind: "table"; caption: Copy; headers: Copy[]; rows: (string | Copy)[][] }
  | { kind: "figure"; src: string; alt: Copy; caption: Copy }
  | { kind: "code"; caption: Copy; code: string }
  | { kind: "quote"; text: Copy; cite: Copy };

export type Article = {
  slug: string;
  minutes: number;
  kind: "start" | "guide" | "case" | "tips";
  title: Copy;
  description: Copy;
  kicker: Copy;
  blocks: Block[];
  related: string[];
};

const QUICKSTART = `python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m bot --demo
python -m bot`;

export const articles: Article[] = [
  {
    slug: "como-comecar",
    minutes: 7,
    kind: "start",
    title: {
      pt: "Como começar no paper trading na Revolut X",
      en: "How to start paper trading on Revolut X",
    },
    description: {
      pt: "O que é paper, o que a Revolut X publica sem chave, e os comandos que ficam em simulação.",
      en: "What paper means, what Revolut X publishes without a key, and the commands that stay simulated.",
    },
    kicker: { pt: "Primeiro passo", en: "First step" },
    related: ["dicas-para-iniciantes", "os-bots", "por-que-no-go"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "Paper trading é um ensaio com dinheiro imaginário e preços reais. Você vê o mercado, o bot escreve uma decisão, e nenhuma ordem sai da máquina. É assim que este projeto abre: sem chave, sem depósito, sem a sensação falsa de que um gráfico verde já é uma estratégia.",
          en: "Paper trading is a rehearsal with imaginary money and real prices. You see the market, the bot writes a decision, and no order leaves the machine. That is how this project opens: no key, no deposit, and no false feeling that a green chart is already a strategy.",
        },
      },
      {
        kind: "callout",
        tone: "sim",
        title: { pt: "SIMULADO, de propósito", en: "Simulated, on purpose" },
        text: {
          pt: "O modo por defeito é paper. `BOT_DRY_RUN` começa em 1 e, enquanto estiver assim, o broker simulado é o que corre. Este guia não traz um comando para ligar dinheiro real.",
          en: "The default mode is paper. `BOT_DRY_RUN` starts at 1, and while it stays there the simulated broker is what runs. This guide does not include a command that turns real money on.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O que a Revolut X é, neste projeto", en: "What Revolut X is, in this project" },
      },
      {
        kind: "p",
        text: {
          pt: "A Revolut X, aqui, é uma exchange de cripto à vista. Este código não usa alavancagem e não abre shorts. Há dois preços de taxa que vale a pena memorizar antes de qualquer indicador: maker 0% e taker 0,09%. O paper ainda soma slippage de 5 a 15 pontos-base e o spread do livro. Uma ideia que não paga isso não é uma ideia.",
          en: "Revolut X, here, is a spot crypto exchange. This code does not use leverage and does not open shorts. Two fees are worth memorising before any indicator: maker 0% and taker 0.09%. Paper mode also adds 5–15 basis points of slippage and the book spread. An idea that cannot pay for that is not an idea.",
        },
      },
      {
        kind: "ul",
        items: [
          {
            pt: "À vista apenas. Sem alavancagem neste projeto.",
            en: "Spot only. No leverage in this project.",
          },
          {
            pt: "Maker 0%. Taker 0,09%.",
            en: "Maker 0%. Taker 0.09%.",
          },
          {
            pt: "O paper modela essas taxas, mais 5–15 bps de slippage, mais o spread.",
            en: "Paper mode models those fees, plus 5–15 bps of slippage, plus the spread.",
          },
          {
            pt: "Dados públicos (velas, tickers, regras dos pares) não pedem chave de API.",
            en: "Public data (candles, tickers, pair rules) does not ask for an API key.",
          },
        ],
      },
      {
        kind: "h2",
        text: { pt: "Cinco minutos, ainda em paper", en: "Five minutes, still on paper" },
      },
      {
        kind: "ol",
        items: [
          {
            pt: "Clone o repositório e entre na pasta.",
            en: "Clone the repository and enter the folder.",
          },
          {
            pt: "Crie um ambiente virtual e instale `requirements.txt`.",
            en: "Create a virtual environment and install `requirements.txt`.",
          },
          {
            pt: "Corra os testes. Eles usam HTTP simulado, não a sua conta.",
            en: "Run the tests. They use mocked HTTP, not your account.",
          },
          {
            pt: "`python -m bot --demo` faz um ciclo com dados sintéticos.",
            en: "`python -m bot --demo` runs one cycle on synthetic data.",
          },
          {
            pt: "`python -m bot` repete o ciclo com dados públicos da Revolut X. Continua sem credenciais.",
            en: "`python -m bot` repeats the cycle with public Revolut X data. Still no credentials.",
          },
        ],
      },
      { kind: "code", caption: { pt: "Comandos por defeito", en: "Default commands" }, code: QUICKSTART },
      {
        kind: "h2",
        text: { pt: "A primeira resposta honesta: HOLD", en: "The first honest answer: HOLD" },
      },
      {
        kind: "p",
        text: {
          pt: "Sem um ledger de backtest ligado, o motor responde `INSUFFICIENT_DATA` e fica em HOLD. Não inventa uma vantagem para ter alguma coisa para fazer. Essa recusa é a regra, não um bug. Se um bot lhe parece ocupado demais no primeiro dia, desconfie do bot, não da pausa.",
          en: "Without a connected backtest ledger, the engine answers `INSUFFICIENT_DATA` and stays on HOLD. It does not invent an edge just to have something to do. That refusal is the rule, not a bug. If a bot looks too busy on day one, distrust the bot, not the pause.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O que este começo não é", en: "What this start is not" },
      },
      {
        kind: "ul",
        items: [
          {
            pt: "Não é um produto oficial da Revolut.",
            en: "It is not an official Revolut product.",
          },
          {
            pt: "Não é conselho financeiro, nem um convite para copiar um trade de paper.",
            en: "It is not financial advice, and not an invitation to copy a paper trade.",
          },
          {
            pt: "Não liga ordens reais. O caminho público acaba no paper.",
            en: "It does not place real orders. The public path ends at paper.",
          },
          {
            pt: "Não promete que uma estratégia vai passar no auditor. Até agora, a maior parte não passou.",
            en: "It does not promise that a strategy will pass the auditor. So far, most have not.",
          },
        ],
      },
    ],
  },
  {
    slug: "os-bots",
    minutes: 8,
    kind: "guide",
    title: {
      pt: "Os bots: D, A, B, scalpers, EMS e notícias",
      en: "The bots: D, A, B, scalpers, EMS, and news",
    },
    description: {
      pt: "Um mapa simples de cada livro simulado, e o que o Bot C não é.",
      en: "A plain map of each simulated book, and what Bot C is not.",
    },
    kicker: { pt: "Mapa da mesa", en: "Desk map" },
    related: ["estrategias", "bot-de-noticias", "moedas-pouco-negociadas"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "Há vários livros em paper porque uma pergunta só — “isto ganha?” — é preguiçosa. Cada bot faz uma pergunta menor. Nenhum está validado para dinheiro real. Os números abaixo são a amostra de ensino de início de novembro de 2026, com livros que começaram perto de 65 dólares simulados.",
          en: "There are several paper books because a single question — “does this make money?” — is lazy. Each bot asks a smaller question. None is validated for real money. The figures below are the early-November 2026 teaching sample, from books that started near 65 simulated dollars.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Bot D, o executor da mesa", en: "Bot D, the desk executor" },
      },
      {
        kind: "p",
        text: {
          pt: "O Bot D procura entradas por zonas em pares da Revolut X. Arrisca cerca de 1% do equity por trade e não passa de 15% numa só moeda. Prefere entradas limite, do lado maker. Na amostra, o livro estava perto de 62,07 dólares, com drawdown de cerca de 5,1%, e sem posição aberta depois do último stop.",
          en: "Bot D looks for zone entries on Revolut X pairs. It risks about 1% of equity per trade and will not put more than 15% into one coin. It prefers limit entries, on the maker side. In the sample the book was about $62.07, drawdown about 5.1%, with no open position after the last stop.",
        },
      },
      {
        kind: "p",
        text: {
          pt: "Há filtros que ele observa e ainda não bloqueia: volume em 24h abaixo de 50 mil dólares, spread acima de 0,50%, tendência de 4h fraca ou regime do BTC fraco, e macro em CAUTION. Observar não é o mesmo que impedir. O estudo das moedas pouco negociadas mostra o que acontece quando o aviso fica só no diário.",
          en: "Some filters are watched and not yet blocking: 24h volume below $50k, spread above 0.50%, a weak 4h trend or BTC regime, and macro CAUTION. Watching is not the same as stopping. The thin-coin study shows what happens when the warning stays in the diary.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Bot A, a mesma ideia duas vezes", en: "Bot A, the same idea twice" },
      },
      {
        kind: "p",
        text: {
          pt: "O Bot A é a sombra C3: dois livros paper da mesma estratégia diária. Um com teto de 12,5% por moeda, outro sem esse teto. Por volta das 19:00 de 5 de novembro, o livro com teto estava perto de 63,13 dólares (drawdown ~2,0%, kill 14%). O livro sem teto estava perto de 57,72 dólares (drawdown ~7,7%, kill 20%). Não está validado.",
          en: "Bot A is the C3 shadow: two paper books of the same daily strategy. One with a 12.5% per-coin cap, one without that cap. Around 19:00 on 5 November, the capped book was about $63.13 (drawdown ~2.0%, kill 14%). The uncapped book was about $57.72 (drawdown ~7.7%, kill 20%). It is not validated.",
        },
      },
      {
        kind: "p",
        text: {
          pt: "Na noite de 5 para 6 de novembro, esses livros C3 também registaram vendas paper `STOP_8PCT` em BTC e ETH. Serve só para uma frase: o hard stop de −8% também pode disparar na estratégia diária.",
          en: "On the night of 5–6 November, those C3 books also recorded paper `STOP_8PCT` sells on BTC and ETH. It supports one sentence: the −8% hard stop can fire on the daily strategy too.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Bot B, só para comparar", en: "Bot B, only for comparison" },
      },
      {
        kind: "p",
        text: {
          pt: "O Bot B segura BTC. Não tenta ser esperto. A pergunta dele é: a estratégia bateu o gesto mais simples, que é ficar em bitcoin? Na mesma amostra, esse livro estava perto de 60,31 dólares. Um bot que perde para “não fazer nada de especial” ainda não mereceu complexidade.",
          en: "Bot B just holds BTC. It does not try to be clever. Its question is: did the strategy beat the simplest act, which is sitting in bitcoin? In the same sample that book was about $60.31. A bot that loses to “don’t do anything special” has not earned its complexity.",
        },
      },
      {
        kind: "callout",
        tone: "note",
        title: { pt: "Bot C está desligado", en: "Bot C is off" },
        text: {
          pt: "O Bot C não está disponível. Não há modo escondido, nem flag de demonstração. Se um texto o tratar como produto, está errado.",
          en: "Bot C is not available. There is no hidden mode and no demo flag. If a write-up treats it as a product, that write-up is wrong.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Seis scalpers, em minutos", en: "Six scalpers, on minutes" },
      },
      {
        kind: "p",
        text: {
          pt: "Os scalpers olham para BTC, ETH e SOL em velas de 1 ou 5 minutos. As regras que lhes deram: stop no mais apertado entre 0,4% e 1,5×ATR(14); relação mínima de 1,5R; kill diário a −2%; no máximo 5 posições; rejeitar um sinal que não cubra custos e slippage.",
          en: "The scalpers watch BTC, ETH, and SOL on 1- or 5-minute candles. The rules they were given: stop at the tighter of 0.4% and 1.5×ATR(14); minimum reward-to-risk 1.5; a daily kill at −2%; at most 5 positions; reject a signal that does not cover costs and slippage.",
        },
      },
      {
        kind: "table",
        caption: { pt: "Scalpers na amostra. Nenhum está validado.", en: "Scalpers in the sample. None is validated." },
        headers: [
          { pt: "Livro", en: "Book" },
          { pt: "Trades", en: "Trades" },
          { pt: "Acerto", en: "Win rate" },
          { pt: "Expectancy", en: "Expectancy" },
          { pt: "Equity", en: "Equity" },
          { pt: "Estado", en: "State" },
        ],
        rows: [
          ["bb_rsi · Bollinger + RSI, 1m", "311", "14%", "−0.69R", "$57.25", "NO-GO"],
          ["bb_rsi_adx", "16", "12%", "−0.76R", "$64.57", { pt: "Poucos dados", en: "Not enough data" }],
          ["ema_pb · pullback de EMA, 5m", "208", "18%", "−0.53R", "$59.31", "NO-GO"],
          ["ema_pb_adx", "67", "31%", "−0.36R", "$63.62", "NO-GO"],
          ["brk · breakout, 1m", "25", "24%", "−0.66R", "$64.25", { pt: "Poucos dados", en: "Not enough data" }],
          ["brk_adx", "2", "50%", "−0.19R", "$64.99", { pt: "Poucos dados", en: "Not enough data" }],
        ],
      },
      {
        kind: "p",
        text: {
          pt: "O `bb_rsi` chegou ao kill automático de −2% por volta das 15:53 de Londres, no dia 5 de novembro, e ficou em pausa o resto desse dia. O travão funcionou. A estratégia, mesmo assim, está NO-GO.",
          en: "bb_rsi hit the automatic −2% daily kill around 15:53 London time on 5 November and stayed paused for the rest of that day. The brake worked. The strategy is still NO-GO.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Quatro livros EMS", en: "Four EMS books" },
      },
      {
        kind: "p",
        text: {
          pt: "EMS aqui quer dizer microestrutura de execução, num horizonte mais curto: reversão à VWAP, VWAP com desequilíbrio do livro, divergência de RSI, e breakout depois de uma compressão de volatilidade. Também não estão validados.",
          en: "EMS here means execution microstructure, on a shorter horizon: VWAP mean reversion, VWAP plus order-book imbalance, RSI divergence, and a breakout after a volatility squeeze. They are not validated either.",
        },
      },
      {
        kind: "table",
        caption: { pt: "EMS na amostra.", en: "EMS in the sample." },
        headers: [
          { pt: "Livro", en: "Book" },
          { pt: "Trades", en: "Trades" },
          { pt: "Acerto", en: "Win rate" },
          { pt: "Expectancy", en: "Expectancy" },
          { pt: "Equity", en: "Equity" },
          { pt: "Estado", en: "State" },
        ],
        rows: [
          ["ems_vwap_mr", "62", "23%", "−0.43R", "$62.06", "NO-GO"],
          ["ems_rsi_div", "70", "24%", "−0.43R", "$61.77", "NO-GO"],
          ["ems_squeeze_bo", "48", "17%", "−0.54R", "$62.27", "NO-GO"],
          ["ems_vwap_obi", "4/40", "0%", "−1.00R", "$64.53", { pt: "A treinar", en: "Still training" }],
        ],
      },
      {
        kind: "h2",
        text: { pt: "Dois livros de notícias", en: "Two news books" },
      },
      {
        kind: "p",
        text: {
          pt: "`news_momo` tenta entrar com o momentum e o volume que acompanham uma notícia. `news_pullback` tenta um limite no recuo depois da mesma notícia. Na amostra: momo 6/40, acerto 33%, −0,20R, equity cerca de 65,16 dólares; pullback 0/40, equity 65,00, porque um sinal chegou a ser aceite e o limite não encheu. O capítulo próprio conta o caso do XRP e as recusas.",
          en: "news_momo tries to enter with the momentum and volume that follow a headline. news_pullback tries a limit on the dip after the same headline. In the sample: momo 6/40, 33% wins, −0.20R, equity about $65.16; pullback 0/40, equity $65.00, because a signal was accepted once and the limit did not fill. Its own chapter tells the XRP case and the refusals.",
        },
      },
    ],
  },
  {
    slug: "estrategias",
    minutes: 8,
    kind: "guide",
    title: {
      pt: "As estratégias, sem jargão inútil",
      en: "The strategies, without useless jargon",
    },
    description: {
      pt: "As regras que todas as ideias têm de atravessar, explicadas como se fosse a primeira vez.",
      en: "The rules every idea has to walk through, explained as if it were the first time.",
    },
    kicker: { pt: "Regras, não feitiços", en: "Rules, not spells" },
    related: ["relatorio-do-auditor", "dicas-para-iniciantes", "os-bots"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "Uma estratégia, neste projeto, não é um nome bonito no gráfico. É uma hipótese que tem de pagar os custos, caber num tamanho pequeno, e sobreviver a um auditor que não é seu amigo. Os cadernos em `desk/strategies/` são notas de pesquisa. Nenhum deles traz um GO público.",
          en: "A strategy, in this project, is not a pretty name on a chart. It is a hypothesis that has to pay its costs, fit in a small size, and survive an auditor who is not your friend. The notes in `desk/strategies/` are research notes. None of them carries a public GO.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O portão do valor esperado", en: "The expected-value gate" },
      },
      {
        kind: "p",
        text: {
          pt: "Antes de comprar, o motor pergunta se o trade ainda vale alguma coisa depois das taxas e do slippage. Se a resposta for não, não há trade. “O padrão é bonito” não entra na conta.",
          en: "Before a buy, the engine asks whether the trade is still worth anything after fees and slippage. If the answer is no, there is no trade. “The pattern looks nice” does not enter the sum.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Tamanho: um quarto de Kelly, teto 15%", en: "Size: quarter-Kelly, 15% cap" },
      },
      {
        kind: "p",
        text: {
          pt: "Kelly é uma fórmula de tamanho de aposta a partir da vantagem e das perdas. Usá-la inteira é agressivo demais para quem está a aprender, por isso o projeto usa um quarto. E mesmo isso esbarra num teto: 15% do equity numa só moeda. O Bot D arrisca cerca de 1% por trade. Pequeno de propósito.",
          en: "Kelly is a bet-size formula based on edge and losses. Using all of it is too aggressive for someone learning, so the project uses a quarter. Even that hits a ceiling: 15% of equity in one coin. Bot D risks about 1% per trade. Small on purpose.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O stop que não se negocia", en: "The stop that is not up for debate" },
      },
      {
        kind: "p",
        text: {
          pt: "Há um hard stop de −8% a partir da entrada ou do pico local, e também um stop por ATR (a volatilidade recente, medida pelo Average True Range). Se os dados não chegam, a decisão é HOLD. Inventar um número para “não ficar de fora” é exatamente o que o motor recusa.",
          en: "There is a hard stop of −8% from the entry or the local peak, and also an ATR stop (recent volatility, measured by Average True Range). If the data is not there, the decision is HOLD. Inventing a number so you “don’t miss it” is exactly what the engine refuses.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Quando a carteira inteira adoece", en: "When the whole book gets sick" },
      },
      {
        kind: "p",
        text: {
          pt: "Drawdown é a queda desde um pico. O projeto pode REDUZIR o risco ou SUSPENDER entradas novas. Nas regras escritas da mesa, uma queda diária de 3% trava entradas novas; a partir de 15% de queda desde o pico o risco vai a metade; a partir de 30% a mesa suspende. Os scalpers têm um kill ainda mais curto, de −2% no dia. Circuit breakers existem para o dia mau não virar uma semana de teimosia.",
          en: "Drawdown is the fall from a peak. The project can REDUCE risk or SUSPEND new entries. In the desk’s written rules, a 3% down day halts new entries; from a 15% drop off the peak, risk is cut in half; from 30%, the desk suspends. The scalpers have an even shorter kill, −2% on the day. Circuit breakers exist so a bad day does not become a stubborn week.",
        },
      },
      {
        kind: "h2",
        text: { pt: "A camada de linguagem só diz não", en: "The language layer only says no" },
      },
      {
        kind: "p",
        text: {
          pt: "Se ligar um modelo de linguagem, ele pode vetar ou reduzir. Não pode inventar uma compra, não dimensiona a posição, e não salta o auditor. Um texto convincente não é uma estatística.",
          en: "If you switch a language model on, it may veto or reduce. It cannot invent a buy, it does not size the position, and it does not skip the auditor. A convincing paragraph is not a statistic.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Fair value gap, em uma frase", en: "Fair value gap, in one sentence" },
      },
      {
        kind: "p",
        text: {
          pt: "Um fair value gap é um buraco entre velas: o preço andou tão depressa que deixou uma zona onde quase não houve negócio. A mesa de zonas trata esse buraco como um sítio possível de retorno, só depois de uma viragem diária e de uma confirmação em 1h. É uma hipótese. O relatório de 2 de novembro diz que, até ali, a hipótese não tinha edge.",
          en: "A fair value gap is a hole between candles: price moved so fast it left a zone where almost no trade happened. The zone desk treats that hole as a possible place for a return, only after a daily flip and a 1h confirmation. It is a hypothesis. The 2 November report says that, up to then, the hypothesis had no edge.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O selo que quase ninguém merece", en: "The stamp almost nobody deserves" },
      },
      {
        kind: "p",
        text: {
          pt: "Uma estratégia fica em paper até ter, ao mesmo tempo, pelo menos 40 trades fechados, acerto de pelo menos 33%, média de pelo menos +0,4R por trade, e drawdown máximo de no máximo 20%. Falhou depois dos 40? É NO-GO. Continua em paper. Não se afina o bot só para perseguir o selo.",
          en: "A strategy stays on paper until it has, at the same time, at least 40 closed trades, a win rate of at least 33%, an average of at least +0.4R per trade, and a max drawdown of at most 20%. Failed after 40? That is a NO-GO. It stays on paper. You do not retune the bot just to chase the stamp.",
        },
      },
      {
        kind: "p",
        text: {
          pt: "A página Estratégias lista cada caderno em linguagem simples. Leia-os como experiências com nome, não como um menu de coisas que funcionam.",
          en: "The Strategies page lists each note in plain language. Read them as named experiments, not as a menu of things that work.",
        },
      },
    ],
  },
  {
    slug: "bot-de-noticias",
    minutes: 7,
    kind: "case",
    title: {
      pt: "O bot de notícias: o que ele lê, o que ele recusa, e o caso do XRP",
      en: "The news bot: what it reads, what it refuses, and the XRP case",
    },
    description: {
      pt: "Manchetes públicas, um ganho pequeno em paper, e várias recusas que são o comportamento certo.",
      en: "Public headlines, a small paper win, and several refusals that are the right behavior.",
    },
    kicker: { pt: "Estudo de caso", en: "Case study" },
    related: ["dicas-para-iniciantes", "os-bots", "por-que-no-go"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "O bot de notícias lê manchetes públicas, dá uma nota às moedas, e só então pensa numa entrada. Há dois livros. `news_momo` entra a favor do movimento e do volume. `news_pullback` tenta comprar o recuo com uma ordem limite. Os dois podem recusar. Recusar é parte do trabalho.",
          en: "The news bot reads public headlines, scores coins, and only then thinks about an entry. There are two books. news_momo enters with the move and the volume. news_pullback tries to buy the dip with a limit order. Both are allowed to refuse. Refusing is part of the job.",
        },
      },
      {
        kind: "ul",
        items: [
          {
            pt: "Volume fraco: fora.",
            en: "Weak volume: out.",
          },
          {
            pt: "Spread largo: fora.",
            en: "Wide spread: out.",
          },
          {
            pt: "Uma manchete negativa recente pode vetar, mesmo que outro sinal esteja verde.",
            en: "A recent negative headline can veto, even if another signal is green.",
          },
          {
            pt: "Não há obrigação de ter um trade por dia.",
            en: "There is no duty to have a trade every day.",
          },
        ],
      },
      {
        kind: "h2",
        text: { pt: "O XRP que subiu apesar do título cético", en: "The XRP that rose despite a skeptical headline" },
      },
      {
        kind: "p",
        text: {
          pt: "No dia 4 de novembro, uma manchete dizia que a subida da contagem de “baleias” de XRP era um sinal de alta falso. O livro `news_momo` entrou mesmo assim, por volta das 14:58, porque o volume e o momentum estavam lá — não porque o título fosse otimista. O alvo chegou por volta das 15:08. Resultado de paper: cerca de +1,33R, mais 0,32 dólares simulados.",
          en: "On 4 November, a headline said that rising XRP “whale” counts were a fake bullish signal. The news_momo book entered anyway, around 14:58, because volume and momentum were there — not because the headline was cheerful. The target arrived around 15:08. Paper result: about +1.33R, plus $0.32 simulated.",
        },
      },
      {
        kind: "callout",
        tone: "note",
        title: { pt: "Um bom exemplo continua pequeno", en: "A good example is still small" },
        text: {
          pt: "Trinta e dois cêntimos simulados não são uma carreira. O livro, na amostra, tinha 6 trades de 40, acerto de 33% e expectancy de −0,20R, com equity cerca de 65,16 dólares. O acerto encosta na régua de 33%. A expectancy não encosta em +0,4R. Não há GO.",
          en: "Thirty-two simulated cents are not a career. In the sample the book had 6 trades out of 40, a 33% win rate, and expectancy of −0.20R, with equity about $65.16. The win rate touches the 33% ruler. Expectancy does not touch +0.4R. There is no GO.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O que ainda estava aberto no boletim", en: "What was still open in the bulletin" },
      },
      {
        kind: "p",
        text: {
          pt: "No boletim das 19:00 de 5 de novembro, duas entradas de paper ainda estavam abertas. ETH, por volta das 16:13, ligada a uma notícia da Anchorage Digital a pedir registo de swap dealer na CFTC para opções de cripto. AAVE, por volta das 16:22, ligada a um fundo associado à Payward/Kraken a comprar uma participação. Isto é um retrato daquela hora. Não é uma posição para copiar, e não é dinheiro real.",
          en: "In the 19:00 bulletin on 5 November, two paper entries were still open. ETH, around 16:13, tied to a headline about Anchorage Digital requesting CFTC swap-dealer registration for crypto options. AAVE, around 16:22, tied to a Payward/Kraken-linked fund buying a stake. That is a picture of that hour. It is not a position to copy, and it is not real money.",
        },
      },
      {
        kind: "h2",
        text: { pt: "As recusas são a parte adulta", en: "The refusals are the grown-up part" },
      },
      {
        kind: "p",
        text: {
          pt: "BTC foi vetado por uma manchete negativa recente. CC, INJ e SOL foram recusados por volume fraco ou spread largo. O bot não forçou a entrada para “não perder o dia”. `news_pullback`, no mesmo retrato, tinha 0 trades fechados em 40 e equity de 65,00 dólares: houve pelo menos um sinal aceite cujo limite não encheu. Não encher também é um resultado. Esperar um preço e não o conseguir é melhor do que pagar o que quer que seja.",
          en: "BTC was vetoed by a recent negative headline. CC, INJ, and SOL were rejected for weak volume or a wide spread. The bot did not force an entry so it “wouldn’t miss the day.” news_pullback, in the same picture, had 0 closed trades out of 40 and equity of $65.00: at least one signal was accepted and its limit did not fill. Not filling is also a result. Waiting for a price and missing it is better than paying whatever is asked.",
        },
      },
    ],
  },
  {
    slug: "relatorio-do-auditor",
    minutes: 8,
    kind: "guide",
    title: {
      pt: "Como ler um relatório do auditor",
      en: "How to read an auditor report",
    },
    description: {
      pt: "A tabela de 2 de novembro, linha a linha, e por que NO-GO é a frase útil.",
      en: "The 2 November table, line by line, and why NO-GO is the useful sentence.",
    },
    kicker: { pt: "Ler números", en: "Reading numbers" },
    related: ["por-que-no-go", "estrategias", "moedas-pouco-negociadas"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "O auditor não é um comentador. Compara o livro com quatro limiares congelados e escreve uma de três etiquetas: DATA_VALIDATED, TRADE_OFF ou NO_EDGE. Não sugere “mexer só um pouco no stop”. O relatório de ensino está em `examples/reports/weekly_2026-11-02.md`.",
          en: "The auditor is not a commentator. It compares the book with four frozen thresholds and writes one of three labels: DATA_VALIDATED, TRADE_OFF, or NO_EDGE. It does not suggest “nudging the stop a little.” The teaching report is in `examples/reports/weekly_2026-11-02.md`.",
        },
      },
      {
        kind: "table",
        caption: {
          pt: "Relatório semanal do desk — 2026-11-02. Paper.",
          en: "Weekly desk report — 2026-11-02. Paper.",
        },
        headers: [
          { pt: "Métrica", en: "Metric" },
          { pt: "Valor", en: "Value" },
          { pt: "Limiar", en: "Threshold" },
          { pt: "Estado", en: "State" },
        ],
        rows: [
          ["Trades (paper)", "34", "≥ 40", { pt: "FALHA", en: "FAIL" }],
          ["Win rate", "17.6%", "≥ 33%", { pt: "FALHA", en: "FAIL" }],
          ["Expectancy", "−0.518R", "≥ +0.4R", { pt: "FALHA", en: "FAIL" }],
          ["Max DD", "4.9%", "≤ 20%", { pt: "PASSA", en: "PASS" }],
        ],
      },
      {
        kind: "quote",
        text: {
          pt: "Veredito: NO-GO (continuar em paper). Finding: NO_EDGE.",
          en: "Verdict: NO-GO (stay on paper). Finding: NO_EDGE.",
        },
        cite: { pt: "weekly_2026-11-02.md", en: "weekly_2026-11-02.md" },
      },
      {
        kind: "h2",
        text: { pt: "Linha a linha", en: "Line by line" },
      },
      {
        kind: "ul",
        items: [
          {
            pt: "Trades. 34 fechados. A régua pede 40. Abaixo disso, o veredito nem deveria ser uma festa: a amostra ainda é curta, e mesmo assim o resto já falha.",
            en: "Trades. 34 closed. The ruler asks for 40. Below that, the verdict should not be a party: the sample is still short, and the rest already fails.",
          },
          {
            pt: "Win rate. 17,6% das saídas foram ganhos. A régua pede 33%. Acertar pouco pode ser aceitável se os ganhos forem grandes. Aqui não foram.",
            en: "Win rate. 17.6% of exits were wins. The ruler asks for 33%. Winning rarely can be fine if the wins are large. Here they were not.",
          },
          {
            pt: "Expectancy. −0,518R é a média por trade, em múltiplos do risco. Negativo quer dizer: em média, cada trade devolveu cerca de metade de um risco a menos. A régua pede +0,4R.",
            en: "Expectancy. −0.518R is the average per trade, in multiples of risk. Negative means: on average, each trade gave back about half a risk. The ruler asks for +0.4R.",
          },
          {
            pt: "Max DD. 4,9% de queda máxima. A régua aceita até 20%. Esta linha passa. Uma linha verde não salva três vermelhas.",
            en: "Max DD. A 4.9% maximum drop. The ruler allows up to 20%. This line passes. One green line does not save three red ones.",
          },
        ],
      },
      {
        kind: "h2",
        text: { pt: "O ensaio acelerado não muda a frase", en: "The accelerated trial does not change the sentence" },
      },
      {
        kind: "p",
        text: {
          pt: "O ficheiro separa um ensaio acelerado (paper_fast, até 10 posições, o mesmo risco de 1%): 30 trades, acerto 16,7%, −0,634R. Os trades normais foram 4, acerto 25,0%, +0,357R. O veredito junta os dois. Só com os normais, também seria NO-GO. Houve ainda 1 alerta SKIPPED hipotético, com expectancy de −0,049R.",
          en: "The file separates an accelerated trial (paper_fast, up to 10 positions, the same 1% risk): 30 trades, 16.7% wins, −0.634R. The normal trades were 4, 25.0% wins, +0.357R. The verdict counts both. Normals alone would still be NO-GO. There was also 1 hypothetical SKIPPED alert, with expectancy of −0.049R.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Números que descrevem e não mandam", en: "Numbers that describe and do not decide" },
      },
      {
        kind: "p",
        text: {
          pt: "O relatório acrescenta métricas descritivas, e diz que elas não mudam o GO: profit factor 0,48, SQN −1,41, Sortino sobre R −0,32, CVaR 95 −4,51R, Omega 0,48. Profit factor abaixo de 1 significa que o dinheiro dos ganhos não cobriu o dos perdas. O resto aponta para o mesmo lado. Nenhum deles abre uma exceção.",
          en: "The report adds descriptive metrics, and says they do not change the GO: profit factor 0.48, SQN −1.41, Sortino on R −0.32, CVaR 95 −4.51R, Omega 0.48. A profit factor under 1 means win money did not cover loss money. The rest points the same way. None of them opens an exception.",
        },
      },
      {
        kind: "callout",
        tone: "note",
        title: { pt: "Dois equities, duas etiquetas", en: "Two equities, two labels" },
        text: {
          pt: "Esse ficheiro regista equity paper de 9.703,14 USD no livro que auditou. A amostra de 5–6 de novembro, nos capítulos dos bots, usa livros que começaram perto de 65 dólares. São retratos com etiquetas diferentes. Não os some. Não os troque.",
          en: "That file records paper equity of 9,703.14 USD on the book it audited. The 5–6 November sample, in the bot chapters, uses books that started near $65. They are pictures with different labels. Do not add them. Do not swap them.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O que fazer com um NO-GO", en: "What to do with a NO-GO" },
      },
      {
        kind: "p",
        text: {
          pt: "Continuar em paper. Não procurar o parâmetro que teria passado. Um limiar que se muda depois de ver o resultado deixa de ser um limiar. A honestidade desta mesa é publicar a falha com o mesmo tipo de letra da hipótese.",
          en: "Stay on paper. Do not hunt for the parameter that would have passed. A threshold you move after seeing the result stops being a threshold. The honesty of this desk is publishing the failure in the same type size as the hypothesis.",
        },
      },
    ],
  },
  {
    slug: "moedas-pouco-negociadas",
    minutes: 9,
    kind: "case",
    title: {
      pt: "Estudo de caso: FORT, BEAM, MORPHO e FAI (moedas pouco negociadas)",
      en: "Case study: FORT, BEAM, MORPHO, and FAI (thinly traded coins)",
    },
    description: {
      pt: "Quatro stops de paper, os gráficos de entrada reais da mesa, e um filtro que só observava.",
      en: "Four paper stops, the desk’s real entry charts, and a filter that was only watching.",
    },
    kicker: { pt: "Estudo de caso", en: "Case study" },
    related: ["os-bots", "dicas-para-iniciantes", "por-que-no-go"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "O Bot D, na amostra de início de novembro, saiu de quatro moedas pouco negociadas por stop. Nenhuma destas linhas é uma perda de dinheiro real. São o diário de um livro que começou perto de 65 dólares simulados e, depois do último stop, ficou sem posição aberta, com equity cerca de 62,07 dólares e drawdown cerca de 5,1%.",
          en: "Bot D, in the early-November sample, left four thinly traded coins by stop. None of these lines is a real-money loss. They are the diary of a book that started near 65 simulated dollars and, after the last stop, had no open position, with equity about $62.07 and drawdown about 5.1%.",
        },
      },
      {
        kind: "callout",
        tone: "sim",
        title: { pt: "Gráficos de entrada, não ilustrações novas", en: "Entry charts, not new illustrations" },
        text: {
          pt: "As quatro imagens são os gráficos de entrada em paper gerados pela mesa (FORT, BEAM, MORPHO, FAI). Não foram redesenhados. As linhas de plano no gráfico e o preço de execução no diário podem diferir um pouco: o plano marca a zona; o diário marca o preço simulado.",
          en: "The four images are the paper entry charts the desk generated (FORT, BEAM, MORPHO, FAI). They were not redrawn. The plan lines on the chart and the fill in the diary can differ a little: the plan marks the zone; the diary marks the simulated price.",
        },
      },
      {
        kind: "h2",
        text: { pt: "FORT-USD, quase plano", en: "FORT-USD, almost flat" },
      },
      {
        kind: "p",
        text: {
          pt: "Compra simulada em 2 de novembro, por volta das 22:13, a 0,0276977. Stop em 3 de novembro, por volta das 05:08, a 0,02767. Cerca de −0,03R. O preço mal se mexeu, e mesmo assim o trade gastou uma noite.",
          en: "Simulated buy on 2 November, around 22:13, at 0.0276977. Stop on 3 November, around 05:08, at 0.02767. About −0.03R. Price barely moved, and the trade still spent a night.",
        },
      },
      {
        kind: "figure",
        src: "/charts/ENTRY_P-FORT-USD-1793505600000.png",
        alt: {
          pt: "Gráfico de velas da entrada em paper de FORT-USD, com linhas de entrada, stop e alvo, e zonas marcadas como usadas ou expiradas.",
          en: "Candlestick chart of the FORT-USD paper entry, with entry, stop, and target lines, and zones marked used or expired.",
        },
        caption: {
          pt: "FORT-USD. Gráfico de entrada em paper da mesa. Compra simulada 0,0276977, stop 0,02767, cerca de −0,03R.",
          en: "FORT-USD. The desk’s paper entry chart. Simulated buy 0.0276977, stop 0.02767, about −0.03R.",
        },
      },
      {
        kind: "h2",
        text: { pt: "BEAM-USD, um risco inteiro", en: "BEAM-USD, a full risk" },
      },
      {
        kind: "p",
        text: {
          pt: "Compra em 3 de novembro, por volta das 16:16, a 0,00419148. Stop em 4 de novembro, por volta das 02:13, a 0,00392282. Cerca de −1,03R. Aqui o stop fez o trabalho para o qual existe: limitou a perda a cerca de um risco, em vez de deixar a moeda contar a história até ao fim.",
          en: "Buy on 3 November, around 16:16, at 0.00419148. Stop on 4 November, around 02:13, at 0.00392282. About −1.03R. Here the stop did the job it exists for: it capped the loss near one risk, instead of letting the coin tell the story to the end.",
        },
      },
      {
        kind: "figure",
        src: "/charts/ENTRY_P-BEAM-USD-1793332800000.png",
        alt: {
          pt: "Gráfico de velas da entrada em paper de BEAM-USD, com um salto de preço e linhas de entrada, stop e alvo.",
          en: "Candlestick chart of the BEAM-USD paper entry, with a price jump and entry, stop, and target lines.",
        },
        caption: {
          pt: "BEAM-USD. Entrada simulada 0,00419148, stop 0,00392282, cerca de −1,03R.",
          en: "BEAM-USD. Simulated entry 0.00419148, stop 0.00392282, about −1.03R.",
        },
      },
      {
        kind: "h2",
        text: { pt: "MORPHO-USD, uma hora", en: "MORPHO-USD, one hour" },
      },
      {
        kind: "p",
        text: {
          pt: "Compra em 4 de novembro, por volta das 13:16, a 2,21511. Stop por volta das 14:17, a 2,1966. Cerca de −1,26R. Entre a entrada e a saída passou cerca de uma hora. Mercado pouco profundo não precisa de uma semana para lhe tirar o risco.",
          en: "Buy on 4 November, around 13:16, at 2.21511. Stop around 14:17, at 2.1966. About −1.26R. About an hour passed between entry and exit. A thin market does not need a week to take the risk away from you.",
        },
      },
      {
        kind: "figure",
        src: "/charts/ENTRY_P-MORPHO-USD-1793764800000.png",
        alt: {
          pt: "Gráfico de velas da entrada em paper de MORPHO-USD, com a zona recente e as linhas de entrada, stop e alvo.",
          en: "Candlestick chart of the MORPHO-USD paper entry, with the recent zone and entry, stop, and target lines.",
        },
        caption: {
          pt: "MORPHO-USD. Entrada simulada 2,21511, stop 2,1966, cerca de −1,26R.",
          en: "MORPHO-USD. Simulated entry 2.21511, stop 2.1966, about −1.26R.",
        },
      },
      {
        kind: "h2",
        text: { pt: "FAI-USD, o limite que encheu tarde", en: "FAI-USD, the limit that filled late" },
      },
      {
        kind: "p",
        text: {
          pt: "Limite colocado em 4 de novembro, por volta das 22:14. Encheu por volta das 00:13 de 5 de novembro, a 0,00209434. Stop em 5 de novembro, por volta das 13:09, a 0,00204795. Cerca de −1,31R. Esperar por um limite maker é disciplinado. Encher numa moeda sem volume não deixa de ser uma entrada má.",
          en: "Limit placed on 4 November, around 22:14. It filled around 00:13 on 5 November, at 0.00209434. Stop on 5 November, around 13:09, at 0.00204795. About −1.31R. Waiting for a maker limit is disciplined. Filling on a coin with no volume is still a bad entry.",
        },
      },
      {
        kind: "figure",
        src: "/charts/ENTRY_P-FAI-USD-1793793600000.png",
        alt: {
          pt: "Gráfico de velas da entrada em paper de FAI-USD, com as linhas de entrada, stop e alvo quase juntas no preço.",
          en: "Candlestick chart of the FAI-USD paper entry, with entry, stop, and target lines sitting close together in price.",
        },
        caption: {
          pt: "FAI-USD. Limite preenchido a 0,00209434, stop 0,00204795, cerca de −1,31R.",
          en: "FAI-USD. Limit filled at 0.00209434, stop 0.00204795, about −1.31R.",
        },
      },
      {
        kind: "h2",
        text: { pt: "O filtro já tinha falado", en: "The filter had already spoken" },
      },
      {
        kind: "p",
        text: {
          pt: "Os filtros em observação já tinham marcado volume baixo e spread largo neste tipo de moeda. No FAI, o volume andava perto de 13,8 mil dólares, contra um mínimo de referência de 50 mil. O spread andava perto de 0,96%, contra um máximo de referência de 0,50%. Uma variante proposta, `d_liquid_day`, bloquearia esta classe de entrada. Não estava ligada. As entradas de noite também tenderam a doer.",
          en: "The watching filters had already flagged low volume and a wide spread on this kind of coin. On FAI, volume was about $13.8k, against a reference minimum of $50k. The spread was about 0.96%, against a reference maximum of 0.50%. A proposed variant, d_liquid_day, would block this class of entry. It was not enabled. Night entries also tended to hurt.",
        },
      },
      {
        kind: "callout",
        tone: "nogo",
        title: { pt: "Um aviso que não bloqueia é um diário", en: "A warning that does not block is a diary" },
        text: {
          pt: "A lição não é “moedas pequenas são más para sempre”. A lição é: se a regra de volume e de spread só escreve uma nota, a nota não protege o livro. Ou o filtro passa a impedir, em paper, e mede-se de novo — ou assume-se que estas entradas vão continuar a aparecer.",
          en: "The lesson is not “small coins are bad forever.” The lesson is: if the volume and spread rule only writes a note, the note does not protect the book. Either the filter starts blocking, on paper, and you measure again — or you accept that these entries will keep showing up.",
        },
      },
    ],
  },
  {
    slug: "por-que-no-go",
    minutes: 7,
    kind: "case",
    title: {
      pt: "O que o paper ensinou: por que tantas estratégias receberam NO-GO",
      en: "What paper taught: why so many strategies were marked NO-GO",
    },
    description: {
      pt: "A maior parte dos livros falhou a régua. Publicar isso é a funcionalidade, não a vergonha.",
      en: "Most books failed the ruler. Publishing that is the feature, not the embarrassment.",
    },
    kicker: { pt: "A parte honesta", en: "The honest part" },
    related: ["relatorio-do-auditor", "os-bots", "dicas-para-iniciantes"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "A maior parte das estratégias em paper, até esta amostra, está NO-GO. Não é uma fase tímida antes do lançamento. É o resultado. Um projeto que só mostra a curva que sobe está a escolher o gráfico, não a testar a ideia.",
          en: "Most of the paper strategies, up to this sample, are NO-GO. That is not a shy phase before launch. It is the result. A project that only shows the curve that rises is choosing the chart, not testing the idea.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Quem já falhou a régua", en: "Who already failed the ruler" },
      },
      {
        kind: "table",
        caption: {
          pt: "NO-GO explícito na amostra e no relatório de 2 nov. Tudo paper.",
          en: "Explicit NO-GO in the sample and in the 2 Nov report. All paper.",
        },
        headers: [
          { pt: "Livro", en: "Book" },
          { pt: "Trades", en: "Trades" },
          { pt: "Acerto", en: "Win rate" },
          { pt: "Expectancy", en: "Expectancy" },
          { pt: "Notas", en: "Notes" },
        ],
        rows: [
          [
            { pt: "Desk, relatório 2026-11-02", en: "Desk, report 2026-11-02" },
            "34",
            "17.6%",
            "−0.518R",
            { pt: "DD 4.9% passa; NO_EDGE", en: "DD 4.9% passes; NO_EDGE" },
          ],
          ["bb_rsi", "311", "14%", "−0.69R", "$57.25"],
          ["ema_pb", "208", "18%", "−0.53R", "$59.31"],
          ["ema_pb_adx", "67", "31%", "−0.36R", "$63.62"],
          ["ems_vwap_mr", "62", "23%", "−0.43R", "$62.06"],
          ["ems_rsi_div", "70", "24%", "−0.43R", "$61.77"],
          ["ems_squeeze_bo", "48", "17%", "−0.54R", "$62.27"],
        ],
      },
      {
        kind: "h2",
        text: { pt: "Quem ainda não tem o direito a uma frase final", en: "Who does not yet have the right to a final sentence" },
      },
      {
        kind: "p",
        text: {
          pt: "Poucos trades não são um GO silencioso. `brk` (25), `bb_rsi_adx` (16) e `brk_adx` (2) não chegam aos 40. `ems_vwap_obi` vai em 4/40, com 0% de acerto e −1,00R. As notícias vão em 6/40 e 0/40. O Bot A não está validado. O Bot B é a baseline de segurar BTC, cerca de 60,31 dólares, não uma estratégia a promover. O Bot C está desligado.",
          en: "Too few trades is not a quiet GO. brk (25), bb_rsi_adx (16), and brk_adx (2) do not reach 40. ems_vwap_obi is at 4/40, with a 0% win rate and −1.00R. The news books are at 6/40 and 0/40. Bot A is not validated. Bot B is the hold-BTC baseline, about $60.31, not a strategy to promote. Bot C is off.",
        },
      },
      {
        kind: "h2",
        text: { pt: "Por que a falha se repete", en: "Why the failure repeats" },
      },
      {
        kind: "ul",
        items: [
          {
            pt: "O custo é real mesmo no paper. Taker, slippage e spread comem o movimento pequeno que o gráfico parecia prometer.",
            en: "The cost is real even on paper. Taker, slippage, and spread eat the small move the chart seemed to promise.",
          },
          {
            pt: "Acertar muitas vezes não chega. Vários livros têm acerto na casa dos 15–30% e expectancy negativa. Os ganhos não pagam os stops.",
            en: "Winning often is not enough. Several books win around 15–30% of the time and still have negative expectancy. The wins do not pay for the stops.",
          },
          {
            pt: "Mais trades não salvaram o scalper mais ocupado. 311 trades no `bb_rsi` tornaram o NO-GO mais claro, não menos.",
            en: "More trades did not save the busiest scalper. 311 trades on bb_rsi made the NO-GO clearer, not softer.",
          },
          {
            pt: "Um filtro que só observa deixa passar a classe de moeda que já estava marcada. FORT, BEAM, MORPHO e FAI são esse capítulo.",
            en: "A filter that only watches lets through the coin class it had already flagged. FORT, BEAM, MORPHO, and FAI are that chapter.",
          },
        ],
      },
      {
        kind: "callout",
        tone: "good",
        title: { pt: "NO-GO é uma funcionalidade", en: "NO-GO is a feature" },
        text: {
          pt: "O papel do paper é gastar tempo e atenção, não saldo. Uma estratégia que falha aqui fica no repositório com o veredito ao lado do nome. Isso é mais útil para quem está a começar do que um bot que “ainda não mostrou os números”.",
          en: "The job of paper is to spend time and attention, not a balance. A strategy that fails here stays in the repository with the verdict next to the name. That is more useful to a beginner than a bot that “hasn’t shown the numbers yet.”",
        },
      },
      {
        kind: "p",
        text: {
          pt: "Se um dia um livro passar nos quatro limiares ao mesmo tempo, o relatório dirá GO. Até lá, o estado público é este: a maior parte está NO-GO, o resto ainda não tem amostra, e o modo continua a ser paper.",
          en: "If a book someday passes all four thresholds at once, the report will say GO. Until then, the public state is this: most are NO-GO, the rest do not have a sample yet, and the mode remains paper.",
        },
      },
    ],
  },
  {
    slug: "dicas-para-iniciantes",
    minutes: 7,
    kind: "tips",
    title: {
      pt: "Dicas para iniciantes: custos, R, kill diário, não forçar trade",
      en: "Beginner tips: costs, R, the daily kill, and not forcing a trade",
    },
    description: {
      pt: "Quatro ideias que evitam a maior parte dos erros de quem abre o primeiro gráfico.",
      en: "Four ideas that prevent most mistakes people make on their first chart.",
    },
    kicker: { pt: "Dicas", en: "Tips" },
    related: ["como-comecar", "moedas-pouco-negociadas", "bot-de-noticias"],
    blocks: [
      {
        kind: "p",
        text: {
          pt: "Se só guardar quatro coisas deste projeto, que sejam estas. Não precisam de um indicador novo. Precisam de paciência, que é mais barata do que uma ordem.",
          en: "If you keep only four things from this project, keep these. They do not need a new indicator. They need patience, which is cheaper than an order.",
        },
      },
      {
        kind: "h2",
        text: { pt: "1. O custo não é um detalhe no rodapé", en: "1. Cost is not a footnote" },
      },
      {
        kind: "p",
        text: {
          pt: "Na Revolut X, maker é 0% e taker é 0,09%. Uma ida e volta a mercado paga taker duas vezes, mais o slippage que o paper usa (5 a 15 pontos-base), mais o spread. O motor resume o custo como duas vezes (taker + slippage). Um movimento de 0,2% que parece um “scalp fácil” pode ser só a taxa a disfarçar-se de oportunidade.",
          en: "On Revolut X, maker is 0% and taker is 0.09%. A market round trip pays taker twice, plus the slippage paper mode uses (5 to 15 basis points), plus the spread. The engine summarises cost as twice (taker + slippage). A 0.2% move that looks like an “easy scalp” can be just the fee dressed up as an opportunity.",
        },
      },
      {
        kind: "p",
        text: {
          pt: "Por isso o Bot D prefere limite. E por isso um sinal que não cobre custos é rejeitado, nos scalpers e no portão da mesa. Se a sua ideia só funciona com taxa zero e spread zero, não funciona.",
          en: "That is why Bot D prefers limits. And why a signal that does not cover costs is rejected, on the scalpers and at the desk gate. If your idea only works with zero fees and zero spread, it does not work.",
        },
      },
      {
        kind: "h2",
        text: { pt: "2. R é o tamanho do seu erro, não o preço", en: "2. R is the size of your mistake, not the price" },
      },
      {
        kind: "p",
        text: {
          pt: "R é a distância entre a entrada e o stop, o prejuízo que você aceitou antes de clicar. Um trade a −1R perdeu cerca dessa distância. Um trade a +1,33R ganhou cerca de 1,33 vezes essa distância. Falar em R deixa o FORT (−0,03R) e o MORPHO (−1,26R) na mesma régua, mesmo com preços completamente diferentes. O XRP de notícias, +1,33R, foram 0,32 dólares simulados. Sem o R, o cêntimo parece irrelevante ou enorme, conforme o humor.",
          en: "R is the distance from entry to stop, the loss you accepted before clicking. A −1R trade lost about that distance. A +1.33R trade gained about 1.33 times that distance. Speaking in R puts FORT (−0.03R) and MORPHO (−1.26R) on the same ruler, even with completely different prices. The news XRP, +1.33R, was $0.32 simulated. Without R, the cents look either irrelevant or huge, depending on your mood.",
        },
      },
      {
        kind: "h2",
        text: { pt: "3. O kill diário é um amigo mal-educado", en: "3. The daily kill is a rude friend" },
      },
      {
        kind: "p",
        text: {
          pt: "Os scalpers param o dia se a equity marcada cair 2% face à abertura. No dia 5 de novembro, o `bb_rsi` bateu nesse kill por volta das 15:53, hora de Londres, e ficou em pausa até ao dia acabar. A mesa, nas regras escritas, tem um halt diário de 3%, que é outra régua, noutro livro. Não os misture. Os dois existem para a mesma cena: você, à noite, a “recuperar”.",
          en: "The scalpers stop the day if marked equity falls 2% from the open. On 5 November, bb_rsi hit that kill around 15:53 London time and stayed paused until the day ended. The desk, in its written rules, has a 3% daily halt, which is a different ruler on a different book. Do not mix them. Both exist for the same scene: you, at night, “getting it back.”",
        },
      },
      {
        kind: "h2",
        text: { pt: "4. Não forçar o trade é uma posição", en: "4. Not forcing the trade is a position" },
      },
      {
        kind: "p",
        text: {
          pt: "O bot de notícias recusou BTC por uma manchete negativa, e recusou CC, INJ e SOL por volume ou spread. `news_pullback` chegou a aceitar um sinal cujo limite não encheu, e o equity ficou em 65,00 dólares. HOLD e “não encheu” contam. Uma mesa que precisa de estar sempre dentro do mercado está a trabalhar para a taxa, não para si.",
          en: "The news bot refused BTC because of a negative headline, and refused CC, INJ, and SOL for volume or spread. news_pullback once accepted a signal whose limit did not fill, and equity stayed at $65.00. HOLD and “it did not fill” count. A desk that needs to be in the market at all times is working for the fee, not for you.",
        },
      },
      {
        kind: "ul",
        items: [
          {
            pt: "Escreva o stop antes de se apaixonar pela entrada.",
            en: "Write the stop before you fall for the entry.",
          },
          {
            pt: "Se o spread já é maior que a sua ideia, não há ideia.",
            en: "If the spread is already larger than your idea, there is no idea.",
          },
          {
            pt: "Volume de 13,8 mil contra um mínimo de 50 mil, como no FAI, não é “cedo demais”. É fino demais.",
            en: "Volume of $13.8k against a $50k minimum, as on FAI, is not “a bit early.” It is too thin.",
          },
          {
            pt: "Cinco posições no máximo, nos scalpers, existe para você não colecionar erros ao mesmo tempo.",
            en: "Five positions at most, on the scalpers, exists so you do not collect mistakes at the same time.",
          },
          {
            pt: "Se der vontade de “ligar ao vivo só um pouco”, releia o relatório do auditor. O caminho público deste repositório acaba no paper.",
            en: "If you feel like “turning it live just a little,” reread the auditor report. The public path of this repository ends at paper.",
          },
        ],
      },
    ],
  },
];

export function getArticle(slug: string) {
  return articles.find((article) => article.slug === slug);
}

export const kindLabel: Record<Article["kind"], Copy> = {
  start: { pt: "Começar", en: "Start" },
  guide: { pt: "Guia", en: "Guide" },
  case: { pt: "Estudo", en: "Case study" },
  tips: { pt: "Dicas", en: "Tips" },
};
