import json
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
from callback_logging import log_query_to_model, log_model_response
from common.config import MODEL, CLEAN_CFG
from common.rbac import identity_policy, redact_row

def route_low_conf(tool_context: ToolContext) -> dict:
    """
    Route low-confidence (<0.75) items to governance queue and append to Sheets via MCP.
    """
    cl = tool_context.state.get("classifications", [])
    if not cl:
        return {"status":"no_data","low_conf":0}

    low = []
    for r in cl:
        if float(r.get("confidence",1.0)) < 0.75:
            low.append({
                "worker_id": r.get("worker_id",""),
                "date": r.get("date",""),
                "technology": r.get("technology",""),
                "work_type": r.get("work_type",""),
                "confidence": float(r.get("confidence",0)),
                "duration_seconds": int(r.get("duration_seconds",0)),
                "reason": "confidence<0.75"
            })

    tool_context.state["low_conf_queue"] = low

    # Ask model to call MCP tool to append governance rows
    # (instruction prompts will guide the model to invoke `prism_append_governance`)
    return {"status":"governed","low_conf": len(low)}

governance_agent = Agent(
    name="governance_agent",
    model=MODEL,
    description="Ensures audit posture and routes low-confidence items to a HITL queue (Sheets).",
    instruction="""
You are Governance. Your job is confidence assurance + audit trace.

Steps:
1) From `state["classified"]`, select items with confidence < 0.75.
2) Store them in `state["low_conf_queue"]` (list of dicts).
3) Then CALL the MCP tool: `prism_append_governance(items=state["low_conf_queue"])`.
4) Never output worker identifiers in natural-language replies; only counts.
5) Idempotent: safe to re-run; rely on append logging in Sheets.
6) Response schema: {"status":"governed","low_conf":N}.
    """,
    before_model_callback=log_query_to_model,
    after_model_callback=log_model_response,
    tools=[route_low_conf],
    generate_content_config=CLEAN_CFG,
)
