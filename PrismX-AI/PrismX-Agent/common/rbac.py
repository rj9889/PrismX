# google_maps_mcp_agent/common/rbac.py
from typing import Dict, Any, Tuple

ROLE_ANALYST = "analyst"           # default
ROLE_ASSOC_DIR = "associate_director"
ROLE_GOVERNOR = "governor"

def normalize_role_phrase(text: str) -> str | None:
    t = (text or "").strip().lower()
    if "i am governor" in t or "i'm governor" in t or "i am the governor" in t:
        return ROLE_GOVERNOR
    if "i am associate director" in t or "i'm associate director" in t:
        return ROLE_ASSOC_DIR
    if "i am analyst" in t or "i'm analyst" in t:
        return ROLE_ANALYST
    return None

def set_role(state: Dict[str, Any], role: str) -> None:
    state["user_role"] = role

def get_role(state: Dict[str, Any]) -> str:
    return state.get("user_role", ROLE_ANALYST)

def identity_policy(state: Dict[str, Any]) -> Tuple[bool, bool]:
    """
    Returns (allow_name, allow_worker_id)
    """
    role = get_role(state)
    if role == ROLE_GOVERNOR:
        return (True, True)
    if role == ROLE_ASSOC_DIR:
        return (True, False)
    return (False, False)  # analyst / default

def redact_row(row: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """Non-destructive redaction copy based on role."""
    allow_name, allow_worker_id = identity_policy(state)
    out = dict(row)
    if not allow_name and "name" in out:
        out["name"] = "ANON"
    if not allow_worker_id and "worker_id" in out:
        out["worker_id"] = "ANON"
    return out
