import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import httpx

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


def _get_shopify_admin_update_policy(config: Dict[str, Any]) -> Dict[str, Any]:
    return (
        config.get("source_policies", {})
        .get("shopify", {})
        .get("shopify_admin_updates", {})
    )


def _render_note(template: str, *, reason: str) -> str:
    return template.replace("{reason}", reason)


def _write_shopify_admin_update_draft(event: Event, decision: Decision) -> str:
    """
    Emit a draft artifact describing intended Shopify Admin updates (tags + note).
    This is config-driven and produces no external side effects.
    """
    if event.source != "shopify":
        return ""

    config = _load_routing_config()
    updates = _get_shopify_admin_update_policy(config)
    policy = updates.get(decision.route)

    if not policy:
        return ""

    normalized = (event.metadata or {}).get("normalized") or {}

    tags_add = policy.get("tags_add", [])
    tags_remove = policy.get("tags_remove", [])
    note_template = policy.get("note_template", "")
    note = _render_note(note_template, reason=decision.reason) if note_template else ""

    artifact_path = DRAFT_DIR / f"{event.event_id}.shopify_admin_update.{decision.route}.json"

    draft_payload: Dict[str, Any] = {
        "schema_version": "shopify_admin_update_v0",
        "event_id": event.event_id,
        "decision_id": decision.decision_id,
        "route": decision.route,
        "status": "DRAFT",
        "order_id": normalized.get("order_id"),
        "shop_domain": normalized.get("shop_domain"),
        "tags_add": tags_add,
        "tags_remove": tags_remove,
        "note": note,
    }

    _write_json(artifact_path, draft_payload)
    return str(artifact_path)


