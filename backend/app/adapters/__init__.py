from app.adapters.paypal_mock import MockPayPalAdapter
from app.adapters.paypal_real import SandboxPayPalAdapter
from app.config import settings


def get_adapter():
    """Real sandbox implementation or labeled mock, switched by PAYPAL_MODE."""
    return SandboxPayPalAdapter() if settings.paypal_mode == "sandbox" else MockPayPalAdapter()
