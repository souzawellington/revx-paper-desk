"""Snapshot PÚBLICO (página online na Vercel) do estado dos bots SIMULADOS.

Reaproveita bot.live_view.live_snapshot (mesmo modelo de dados do painel local /live), reduz o tamanho (curvas
amostradas, listas cortadas) e passa por um SANITIZADOR que:
  * remove qualquer campo cujo nome pareça segredo (key, secret, token, password, pem, auth, credential, env, path...);
  * apaga strings que pareçam caminhos de ficheiros, blocos PEM, JWT, tokens longos (hex/base64) ou "KEY=valor";
  * no fim, `assert_clean` FALHA (SecretLeak) se ainda aparecer algo suspeito ou o valor exato de um segredo conhecido
    (REVX_API_KEY do ambiente, senha do painel local, senha da página Vercel, token de ingestão).
Só leitura: nunca escreve estado dos bots, nunca coloca ordens, nunca lê a chave privada.
Uso: python -m bot.public_snapshot [--out ficheiro.json]
"""
from __future__ import annotations
import argparse, json, math, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_FILES = (".dashboard_password", ".vercel_dashboard_password", ".vercel_ingest_token")
SCHEMA = 1
MAX_CURVE = 240          # pontos por curva de equity
MAX_LIST = 10            # posições / trades por bot

_BAD_KEY = re.compile(r"(api[_-]?key|secret|token|passw|pwd|\bpem\b|private|credential|auth|cookie|session|"
                      r"signature|bearer|env|path|dir$|file$|revx)", re.I)
_BAD_VAL = [
    re.compile(r"-----BEGIN [A-Z ]+-----"),                                   # PEM
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),             # JWT
    re.compile(r"(?<![\w/])(?:/[\w.\-~]+){2,}"),                              # caminho /a/b
    re.compile(r"~/[\w.\-]+"),                                                # ~/qualquer
    re.compile(r"\b[A-Za-z0-9+/_\-]{32,}={0,2}(?![\w])"),                     # token longo base64/url-safe
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),                                      # hex longo
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}=\S+"),                                  # ENV=valor
    re.compile(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9+/=._\-]{8,}"),           # cabeçalho auth
    re.compile(r"\.revx-keys|private\.pem|REVX_", re.I),
]


class SecretLeak(AssertionError):
    pass


def known_secrets(env=None, root=ROOT) -> list[str]:
    env = os.environ if env is None else env
    out = []
    for k in ("REVX_API_KEY", "DASHBOARD_PASSWORD", "VERCEL_DASHBOARD_PASSWORD", "INGEST_TOKEN"):
        v = env.get(k)
        if v and len(v) >= 6: out.append(v)
    for f in SECRET_FILES:
        try:
            with open(os.path.join(root, f)) as fh:
                v = fh.read().strip()
            if len(v) >= 6: out.append(v)
        except OSError:
            pass
    return out


def _bad_str(s: str) -> bool:
    return any(p.search(s) for p in _BAD_VAL)


def sanitize(obj, _depth=0):
    """Cópia limpa: só tipos JSON simples; chaves suspeitas removidas; strings suspeitas trocadas por '[removido]'."""
    if _depth > 12: return None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            k = str(k)
            if _BAD_KEY.search(k) and not _allowed_key(k): continue
            out[k] = sanitize(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, _depth + 1) for v in obj]
    if isinstance(obj, bool) or obj is None: return obj
    if isinstance(obj, int): return obj
    if isinstance(obj, float): return obj if math.isfinite(obj) else None
    s = str(obj)[:300]
    return "[removido]" if _bad_str(s) else s


# nomes legítimos do modelo do painel que contêm subcadeias como "env" (nenhum aqui) — lista explícita, vazia por defeito
_ALLOWED = set()
def _allowed_key(k: str) -> bool:
    return k in _ALLOWED


