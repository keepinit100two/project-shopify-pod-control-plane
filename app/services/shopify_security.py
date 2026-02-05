import base64
import hashlib
import hmac


def compute_shopify_hmac_b64(secret: str, body_bytes: bytes) -> str:
    """
    Shopify webhook HMAC format:
      base64( HMAC_SHA256(secret, raw_request_body_bytes) )
    """
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def verify_shopify_hmac_b64(secret: str, body_bytes: bytes, header_hmac_b64: str) -> bool:
    """
    Constant-time compare against Shopify's X-Shopify-Hmac-Sha256 header value.
    """
    expected = compute_shopify_hmac_b64(secret, body_bytes)
    return hmac.compare_digest(expected, header_hmac_b64.strip())
