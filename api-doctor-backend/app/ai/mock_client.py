"""TEST-ONLY deterministic mock AI client.

NOT reachable from the running application. The production provider factory
(:func:`app.ai.base.create_ai_client`) only ever builds the real NVIDIA NIM
client and this mock is never selected. It exists solely so the automated test
suite can exercise the diagnosis pipeline in CI without a real API key.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
from pathlib import Path
from typing import Any

from app.ai.base import AIClient

logger = logging.getLogger("app.ai.mock_client")

_ROUTER_REL = "app/demo_api/router.py"
_BUGS_REL = "app/demo_api/bugs.py"

_ROUTER_OLD = (
    "    transaction_id = bugs.charge_user(user_id, body.amount)\n"
    '    return {"success": True, "transaction_id": transaction_id}\n'
)
_ROUTER_NEW = (
    "    if user.payment_method is None:\n"
    '        raise HTTPException(status_code=400, detail="no payment method on file")\n'
    "    transaction_id = bugs.charge_user(user_id, body.amount)\n"
    '    return {"success": True, "transaction_id": transaction_id}\n'
)
_BUGS_OLD = "    token = user.payment_method.token  # BUG: no null check on payment_method\n"
_BUGS_NEW = (
    "    if user.payment_method is None:\n"
    '        token = "missing_payment_method"\n'
    "    else:\n"
    "        token = user.payment_method.token\n"
)

_STATIC_BUGS_DIFF = """--- a/app/demo_api/bugs.py
+++ b/app/demo_api/bugs.py
@@ -121,1 +121,4 @@
-    token = user.payment_method.token  # BUG: no null check on payment_method
+    if user.payment_method is None:
+        token = "missing_payment_method"
+    else:
+        token = user.payment_method.token
"""


def _unified(rel: str, original: str, fixed: str) -> str:
    return (
        "\n".join(
            difflib.unified_diff(
                original.splitlines(),
                fixed.splitlines(),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
            )
        )
        + "\n"
    )


def build_demo_null_pointer_diff(repo_root: str | Path | None = None) -> str:
    """Build a unified diff that applies cleanly to the current demo API."""
    if repo_root is None:
        from app.core.config import settings

        root = Path(settings.INTERNAL_REPO_ROOT)
    else:
        root = Path(repo_root)

    router = root / _ROUTER_REL
    if router.is_file():
        original = router.read_text(encoding="utf-8")
        if _ROUTER_OLD in original:
            return _unified(_ROUTER_REL, original, original.replace(_ROUTER_OLD, _ROUTER_NEW, 1))

    bugs = root / _BUGS_REL
    if bugs.is_file():
        original = bugs.read_text(encoding="utf-8")
        if _BUGS_OLD in original:
            return _unified(_BUGS_REL, original, original.replace(_BUGS_OLD, _BUGS_NEW, 1))

    return _STATIC_BUGS_DIFF


def _extract_first_json_object(text: str, start_at: int = 0) -> dict[str, Any] | None:
    start = text.find("{", start_at)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _schema_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    """Fill a JSON-schema-shaped response with deterministic values."""
    props = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    out: dict[str, Any] = {}

    known: dict[str, Any] = {
        "confidence": 0.95,
        "root_cause": "Null pointer dereference: payment_method is None",
        "classification": "CODE_BUG",
        "category": "CODE_BUG",
        "affected_files": [_BUGS_REL, _ROUTER_REL],
        "affected_lines": [121],
        "affected_functions": ["charge_user", "charge"],
        "evidence": ["AttributeError on line 121"],
        "recommended_action": "Check for null before dereferencing token",
        "safe_to_repair": True,
        "risk": "low",
        "summary": "Gracefully handle missing payment method",
        "files_changed": [_ROUTER_REL],
        "files": [
            {
                "path": _ROUTER_REL,
                "patch": build_demo_null_pointer_diff(),
                "reason": "Add check before charge",
            }
        ],
        "reason": "user.payment_method can be None; accessing .token crashes with AttributeError",
        "diff": build_demo_null_pointer_diff(),
    }

    for name, spec in props.items():
        key = name.lower()
        if key in known:
            out[name] = known[key]
            continue
        ftype = str(spec.get("type", "string"))
        if "number" in ftype or "integer" in ftype:
            out[name] = 1 if "integer" in ftype else 0.9
        elif "boolean" in ftype:
            out[name] = False
        elif "array" in ftype:
            out[name] = ["mock"]
        else:
            out[name] = "mock"

    for name in required:
        if name not in out:
            out[name] = known.get(name.lower(), "mock")
    return out


class MockAIClient(AIClient):
    name = "mock"

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        response_format: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        joined = "\n".join(m.get("content", "") for m in messages)
        logger.info("MockAIClient received messages preview: %s", joined[:500])

        schema = None
        marker = "Return ONLY valid JSON matching this schema:"
        idx = joined.find(marker)
        if idx != -1:
            schema = _extract_first_json_object(joined, idx)

        if schema is None:
            schema = _extract_first_json_object(joined)

        if schema and isinstance(schema, dict) and schema.get("properties"):
            content = json.dumps(_schema_defaults(schema))
        else:
            content = json.dumps(
                {
                    "root_cause": "Null pointer dereference: payment_method is None",
                    "classification": "CODE_BUG",
                    "category": "CODE_BUG",
                    "confidence": 0.95,
                    "affected_files": [_BUGS_REL, _ROUTER_REL],
                    "affected_lines": [121],
                    "affected_functions": ["charge_user", "charge"],
                    "evidence": ["AttributeError on line 121"],
                    "recommended_action": "Check for null before dereferencing token",
                    "safe_to_repair": True,
                    "reason": "payment_method may be None when charging user",
                    "summary": "Gracefully handle missing payment method",
                    "files_changed": [_ROUTER_REL],
                    "diff": build_demo_null_pointer_diff(),
                    "risk": "low",
                }
            )

        await asyncio.sleep(0)
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {},
            "model": model,
        }

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]

    async def check_health(self) -> bool:
        return True
