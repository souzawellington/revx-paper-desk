import sys, json, random
sys.path.insert(0, "/workspace/revolut-crypto-bot")
import pandas as pd
from financetoolkit.risk import risk_model, var_model, cvar_model
from financetoolkit.performance import performance_model as pm
from desk import metrics as M
random.seed(7)
rets = [random.gauss(0.001, 0.03) for _ in range(400)]
s = pd.Series(rets)
eq = [10000.0]
for r in rets: eq.append(eq[-1] * (1 + r))
mine = M.curve_metrics(eq)
out = {"sortino": [float(pm.get_sortino_ratio(s)), M.sortino(rets)],
       "var95": [float(var_model.get_var_historic(s, 0.05)), M.var_cvar(rets)[0]],
       "cvar95": [float(cvar_model.get_cvar_historic(s, 0.05)), M.var_cvar(rets)[1]],
       "ulcer": [float(risk_model.get_ui(s, rolling=None)), mine["ulcer_index"]],
       "max_dd": [float(-risk_model.get_max_drawdown(s)), mine["max_dd"]]}
print(json.dumps(out))
