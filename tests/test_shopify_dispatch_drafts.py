import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_dispatch_drafts_writes_one_draft_per_line_item(tmp_path, monkeypatch):
    # Redirect DRAFT_DIR to temp
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    # Build an event by ingesting a Shopify order that will normalize cleanly
    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "dispatch-test-1",
        "payload": {
            "line_items": [
                {
                    "sku": "CANVAS_16x20",
                    "variant_id": 1,
                    "quantity": 1,
                    "properties": [
                        {"name": "pet_name", "value": "Luna"},
                        {"name": "style", "value": "Watercolor"},
                    ],
                },
                {
                    "sku": "CANVAS_12x16",
                    "variant_id": 2,
                    "quantity": 1,
                    "properties": [
                        {"name": "pet_name", "value": "Max"},
                        {"name": "style", "value": "Minimalist"},
                    ],
                },
            ]
        },
    }

    r = client.post(
        "/ingest/shopify/order_created",
        json=payload,
        headers={"Idempotency-Key": "dispatch-test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    event = body["event"]

    # Now directly execute the dispatch-draft phase using the actuator.
    # We keep this deterministic and in-process (no external calls).
    from app.domain.schemas import Decision
    decision = Decision(
        decision_id="test-decision",
        event_id=event["event_id"],
        route="CREATE_DISPATCH_DRAFTS",
        reason="test",
        risk_level="low",
        proposed_action={},
    )

    # Reconstruct a minimal Event-like object by importing the stored event via idempotency is complex;
    # easier: call actuator with a synthetic Event from schemas using the event payload/metadata we got back.
    from app.domain.schemas import Event as EventModel
    event_model = EventModel(**event)

    result = actuator.execute_decision(event_model, decision)
    assert result.status == "executed"

    artifacts = list(tmp_path.glob("*.dispatch_request.item_*.json"))
    assert len(artifacts) == 2

    data = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "dispatch_request_v0"
    assert data["status"] == "DRAFT"
    assert data["partner"] in {"POD_A", "POD_B"}
    assert data["idempotency_key"].startswith("dispatch:")
    assert "payload" in data
