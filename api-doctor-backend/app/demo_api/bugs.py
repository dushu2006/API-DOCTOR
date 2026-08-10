"""The "patient" — a seeded, deterministic API with toggleable failures.

Each bug is:
    * deterministic (always fires for the given inputs),
    * easy to trigger (a single endpoint + parameter),
    * realistic (real Python exceptions -> real tracebacks).

Three categories from the spec are covered:
    1. EXTERNAL_API_FAILURE   -> /external/status  (mock upstream API times out)
    2. CONFIGURATION_ERROR    -> /config  (reads a missing env var)
    3. APPLICATION_RUNTIME    -> /users/{id}/charge (None attribute access)
       and /orders/{id} (schema/serialization mismatch)
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Mock persistence layer
# ---------------------------------------------------------------------------
class User(BaseModel):
    id: str
    name: str
    payment_method: Optional["PaymentMethod"] = None  # BUG 2: can be None


class PaymentMethod(BaseModel):
    token: str
    brand: str


class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    DELIVERED = "delivered"
    # NOTE: "shipped" intentionally missing from the Enum but present in the DB.


class Order(BaseModel):
    id: str
    user_id: str
    status: str  # kept as str to model a DB/Enum mismatch
    amount: float


USERS_DB = {
    "user_1": User(
        id="user_1",
        name="Alice",
        payment_method=PaymentMethod(token="pm_card_visa", brand="Visa"),
    ),
    "user_2": User(id="user_2", name="Bob", payment_method=None),  # triggers BUG 2
}

ORDERS_DB = {
    "order_1": Order(id="order_1", user_id="user_1", status="paid", amount=100.0),
    "order_2": Order(id="order_2", user_id="user_1", status="shipped", amount=50.0),
}


def get_user(user_id: str) -> Optional[User]:
    return USERS_DB.get(user_id)


def get_order(order_id: str) -> Optional[Order]:
    return ORDERS_DB.get(order_id)


# ---------------------------------------------------------------------------
# External dependency (mock Stripe-like provider) — BUG 1
# ---------------------------------------------------------------------------
class ExternalPaymentProvider:
    """Simulates an upstream payment API that may be down."""

    def __init__(self, base_url: str, healthy: bool = True) -> None:
        self.base_url = base_url
        self.healthy = healthy

    def get_publishable_key(self) -> str:
        if not self.healthy:
            raise ConnectionError(
                f"Failed to connect to upstream payment provider at {self.base_url}: "
                "connection refused (provider is down or the network is unavailable)"
            )
        return os.getenv("PAYMENT_PUBLISHABLE_KEY", "")


_payment_provider = ExternalPaymentProvider(
    base_url="https://payments.example.internal", healthy=False  # BUG 1: provider down
)


# ---------------------------------------------------------------------------
# Config helper — BUG 3
# ---------------------------------------------------------------------------
def get_stripe_publishable_key() -> str:
    # BUG 3: reads the wrong env var name. The app configures
    # PAYMENT_PUBLISHABLE_KEY, but this reads STRIPE_PUBLISHABLE_KEY (unset).
    key = os.getenv("STRIPE_PUBLISHABLE_KEY")
    if not key:
        raise EnvironmentError(
            "STRIPE_PUBLISHABLE_KEY environment variable is not set. "
            "The application expects PAYMENT_PUBLISHABLE_KEY to be configured."
        )
    return f"{key[:4]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Charge logic — BUG 4 (null pointer / missing guard)
# ---------------------------------------------------------------------------
def charge_user(user_id: str, amount: float) -> str:
    user = get_user(user_id)
    if user is None:
        raise LookupError(f"user {user_id!r} not found")
    token = user.payment_method.token  # BUG: no null check on payment_method
    return f"txn_{token}_{amount:.2f}"
