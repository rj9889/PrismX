# google_maps_mcp_agent/agent.py
import sys, os
sys.path.append(os.path.dirname(__file__))

# from common.rbac import (
#     normalize_role_phrase, set_role, get_role, identity_policy, redact_row,
#     ROLE_ANALYST, ROLE_ASSOC_DIR, ROLE_GOVERNOR
# )

from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters, StdioConnectionParams

from common.config import MODEL, CLEAN_CFG, DATA_DIR, MCP_SHEETS
from common.data_loader import load_json_data_tool

from subagents.classification_agent import classification_agent
from subagents.ui_feedback_agent import ui_feedback_agent
from subagents.learning_agent import learning_agent
from subagents.governance_agent import governance_agent
from subagents.executive_summary_agent import executive_summary_agent
from subagents.query_agent import query_agent

# ---------- Data ensure tool ----------

def ensure_data(tool_context: ToolContext) -> dict:
    need_keys = ("employees","cmdb","activity_logs","weights")
    missing = []
    for k in need_keys:
        if k not in tool_context.state:
            missing.append(k)
        else:
            v = tool_context.state.get(k)
            if isinstance(v, list) and len(v) == 0:
                missing.append(k)

    if missing:
        return {"status":"needs_load","missing":missing}
    return {"status":"already_loaded"}


# def set_user_role(tool_context: ToolContext, role: str) -> dict:
#     role = (role or "").strip().lower()
#     if role not in (ROLE_ANALYST, ROLE_ASSOC_DIR, ROLE_GOVERNOR):
#         return {"status": "error", "error": f"unknown role '{role}'"}
#     set_role(tool_context.state, role)
#     return {"status": "ok", "role": role}

# def clear_user_role(tool_context: ToolContext) -> dict:
#     set_role(tool_context.state, ROLE_ANALYST)
#     return {"status": "ok", "role": ROLE_ANALYST}


def stage_sources(tool_context: ToolContext, sources: dict) -> dict:
    """
    Persist sources returned from MCP `prism_read_all_sources` into state.
    Accepts either:
      {"sources": {...}}  OR the inner {...} directly.
    """
    payload = sources.get("sources", sources) or {}
    employees = payload.get("employees", [])
    cmdb = payload.get("cmdb", [])
    activity_logs = payload.get("activity_logs", [])
    taxonomy_rows = payload.get("taxonomy_weights", [])

    # Build weights dict-of-dicts: weights[category][label] = float(weight)
    weights = {}
    for row in taxonomy_rows:
        cat = str(row.get("category", "")).strip()
        lab = str(row.get("label", "")).strip()
        try:
            w = float(row.get("weight", 0))
        except Exception:
            w = 0.0
        if cat and lab:
            weights.setdefault(cat, {})[lab] = w

    tool_context.state["employees"] = employees
    tool_context.state["cmdb"] = cmdb
    tool_context.state["activity_logs"] = activity_logs
    tool_context.state["weights"] = weights
    tool_context.state["taxonomy_weights"] = taxonomy_rows


    return {
        "status": "staged",
        "counts": {
            "employees": len(employees),
            "cmdb": len(cmdb),
            "activity_logs": len(activity_logs),
            "taxonomy_weights": sum(len(v) for v in weights.values()),
        },
    }

# def rbac_bind_helpers(tool_context: ToolContext) -> dict:
#     # store identifiers not actual functions
#     tool_context.state["_rbac_identity_policy"] = "identity_policy_enabled"
#     tool_context.state["_rbac_redact_row"] = True    # feature flag style
#     return {"status": "ok"}

# ---------- Root Agent ----------
root_agent = Agent(
    name="project_prism_assistant",
    model=MODEL,
    description="Unified orchestrator for Prism — coordinates sub-agents + MCP Sheets.",
    instruction=f"""
You are Project Prism — an executive-friendly assistant that coordinates
Google Sheets data via MCP and specialized sub-agents.

Data Loading Protocol (always run silently before any task if needed):
1) Call MCP tool `prism_read_all_sources` (no args)
2) Call local tool `stage_sources` with the full result

Task Routing:
- If user asks to classify or run a cycle: run ensure_data → classification → governance → learning → executive summary.
- For analytics/Q&A: if data missing, first run the Data Loading Protocol silently.
- For feedback: persist via UI Feedback agent; also call MCP `prism_append_feedback` when appropriate.
- For governance queue writes: also call MCP `prism_append_governance`.
- After learning updates: call MCP `prism_upsert_taxonomy` with upserts.


-----------------------------------------
VECTOR SEARCH CONTROL (Root Managed)
-----------------------------------------

User Commands:
- If user says "enable vector search" or "enable prism vector" or "use prism knowledge" or "enable system knowledge":
      → set state["vector_enabled"] = True
      → reply: "Vector search enabled."

- If user says "disable vector search" or "turn off vector" or "no vector":
      → set state["vector_enabled"] = False
      → reply: "Vector search disabled."

-----------------------------------------
VECTOR ROUTING RULE
-----------------------------------------

- If state.get("vector_enabled") == True:
      If user asks factual question / analytics / search / meaning / understanding type query:
            → delegate FIRST to query_agent

      If query_agent returns no result (weak match <0.32):
            → orchestrator continues normally (sheet reasoning / classification / fallback)

- If vector search disabled or not enabled yet:
      → skip vector route completely and run normal orchestrator behavior


Whenever user asks summary / insights / analytics:
Before calling executive_summary_agent:
ALWAYS do:
1) ensure_data
2) if needs_load → run data loading protocol steps silently
3) ALWAYS run classification_agent first to populate state["classified"]
Only after classification succeeded → run executive_summary_agent.

Global General Behavior Rule:
- If the user asks something that is NOT related to Prism (example: weather, general python help, interview questions, personal finance, tech general concepts, general knowledge, random questions etc) the agent MUST STILL ANSWER normally with a general helpful response.
- Do NOT refuse such questions.
- Do NOT say “I am limited” or “I cannot answer outside Prism”.
- Only refuse if illegal, harmful or unsafe. Otherwise ALWAYS attempt a helpful general answer.
""",

    sub_agents=[
        classification_agent,
        ui_feedback_agent,
        learning_agent,
        governance_agent,
        executive_summary_agent,
        query_agent
    ],
    tools=[ensure_data, stage_sources, load_json_data_tool, MCP_SHEETS],
    generate_content_config=CLEAN_CFG,
)

