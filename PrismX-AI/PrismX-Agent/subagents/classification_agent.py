import json, os
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
from callback_logging import log_query_to_model, log_model_response
from common.config import MODEL, CLEAN_CFG, DATA_DIR, MCP_SHEETS

def classify_from_state(tool_context: ToolContext) -> dict:
    """
    Classify activity logs into work_type × technology.
    This ALWAYS forces the root agent to load if missing.
    """
    # HARD AUTO LOAD GATE
    if not tool_context.state.get("activity_logs"):
        # tell root agent: stop + load + re-call me again
        return {"status":"needs_load"}

    logs = tool_context.state.get("activity_logs", [])
    if not logs:
        return {"status": "no_logs", "rows": 0}

    known_tech = {
        "VSCode","GitHub","SSMS","Jira","ServiceNow","Confluence",
        "Outlook","Teams","Zoom","Splunk","Azure Portal","Power BI","Databricks"
    }

    def tech(name: str) -> str:
        return name if name in known_tech else "General"

    def work(cat: str, observed: str) -> str:
        cat = str(cat)
        observed = str(observed)
        if any(k in cat for k in ("IDE","Source Control","Cloud Platform","Data Platform","Analytics/BI","Database")):
            if observed in {"Development","Testing","Integration","Data Engineering","Analysis","Operations","Reporting"}:
                return observed
        if "Monitoring" in cat: return "Oncall/Monitoring"
        if "Ticketing" in cat: return "Ticket Handling"
        if "Email" in cat or "Collaboration" in cat:
            return "Meeting" if observed == "Meeting" else (observed or "Documentation")
        return observed or "Admin"

    classified = []
    for r in logs:
        classified.append({
            "worker_id": r.get("worker_id"),
            "work_type": work(r.get("app_category",""), r.get("activity_observed","")),
            "technology": tech(r.get("app_name","")),
            "confidence": float(r.get("signal_confidence", 0.8)),
            "duration_seconds": int(r.get("duration_seconds", 1800)),
            "date": str(r.get("date",""))
        })

    tool_context.state["classified"] = classified

    return {"status": "classified", "rows": len(classified)}


classification_agent = Agent(
    name="classification_agent",
    model=MODEL,
    description="Classifies logs into work_type × technology; stores JSON in shared state.",
    instruction="""
You are the Classification module for Project Prism.

Objective:
- Convert normalized activity logs into structured classifications (work_type × technology) with a confidence score.

Operational Rules (follow strictly):
1) If source tables are not in memory, call the MCP tools to fetch them
2) If source tables missing, call MCP tool `prism_read_all_sources` and place results into:
   • state["employees"], state["cmdb"], state["activity_logs"], state["weights_raw"] (taxonomy list)
   Then reshape `weights_raw` into dict-of-dicts in state["weights"] if needed.
3) Work with JSON lists only (no DataFrames, no CSV).
4) Map app_name/app_category/activity_observed to a final `work_type` using deterministic rules:
   • IDE/Source Control/Cloud/Data/Analytics/Database → {Development, Testing, Integration, Data Engineering, Analysis, Operations, Reporting} if observed matches
   • Monitoring → Oncall/Monitoring
   • Ticketing → Ticket Handling
   • Email/Collaboration → Meeting (if observed == "Meeting") else Documentation
   • Else → Admin
5) Map app_name to technology using known tech set; unknowns → "General".
6) Confidence is a float in [0,1]. Default 0.80 when signal_confidence missing.
7) Save results in `state["classified"]` (list[dict]) and also write audit JSON to data/classifications.json.
8) Keep deterministic output across runs for the same inputs.
9) Never mention tool or agent names to the user.
10) Return a compact status like: {"status":"classified","rows":N}.
    """,
    before_model_callback=log_query_to_model,
    after_model_callback=log_model_response,
    tools=[classify_from_state, MCP_SHEETS],
    generate_content_config=CLEAN_CFG,
)
