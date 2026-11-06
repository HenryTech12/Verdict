from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import pipeline


class NeverCallRealPayPal:
    simulated = False

    async def provide_evidence(self, *args, **kwargs):
        raise AssertionError("Synthetic dispute must not call real PayPal")

    async def refund_capture(self, *args, **kwargs):
        raise AssertionError("Synthetic capture must not call real PayPal")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["FIGHT", "REFUND"])
async def test_simulated_case_never_calls_real_paypal(monkeypatch, action):
    monkeypatch.setattr(pipeline, "get_adapter", lambda: NeverCallRealPayPal())
    dispute = SimpleNamespace(
        id="DSP-TEST01",
        paypal_dispute_id="SIM-PP-TEST01",
        simulated=True,
        amount=Decimal("90.00"),
        currency="USD",
    )
    order = SimpleNamespace(paypal_capture_id="SIM-CAP-TEST01")
    shipment = SimpleNamespace(tracking="SIM-TRK-TEST01")

    result = await pipeline.execute_action(dispute, action, order, shipment, "demo packet")

    assert result["simulated"] is True
    assert result["attempts"] == 0
    assert "never sent to PayPal" in result["fallback_reason"]
    if action == "FIGHT":
        assert result["result"]["status"] == "EVIDENCE_SUBMITTED"
    else:
        assert result["result"]["status"] == "REFUNDED"


@pytest.mark.asyncio
async def test_synthetic_capture_prefix_is_defensive_routing_guard(monkeypatch):
    monkeypatch.setattr(pipeline, "get_adapter", lambda: NeverCallRealPayPal())
    dispute = SimpleNamespace(
        id="DSP-TEST02",
        paypal_dispute_id="PP-REALISH",
        simulated=False,
        amount=Decimal("10.00"),
        currency="USD",
    )
    order = SimpleNamespace(paypal_capture_id="SIM-CAP-OLD-RECORD")

    result = await pipeline.execute_action(dispute, "REFUND", order, None, "")

    assert result["simulated"] is True
    assert result["attempts"] == 0
