from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_shopify_missing_personalization_routes_to_request_more_info(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "route-test-1",
        "payload": {
            "line_items": [
                {
                    "sku": "CANVAS_16x20",
                    "variant_id": 999,
                    "quantity": 1,
                    "properties": [
                        {"name": "style", "value": "Watercolor"}
                        # pet_name missing
                    ],
                }
            ]
        },
    }

    req = shopify_signed_request(payload, idempotency_key="shopify-route-test-1")

    r = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["route"] == "REQUEST_MORE_INFO"
    assert "Missing personalization field" in body["decision"]["reason"]


def test_shopify_complete_personalization_routes_to_fulfillment_plan(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "route-test-2",
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

    req = shopify_signed_request(payload, idempotency_key="shopify-route-test-2")

    r = client.post(
        "/ingest/shopify/order_created",
        content=req["content"],
        headers=req["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["route"] == "SHOPIFY_FULFILLMENT_PLAN"
