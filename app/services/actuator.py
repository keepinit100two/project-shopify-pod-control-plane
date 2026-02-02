import json
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.domain.schemas import Event, Decision, ActionResult

# Where draft artifacts are stored: <repo_root>/artifacts/drafts/
DRAFT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "drafts"
CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "routing.json"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_routing_config() -> Dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _get_shopify_partner_rules(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (
        config.get("source_policies", {})
        .get("shopify", {})
        .get("pod_partner_rules", [])
    )


def _select_pod_partner_for_item(
    item: Dict[str, Any],
    rules: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Deterministically select a POD partner for a normalized line item using ordered rules.
    Fail-open behavior: if no rule matches, return PENDING (but config includes a default rule).
    """
    sku = str(item.get("sku") or "")

    for rule in rules:
        match = rule.get("match", {}) if isinstance(rule, dict) else {}
        partner = rule.get("partner")
        reason = rule.get("reason", "Matched partner rule")

        # Rule: sku contains substring
        sku_contains = match.get("sku_contains")
        if isinstance(sku_contains, str) and sku_contains and sku_contains in sku:
            return {"status": "SELECTED", "partner": partner, "reason": reason}

        # Rule: default catch-all
        if match.get("default") is True:
            return {"status": "SELECTED", "partner": partner, "reason": reason}

    # Shouldn't happen if default rule exists
    return {"status": "PENDING", "partner": None, "reason": "No partner rule matched"}


def _write_fulfillment_plan_drafts(event: Event, decision: Decision) -> List[str]:
    """
    Write one draft fulfillment plan artifact per line item.

    Normalized canonical data is expected at:
      event.metadata["normalized"]

    Returns a list of artifact paths written.
    """
    normalized = (event.metadata or {}).get("normalized") or {}
    line_items = normalized.get("line_items") or []

    config = _load_routing_config()
    partner_rules = _get_shopify_partner_rules(config)

    artifact_paths: List[str] = []

    for idx, item in enumerate(line_items):
        artifact_path = DRAFT_DIR / f"{event.event_id}.fulfillment_plan.item_{idx}.json"

        partner_selection = _select_pod_partner_for_item(item, partner_rules)

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
            # Selected partner (Tier-1 deterministic)
            "partner_selection": partner_selection,
        }

        _write_json(artifact_path, draft_payload)
        artifact_paths.append(str(artifact_path))

    return artifact_paths


def _write_dispatch_request_drafts(event: Event, decision: Decision) -> List[str]:
    """
    Write one draft dispatch request artifact per line item.

    This does NOT call partner APIs. It creates inspectable request payloads
    that can be dispatched in a later phase.
    """
    normalized = (event.metadata or {}).get("normalized") or {}
    line_items = normalized.get("line_items") or []

    config = _load_routing_config()
    partner_rules = _get_shopify_partner_rules(config)

    artifact_paths: List[str] = []

    for idx, item in enumerate(line_items):
        artifact_path = DRAFT_DIR / f"{event.event_id}.dispatch_request.item_{idx}.json"

        # Deterministically select partner (same logic as planning)
        partner_selection = _select_pod_partner_for_item(item, partner_rules)
        partner = partner_selection.get("partner")

        dispatch_payload: Dict[str, Any] = {
            "schema_version": "dispatch_request_v0",
            "event_id": event.event_id,
            "decision_id": decision.decision_id,
            "route": decision.route,
            "status": "DRAFT",
            # Audit context
            "order_id": normalized.get("order_id"),
            "shop_domain": normalized.get("shop_domain"),
            "topic": normalized.get("topic"),
            # Per-item scope
            "line_item_index": idx,
            "partner": partner,
            "partner_reason": partner_selection.get("reason"),
            # Deterministic idempotency key for later real dispatch
            "idempotency_key": f"dispatch:{event.event_id}:item_{idx}",
            # What would be sent (placeholder fields allowed at v0)
            "payload": {
                "sku": item.get("sku"),
                "variant_id": item.get("variant_id"),
                "quantity": item.get("quantity"),
                "personalization": item.get("personalization"),
                "shipping": {"status": "PENDING"},
                "assets": {"status": "PENDING"},
            },
            "reason": "Dispatch draft created; awaiting assets and shipping details",
        }

        _write_json(artifact_path, dispatch_payload)
        artifact_paths.append(str(artifact_path))

    return artifact_paths


def execute_decision(event: Event, decision: Decision) -> ActionResult:
    """
    Act v0: Execute only safe, reversible actions.
    - CREATE_DRAFT_TICKET -> write a local draft JSON artifact
    - SHOPIFY_FULFILLMENT_PLAN -> write per-line-item fulfillment plan draft artifacts (with partner selected)
    - CREATE_DISPATCH_DRAFTS -> write per-line-item dispatch request draft artifacts (draft-only)
    - REQUEST_MORE_INFO / ESCALATE_HUMAN -> no side effects (noop)

    This function is intentionally deterministic and side-effect bounded.
    """
    action_id = str(uuid.uuid4())

    # Only execute draft ticket creation (safe, reversible)
    if decision.route == "CREATE_DRAFT_TICKET":
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

    # Dispatch preparation: create per-line-item dispatch request drafts (safe, reversible)
    if decision.route == "CREATE_DISPATCH_DRAFTS":
        artifact_paths = _write_dispatch_request_drafts(event, decision)

        return ActionResult(
            action_id=action_id,
            event_id=event.event_id,
            decision_id=decision.decision_id,
            action_type="create_dispatch_drafts",
            status="executed",
            artifact_path=";".join(artifact_paths) if artifact_paths else None,
            reason=f"Wrote {len(artifact_paths)} dispatch request draft artifact(s)",
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
