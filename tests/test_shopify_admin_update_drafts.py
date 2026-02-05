import json

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_shopify_request_more_info_writes_admin_update_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    # Redirect DRAFT_DIR to a temp directory so we don't touch real artifacts
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "admin-update-1",
        "payload": {
            "line_items": [
                {
                    "sku": "CANVAS_16x20",
                    "variant_id": 1,
                    "quantity": 1,
                    "properties": [
                        {"name": "style", "value": "Watercolor"}
                    ],
                }
            ]
        },
    }

    req = shopify_signed_request(payload, idempotency_key="admin-update-key-1")

    r = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )

    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["route"] == "REQUEST_MORE_INFO"

    artifacts = list(tmp_path.glob("*.shopify_admin_update.REQUEST_MORE_INFO.json"))
    assert len(artifacts) == 1

    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "shopify_admin_update_v0"
    assert data["status"] == "DRAFT"
    assert "NEEDS_INFO" in data["tags_add"]
    assert "note" in data
    assert "Order requires more info:" in data["note"]