def _select_pod_partner_for_item(item: Dict[str, Any], rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Deterministically select a POD partner for a normalized line item using ordered rules.
    Fail-open behavior: default rule should exist in config.
    """
    sku = str(item.get("sku") or "")

    for rule in rules:
        match = rule.get("match", {}) if isinstance(rule, dict) else {}
        partner = rule.get("partner")
        reason = rule.get("reason", "Matched partner rule")

        sku_contains = match.get("sku_contains")
        if isinstance(sku_contains, str) and sku_contains and sku_contains in sku:
            return {"status": "SELECTED", "partner": partner, "reason": reason}

        if match.get("default") is True:
            return {"status": "SELECTED", "partner": partner, "reason": reason}

    return {"status": "PENDING", "partner": None, "reason": "No partner rule matched"}


def _write_fulfillment_plan_drafts(event: Event, decision: Decision) -> List[str]:
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
            "order_id": normalized.get("order_id"),
            "shop_domain": normalized.get("shop_domain"),
            "topic": normalized.get("topic"),
            "line_item_index": idx,
            "line_item": item,
            "partner_selection": partner_selection,
        }

        _write_json(artifact_path, draft_payload)
        artifact_paths.append(str(artifact_path))

    return artifact_paths


def _write_dispatch_request_drafts(event: Event, decision: Decision) -> List[str]:
    normalized = (event.metadata or {}).get("normalized") or {}
    line_items = normalized.get("line_items") or []

    config = _load_routing_config()
    partner_rules = _get_shopify_partner_rules(config)

    artifact_paths: List[str] = []

    for idx, item in enumerate(line_items):
        artifact_path = DRAFT_DIR / f"{event.event_id}.dispatch_request.item_{idx}.json"

        partner_selection = _select_pod_partner_for_item(item, partner_rules)
        partner = partner_selection.get("partner")

        dispatch_payload: Dict[str, Any] = {
            "schema_version": "dispatch_request_v0",
            "event_id": event.event_id,
            "decision_id": decision.decision_id,
            "route": decision.route,
            "status": "DRAFT",
            "order_id": normalized.get("order_id"),
            "shop_domain": normalized.get("shop_domain"),
            "topic": normalized.get("topic"),
            "line_item_index": idx,
            "partner": partner,
            "partner_reason": partner_selection.get("reason"),
            "idempotency_key": f"dispatch:{event.event_id}:item_{idx}",
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


def _execute_dispatch_to_mock_partner(event: Event, decision: Decision) -> List[str]:
    """
    Execute real HTTP dispatch calls to the mock partner service for each line item.
    Writes one partner job result artifact per line item.

    Uses per-line-item idempotency keys:
      dispatch:<event_id>:item_<i>
    """
    base_url = os.environ.get("MOCK_POD_BASE_URL", "http://127.0.0.1:9090")

    normalized = (event.metadata or {}).get("normalized") or {}
    line_items = normalized.get("line_items") or []

    config = _load_routing_config()
    partner_rules = _get_shopify_partner_rules(config)

    artifact_paths: List[str] = []

    for idx, item in enumerate(line_items):
        partner_selection = _select_pod_partner_for_item(item, partner_rules)
        partner = str(partner_selection.get("partner"))

        dispatch_idem = f"dispatch:{event.event_id}:item_{idx}"

        url = f"{base_url.rstrip('/')}/partner/{partner}/jobs"
        body = {
            "order_id": str(normalized.get("order_id")),
            "shop_domain": str(normalized.get("shop_domain")),
            "line_item_index": idx,
            "payload": {
                "sku": item.get("sku"),
                "variant_id": item.get("variant_id"),
                "quantity": item.get("quantity"),
                "personalization": item.get("personalization"),
            },
        }

        with httpx.Client(timeout=10.0) as client:
            r = client.post(url, json=body, headers={"Idempotency-Key": dispatch_idem})
            r.raise_for_status()
            resp = r.json()

        artifact_path = DRAFT_DIR / f"{event.event_id}.partner_job.item_{idx}.json"
        _write_json(
            artifact_path,
            {
                "schema_version": "partner_job_result_v0",
                "event_id": event.event_id,
                "decision_id": decision.decision_id,
                "route": decision.route,
                "status": "EXECUTED",
                "order_id": normalized.get("order_id"),
                "shop_domain": normalized.get("shop_domain"),
                "line_item_index": idx,
                "partner": partner,
                "dispatch_idempotency_key": dispatch_idem,
                "partner_response": resp,
            },
        )
        artifact_paths.append(str(artifact_path))

    return artifact_paths


def execute_decision(event: Event, decision: Decision) -> ActionResult:
    """
    Act v0: Execute only safe, reversible actions.
    Additionally, for Shopify routes with admin update policy, emit a Shopify Admin Update Draft artifact.

    - CREATE_DRAFT_TICKET -> write a local draft JSON artifact
    - SHOPIFY_FULFILLMENT_PLAN -> write per-line-item fulfillment plan drafts
    - CREATE_DISPATCH_DRAFTS -> write per-line-item dispatch request drafts
    - EXECUTE_DISPATCH_MOCK -> call mock partner API and write partner job result artifacts
    - REQUEST_MORE_INFO / ESCALATE_HUMAN -> noop (but may emit admin update draft)
    """
    action_id = str(uuid.uuid4())

    # Always emit Shopify admin update draft when policy exists for this route
    admin_update_artifact = _write_shopify_admin_update_draft(event, decision)

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

    if decision.route == "SHOPIFY_FULFILLMENT_PLAN":
        artifact_paths = _write_fulfillment_plan_drafts(event, decision)
        extra = f" | admin_update={admin_update_artifact}" if admin_update_artifact else ""
        return ActionResult(
            action_id=action_id,
            event_id=event.event_id,
            decision_id=decision.decision_id,
            action_type="create_fulfillment_plan_drafts",
            status="executed",
            artifact_path=";".join(artifact_paths) if artifact_paths else None,
            reason=f"Wrote {len(artifact_paths)} fulfillment plan draft artifact(s){extra}",
        )

    if decision.route == "CREATE_DISPATCH_DRAFTS":
        artifact_paths = _write_dispatch_request_drafts(event, decision)
        extra = f" | admin_update={admin_update_artifact}" if admin_update_artifact else ""
        return ActionResult(
            action_id=action_id,
            event_id=event.event_id,
            decision_id=decision.decision_id,
            action_type="create_dispatch_drafts",
            status="executed",
            artifact_path=";".join(artifact_paths) if artifact_paths else None,
            reason=f"Wrote {len(artifact_paths)} dispatch request draft artifact(s){extra}",
        )

    if decision.route == "EXECUTE_DISPATCH_MOCK":
        artifact_paths = _execute_dispatch_to_mock_partner(event, decision)
        extra = f" | admin_update={admin_update_artifact}" if admin_update_artifact else ""
        return ActionResult(
            action_id=action_id,
            event_id=event.event_id,
            decision_id=decision.decision_id,
            action_type="execute_dispatch_mock",
            status="executed",
            artifact_path=";".join(artifact_paths) if artifact_paths else None,
            reason=f"Dispatched {len(artifact_paths)} line item(s) to mock partner service{extra}",
        )

    return ActionResult(
        action_id=action_id,
        event_id=event.event_id,
        decision_id=decision.decision_id,
        action_type="noop",
        status="noop",
        artifact_path=admin_update_artifact or None,
        reason=f"No action executed for route: {decision.route}",
    )
