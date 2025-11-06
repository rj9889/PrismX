import os, json
from google.adk.tools.tool_context import ToolContext
from common.config import DATA_DIR

def load_json_data_tool(tool_context: ToolContext, data_dir: str = DATA_DIR) -> dict:
    """ADK tool wrapper to refresh state from local JSON (fallback only)."""
    return load_state_from_json(tool_context, data_dir=data_dir)

def _safe_load_json(path: str):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []

def load_state_from_json(ctx: ToolContext, data_dir: str = DATA_DIR) -> dict:
    employees = _safe_load_json(os.path.join(data_dir, "employees.json"))
    cmdb = _safe_load_json(os.path.join(data_dir, "cmdb.json"))
    logs = _safe_load_json(os.path.join(data_dir, "activity_logs.json"))
    weights = _safe_load_json(os.path.join(data_dir, "taxonomy_weights.json"))
    ctx.state["employees"] = employees or []
    ctx.state["cmdb"] = cmdb or []
    ctx.state["activity_logs"] = logs or []
    ctx.state["weights"] = weights or {}
    return {
        "status":"loaded",
        "employees": len(ctx.state["employees"]),
        "apps": len(ctx.state["cmdb"]),
        "logs": len(ctx.state["activity_logs"]),
        "dir": data_dir
    }
