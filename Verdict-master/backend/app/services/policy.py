"""Decision policy: maps win likelihood and confidence to FIGHT, REFUND or ESCALATE."""


def choose_policy_with_rule(win_likelihood: float, confidence: float, fight_min: float = 0.60, refund_max: float = 0.35, min_confidence: float = 0.70) -> tuple[str, str]:
    if win_likelihood >= fight_min and confidence >= min_confidence:
        return "FIGHT", "FIGHT_THRESHOLD"
    if win_likelihood < refund_max and confidence >= min_confidence:
        return "REFUND", "REFUND_THRESHOLD"
    if confidence < min_confidence:
        return "ESCALATE", "LOW_CONFIDENCE_DEFAULT"
    return "ESCALATE", "UNCERTAIN_BAND_DEFAULT"


def choose_policy(win_likelihood: float, confidence: float, fight_min: float = 0.60, refund_max: float = 0.35, min_confidence: float = 0.70) -> str:
    return choose_policy_with_rule(win_likelihood, confidence, fight_min, refund_max, min_confidence)[0]


def lean_action(win_likelihood: float) -> str:
    """The concrete action an escalated approval request proposes."""
    return "FIGHT" if win_likelihood >= 0.5 else "REFUND"
