from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


class IngestRequest(BaseModel):
    event_type: str = Field(..., description="Type of event, e.g. support_request, user_message, task_requested")
    source: str = Field("api", description="Where this event came from, e.g. api, slack, telegram")
    actor: Optional[str] = Field(None, description="Who initiated the event (user id/email), if available")
    payload: Dict[str, Any] = Field(..., description="The core content of the event")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional extra context for debugging/routing")


class Event(BaseModel):
    event_id: str = Field(..., description="Unique idempotency anchor for this event")
    event_type: str
    source: str
    timestamp: datetime
    actor: Optional[str] = None
    payload: Dict[str, Any]
    metadata: Dict[str, Any]


class Decision(BaseModel):
    decision_id: str = Field(..., description="Unique identifier for this decision")
    event_id: str = Field(..., description="The event this decision was derived from")
    route: str = Field(
        ...,
        description="Chosen route, e.g. ESCALATE_HUMAN, REQUEST_MORE_INFO, CREATE_DRAFT_TICKET",
    )
    reason: str = Field(..., description="Human-readable reason for this decision")
    risk_level: str = Field("low", description="Risk level: low, medium, high")
    proposed_action: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured action request",
    )


class IngestResponse(BaseModel):
    event: Event
    decision: Decision


class ActionResult(BaseModel):
    action_id: str = Field(..., description="Unique identifier for this action execution")
    event_id: str = Field(..., description="Event the action corresponds to")
    decision_id: str = Field(..., description="Decision that triggered this action")
    action_type: str = Field(..., description="Type of action executed (or attempted)")
    status: str = Field(..., description="Outcome: executed, skipped, noop, failed")
    artifact_path: Optional[str] = Field(None, description="Where a draft artifact was stored (if any)")
    reason: str = Field(..., description="Human-readable explanation of what happened")


class ShopifyWebhookIngestRequest(BaseModel):
    """
    Adapter-specific input schema for Shopify webhooks.

    This model represents the *raw* webhook payload as received
    from Shopify before normalization into a canonical Event.
    """

    topic: str = Field(
        ...,
        description="Shopify webhook topic (e.g. 'orders/create')",
    )

    shop_domain: str = Field(
        ...,
        description="The Shopify shop domain (e.g. 'example.myshopify.com')",
    )

    order_id: str = Field(
        ...,
        description="Shopify order identifier (stringified for stability)",
    )

    payload: Dict[str, Any] = Field(
        ...,
        description="Raw Shopify webhook JSON payload",
    )

    idempotency_key: Optional[str] = Field(
        None,
        description=(
            "Optional idempotency key. If not provided, the adapter "
            "will deterministically derive one from the payload."
        ),
    )


class PersonalizationInput(BaseModel):
    """
    Typed personalization inputs extracted from line item properties.
    Keep this minimal at first; expand safely later.
    """
    pet_name: Optional[str] = Field(None, description="Customer-provided pet name")
    style: Optional[str] = Field(None, description="Style choice (e.g., 'Watercolor')")
    photo_url: Optional[str] = Field(None, description="URL to uploaded photo or asset reference")


class OrderLineItem(BaseModel):
    sku: Optional[str] = Field(None, description="SKU if present")
    variant_id: Optional[str] = Field(None, description="Variant ID if present (string)")
    quantity: int = Field(..., description="Quantity ordered")
    personalization: PersonalizationInput = Field(
        default_factory=PersonalizationInput,
        description="Extracted personalization inputs for this item",
    )


class RulesSnapshot(BaseModel):
    """
    Placeholder for 'policy knobs' captured at decision time.
    For now, keep it minimal and expand later when you integrate metafields/metaobjects.
    """
    snapshot_version: str = Field("v0", description="Snapshot schema version")
    data: Dict[str, Any] = Field(default_factory=dict, description="Resolved routing knobs")


class OrderFulfillmentEvent(BaseModel):
    """
    Canonical normalized payload for a Shopify order fulfillment workflow.
    Stored under Event.metadata['normalized'] to preserve raw payload for audit.
    """
    order_id: str = Field(..., description="Shopify order ID (string)")
    shop_domain: str = Field(..., description="Shop domain for tenancy/audit")
    topic: str = Field(..., description="Webhook topic/event type (e.g., orders/create)")
    line_items: List[OrderLineItem] = Field(default_factory=list)
    rules_snapshot: RulesSnapshot = Field(default_factory=RulesSnapshot)
    

class OpsDispatchDraftsRequest(BaseModel):
    idempotency_key: str = Field(..., description="Idempotency key of an already-ingested Shopify event")
