from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shopify_ingest_endpoint_valid_payload():
    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "1234567890",
        "payload": {
            "id": 1234567890,
            "line_items": [],
        },
    }

    response = client.post(
        "/ingest/shopify/order_created",
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] in {"accepted", "duplicate"}


def test_shopify_ingest_endpoint_invalid_payload():
    payload = {
        # missing required fields
        "payload": {}
    }

    response = client.post(
        "/ingest/shopify/order_created",
        json=payload,
    )

    assert response.status_code == 422
