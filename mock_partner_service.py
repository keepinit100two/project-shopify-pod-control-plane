import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Mock POD Partner Service")

# In-memory idempotency store: idem_key -> job record
_JOBS_BY_IDEM: Dict[str, Dict[str, Any]] = {}


class PartnerJobRequest(BaseModel):
    order_id: str = Field(..., description="Merchant order id")
    shop_domain: str = Field(..., description="Shop domain")
    line_item_index: int = Field(..., ge=0)
    payload: Dict[str, Any] = Field(..., description="Partner-specific payload")


class PartnerJobResponse(BaseModel):
    partner: str
    job_id: str
    status: str
    created_at: str
    idempotency_key: str
    echo: Dict[str, Any]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/partner/{partner}/jobs", response_model=PartnerJobResponse)
def create_job(
    partner: str,
    req: PartnerJobRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    Create a partner job with idempotency.
    - If Idempotency-Key is missing -> 400
    - If Idempotency-Key already exists -> return the same job (dedupe)
    """
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")

    if idempotency_key in _JOBS_BY_IDEM:
        record = _JOBS_BY_IDEM[idempotency_key]
        return PartnerJobResponse(**record)

    record = {
        "partner": partner,
        "job_id": f"job_{uuid.uuid4().hex[:12]}",
        "status": "created",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "idempotency_key": idempotency_key,
        "echo": {
            "order_id": req.order_id,
            "shop_domain": req.shop_domain,
            "line_item_index": req.line_item_index,
            "payload": req.payload,
        },
    }
    _JOBS_BY_IDEM[idempotency_key] = record
    return PartnerJobResponse(**record)
