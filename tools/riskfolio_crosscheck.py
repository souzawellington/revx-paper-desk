import sys, json, random
sys.path.insert(0, "/workspace/revolut-crypto-bot")
import pandas as pd, riskfolio as rp
from desk.allocation import hrp_weights
random.seed(3); out = {}
for n in (2, 3, 4, 5):
    T = 90; f = [random.gauss(0, 0.02) for _ in range(T)]
    R = [[0.5 * (k + 1) / n * f[t] + random.gauss(0, 0.01 * (1 + k)) for t in range(T)] for k in range(n)]
    df = pd.DataFrame({f"A{k}": R[k] for k in range(n)})
    for rm in ("MV", "CVaR"):
        port = rp.HCPortfolio(returns=df)
        w = port.optimization(model="HRP", codependence="pearson", rm=rm, rf=0, linkage="single", leaf_order=False)
        mine = hrp_weights(R, rm)
        out[f"n{n}_{rm}"] = max(abs(a - b) for a, b in zip(w["weights"].tolist(), mine))
print(json.dumps(out))
