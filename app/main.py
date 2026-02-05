from datetime import datetime
import uuid
import os
import json
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request

from app.core.idempotency import get_event, set_event
from app.core.logging import get_logger, log_event
from app.domain.schemas import (
    IngestRequest,
    Event,
    IngestResponse,
    ShopifyWebhookIngestRequest,
    OpsDispatchDraftsRequest,
    Decision,
)
from app.services.router import route_event
from app.services.actuator import execute_decision
from app.services.normalizer import normalize_shopify_order
from app.services.shopify_security import verify_shopify_hmac_b64

app = FastAPI(title="AI Control Plane")
logger = get_logger()


@app.get("/health")
def health_check():
    return {"status": "ok"}


def _process_ingest(req: IngestRequest, idempotency_key: str) -> IngestResponse:
    """
    Canonical pipeline runner for all adapters.
    Ingest -> Normalize (deterministic) -> Decide -> Act -> Observe

    IMPORTANT:
    - For audit, raw vendor payload remains in Event.payload.
    - Normalized canonical data (if available) is stored under Event.metadata["normalized"].
    """

    # Gate 2: Reuse existing Event if this key was already processed
    existing_event = get_event(idempotency_key)
    if existing_event:
        log_event(
            logger,
            event_name="ingest_duplicate",
            fields={
                "idempotency_key": idempotency_key,
                "event_id": existing_event.event_id,
                "event_type": existing_event.event_type,
                "source": existing_event.source,
            },
        )

        # Decide
        decision = route_event(existing_event)
        log_event(
            logger,
            event_name="decision_created",
            fields={
                "decision_id": decision.decision_id,
                "event_id": decision.event_id,
                "route": decision.route,
                "risk_level": decision.risk_level,
                "reason": decision.reason,
            },
        )

        # Act (safe execution)
        try:
            action_result = execute_decision(existing_event, decision)
            log_event(
                logger,
                event_name="action_executed"
                if action_result.status == "executed"
                else "action_noop",
                fields={
                    "action_id": action_result.action_id,
                    "event_id": action_result.event_id,
                    "decision_id": action_result.decision_id,
                    "action_type": action_result.action_type,
                    "status": action_result.status,
                    "artifact_path": action_result.artifact_path,
                    "reason": action_result.reason,
                },
            )
        except Exception as e:
            log_event(
                logger,
                event_name="action_failed",
                fields={
                    "event_id": existing_event.event_id,
                    "decision_id": decision.decision_id,
                    "route": decision.route,
                    "error": str(e),
                },
            )
            # We do not fail the whole request in Tier-1 v0; we stay observable and safe.
            return IngestResponse(event=existing_event, decision=decision)

        return IngestResponse(event=existing_event, decision=decision)

    # New Event
    event = Event(
        event_id=str(uuid.uuid4()),
        event_type=req.event_type,
        source=req.source,
        timestamp=datetime.utcnow(),
        actor=req.actor,
        payload=req.payload,   # raw vendor payload stays here for audit
        metadata=req.metadata, # adapter metadata (and normalized data later)
    )

    # Normalize Shopify orders into canonical fulfillment shape (stored in metadata)
    if req.source == "shopify":
        normalized = normalize_shopify_order(
            payload=req.payload,
            shop_domain=(req.metadata or {}).get("shop_domain", ""),
            topic=req.event_type,
            order_id=(req.metadata or {}).get("order_id", ""),
        )

        event.metadata = {
            **(event.metadata or {}),
            "normalized": normalized.model_dump(),
        }

    log_event(
        logger,
        event_name="ingest_created",
        fields={
            "idempotency_key": idempotency_key,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "source": event.source,
        },
    )

    # Decide
    decision = route_event(event)
    log_event(
        logger,
        event_name="decision_created",
        fields={
            "decision_id": decision.decision_id,
            "event_id": decision.event_id,
            "route": decision.route,
            "risk_level": decision.risk_level,
            "reason": decision.reason,
        },
    )

    # Persist Event for idempotency
    set_event(idempotency_key, event)

    # Act (safe execution)
    try:
        action_result = execute_decision(event, decision)
        log_event(
            logger,
            event_name="action_executed" if action_result.status == "executed" else "action_noop",
            fields={
                "action_id": action_result.action_id,
                "event_id": action_result.event_id,
                "decision_id": action_result.decision_id,
                "action_type": action_result.action_type,
                "status": action_result.status,
                "artifact_path": action_result.artifact_path,
                "reason": action_result.reason,
            },
        )
    except Exception as e:
        log_event(
            logger,
            event_name="action_failed",
            fields={
                "event_id": event.event_id,
                "decision_id": decision.decision_id,
                "route": decision.route,
                "error": str(e),
            },
        )
        # We do not fail the whole request in Tier-1 v0; we stay observable and safe.
        return IngestResponse(event=event, decision=decision)

    return IngestResponse(event=event, decision=decision)


