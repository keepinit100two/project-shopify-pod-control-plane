import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.domain.schemas import Event, Decision, ActionResult

# Where draft artifacts are stored: <repo_root>/artifacts/drafts/
DRAFT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "drafts"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _write_fulfillment_plan_drafts(event: Event, decision: Decision) -> List[str]:
    """
    Write one draft fulfillment plan artifact per line item.

    Normalized canonical data is expected at:
      event.metadata["normalized"]

    Returns a list of artifact paths written.
    """
    normalized = (event.metadata or {}).get("normalized") or {}
    line_items = normalized.get("line_items") or []

    artifact_paths: List[str] = []

    for idx, item in enumerate(line_items):
        artifact_path = DRAFT_DIR / f"{event.event_id}.fulfillment_plan.item_{idx}.json"

        draft_payload: Dict[str, Any] = {
            "schema_version": "fulfillment_plan_v0",
            "event_id": event.event_id,
            "decision_id": decision.decision_id,
            "route": decision.route,
            "risk_level": decision.risk_level,
            "reason": decision.reason,
            "status": "DRAFT",
            # High-value audit context
            "order_id": normalized.get("order_id"),
            "shop_domain": normalized.get("shop_domain"),
            "topic": normalized.get("topic"),
            # Per-item planning scope
            "line_item_index": idx,
            "line_item": item,
            # Placeholder for Micro-Step 6 (partner selection)
            "partner_selection": {"status": "PENDING"},
        }

        _write_json(artifact_path, draft_payload)
        artifact_paths.append(str(artifact_path))

    return artifact_paths


def execute_decision(event: Event, decision: Decision) -> ActionResult:
    """
    Act v0: Execute only safe, reversible actions.
    - CREATE_DRAFT_TICKET -> write a local draft JSON artifact
    - SHOPIFY_FULFILLMENT_PLAN -> write per-line-item fulfillment plan draft artifacts
    - REQUEST_MORE_INFO / ESCALATE_HUMAN -> no side effects (noop)

    This function is intentionally deterministic and side-effect bounded.
    """
    action_id = str(uuid.uuid4())

    # Only execute draft ticket creation (safe, reversible)
    if decision.route == "CREATE_DRAFT_TICKET":
        # Idempotency at the action layer:
        # Draft artifact path is derived from event_id, so repeated runs overwrite the same file.
        artifact_path = DRAFT_DIR / f"{event.event_id}.draft_ticket.json"

        draft_payload = {
            "event_id": event.event_id,
            "decision_id": decision.decision_id,
            "route": decision.route,
            "risk_level": decision.risk_level,
            "reason": decision.reason,
            "proposed_action": decision.proposed_action,
        }

        _write_json(artifact_path, draft_payload)

        return ActionResult(
            action_id=action_id,
            event_id=event.event_id,
            decision_id=decision.decision_id,
            action_type="create_ticket_draft",
            status="executed",
            artifact_path=str(artifact_path),
            reason="Draft ticket artifact written",
        )

    # Shopify: create per-line-item fulfillment plan drafts (safe, reversible)
    if decision.route == "SHOPIFY_FULFILLMENT_PLAN":
        artifact_paths = _write_fulfillment_plan_drafts(event, decision)

        return ActionResult(
            action_id=action_id,
            event_id=event.event_id,
            decision_id=decision.decision_id,
            action_type="create_fulfillment_plan_drafts",
            status="executed",
            artifact_path=";".join(artifact_paths) if artifact_paths else None,
            reason=f"Wrote {len(artifact_paths)} fulfillment plan draft artifact(s)",
        )

    # Everything else: no action executed (still a valid result)
    return ActionResult(
        action_id=action_id,
        event_id=event.event_id,
        decision_id=decision.decision_id,
        action_type="noop",
        status="noop",
        artifact_path=None,
        reason=f"No action executed for route: {decision.route}",
    )
