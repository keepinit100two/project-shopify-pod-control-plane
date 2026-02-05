import json
import os

from fastapi.testclient import TestClient

from app.main import app
from app.services.shopify_security import compute_shopify_hmac_b64

client = TestClient(app)


def test_shopify_webhook_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", "dev_secret_123")

    body = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "hmac-1",
        "payload": {"line_items": []},
    }

    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")

    r = client.post(
        "/ingest/shopify/order_created",
        content=raw,
        headers={"Content-Type": "application/json", "Idempotency-Key": "hmac-test-1"},
    )
    assert r.status_code == 401


def test_shopify_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", "dev_secret_123")

    body = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "hmac-2",
        "payload": {"line_items": []},
    }

    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")

    r = client.post(
        "/ingest/shopify/order_created",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "hmac-test-2",
            "X-Shopify-Hmac-Sha256": "totally-wrong",
        },
    )
    assert r.status_code == 401


def test_shopify_webhook_accepts_valid_signature(monkeypatch):
    monkeypatch.setenv("SHOPIFY_WEBHOOK_SECRET", "dev_secret_123")

    body = {
        "topic": "orders/create",
        "shop_domain": "example.myshopify.com",
        "order_id": "hmac-3",
        "payload": {"line_items": []},
    }

    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = compute_shopify_hmac_b64("dev_secret_123", raw)

    r = client.post(
        "/ingest/shopify/order_created",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "hmac-test-3",
            "X-Shopify-Hmac-Sha256": sig,
        },
    )
    assert r.status_code == 200
