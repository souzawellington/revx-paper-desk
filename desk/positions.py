"""Conversão positions.csv <-> logic.Position."""
from . import logic as L, store


def to_pos(r) -> L.Position:
    tp = store.f(r.get("tp_price"))
    p = L.Position(r["pid"], r["coin"], float(r["entry"]), float(r["stop"]), float(r["qty"]), float(r["risk_pct"]),
                   int(r["add_number"]), float(r["anchor_low"]), int(r["opened_ts"]), peak=float(r["peak"]),
                   at_be=r["at_be"] == "True", initial_stop=float(r["initial_stop"]),
                   tp_price=tp, initial_tp=tp, stale_flagged=r["stale_flagged"] == "True")
    return p


def update_row(r, p: L.Position):
    # stop pode subir a BE; tp_price NUNCA muda após abertura
    r.update(stop=p.stop, peak=p.peak, at_be=p.at_be, stale_flagged=p.stale_flagged)
    if "tp_price" in r and r["tp_price"] not in ("", None):
        # freeze: repor o valor congelado se alguém o tentou alterar no objecto
        if p.initial_tp is not None:
            p.tp_price = p.initial_tp
            r["tp_price"] = p.initial_tp
    return r


def decision_for(plan_id):
    for d in store.read("decisions.csv"):
        if d["plan_id"] == plan_id: return d["decision"]
    return "PENDING"
