"""python -m bot --demo  (paper, dados sintéticos). Sem --demo: dados públicos Revolut X.  Produção: implementar bot/data.py e definir BOT_BROKER."""
import argparse, json, time
from .config import load_config
from .brokers import make_broker
from .engine import Engine


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--demo", action="store_true")
    ap.add_argument("--loop", type=int, default=0, help="segundos entre ciclos (0 = um ciclo)")
    a = ap.parse_args(); cfg = load_config()
    if a.demo:
        from .sim import SyntheticMarket, NullSentiment, FixedStats
        market, sent, stats, rules = SyntheticMarket(cfg.symbols), NullSentiment(), FixedStats(), None
    else:
        from .data import RevolutXMarketFeed, SentimentFeed, SignalStatsStore
        from .revolutx import RevolutXClient
        from .revolutx.rules import pairs_to_rules
        pub = RevolutXClient()  # público, sem credenciais
        rules = pairs_to_rules(pub.public_pairs(cfg.region))
        market, sent, stats = RevolutXMarketFeed(pub, cfg), SentimentFeed(), SignalStatsStore(cfg)
    llm = None
    if cfg.llm_enabled:
        from .llm import propose as llm
    eng = Engine(cfg, make_broker(cfg, rules), market, sent, stats, llm)
    while True:
        print(json.dumps(eng.cycle(), indent=2, default=str))
        if not a.loop or eng.cb.tripped: break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
