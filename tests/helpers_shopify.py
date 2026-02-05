import json
from typing import Any, Dict, Optional

from app.services.shopify_security import compute_shopify_hmac_b64


DEFAULT_SHOPIFY_SECRET = "dev_secret_123"


def shopify_signed_request(
    body: Dict[str, Any],
    *,
    secret: str = DEFAULT_SHOPIFY_SECRET,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns a dict with:
      - content: raw JSON bytes (canonical encoding)
      - headers: includes Content-Type, X-Shopify-Hmac-Sha256, and optional Idempotency-Key
    """
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = compute_shopify_hmac_b64(secret, raw)

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Hmac-Sha256": sig,
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    return {"content": raw, "headers": headers}
