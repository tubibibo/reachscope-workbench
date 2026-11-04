"""Bounded, model-independent queries over a persisted analysis artifact.

``EvidenceSession`` is shared by the CLI and Python callers. It does not run a
model, execute an APK, or claim to prove exploitability.
"""

from .session import EvidenceSession, QueryError

__all__ = ["EvidenceSession", "QueryError"]
