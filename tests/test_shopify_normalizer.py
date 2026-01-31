from app.services.normalizer import normalize_shopify_order


def test_normalize_shopify_order_basic_extracts_line_items_and_personalization():
    payload = {
        "id": 123,
        "line_items": [
            {
                "sku": "CANVAS_PET_16x20",
                "variant_id": 999,
                "quantity": 1,
                "properties": [
                    {"name": "pet_name", "value": "Luna"},
                    {"name": "style", "value": "Watercolor"},
                    {"name": "photo_url", "value": "https://example.com/photo.jpg"},
                ],
            }
        ],
    }

    normalized = normalize_shopify_order(
        payload,
        shop_domain="example.myshopify.com",
        topic="orders/create",
        order_id="1234567890",
    )

    assert normalized.order_id == "1234567890"
    assert normalized.shop_domain == "example.myshopify.com"
    assert normalized.topic == "orders/create"
    assert len(normalized.line_items) == 1

    item = normalized.line_items[0]
    assert item.sku == "CANVAS_PET_16x20"
    assert item.variant_id == "999"
    assert item.quantity == 1
    assert item.personalization.pet_name == "Luna"
    assert item.personalization.style == "Watercolor"
    assert item.personalization.photo_url == "https://example.com/photo.jpg"


def test_normalize_shopify_order_handles_missing_properties():
    payload = {
        "line_items": [
            {"sku": "X", "variant_id": 1, "quantity": 2}
        ]
    }

    normalized = normalize_shopify_order(
        payload,
        shop_domain="example.myshopify.com",
        topic="orders/create",
        order_id="1",
    )

    assert len(normalized.line_items) == 1
    item = normalized.line_items[0]
    assert item.quantity == 2
    assert item.personalization.pet_name is None
