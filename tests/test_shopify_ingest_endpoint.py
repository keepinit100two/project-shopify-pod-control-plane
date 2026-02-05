import pytest

from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_shopify_ingest_endpoint_valid_payload(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "1234567890",
        "payload": {
            "id": 1234567890,
            "line_items": [],
        },
    }

    req = shopify_signed_request(payload, idempotency_key="signed-test-1")

    response = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )

    assert response.status_code == 200
    body = response.json()

    assert "event" in body
    assert "decision" in body


def test_shopify_ingest_endpoint_invalid_payload(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    payload = {
        # missing required fields on purpose
        "payload": {}
    }

    # Even invalid payload must be signed; signature verifies before schema validation
    req = shopify_signed_request(payload, idempotency_key="signed-test-2")

    response = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )

    # Your handler returns 422 via HTTPException right now for schema validation
    assert response.status_code in (400, 422)
