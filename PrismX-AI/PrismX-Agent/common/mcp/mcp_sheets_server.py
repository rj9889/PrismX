# common/mcp/mcp_sheets_server.py
# ------------------------------------------------------------
# Prism Sheets MCP Server (stdio) + Semantic Vector Tools
#
# Tools exposed (via MCP):
#   - prism_ensure_tabs()
#   - prism_read_table({sheet_name})
#   - prism_append_rows({sheet_name, rows})
#   - prism_upsert_taxonomy({rows})
#   - prism_append_feedback({timestamp, feedback})
#   - prism_append_governance({items})
#   - prism_read_all_sources()
#   - prism_vector_build({source_sheet, text_columns?})
#   - prism_vector_autobuild()
#   - prism_vector_query({text, top_k})
#
# Vector store: Google Sheet tab "prism_vectors"
#   headers = ["id","source_tab","row_index","text","embedding_json","model","updated_at"]
#
# Embeddings:
#   Primary: Google Generative AI "text-embedding-004" using API key (GENAI_API_KEY)
#   Fallback: deterministic 128-dim hashing embedding (keeps demos working if API not available)
# ------------------------------------------------------------

import os
import json
import math
import time
import asyncio
from typing import Any, Dict, List, Tuple

import gspread
from google.oauth2.service_account import Credentials

# MCP (Anthropic) SDK
import mcp.types as types
from mcp.server.stdio import stdio_server
from mcp.server import Server, NotificationOptions
from mcp.types import Tool

# ---------- Configuration ----------
SHEET_ID = ""
CREDS_PATH = "/home/student_02_9ba65c2ab9da/PrismX-AI/PrismX-Agent/common/mcp/service_account.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
# Canonical tabs + headers (headers are fixed; never overwrite if already correct)
TAB_HEADERS: Dict[str, List[str]] = {
    "employees": ["worker_id","worker_type","name","role","team","manager_role","location","country","employment_status","start_date"],
    "cmdb": ["app_id","app_name","app_category","owner_team","technology_family"],
    "activity_logs": ["date","worker_id","app_name","app_category","activity_observed","duration_seconds","signal_confidence"],
    "taxonomy_weights": ["category","label","weight"],
    "prism_feedback": ["timestamp","feedback"],
    "prism_governance": ["worker_id","date","technology","work_type","confidence","duration_seconds","reason"],
    "prism_vectors": ["id","source_tab","row_index","text","embedding_json","model","updated_at"],
}
CORE_SOURCE_TABS = ["employees","cmdb","activity_logs","taxonomy_weights"]
# ---------- gspread helpers ----------
def _client():
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)
def _sheet(gc):
    return gc.open_by_key(SHEET_ID)
def _ensure_tab(ws, headers: List[str]):
    """Ensure the header row is exactly what we expect (no destructive overwrite if correct)."""
    existing = ws.row_values(1)
    norm = lambda row: [str(h).strip().lower() for h in row]
    if norm(existing) != norm(headers):
        ws.clear()
        ws.append_row(headers)
def _get_or_create(ws_name: str, headers: List[str]):
    gc = _client()
    sh = _sheet(gc)
    try:
        ws = sh.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_name, rows=1000, cols=max(20, len(headers)))
    _ensure_tab(ws, headers)
    return ws
def _read_table(ws_name: str) -> List[Dict[str, Any]]:
    gc = _client()
    sh = _sheet(gc)
    ws = sh.worksheet(ws_name)
    return ws.get_all_records()
def _append_rows(ws_name: str, rows: List[List[Any]]):
    if not rows:
        return
    gc = _client()
    sh = _sheet(gc)
    ws = sh.worksheet(ws_name)
    ws.append_rows(rows, value_input_option="RAW")
