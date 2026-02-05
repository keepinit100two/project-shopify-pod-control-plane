import json

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_ops_dispatch_drafts_endpoint_generates_dispatch_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    # Redirect DRAFT_DIR to temp so we don't touch real artifacts
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    idem_key = "ops-dispatch-demo-1"

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "ops-demo-1",
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

    req = shopify_signed_request(payload, idempotency_key=idem_key)

    r1 = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/ops/shopify/dispatch_drafts",
        json={"idempotency_key": idem_key},
    )
    assert r2.status_code == 200
    body = r2.json()

    assert "event_id" in body
    assert body["action_result"]["status"] == "executed"

    dispatch_artifacts = list(tmp_path.glob("*.dispatch_request.item_*.json"))
    assert len(dispatch_artifacts) == 2

    artifact = json.loads(dispatch_artifacts[0].read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "dispatch_request_v0"
    assert artifact["status"] == "DRAFT"
    assert artifact["partner"] in {"POD_A", "POD_B"}
    assert artifact["idempotency_key"].startswith("dispatch:")
