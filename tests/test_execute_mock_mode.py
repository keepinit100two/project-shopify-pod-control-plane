import json

import httpx
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers_shopify import shopify_signed_request, DEFAULT_SHOPIFY_SECRET

client = TestClient(app)


def test_ops_dispatch_execute_mock_writes_partner_job_results(tmp_path, monkeypatch):
    """
    Ensures mode="execute_mock" performs outbound HTTP calls (mocked) and writes
    partner job result artifacts per line item.

    We do NOT require the real mock partner service to be running for this test.
    """

    # Required for strict Shopify HMAC verification
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", DEFAULT_SHOPIFY_SECRET)
    monkeypatch.setenv("MOCK_POD_BASE_URL", "http://mock.local")

    # Redirect artifacts to temp
    from app.services import actuator
    monkeypatch.setattr(actuator, "DRAFT_DIR", tmp_path)

    # Patch httpx.Client used inside actuator to avoid real network calls
    class PatchedClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None):
            # Extract partner from URL: http://mock.local/partner/<partner>/jobs
            # Example path: /partner/POD_B/jobs
            path = httpx.URL(url).path
            parts = [p for p in path.split("/") if p]
            partner = parts[1] if len(parts) >= 2 else "UNKNOWN"

            idem = (headers or {}).get("Idempotency-Key", "")

            req = httpx.Request("POST", url)
            return httpx.Response(
                200,
                request=req,
                json={
                    "partner": partner,
                    "job_id": "job_test_123",
                    "status": "created",
                    "created_at": "now",
                    "idempotency_key": idem,
                    "echo": json or {},
                },
            )

    monkeypatch.setattr(actuator.httpx, "Client", PatchedClient)

    # Step 1: Ingest a Shopify order (creates fulfillment plan drafts + stores event)
    idem_key = "shopify:example.myshopify.com:orders/create:exec-mock-1"

    payload = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "exec-mock-1",
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

    signed = shopify_signed_request(payload, idempotency_key=idem_key)

    r1 = client.post(
        "/ingest/shopify/order_created",
        content=signed["content"],
        headers=signed["headers"],
    )
    assert r1.status_code == 200

    # Step 2: Operator triggers execute_mock mode on the SAME ops endpoint
    r2 = client.post(
        "/ops/shopify/dispatch_drafts",
        json={"idempotency_key": idem_key, "mode": "execute_mock"},
    )
    assert r2.status_code == 200

    body = r2.json()
    assert body["action_result"]["status"] == "executed"

    # Step 3: Verify partner job result artifacts exist (2 items => 2 results)
    results = list(tmp_path.glob("*.partner_job.item_*.json"))
    assert len(results) == 2

    data = json.loads(results[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == "partner_job_result_v0"
    assert data["status"] == "EXECUTED"
    assert data["partner"] in {"POD_A", "POD_B"}
    assert data["dispatch_idempotency_key"].startswith("dispatch:")
    assert "partner_response" in data
    assert data["partner_response"]["job_id"] == "job_test_123"
