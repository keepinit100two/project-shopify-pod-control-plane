import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from app.domain.schemas import Event, Decision


_CONFIG_PATH = Path("configs/routing.json")


def _load_config() -> Dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _get_text(event: Event) -> str:
    """
    Extract a best-effort text field from the event payload.
    We keep this defensive because payloads vary across sources/domains.
    """
    payload: Any = event.payload or {}
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text
    return ""


def _get_by_path(event: Event, path: str) -> Any:
    """
    Resolve dotted path like:
      - metadata.normalized.order_id
    against an Event object with attributes + dict metadata.
    """
    parts = path.split(".")
    cur: Any = event
    for part in parts:
        if cur is None:
            return None

        # Event attributes first (event_id, source, payload, metadata...)
        if hasattr(cur, part):
            cur = getattr(cur, part)
            continue

        # Dict traversal for payload/metadata/normalized structures
        if isinstance(cur, dict):
            cur = cur.get(part)
            continue

        return None

    return cur


def _missing_fields(event: Event, field_paths: list[str]) -> list[str]:
    missing: list[str] = []
    for p in field_paths:
        v = _get_by_path(event, p)
        if v in (None, "", [], {}):
            missing.append(p)
    return missing


def route_event(event: Event) -> Decision:
    """
    Decide what should happen next for an Event using a deterministic routing stack.

    Rule order:
      1) Security keywords -> ESCALATE_HUMAN (high risk)
      2) Source policy required fields (if configured) -> REQUEST_MORE_INFO (medium risk)
      3) Shopify: missing personalization per item -> REQUEST_MORE_INFO (medium risk)
      4) Otherwise -> source default route (if configured) or global default route
      5) For non-Shopify (legacy behavior): missing urgency -> REQUEST_MORE_INFO else CREATE_DRAFT_TICKET

    No side effects. Returns a reviewable plan only.
    """
    config = _load_config()
    decision_id = str(uuid.uuid4())
    text = _get_text(event).lower()

    # Rule 1: High-risk / security keywords -> escalate
    security_keywords = config.get("security_keywords", ["password", "credential", "security", "breach"])
    if any(k in text for k in security_keywords):
        return Decision(
            decision_id=decision_id,
            event_id=event.event_id,
            route="ESCALATE_HUMAN",
            reason="Security-related keyword detected",
            risk_level="high",
            proposed_action={},
        )

    # Source policy override (Shopify + future sources)
    source_policies: Dict[str, Any] = config.get("source_policies", {})
    policy: Optional[Dict[str, Any]] = source_policies.get(event.source)

    if policy:
        # Rule 2: Missing required fields under the source policy
        req_fields = policy.get("required_fields", [])
        missing = _missing_fields(event, req_fields)
        if missing:
            question = policy.get("clarification_question") or config.get("clarification_question") or "Missing required fields."
            return Decision(
                decision_id=decision_id,
                event_id=event.event_id,
                route="REQUEST_MORE_INFO",
                reason=f"Missing required field(s): {', '.join(missing)}",
                risk_level="medium",
                proposed_action={
                    "question": question,
                    "missing_fields": missing,
                },
            )

        # Rule 3: Shopify personalization requirements (UX choice: request more info)
        if event.source == "shopify":
            normalized = (event.metadata or {}).get("normalized") or {}
            line_items = normalized.get("line_items") or []
            required_keys = policy.get("personalization_required_per_item", [])

            missing_personalization: list[str] = []
            for idx, item in enumerate(line_items):
                p = (item.get("personalization") or {})
                for k in required_keys:
                    if p.get(k) in (None, ""):
                        missing_personalization.append(f"line_items[{idx}].personalization.{k}")

            if missing_personalization:
                question = policy.get("clarification_question") or "Missing required personalization inputs."
                return Decision(
                    decision_id=decision_id,
                    event_id=event.event_id,
                    route="REQUEST_MORE_INFO",
                    reason=f"Missing personalization field(s): {', '.join(missing_personalization)}",
                    risk_level="medium",
                    proposed_action={
                        "question": question,
                        "missing_fields": missing_personalization,
                    },
                )

        # Rule 4: Use source-specific default route
        default_route = policy.get("default_route") or config.get("default_route") or "REQUEST_MORE_INFO"
        return Decision(
            decision_id=decision_id,
            event_id=event.event_id,
            route=default_route,
            reason=f"Routed via source policy: {event.source}",
            risk_level="low",
            proposed_action={},
        )

    # ---- Legacy fallback behavior (non-Shopify, preserves current semantics) ----

    # Rule 2 (legacy): Missing urgency -> request more info
    urgency = None
    if isinstance(event.payload, dict):
        urgency = event.payload.get("urgency")

    if not urgency:
        return Decision(
            decision_id=decision_id,
            event_id=event.event_id,
            route="REQUEST_MORE_INFO",
            reason="Missing required field: urgency",
            risk_level="medium",
            proposed_action={
                "question": config.get("clarification_question", "How urgent is this? (low / medium / high)"),
                "missing_fields": ["urgency"],
            },
        )

    # Rule 3 (legacy): Default -> create a draft ticket
    summary = "Support request"
    if text:
        summary = text[:80]  # keep short and safe

    return Decision(
        decision_id=decision_id,
        event_id=event.event_id,
        route=config.get("default_route", "CREATE_DRAFT_TICKET"),
        reason="Standard support request",
        risk_level="low",
        proposed_action={
            "type": "create_ticket_draft",
            "queue": config.get("default_queue", "IT"),
            "priority": str(urgency).lower(),
            "summary": summary,
            "description": (event.payload if isinstance(event.payload, dict) else {"text": text}),
        },
    )
