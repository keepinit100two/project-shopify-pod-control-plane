import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shopify_fulfillment_plan_creates_one_draft_per_line_item(tmp_path, monkeypatch):
    """
    When a Shopify order routes to SHOPIFY_FULFILLMENT_PLAN,
    one draft fulfillment plan artifact should be written per line item.
    """

    # Redirect DRAFT_DIR to a temp directory so we don't touch real artifacts
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

    response = client.post(
        "/ingest/shopify/order_created",
        json=payload,
        headers={"Idempotency-Key": "artifact-test-key"},
    )

    assert response.status_code == 200

    # There should be exactly 2 draft artifacts (one per line item)
    artifacts = list(tmp_path.glob("*.fulfillment_plan.item_*.json"))
    assert len(artifacts) == 2

    # Validate structure of one artifact
    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "fulfillment_plan_v0"
    assert data["status"] == "DRAFT"
    assert "line_item" in data
    assert data["partner_selection"]["status"] == "PENDING"
