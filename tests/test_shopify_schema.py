import pytest
from pydantic import ValidationError

from app.domain.schemas import ShopifyWebhookIngestRequest


def test_shopify_webhook_schema_valid_payload():
    data = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "1234567890",
        "payload": {
            "id": 1234567890,
            "line_items": [],
        },
    }

    req = ShopifyWebhookIngestRequest(**data)

    assert req.topic == "orders/create"
    assert req.shop_domain == "example.myshopify.com"
    assert req.order_id == "1234567890"
    assert isinstance(req.payload, dict)
    assert req.idempotency_key is None


def test_shopify_webhook_schema_missing_required_field():
    data = {
        # "topic" is intentionally missing
        "shop_domain": "example.myshopify.com",
        "order_id": "1234567890",
        "payload": {},
    }

    with pytest.raises(ValidationError):
        ShopifyWebhookIngestRequest(**data)
