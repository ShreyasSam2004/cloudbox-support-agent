from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Opaque, unguessable identifier such as ``exec_3f9c2a...``."""
    return f"{prefix}_{uuid.uuid4().hex[:24]}"