def _update_range(ws, row_idx: int, values: List[Any]):
    """Update a full row starting at column A."""
    col_count = len(values)
    # Convert 1-based column index to Excel-style letters (A, B, ..., AA, AB, ...)
    def col_letter(n: int) -> str:
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s
    end_col = col_letter(col_count)
    ws.update(f"A{row_idx}:{end_col}{row_idx}", [values])

# ---------- Embedding helpers ----------
# Primary: Google Generative AI - text-embedding-004 (API key)
# Fallback: deterministic 128-d hash embedding (always available)
def _fallback_hash_embedding(text: str, dim: int = 128) -> List[float]:
    # Simple deterministic embedding: bag-of-tokens hashed to dim, L2-normalized
    import hashlib
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0
    # L2 normalize
    norm = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x / norm for x in vec]

def _embed_texts(texts: List[str]) -> Tuple[List[List[float]], str]:
    import google.generativeai as genai
    import math, os
    genai.configure(api_key="AIzaSyDwR3CPap8we4N6JaO6vC0aZKIpDpj3698")
    resp = genai.embed_content(
        model="models/text-embedding-004",
        content=texts
    )
    def extract_embedding(obj):
        """handles 3 possible formats google returns"""
        emb = obj.get("embedding")
        if isinstance(emb, dict):
            emb = emb.get("values")
        # if still nested list of list flatten 1 level
        if isinstance(emb, list) and len(emb)>0 and isinstance(emb[0], list):
            emb = emb[0]
        return emb
    if isinstance(resp, list):
        raw_embs = [extract_embedding(r) for r in resp]
    else:
        raw_embs = [extract_embedding(resp)]
    final=[]
    for e in raw_embs:
        norm = math.sqrt(sum(float(x)*float(x) for x in e)) or 1.0
        final.append([float(x)/norm for x in e])
    return final, "text-embedding-004"



def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x*y for x, y in zip(a, b))
    # vectors should be normalized; still guard
    na = math.sqrt(sum(x*x for x in a)) or 1.0
    nb = math.sqrt(sum(x*x for x in b)) or 1.0
    return dot / (na * nb)
