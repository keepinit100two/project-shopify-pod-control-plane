import json
from pathlib import Path


def test_routing_config_contains_shopify_source_policy():
    config_path = Path("configs/routing.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))

    assert "source_policies" in data
    assert "shopify" in data["source_policies"]

    shopify = data["source_policies"]["shopify"]
    assert shopify["default_route"] == "SHOPIFY_FULFILLMENT_PLAN"
    assert "personalization_required_per_item" in shopify
