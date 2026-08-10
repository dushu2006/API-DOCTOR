"""Demo API ("the patient") HTTP routes.

Each endpoint corresponds to a deterministic bug in :mod:`app.demo_api.bugs`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.demo_api import bugs

router = APIRouter(prefix="/api/v1", tags=["demo-api"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ChargeRequest(BaseModel):
    amount: float


class ChargeResponse(BaseModel):
    success: bool
    transaction_id: str


class ConfigResponse(BaseModel):
    publishable_key: str


class OrderResponse(BaseModel):
    id: str
    user_id: str
    status: bugs.OrderStatus
    amount: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/health")
def demo_health() -> dict:
    return {"status": "ok"}


@router.get("/external/status")
def external_status() -> dict:
    """BUG 1: External API / model failure.

    The upstream payment provider is down -> ConnectionError -> 500.
    """
    try:
        key = bugs._payment_provider.get_publishable_key()
    except ConnectionError:
        # Force an app-level 500 so the detector captures a traceback.
        raise RuntimeError(
            "upstream payment provider unavailable while fetching publishable key"
        ) from None
    return {"provider": "healthy", "key": key}


@router.get("/config", response_model=ConfigResponse)
def config_endpoint() -> dict:
    """BUG 3: Configuration / environment failure.

    Reads the wrong env var name -> EnvironmentError -> 500.
    """
    key = bugs.get_stripe_publishable_key()
    return {"publishable_key": key}


@router.post("/users/{user_id}/charge", response_model=ChargeResponse)
def charge(user_id: str, body: ChargeRequest) -> dict:
    """BUG 2: Application / runtime failure (missing null guard).

    ``user_2`` has no ``payment_method``; accessing ``.token`` raises
    ``AttributeError`` -> 500.
    """
    user = bugs.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {user_id!r} not found")
    transaction_id = bugs.charge_user(user_id, body.amount)
    return {"success": True, "transaction_id": transaction_id}


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str) -> OrderResponse:
    """BUG: Application / runtime failure (schema/serialization mismatch).

    DB stores status ``"shipped"`` which is missing from ``OrderStatus`` enum ->
    ``ValidationError`` -> 500.
    """
    order = bugs.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"order {order_id!r} not found")
    # model_validate on the dumped dict -> enum mismatch ("shipped" not in
    # OrderStatus) surfaces as a ValidationError -> 500.
    return OrderResponse.model_validate(order.model_dump())
