import json
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_shopify_fulfillment_plan_creates_one_draft_per_line_item(tmp_path, monkeypatch):
    """
    When a Shopify order routes to SHOPIFY_FULFILLMENT_PLAN,
    one draft fulfillment plan artifact should be written per line item.
    Each artifact should include deterministic POD partner selection.
    """
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    # Redirect DRAFT_DIR to temp so we don't touch real artifacts
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "artifact-test-1",
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

    req = shopify_signed_request(payload, idempotency_key="artifact-test-key")

    response = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )

    assert response.status_code == 200

    artifacts = list(tmp_path.glob("*.fulfillment_plan.item_*.json"))
    assert len(artifacts) == 2

    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "fulfillment_plan_v0"
    assert data["status"] == "DRAFT"
    assert "line_item" in data

    assert "partner_selection" in data
    assert data["partner_selection"]["status"] == "SELECTED"
    assert data["partner_selection"]["partner"] in {"POD_A", "POD_B"}
    assert "reason" in data["partner_selection"]
