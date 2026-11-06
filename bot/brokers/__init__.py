from .base import Broker, Order, Position
from .paper import PaperBroker


def make_broker(cfg, rules=None):
    if cfg.dry_run or cfg.broker == "paper":   # dry-run força paper
        return PaperBroker(rules=rules, taker_fee=cfg.taker_fee, slippage=cfg.slippage_est)
    if cfg.broker == "revolutx":
        from .revolutx import RevolutXBroker
        return RevolutXBroker.from_env(cfg)
    raise ValueError(cfg.broker)