@app.post("/ingest/api", response_model=IngestResponse)
def ingest_api(
    req: IngestRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> IngestResponse:
    # Gate 1: Idempotency-Key is required for generic ingest
    if not idempotency_key:
        log_event(
            logger,
            event_name="ingest_rejected",
            fields={
                "reason": "missing_idempotency_key",
                "event_type": req.event_type,
                "source": req.source,
            },
        )
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")

    return _process_ingest(req=req, idempotency_key=idempotency_key)


@app.post("/ingest/shopify/order_created", response_model=IngestResponse)
async def ingest_shopify_order_created(
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    x_shopify_hmac_sha256: Optional[str] = Header(default=None, alias="X-Shopify-Hmac-Sha256"),
) -> IngestResponse:
    """
    Shopify webhook ingest endpoint (Tier-1, strict HMAC verification).

    Strict mode:
      - Missing or invalid X-Shopify-Hmac-Sha256 => 401
    """
    secret = os.environ.get("SHOPIFY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="SHOPIFY_WEBHOOK_SECRET is not set")

    raw_body = await request.body()

    if not x_shopify_hmac_sha256:
        log_event(logger, "ingest_rejected", {"reason": "missing_shopify_hmac"})
        raise HTTPException(status_code=401, detail="Missing Shopify webhook signature")

    if not verify_shopify_hmac_b64(secret, raw_body, x_shopify_hmac_sha256):
        log_event(logger, "ingest_rejected", {"reason": "invalid_shopify_hmac"})
        raise HTTPException(status_code=401, detail="Invalid Shopify webhook signature")

    # Parse JSON only after signature verification
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Validate against adapter schema
    try:
        req = ShopifyWebhookIngestRequest(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    effective_key = (
        idempotency_key
        or req.idempotency_key
        or f"shopify:{req.shop_domain}:{req.topic}:{req.order_id}"
    )

    ingest_req = IngestRequest(
        source="shopify",
        event_type=req.topic,
        actor="shopify_webhook",
        payload=req.payload,
        metadata={
            "shop_domain": req.shop_domain,
            "order_id": str(req.order_id),
            "topic": req.topic,
        },
    )

    return _process_ingest(req=ingest_req, idempotency_key=effective_key)


@app.post("/ops/shopify/dispatch_drafts")
def ops_shopify_dispatch_drafts(req: OpsDispatchDraftsRequest):
    """
    Operator-controlled phase transition.

    Given an idempotency_key for an already-ingested Shopify event,
    generate dispatch request draft artifacts (no external calls).
    """
    existing_event = get_event(req.idempotency_key)
    if not existing_event:
        raise HTTPException(
            status_code=404,
            detail="Event not found for idempotency_key. Ingest must happen first.",
        )

    if existing_event.source != "shopify":
        raise HTTPException(
            status_code=400,
            detail="Dispatch drafts are only supported for Shopify events.",
        )

    decision = Decision(
        decision_id=str(uuid.uuid4()),
        event_id=existing_event.event_id,
        route="CREATE_DISPATCH_DRAFTS",
        reason="Operator triggered dispatch draft generation",
        risk_level="low",
        proposed_action={},
    )

    log_event(
        logger,
        event_name="ops_dispatch_drafts_requested",
        fields={
            "idempotency_key": req.idempotency_key,
            "event_id": existing_event.event_id,
        },
    )

    action_result = execute_decision(existing_event, decision)

    log_event(
        logger,
        event_name="ops_dispatch_drafts_completed",
        fields={
            "idempotency_key": req.idempotency_key,
            "event_id": existing_event.event_id,
            "status": action_result.status,
            "artifact_path": action_result.artifact_path,
        },
    )

    return {
        "event_id": existing_event.event_id,
        "action_result": action_result.model_dump(),
    }
