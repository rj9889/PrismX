import re
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
from callback_logging import log_query_to_model, log_model_response
from common.config import MODEL, CLEAN_CFG, MCP_SHEETS
from common.utils import percent, parse_days_window
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters, StdioConnectionParams

import sys, os


# query_agent = Agent(
#     name="query_agent",
#     model=MODEL,
#     description="Unified orchestrator for Prism — coordinates sub-agents + MCP Sheets.",
#     instruction="""
# Vector Enforcement Rule:
# Before doing any vector based answering:
#  -Then call MCP tool `prism_vector_autobuild` silently.

# Only after vector autobuild step completes → now perform vector query.

# Vector First Retrieval Rule:
# When user asks any question:
# 1) Call MCP tool `prism_vector_query` with {"text": user_message, "top_k": 3}
# 2) If the best score >= 0.32 → summarize answer ONLY from that vector match.
# 3) If the best score < 0.32 OR vector returned no relevant results → fallback to sheet data → classification / metrics / normal Prism reasoning.

# Never mention "vector" or "semantic match" in the final answer. Produce answer naturally.


# """,
#     tools=[MCP_SHEETS],
#     generate_content_config=CLEAN_CFG,
# )

query_agent = Agent(
    name="query_agent",
    model=MODEL,
    description="Primary Q&A agent for Prism — semantic search first, then structured reasoning fallback.",
    instruction="""
Behavior Priority:

1) VECTOR FIRST (Project Prism System Only)
   - Always silently call MCP tool `prism_vector_autobuild` first.
   - Then call MCP tool `prism_vector_query`:
        {"text": user_message, "top_k": 3}

   If best match score >= 0.32:
        - Answer ONLY based on the matched Prism system record(s)
        - Output must be short readable natural summary
        - DO NOT mention vector, sheets, embeddings, MCP, database etc.

2) If score < 0.32 OR vector result empty:
        - Do NOT answer anything here
        - Immediately return control to Root/Orchestrator agent
          (just yield, no self fallback reasoning)

3) Query agent is NOT allowed to generate generic domain knowledge.
   Only Prism internal records. Root decides fallback.

Output Rules:
- Plain natural English summary
- Human readable
- No debug / no internal execution details
""",
    tools=[MCP_SHEETS],
    generate_content_config=CLEAN_CFG,
)

