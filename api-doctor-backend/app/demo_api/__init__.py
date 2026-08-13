"""TEST-ONLY sample buggy API.

This package is NOT mounted by the running application and is never reachable
from production. It exists purely as a deterministic sample workspace that the
sandbox and end-to-end tests use to verify reproduce -> patch -> verify without
a real external project. The production app diagnoses the user's own connected
repository instead.
"""
