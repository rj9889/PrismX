import json
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
from callback_logging import log_query_to_model, log_model_response
from common.config import MODEL, CLEAN_CFG

def update_weights_from_feedback(tool_context: ToolContext) -> dict:
    """
    Gently update taxonomy weights using recent feedback (in-memory),
    then ask model to upsert into Sheets with `prism_upsert_taxonomy`.
    """
    fb = tool_context.state.get("feedback", [])  # list of {"timestamp","feedback"}
    weights = tool_context.state.get("weights", {})  # {category:{label:weight}}
    if not fb:
        return {"status":"no_feedback","message":"No new feedback this cycle."}

    boost = sum(1 for x in fb if "integrat" in x.get("feedback","").lower()) * 0.02
    changed = []

    for cat, labels in weights.items():
        for label, val in labels.items():
            if str(label).lower().startswith("integrat"):
                new_val = min(0.99, round(float(val) + boost, 3))
                if new_val != val:
                    weights[cat][label] = new_val
                    changed.append({"category":cat, "label":label, "weight": new_val})

    tool_context.state["weights"] = weights
    tool_context.state["weights_upserts"] = changed  # used by MCP tool call

    return {
        "status":"weights_updated",
        "feedback_count": len(fb),
        "changed_count": len(changed)
    }

learning_agent = Agent(
    name="learning_agent",
    model=MODEL,
    description="Updates taxonomy weights gently from accumulated feedback and persists via MCP.",
    instruction="""
You are Learning. Purpose: convert feedback into steady taxonomy improvements.

Rules:
1) Read `state["feedback"]` (list of {"timestamp","feedback"}).
2) Compute tiny boosts based on patterns (e.g., words starting with "integrat").
3) Update `state["weights"]` in-memory (dict-of-dicts).
4) Prepare `state["weights_upserts"]` as a list of {category,label,weight}.
5) Then CALL MCP tool `prism_upsert_taxonomy(rows=state["weights_upserts"])`.
6) Respond compactly with counts: {"status":"weights_updated","feedback_count":X,"changed_count":Y}.
7) No raw dumps, no internals, no worker details.
    """,
    before_model_callback=log_query_to_model,
    after_model_callback=log_model_response,
    tools=[update_weights_from_feedback],
    generate_content_config=CLEAN_CFG,
)
