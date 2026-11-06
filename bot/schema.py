"""Esquema JSON literal do PDF (formatting_requirements) + validação."""
from __future__ import annotations

DECISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["market_intelligence", "quantitative_reasoning_trace", "execution_directive", "system_compliance_audit"],
    "properties": {
        "market_intelligence": {"type": "object", "required": ["evaluation_timestamp_iso", "asset_identification", "network_sentiment_polarity_score", "technical_momentum_confidence"],
            "properties": {"evaluation_timestamp_iso": {"type": "string"}, "asset_identification": {"type": "string"},
                           "network_sentiment_polarity_score": {"type": "number", "minimum": -1, "maximum": 1},
                           "technical_momentum_confidence": {"type": "number", "minimum": 0, "maximum": 1}}},
        "quantitative_reasoning_trace": {"type": "object", "required": ["win_probability_p", "risk_reward_multiplier_b", "full_kelly_index_calculation", "fractional_kelly_quarter_enforced", "atr_multiplier_stop_distance"],
            "properties": {k: {"type": "number"} for k in ["win_probability_p", "risk_reward_multiplier_b", "full_kelly_index_calculation", "fractional_kelly_quarter_enforced", "atr_multiplier_stop_distance"]}},
        "execution_directive": {"type": "object", "required": ["action_type", "order_structure", "limit_price_target", "stop_loss_trigger_price", "capital_allocation_fraction"],
            "properties": {"action_type": {"enum": ["BUY", "SELL", "HOLD"]}, "order_structure": {"enum": ["MARKET", "LIMIT"]},
                           "limit_price_target": {"type": ["number", "null"]}, "stop_loss_trigger_price": {"type": "number"},
                           "capital_allocation_fraction": {"type": "number", "minimum": 0, "maximum": 0.15}}},
        "system_compliance_audit": {"type": "object", "required": ["drawdown_safeguard_status", "analytical_rationale"],
            "properties": {"drawdown_safeguard_status": {"enum": ["PASS", "FAIL"]}, "analytical_rationale": {"type": "string"}}},
    },
}


def validate(decision: dict) -> None:
    import jsonschema
    jsonschema.validate(decision, DECISION_SCHEMA)
    ed = decision["execution_directive"]
    if ed["order_structure"] == "MARKET" and ed["limit_price_target"] is not None:
        raise ValueError("MARKET exige limit_price_target nulo")
