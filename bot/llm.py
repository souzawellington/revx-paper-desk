"""Camada Grok (opcional, desligada por defeito). O LLM PROPÕE; o motor determinístico VERIFICA.
A saída do LLM nunca pode aumentar o tamanho calculado pelo Quarter-Kelly local."""
from __future__ import annotations
import json, os
from .schema import DECISION_SCHEMA, validate

SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "system_prompt.xml")
XAI_API_KEY = os.environ.get("XAI_API_KEY")  # PLACEHOLDER: credencial xAI


def propose(cfg, numeric_context: dict, untrusted_text: list[str]) -> dict:
    if not XAI_API_KEY:
        raise RuntimeError("XAI_API_KEY não definida")
    import requests
    system = open(SYSTEM_PROMPT_PATH, encoding="utf-8").read()
    user = ("<trusted_numeric_context>" + json.dumps(numeric_context) + "</trusted_numeric_context>"
            "<untrusted_data>" + json.dumps(untrusted_text) + "</untrusted_data>")
    body = {  # Parâmetros do PDF; confirmar contra docs xAI atuais (ver GAPS.md)
        "model": cfg.llm_model, "temperature": cfg.llm_temperature,
        "reasoning_effort": cfg.llm_reasoning_effort, "prompt_cache_key": cfg.llm_prompt_cache_key,
        "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "text": {"format": {"type": "json_schema", "name": "decision", "schema": DECISION_SCHEMA, "strict": True}},
    }
    r = requests.post("https://api.x.ai/v1/responses", json=body, timeout=120,
                      headers={"Authorization": f"Bearer {XAI_API_KEY}"})
    r.raise_for_status()
    data = r.json()
    text = data.get("output_text") or next(
        c["text"] for o in data.get("output", []) if o.get("type") == "message" for c in o["content"] if "text" in c)
    decision = json.loads(text)
    validate(decision)
    return decision
