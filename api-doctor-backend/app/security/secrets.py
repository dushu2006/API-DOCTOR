from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretStoreError(Exception):
    pass


class SecretStore:
    def __init__(self, secret_key: str | None = None) -> None:
        seed = (secret_key or settings.SECRET_KEY or "api-doctor-dev-secret").encode("utf-8")
        derived = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
        self._fernet = Fernet(derived)

    def encrypt_dict(self, payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw).decode("utf-8")

    def decrypt_dict(self, token: str | None) -> dict[str, Any]:
        if not token:
            return {}
        try:
            raw = self._fernet.decrypt(token.encode("utf-8"))
        except InvalidToken as exc:
            raise SecretStoreError("Unable to decrypt stored credentials.") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SecretStoreError("Stored credentials are malformed.") from exc
        return data if isinstance(data, dict) else {}


secret_store = SecretStore()
