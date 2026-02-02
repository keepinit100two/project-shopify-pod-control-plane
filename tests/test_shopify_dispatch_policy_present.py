import json
from pathlib import Path


def test_routing_config_contains_shopify_dispatch_policy():
    config_path = Path("configs/routing.json")
    data = json.loads(config_path.read_text(encoding="utf-8"))

    shopify = data["source_policies"]["shopify"]
    assert "dispatch" in shopify
    assert shopify["dispatch"]["draft_route"] == "CREATE_DISPATCH_DRAFTS"
    assert shopify["dispatch"]["mode"] == "draft_only"
