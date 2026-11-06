class RuleError(Exception):
    """A business-rule failure that maps to a structured API error."""

    def __init__(self, code: str, message: str, status: int = 409, details: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details or {}


class ActionFailed(RuntimeError):
    """The PayPal action failed after retries; the case must be escalated with the error logged."""