# ---------- Vector sheet ops ----------
def _load_vectors_index() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Return (records, id->row_idx_map). row_idx is absolute sheet row number."""
    gc = _client()
    sh = _sheet(gc)
    try:
        ws = sh.worksheet("prism_vectors")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="prism_vectors", rows=1000, cols=7)
        _ensure_tab(ws, TAB_HEADERS["prism_vectors"])
        return [], {}
    records = ws.get_all_records()
    # Build map to real row (start from 2)
    id_to_row = {}
    for i, rec in enumerate(records, start=2):
        rid = str(rec.get("id", "")).strip()
        if rid:
            id_to_row[rid] = i
    return records, id_to_row
def _compose_row_id(source_tab: str, row_index: int) -> str:
    return f"{source_tab}:{row_index}"
def _compose_text_from_record(rec: Dict[str, Any], text_columns: List[str] | None) -> str:
    if text_columns:
        parts = []
        for c in text_columns:
            parts.append(str(rec.get(c, "")))
        return " | ".join(parts).strip()
    # default: join all string-like values
    return " | ".join(str(v) for v in rec.values() if v is not None).strip()
def _vector_upsert_sheet(source_tab: str, text_columns: List[str] | None = None) -> Dict[str, Any]:
    """Upsert vectors for all rows in source_tab."""
    # read source
    data = _read_table(source_tab)  # list[dict]
    if not data:
        return {"status": "ok", "updated": 0, "inserted": 0, "skipped": 0, "note": "no source rows"}
    # load current vector sheet + ws
    gc = _client()
    sh = _sheet(gc)
    ws_vec = _get_or_create("prism_vectors", TAB_HEADERS["prism_vectors"])
    existing, id_to_row = _load_vectors_index()
    # Build need-upsert list
    to_embed: List[Tuple[str, int, str]] = []  # (id, row_index, text)
    now = int(time.time())
    model_used = ""
    updated = inserted = skipped = 0
    # Build a quick in-memory map for existing by id
    existing_by_id: Dict[str, Dict[str, Any]] = {str(r.get("id", "")).strip(): r for r in existing}
    for idx, rec in enumerate(data, start=2):  # row 2..N (headers on 1)
        rid = _compose_row_id(source_tab, idx)
        text = _compose_text_from_record(rec, text_columns)
        if not text:
            skipped += 1
            continue
        found = existing_by_id.get(rid)
        if found:
            # Already exists; check if text changed; if same, skip
            if str(found.get("text", "")).strip() == text:
                skipped += 1
                continue
            else:
                # need re-embed (update)
                to_embed.append((rid, idx, text))
        else:
            to_embed.append((rid, idx, text))
    if not to_embed:
        return {"status": "ok", "updated": 0, "inserted": 0, "skipped": skipped, "note": "no changes needed"}
    # Embed in batches
# Embed in batches
    batch_size = 32
    for i in range(0, len(to_embed), batch_size):
        batch = to_embed[i:i+batch_size]
        texts = [t for (_rid, _row, t) in batch]
        embs=[]
        for t in texts:
            ee,_ = _embed_texts([t])
            embs.append(ee[0])
        for (rid, rowi, txt), emb in zip(batch, embs):
            emb_json = json.dumps(emb, separators=(",", ":"))
            updated_at = str(now)
            if rid in id_to_row:
                r = id_to_row[rid]
                ws_vec.update(f"A{r}:G{r}", [[rid, source_tab, rowi, txt, emb_json, model_used, updated_at]])
                updated += 1
            else:
                ws_vec.append_row([rid, source_tab, rowi, txt, emb_json, model_used, updated_at])
                inserted += 1

    return {"status": "ok", "updated": updated, "inserted": inserted, "skipped": skipped, "model": model_used}
def _vector_query(text: str, top_k: int = 5) -> Dict[str, Any]:
    if not text.strip():
        return {"status": "error", "error": "text required"}
    # read all vectors
    gc = _client()
    sh = _sheet(gc)
    ws = _get_or_create("prism_vectors", TAB_HEADERS["prism_vectors"])
    rows = ws.get_all_records()
    if not rows:
        return {"status": "ok", "results": [], "note": "empty vector store"}
    # embed query
    q_embs, model_used = _embed_texts([text])
    q = q_embs[0]
    # score all
    scored = []
    for r in rows:
        try:
            emb = json.loads(r.get("embedding_json", "[]"))
            score = _cosine(q, emb)
            scored.append((score, r))
        except Exception:
            continue
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, r in scored[:max(1, top_k)]:
        out.append({
            "id": r.get("id"),
            "source_tab": r.get("source_tab"),
            "row_index": r.get("row_index"),
            "score": round(float(score), 4),
            "text": r.get("text", "")[:300],
        })
    return {"status": "ok", "model": model_used, "results": out}
# ---------- Tool implementations ----------
def _tool_prism_ensure_tabs(_: Dict[str, Any] | None = None) -> Dict[str, Any]:
    gc = _client()
    sh = _sheet(gc)
    verified = []
    for tab, headers in TAB_HEADERS.items():
        try:
            ws = sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=tab, rows=1000, cols=max(20, len(headers)))
        _ensure_tab(ws, headers)
        verified.append(tab)
    return {"status": "ok", "tabs_verified": verified}
def _tool_prism_read_table(args: Dict[str, Any]) -> Dict[str, Any]:
    sheet_name = str(args.get("sheet_name", "")).strip()
    if not sheet_name:
        return {"status": "error", "error": "sheet_name is required"}
    data = _read_table(sheet_name)
    return {"status": "ok", "sheet_name": sheet_name, "rows": data, "count": len(data)}
def _tool_prism_append_rows(args: Dict[str, Any]) -> Dict[str, Any]:
    sheet_name = str(args.get("sheet_name", "")).strip()
    rows = args.get("rows", [])
    if not sheet_name:
        return {"status": "error", "error": "sheet_name is required"}
    if not isinstance(rows, list):
        return {"status": "error", "error": "rows must be a list of lists"}
    _get_or_create(sheet_name, TAB_HEADERS.get(sheet_name, []))
    _append_rows(sheet_name, rows)
    return {"status": "appended", "sheet_name": sheet_name, "rows_appended": len(rows)}
def _tool_prism_upsert_taxonomy(args: Dict[str, Any]) -> Dict[str, Any]:
    rows = args.get("rows", [])
    if not isinstance(rows, list):
        return {"status": "error", "error": "rows must be a list of {category,label,weight} dicts"}
    # Upsert into taxonomy_weights by rewriting entire table (safe for small N)
    data = _read_table("taxonomy_weights")
    # make map
    idx = {(str(r.get("category","")).lower(), str(r.get("label","")).lower()): r for r in data}
    for r in rows:
        k = (str(r.get("category","")).lower(), str(r.get("label","")).lower())
        idx[k] = {"category": r.get("category",""), "label": r.get("label",""), "weight": r.get("weight", 0)}
    # write back
    gc = _client()
    sh = _sheet(gc)
    ws = _get_or_create("taxonomy_weights", TAB_HEADERS["taxonomy_weights"])
    out = [TAB_HEADERS["taxonomy_weights"]]
    for (_, _), row in idx.items():
        out.append([row["category"], row["label"], row["weight"]])
    ws.clear()
    ws.update("A1", out, value_input_option="RAW")
    return {"status": "ok", "rows": len(rows)}
def _tool_prism_append_feedback(args: Dict[str, Any]) -> Dict[str, Any]:
    timestamp = str(args.get("timestamp", "")).strip()
    feedback  = str(args.get("feedback", "")).strip()
    if not timestamp or not feedback:
        return {"status": "error", "error": "timestamp and feedback are required"}
    _get_or_create("prism_feedback", TAB_HEADERS["prism_feedback"])
    _append_rows("prism_feedback", [[timestamp, feedback]])
    return {"status": "saved", "count": 1}
def _tool_prism_append_governance(args: Dict[str, Any]) -> Dict[str, Any]:
    items = args.get("items", [])
    if not isinstance(items, list):
        return {"status": "error", "error": "items must be a list of dicts"}
    _get_or_create("prism_governance", TAB_HEADERS["prism_governance"])
    rows = []
    for r in items:
        rows.append([
            r.get("worker_id",""),
            r.get("date",""),
            r.get("technology",""),
            r.get("work_type",""),
            float(r.get("confidence",0)),
            int(r.get("duration_seconds",0)),
            r.get("reason","confidence<0.75"),
        ])
    if rows:
        _append_rows("prism_governance", rows)
    return {"status": "queued", "count": len(rows)}
def _tool_prism_read_all_sources(_: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in CORE_SOURCE_TABS:
        data = _read_table(name)
        out[name] = data
    return {"status": "ok", "sources": out}

def _tool_prism_vector_build(args: Dict[str, Any]) -> Dict[str, Any]:
    source_sheet = str(args.get("source_sheet", "")).strip()
    text_columns = args.get("text_columns")  # optional list
    if not source_sheet:
        return {"status": "error", "error": "source_sheet is required"}
    if text_columns is not None and not isinstance(text_columns, list):
        return {"status": "error", "error": "text_columns must be a list of column names"}
    return _vector_upsert_sheet(source_sheet, text_columns)
def _tool_prism_vector_autobuild(_: Dict[str, Any] | None = None) -> Dict[str, Any]:
    # build vectors for all core sources (employees, cmdb, activity_logs)
    # taxonomy not very helpful semantically, but keep for completeness
    totals = {"updated": 0, "inserted": 0, "skipped": 0}
    for tab in ["employees","cmdb","activity_logs"]:
        res = _vector_upsert_sheet(tab, text_columns=None)
        totals["updated"] += res.get("updated", 0)
        totals["inserted"] += res.get("inserted", 0)
        totals["skipped"] += res.get("skipped", 0)
    return {"status": "ok", **totals}
def _tool_prism_vector_query(args: Dict[str, Any]) -> Dict[str, Any]:
    text = str(args.get("text", "")).strip()
    top_k = int(args.get("top_k", 5))
    return _vector_query(text, top_k=top_k)
# ---------- MCP Server setup ----------
server = Server(
    name="prism-mcp-sheets",
    version="1.1.0",
    instructions=(
        "This MCP server exposes read/write access to a Google Sheet backing store for Project Prism, "
        "plus semantic vector tools (build/query)."
    )
)
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="prism_ensure_tabs",
            inputSchema={"type":"object","properties":{}},
            outputSchema={"type":"object","properties":{"status":{"type":"string"}}, "required":["status"]},
        ),
        Tool(
            name="prism_read_table",
            inputSchema={"type":"object","properties":{"sheet_name":{"type":"string"}},"required":["sheet_name"]},
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_append_rows",
            inputSchema={
                "type":"object",
                "properties":{
                    "sheet_name":{"type":"string"},
                    "rows":{"type":"array","items":{"type":"array"}}
                },
                "required":["sheet_name","rows"]
            },
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_upsert_taxonomy",
            inputSchema={
                "type":"object",
                "properties":{"rows":{"type":"array","items":{"type":"object"}}},
                "required":["rows"]
            },
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_append_feedback",
            inputSchema={
                "type":"object",
                "properties":{"timestamp":{"type":"string"},"feedback":{"type":"string"}},
                "required":["timestamp","feedback"]
            },
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_append_governance",
            inputSchema={
                "type":"object",
                "properties":{"items":{"type":"array","items":{"type":"object"}}},
                "required":["items"]
            },
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_read_all_sources",
            inputSchema={"type":"object","properties":{}},
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_vector_build",
            inputSchema={
                "type":"object",
                "properties":{
                    "source_sheet":{"type":"string"},
                    "text_columns":{"type":["array","null"],"items":{"type":"string"}}
                },
                "required":["source_sheet"]
            },
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_vector_autobuild",
            inputSchema={"type":"object","properties":{}},
            outputSchema={"type":"object"},
        ),
        Tool(
            name="prism_vector_query",
            inputSchema={
                "type":"object",
                "properties":{"text":{"type":"string"},"top_k":{"type":"integer","minimum":1}},
                "required":["text"]
            },
            outputSchema={"type":"object"},
        ),
    ]
@server.call_tool(validate_input=True)
async def call_tool(name: str, arguments: dict | None):
    args = arguments or {}
    if name == "prism_ensure_tabs":
        return _tool_prism_ensure_tabs(args)
    if name == "prism_read_table":
        return _tool_prism_read_table(args)
    if name == "prism_append_rows":
        return _tool_prism_append_rows(args)
    if name == "prism_upsert_taxonomy":
        return _tool_prism_upsert_taxonomy(args)
    if name == "prism_append_feedback":
        return _tool_prism_append_feedback(args)
    if name == "prism_append_governance":
        return _tool_prism_append_governance(args)
    if name == "prism_read_all_sources":
        return _tool_prism_read_all_sources(args)
    if name == "prism_vector_build":
        return _tool_prism_vector_build(args)
    if name == "prism_vector_autobuild":
        return _tool_prism_vector_autobuild(args)
    if name == "prism_vector_query":
        return _tool_prism_vector_query(args)
    return {"status":"error","error":f"Unknown tool '{name}'"}
# ---------- Run stdio server ----------
async def main():
    init = server.create_initialization_options(
        notification_options=NotificationOptions(tools_changed=False, resources_changed=False, prompts_changed=False),
        experimental_capabilities={},
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            init,
            raise_exceptions=False,
            stateless=True,
        )
if __name__ == "__main__":
    asyncio.run(main())