def assert_clean(obj, secrets=None, _p="$"):
    """Lança SecretLeak se houver nome de campo suspeito, valor suspeito, ou um segredo conhecido em qualquer lado."""
    secrets = [s for s in (secrets if secrets is not None else known_secrets()) if s]
    blob = json.dumps(obj, ensure_ascii=False)
    for s in secrets:
        if s in blob: raise SecretLeak("segredo conhecido presente no snapshot")
    def walk(o, p):
        if isinstance(o, dict):
            for k, v in o.items():
                if _BAD_KEY.search(str(k)) and not _allowed_key(str(k)): raise SecretLeak(f"campo suspeito {p}.{k}")
                walk(v, f"{p}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o): walk(v, f"{p}[{i}]")
        elif isinstance(o, str) and o != "[removido]" and _bad_str(o):
            raise SecretLeak(f"valor suspeito em {p}")
    walk(obj, _p)
    return True


def _thin(curve, n=MAX_CURVE):
    if not isinstance(curve, list) or len(curve) <= n: return curve
    step = (len(curve) - 1) / (n - 1)
    return [curve[round(i * step)] for i in range(n)]


def _r(x, d=6):
    return round(x, d) if isinstance(x, float) and math.isfinite(x) else x


def shrink(snap: dict) -> dict:
    snap = json.loads(json.dumps(snap, default=str))
    for b in snap.get("bots") or []:
        b["curve"] = [[int(t), _r(v, 4)] for t, v in _thin(b.get("curve") or [])]
        b["positions"] = (b.get("positions") or [])[:MAX_LIST]
        b["recent"] = (b.get("recent") or [])[:MAX_LIST]
    d = snap.get("desk")
    if isinstance(d, dict):
        d["open"] = (d.get("open") or [])[:MAX_LIST]; d["results"] = (d.get("results") or [])[:MAX_LIST]
    return snap


def build(prices=None, marks=None, now=None) -> dict:
    """Snapshot completo, encolhido, sanitizado e verificado. Lança SecretLeak se algo escapar."""
    from .live_view import Prices, Marks, live_snapshot
    now = now or time.time()
    if prices is None:
        from .revolutx.client import RevolutXClient
        from .dashboard import ReadOnlyClient
        prices = Prices(ReadOnlyClient(RevolutXClient()), os.environ.get("BOT_REGION") or None, ttl=20.0)
    if marks is None:
        # lê (não escreve) o log de marcações do painel local para a curva comparativa
        marks = _ReadOnlyMarks(os.path.join(ROOT, "logs", "dashboard_marks.jsonl"))
    raw = live_snapshot(prices, marks, now=now)
    try:                                       # livros EMS (paper) — só leitura de desk/state/ems_paper; falha não parte o snapshot
        from desk.ems.run import dashboard_data
        raw["ems"] = dashboard_data()
    except Exception as e:
        raw["ems"] = {"available": False, "why": f"erro: {type(e).__name__}"}
    try:                                       # bot de notícias news_v1 (paper) — só leitura de desk/state/news_paper
        from desk.news.run import dashboard_data as news_dashboard
        raw["news"] = news_dashboard()
    except Exception as e:
        raw["news"] = {"available": False, "why": f"erro: {type(e).__name__}"}
    snap = sanitize(shrink(raw))
    snap["schema"] = SCHEMA
    snap["generated_at"] = int(now)          # epoch s (UTC) — a página converte para hora de Londres
    snap["simulated"] = True; snap["live_orders"] = False
    snap["banner"] = "SIMULADO — nenhuma ordem real"
    assert_clean(snap)
    return snap


class _ReadOnlyMarks:
    def __init__(self, p): self.p = p
    def read(self, limit=5000):
        from .live_view import Marks
        return Marks(self.p).read(limit)
    def maybe_add(self, *a, **k): pass


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--out")
    a = ap.parse_args(argv)
    for k in ("REVX_API_KEY", "REVX_PRIVATE_KEY_PATH"): os.environ.pop(k, None)
    snap = build()
    data = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    if a.out:
        tmp = a.out + ".tmp"
        with open(tmp, "w") as f: f.write(data)
        os.replace(tmp, a.out)
    else:
        sys.stdout.write(data + "\n")


if __name__ == "__main__":
    main()
