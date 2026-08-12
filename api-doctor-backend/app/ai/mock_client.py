"""A simple local AI client used as a fallback for development/testing.

Returns deterministic, minimal responses suitable for pipeline execution
without external API access.
"""
from __future__ import annotations

from typing import Any
import asyncio
import json
import logging

logger = logging.getLogger("app.ai.mock_client")

from app.ai.base import AIClient


class MockAIClient(AIClient):
    name = "mock"

    async def chat(self, *, model: str, messages: list[dict[str, str]], temperature: float = 0.1, max_tokens: int = 2048, response_format: dict | None = None, stream: bool = False) -> dict[str, Any]:
        # If the prompt includes a JSON schema instruction, synthesize a
        # minimal valid response matching the required fields. Otherwise
        # return a generic mocked JSON.
        joined = "\n".join(m.get("content", "") for m in messages)
        logger.info("MockAIClient received messages preview: %s", joined[:500])

        schema = None
        marker = "Return ONLY valid JSON matching this schema:"
        idx = joined.find(marker)
        if idx != -1:
            # Extract the first JSON object after the marker by balancing braces.
            start = joined.find("{", idx)
            if start != -1:
                depth = 0
                end = -1
                for i in range(start, len(joined)):
                    if joined[i] == "{":
                        depth += 1
                    elif joined[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end != -1:
                    try:
                        schema = json.loads(joined[start:end])
                    except Exception:
                        schema = None

        # If we didn't find the explicit marker, attempt to extract any
        # JSON object in the prompt as a fallback (useful when formatting
        # differs slightly).
        if schema is None:
            start = joined.find("{")
            if start != -1:
                depth = 0
                end = -1
                for i in range(start, len(joined)):
                    if joined[i] == "{":
                        depth += 1
                    elif joined[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end != -1:
                    try:
                        schema = json.loads(joined[start:end])
                    except Exception:
                        schema = None

        # Build a minimal response object when schema is available
        if schema and isinstance(schema, dict):
            logger.info("MockAIClient detected schema with properties: %s required: %s", list(schema.get("properties", {}).keys())[:10], schema.get("required", [])[:10])
            props = schema.get("properties", {})
            required = schema.get("required", [])
            out: dict[str, Any] = {}
            for name, spec in props.items():
                ftype = spec.get("type", "string")
                # Normalise simple types
                # Prefer realistic non-zero/default values for common fields
                if name.lower() == "confidence":
                    val = 0.95
                elif name.lower() == "root_cause":
                    val = "Null pointer dereference: payment_method is None"
                elif name.lower() == "category":
                    val = "bug"
                elif name.lower() == "affected_files":
                    val = ["app/demo_api/bugs.py"]
                elif name.lower() == "affected_functions":
                    val = ["charge_user"]
                elif name.lower() == "safe_to_repair":
                    val = True
                elif name.lower() == "risk":
                    val = "low"
                elif name.lower() == "diff":
                    val = """--- a/app/demo_api/bugs.py
+++ b/app/demo_api/bugs.py
@@ -121,1 +121,5 @@
 def charge_user(user_id: str, amount: float) -> str:
     user = get_user(user_id)
     if user is None:
         raise LookupError(f"user {user_id!r} not found")
-    token = user.payment_method.token  # BUG: no null check on payment_method
+    if user.payment_method is None:
+        # Gracefully handle missing payment method instead of crashing.
+        token = "no_payment"
+    else:
+        token = user.payment_method.token  # BUG: no null check on payment_method
     return f"txn_{token}_{amount:.2f}"
"""
                elif "number" in ftype or "integer" in ftype:
                    val = 1 if "integer" in ftype else 0.9
                elif "boolean" in ftype:
                    val = False
                elif "array" in ftype:
                    val = ["mock"]
                else:
                    val = "mock"
                out[name] = val
            # Ensure required fields exist with reasonable defaults
            for r in required:
                if r not in out:
                    # fill with reasonable defaults for known keys
                    if r.lower() == "confidence":
                        out[r] = 0.95
                    elif r.lower() == "root_cause":
                        out[r] = "Null pointer dereference: payment_method is None"
                    elif r.lower() == "category":
                        out[r] = "bug"
                    elif r.lower() == "affected_files":
                        out[r] = ["app/demo_api/bugs.py"]
                    elif r.lower() == "affected_functions":
                        out[r] = ["charge_user"]
                    elif r.lower() == "safe_to_repair":
                        out[r] = True
                    elif r.lower() == "risk":
                        out[r] = "low"
                    elif r.lower() == "diff":
                        out[r] = """--- a/app/demo_api/bugs.py
+++ b/app/demo_api/bugs.py
@@ -121,1 +121,5 @@
 def charge_user(user_id: str, amount: float) -> str:
     user = get_user(user_id)
     if user is None:
         raise LookupError(f"user {user_id!r} not found")
-    token = user.payment_method.token  # BUG: no null check on payment_method
+    if user.payment_method is None:
+        # Gracefully handle missing payment method instead of crashing.
+        token = "no_payment"
+    else:
+        token = user.payment_method.token  # BUG: no null check on payment_method
     return f"txn_{token}_{amount:.2f}"
"""
                    else:
                        out[r] = "mock"
            content = json.dumps(out)
        else:
            # Provide a default RootCauseAnalysis-like object so downstream
            # validators have a high-confidence response in sandbox mode.
            content = json.dumps({
                "root_cause": "Null pointer dereference: payment_method is None",
                "category": "bug",
                "confidence": 0.95,
                "affected_files": ["app/demo_api/bugs.py"],
                "affected_functions": ["charge_user"],
                "safe_to_repair": True,
                "reason": "payment_method may be None when charging user",
            })

        await asyncio.sleep(0)  # keep it async
        return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}, "model": model}

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        # Return zero-vector embeddings of length 8 for simplicity.
        return [[0.0] * 8 for _ in texts]

    async def check_health(self) -> bool:
        return True
