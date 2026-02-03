import json
from pathlib import Path


def test_routing_config_contains_shopify_admin_updates_policy():
    config_path = Path("configs/routing.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))

    shopify = data["source_policies"]["shopify"]
    assert "shopify_admin_updates" in shopify

    updates = shopify["shopify_admin_updates"]
    assert "REQUEST_MORE_INFO" in updates
    assert "SHOPIFY_FULFILLMENT_PLAN" in updates
    assert "CREATE_DISPATCH_DRAFTS" in updates

    assert "tags_add" in updates["REQUEST_MORE_INFO"]
    assert "note_template" in updates["REQUEST_MORE_INFO"]
