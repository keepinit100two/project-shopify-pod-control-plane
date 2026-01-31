from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_shopify_missing_personalization_routes_to_request_more_info():
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

    r = client.post(
        "/ingest/shopify/order_created",
        json=payload,
        headers={"Idempotency-Key": "shopify-route-test-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["route"] == "REQUEST_MORE_INFO"
    assert "Missing personalization field" in body["decision"]["reason"]


def test_shopify_complete_personalization_routes_to_fulfillment_plan():
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

    r = client.post(
        "/ingest/shopify/order_created",
        json=payload,
        headers={"Idempotency-Key": "shopify-route-test-2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["route"] == "SHOPIFY_FULFILLMENT_PLAN"
