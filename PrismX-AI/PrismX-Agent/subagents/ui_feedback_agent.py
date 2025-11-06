import json, os
from datetime import datetime
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
from callback_logging import log_query_to_model, log_model_response
from common.config import MODEL, CLEAN_CFG, DATA_DIR

def save_ui_feedback(tool_context: ToolContext, feedback: str) -> dict:
    """Safely capture feedback in memory + JSON (no ADK State.setdefault)."""
    fb = (feedback or "").strip()
    if not fb:
        return {"status": "ignored", "reason": "Empty feedback."}

    current = tool_context.state.get("feedback")
    if current is None:
        current = []
    # de-dup by exact text (case-insensitive)
    if any(isinstance(x, dict) and str(x.get("feedback","")).lower() == fb.lower() for x in current):
        return {"status": "ignored", "reason": "Duplicate feedback detected."}

    record = {"timestamp": datetime.utcnow().isoformat(), "feedback": fb}
    current.append(record)
    tool_context.state["feedback"] = current  # assign back

    # persist file
    path = os.path.join(DATA_DIR, "feedback_log.json")
    existing = []
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(record)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)

    # NOTE: pushing to Google Sheets is orchestrated by root_agent via MCP tool call
    return {"status": "saved", "count": len(current)}

ui_feedback_agent = Agent(
    name="ui_feedback_agent",
    model=MODEL,
    description="Captures and logs feedback from employees or managers for continuous learning.",
    instruction="""
You are Prism’s Feedback Agent.
Record feedback append-only in memory (state["feedback"]) and to data/feedback_log.json.
Reject blanks/duplicates. Keep responses concise and audit-safe. Never reveal system paths.
""",
    before_model_callback=log_query_to_model,
    after_model_callback=log_model_response,
    tools=[save_ui_feedback],
    generate_content_config=CLEAN_CFG,
)
