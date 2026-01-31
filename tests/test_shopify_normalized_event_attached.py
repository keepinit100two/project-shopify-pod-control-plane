from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shopify_ingest_attaches_normalized_metadata():
    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "1234567890",
        "payload": {
            "line_items": [
                {
                    "sku": "CANVAS_16x20",
                    "variant_id": 999,
                    "quantity": 1,
                    "properties": [
                        {"name": "pet_name", "value": "Luna"},
                        {"name": "style", "value": "Watercolor"},
                    ],
                }
            ]
        },
    }

    response = client.post(
        "/ingest/shopify/order_created",
        json=payload,
        headers={"Idempotency-Key": "test-normalized-attach-1"},
    )

    assert response.status_code == 200
    body = response.json()

    assert "metadata" in body["event"]
    assert "normalized" in body["event"]["metadata"]

    normalized = body["event"]["metadata"]["normalized"]

    assert normalized["order_id"] == "1234567890"
    assert normalized["shop_domain"] == "example.myshopify.com"
    assert len(normalized["line_items"]) == 1
    assert normalized["line_items"][0]["personalization"]["pet_name"] == "Luna"
