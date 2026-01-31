from typing import Any, Dict

from app.domain.schemas import (
    OrderFulfillmentEvent,
    OrderLineItem,
    PersonalizationInput,
    RulesSnapshot,
)


def _extract_personalization_from_properties(properties: Any) -> PersonalizationInput:
    """
    Shopify line item 'properties' can be:
    - list of {name: ..., value: ...}
    - dict-like
    - missing/None

    We extract known keys into a typed structure.
    """
    if not properties:
        return PersonalizationInput()

    # Normalize to a dict of {name: value}
    props: Dict[str, Any] = {}

    if isinstance(properties, list):
        for item in properties:
            if isinstance(item, dict) and "name" in item:
                props[str(item.get("name"))] = item.get("value")
    elif isinstance(properties, dict):
        props = {str(k): v for k, v in properties.items()}

    # Map to typed fields (expand safely later)
    pet_name = props.get("pet_name") or props.get("Pet Name") or props.get("petName")
    style = props.get("style") or props.get("Style")
    photo_url = props.get("photo_url") or props.get("photo") or props.get("Photo URL")

    return PersonalizationInput(
        pet_name=str(pet_name) if pet_name is not None else None,
        style=str(style) if style is not None else None,
        photo_url=str(photo_url) if photo_url is not None else None,
    )


def normalize_shopify_order(
    payload: Dict[str, Any],
    *,
    shop_domain: str,
    topic: str,
    order_id: str,
) -> OrderFulfillmentEvent:
    """
    Deterministically normalize a Shopify webhook payload into a canonical OrderFulfillmentEvent.

    NOTE: This does not call external services (Tier-1).
    Metafields/metaobjects integration will come later.
    """
    raw_items = payload.get("line_items") or []
    line_items = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        quantity = item.get("quantity", 1)
        try:
            quantity = int(quantity)
        except Exception:
            quantity = 1

        line_items.append(
            OrderLineItem(
                sku=item.get("sku"),
                variant_id=str(item.get("variant_id")) if item.get("variant_id") is not None else None,
                quantity=quantity,
                personalization=_extract_personalization_from_properties(item.get("properties")),
            )
        )

    return OrderFulfillmentEvent(
        order_id=str(order_id),
        shop_domain=shop_domain,
        topic=topic,
        line_items=line_items,
        rules_snapshot=RulesSnapshot(snapshot_version="v0", data={}),
    )
