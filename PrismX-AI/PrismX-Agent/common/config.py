import os
from dotenv import load_dotenv
from google.genai import types

load_dotenv()

MODEL = os.getenv("MODEL")
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # AURION/common -> AURION
DATA_DIR = os.path.join(BASE_DIR, "data")  # optional JSON fallback folder

# Deterministic, clean outputs
CLEAN_CFG = types.GenerateContentConfig(temperature=0)


from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioServerParameters, StdioConnectionParams

import sys, os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # go up from subagents
MCP_PY_PATH = os.path.join(BASE_DIR, "common", "mcp", "mcp_sheets_server.py")

MCP_SHEETS = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="python3",
            args=[MCP_PY_PATH],
            env={
                "GOOGLE_APPLICATION_CREDENTIALS": "/home/student_02_9ba65c2ab9da/PrismX-AI/PrismX-Agent/common/mcp/service_account.json",
                "SHEET_ID": "",
                # Optional: put API key if you have it; otherwise local fallback embedding will be used
                # "GENAI_API_KEY": "YOUR_API_KEY",
            },
        ),
        timeout=300000,
    )
)
