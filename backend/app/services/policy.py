def choose_policy(win_likelihood: float, confidence: float, fight_min: float = 0.60, refund_max: float = 0.35, min_confidence: float = 0.70) -> str:
    if win_likelihood >= fight_min and confidence >= min_confidence:
        return "FIGHT"
    if win_likelihood < refund_max and confidence >= min_confidence:
        return "REFUND"
    return "ESCALATE"
