import json

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_shopify_request_more_info_writes_admin_update_draft(tmp_path, monkeypatch):
    # Redirect DRAFT_DIR to temp so we don't touch real artifacts
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    # Missing pet_name triggers REQUEST_MORE_INFO
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

    r = client.post(
        "/ingest/shopify/order_created",
        json=payload,
        headers={"Idempotency-Key": "admin-update-key-1"},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["decision"]["route"] == "REQUEST_MORE_INFO"

    # Admin update draft should be written for REQUEST_MORE_INFO
    artifacts = list(tmp_path.glob("*.shopify_admin_update.REQUEST_MORE_INFO.json"))
    assert len(artifacts) == 1

    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "shopify_admin_update_v0"
    assert data["status"] == "DRAFT"
    assert "NEEDS_INFO" in data["tags_add"]
    assert "note" in data
    assert "Order requires more info:" in data["note"]
