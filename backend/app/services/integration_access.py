"""Who may use an Integration's credentials: its owner, or anyone when an admin shared it."""
from typing import Any


def integration_usable_by(integration: Any, user_id: Any) -> bool:
    """One rule for Agent DOC tools and workflow nodes (validation and run time)."""
    owner = getattr(integration, "user_id", None)
    if owner is not None and str(owner) == str(user_id):
        return True
    # Anyone else only when an admin explicitly shared it (an ownerless row is not "shared").
    return bool(getattr(integration, "is_shared", False))
