import json

from fastapi.testclient import TestClient

from app.main import app
from app.domain.schemas import Decision, Event as EventModel
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_create_dispatch_drafts_writes_one_draft_per_line_item(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    # Redirect DRAFT_DIR to temp
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "dispatch-test-1",
        "payload": {
            "line_items": [
                {
                    "sku": "CANVAS_16x20",
                    "variant_id": 1,
                    "quantity": 1,
                    "properties": [
                        {"name": "pet_name", "value": "Luna"},
                        {"name": "style", "value": "Watercolor"},
                    ],
                },
                {
                    "sku": "CANVAS_12x16",
                    "variant_id": 2,
                    "quantity": 1,
                    "properties": [
                        {"name": "pet_name", "value": "Max"},
                        {"name": "style", "value": "Minimalist"},
                    ],
                },
            ]
        },
    }

    req = shopify_signed_request(payload, idempotency_key="dispatch-test-key")

    r = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )
    assert r.status_code == 200
    event_dict = r.json()["event"]

    decision = Decision(
        decision_id="test-decision",
        event_id=event_dict["event_id"],
        route="CREATE_DISPATCH_DRAFTS",
        reason="test",
        risk_level="low",
        proposed_action={},
    )

    event_model = EventModel(**event_dict)

    result = actuator.execute_decision(event_model, decision)
    assert result.status == "executed"

    artifacts = list(tmp_path.glob("*.dispatch_request.item_*.json"))
    assert len(artifacts) == 2

    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "dispatch_request_v0"
    assert data["status"] == "DRAFT"
    assert data["partner"] in {"POD_A", "POD_B"}
    assert data["idempotency_key"].startswith("dispatch:")
    assert "payload" in data
