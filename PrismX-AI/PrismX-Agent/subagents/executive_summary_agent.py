# subagents/executive_summary_agent.py
import math
import re
from datetime import date, datetime, timedelta
from calendar import monthrange
from typing import Any, Dict, List, Optional, Tuple

from google.adk import Agent
from google.adk.tools.tool_context import ToolContext
# from common.rbac import identity_policy, redact_row

from common.config import MODEL, CLEAN_CFG, MCP_SHEETS

# -----------------------------
# Natural-language date parsing
# -----------------------------

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January","February","March","April","May","June","July","August","September","October","November","December"], 1
    )
}
_MONTHS.update({m[:3].lower(): i for m, i in _MONTHS.items()})  # Jan, Feb, ...

ISO_DATE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")

def _try_iso(s: str) -> Optional[date]:
    m = ISO_DATE.match(s)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None

def _parse_month_token(tok: str) -> Optional[int]:
    return _MONTHS.get(tok.strip().lower())

def _month_bounds(y: int, m: int) -> Tuple[date, date]:
    last = monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)

def _parse_single_month(expr: str) -> Optional[Tuple[date, date]]:
    # e.g., "Oct 2025", "October 2025"
    parts = expr.strip().replace(",", " ").split()
    if len(parts) != 2:
        return None
    mo = _parse_month_token(parts[0])
    if not mo:
        return None
    try:
        y = int(parts[1])
    except ValueError:
        return None
    return _month_bounds(y, mo)

def _parse_relative(expr: str, today: date) -> Optional[Tuple[date, date]]:
    s = expr.strip().lower()
    # last N days|weeks
    m = re.match(r"last\s+(\d+)\s+(day|days|week|weeks)\b", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(days=n if unit.startswith("day") else 7 * n)
        start = today - delta + timedelta(days=1)
        end = today
        return (start, end)
    # this month
    if s in ("this month", "current month"):
        return _month_bounds(today.year, today.month)
    # past month (previous calendar month)
    if s in ("past month", "last month", "previous month"):
        y, mnum = today.year, today.month
        mnum -= 1
        if mnum == 0:
            mnum = 12
            y -= 1
        return _month_bounds(y, mnum)
    # past week
    if s in ("past week", "last week", "previous week"):
        start = today - timedelta(days=7) + timedelta(days=1)
        end = today
        return (start, end)
    # past quarter (last 90 days)
    if s in ("past quarter", "last quarter", "previous quarter"):
        start = today - timedelta(days=89)
        return (start, today)
    return None

def _parse_range_phrase(expr: str, today: date) -> Optional[Tuple[date, date]]:
    s = expr.strip()
    # "from X to Y" or "between X and Y"
    m = re.match(r"(?i)^\s*(from|between)\s+(.+?)\s+(to|and)\s+(.+)\s*$", s)
    if not m:
        return None
    a = m.group(2).strip()
    b = m.group(4).strip()
    sa = _parse_any_date_or_month(a, today)
    sb = _parse_any_date_or_month(b, today)
    if not sa or not sb:
        return None
    start = sa[0]  # if month, we take first day
    end = sb[1]    # if month, we take last day
    if start > end:
        start, end = end, start
    return (start, end)

def _parse_any_date_or_month(expr: str, today: date) -> Optional[Tuple[date, date]]:
    # Try ISO date
    d = _try_iso(expr)
    if d:
        return (d, d)
    # Try "Oct 2025"
    mm = _parse_single_month(expr)
    if mm:
        return mm
    # Try simple English day like "Oct 7 2025" or "October 7, 2025"
    m = re.match(r"(?i)^\s*([A-Za-z]{3,9})\s+(\d{1,2})(?:,)?\s+(\d{4})\s*$", expr)
    if m:
        mo_tok, day_s, year_s = m.groups()
        mo = _parse_month_token(mo_tok)
        if mo:
            try:
                d2 = date(int(year_s), mo, int(day_s))
                return (d2, d2)
            except ValueError:
                pass
    # Fallback: relative phrases (handled separately above usually)
    rel = _parse_relative(expr, today)
    if rel:
        return rel
    return None

def parse_window_nl(user_text: Optional[str]) -> Tuple[date, date, str]:
    """
    Returns (start_date, end_date, label).
    Default: last 14 days from TODAY (Option A).
    """
    today = date.today()
    if not user_text or not user_text.strip():
        start = today - timedelta(days=13)  # inclusive
        return (start, today, f"Last 14 days (through {today.isoformat()})")

    s = user_text.strip()

    # 1) explicit range: "from ... to ..." / "between ... and ..."
    rng = _parse_range_phrase(s, today)
    if rng:
        st, en = rng
        return (st, en, f"{st.isoformat()} to {en.isoformat()}")

    # 2) relative windows: "last 7/10/14/30 days", "this month", "past month", "past week", "past quarter"
    rel = _parse_relative(s.lower(), today)
    if rel:
        st, en = rel
        return (st, en, s)

    # 3) single date (ISO) or month token
    single = _parse_any_date_or_month(s, today)
    if single:
        st, en = single
        if st == en:
            return (st, en, st.isoformat())
        else:
            return (st, en, f"{st.isoformat()} to {en.isoformat()}")

    # 4) fallback to default
    start = today - timedelta(days=13)
    return (start, today, f"Last 14 days (through {today.isoformat()})")

# -----------------------------
# Executive summary aggregation
# -----------------------------

def _coerce_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return default

def _coerce_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _parse_date_field(x: Any) -> Optional[date]:
    if not x:
        return None
    # try ISO
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        pass
    # try loose "Oct 7 2025"
    m = re.match(r"(?i)^\s*([A-Za-z]{3,9})\s+(\d{1,2})(?:,)?\s+(\d{4})\s*$", str(x))
    if m:
        mo = _parse_month_token(m.group(1))
        if mo:
            try:
                return date(int(m.group(3)), mo, int(m.group(2)))
            except Exception:
                return None
    return None

def _filter_by_window(rows: List[Dict[str, Any]], start: date, end: date, date_key: str = "date") -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        d = _parse_date_field(r.get(date_key))
        if d and start <= d <= end:
            out.append(r)
    return out

def _hours(seconds: int) -> float:
    return round(seconds / 3600.0, 1)

def _summarize(classified_rows: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    # Inputs expect keys:
    # - date
    # - worker_id
    # - work_type  (fallback to activity_observed/app_category if missing)
    # - duration_seconds
    # - confidence (optional) or signal_confidence
    total_sec = 0
    conf_acc = 0.0
    conf_n = 0
    by_work: Dict[str, int] = {}
    workers = set()

    for r in classified_rows:
        workers.add(str(r.get("worker_id", "")))
        wt = (r.get("work_type")
              or r.get("activity_observed")
              or r.get("app_category")
              or "Uncategorized")
        dur = _coerce_int(r.get("duration_seconds"), 0)
        total_sec += dur
        by_work[wt] = by_work.get(wt, 0) + dur

        c = r.get("confidence")
        if c is None:
            c = r.get("signal_confidence")
        if c is not None:
            conf_acc += _coerce_float(c)
            conf_n += 1

    total_hours = _hours(total_sec)
    top = sorted(by_work.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_lines = [f"- {wt}: {_hours(sec)} hrs" for wt, sec in top]
    avg_conf = round(conf_acc / conf_n, 3) if conf_n else None

    lines = []
    lines.append("Project Prism — Executive Insights")
    lines.append("")
    lines.append(f"Coverage: {len([w for w in workers if w])} workers, {len(classified_rows)} classified slices")
    if avg_conf is not None:
        lines.append(f"Average classification confidence: {avg_conf}")
    lines.append("")
    lines.append("Top work types (hours):")
    lines.extend(top_lines if top_lines else ["- (no data)"])
    lines.append("")
    lines.append(f"Total workforce time analyzed: {round(total_hours, 1)} hrs")

    return "\n".join(lines), {
        "coverage_workers": len([w for w in workers if w]),
        "coverage_slices": len(classified_rows),
        "avg_confidence": avg_conf,
        "top_work_types": [{"work_type": wt, "hours": _hours(sec)} for wt, sec in top],
        "total_hours": round(total_hours, 1),
    }

# -----------------------------
# Public tool
# -----------------------------

def _build_window_label(start: date, end: date, label: str) -> str:
    if start == end:
        return f" for {start.isoformat()}"
    return f" for {label}"

def generate_summary(tool_context: ToolContext, window_query: Optional[str] = None) -> Dict[str, Any]:
    """
    Generates an executive summary for the requested date window.

    Args:
      window_query (optional, str): natural language date window.
        Examples:
          - "last 7 days"
          - "this month"
          - "past month"
          - "from 2025-10-20 to 2025-11-01"
          - "between Oct 20 and Nov 1"
          - "Oct 2025"
          - "2025-11-01"

    Default (if omitted or unparseable): last 14 days from TODAY.
    """
    start, end, label = parse_window_nl(window_query)

    # Prefer already classified data if present
    rows = tool_context.state.get("classified") or []
    if not rows:
        # Fallback to raw activity logs; we’ll map minimal fields so the summary still works
        raw = tool_context.state.get("activity_logs") or []
        # Normalize shape
        mapped = []
        for r in raw:
            mapped.append({
                "date": r.get("date"),
                "worker_id": r.get("worker_id"),
                "work_type": r.get("activity_observed") or r.get("app_category") or "Uncategorized",
                "duration_seconds": _coerce_int(r.get("duration_seconds"), 0),
                "confidence": r.get("signal_confidence"),
            })
        rows = mapped

    rows = _filter_by_window(rows, start, end, date_key="date")
    text, metrics = _summarize(rows)
    
    # # RBAC enforce
    # safe_rows = []
    # for r in rows:
    #     if identity_policy(r):       # <-- no state argument here
    #         r2 = redact_row(r, tool_context.state)
    #         safe_rows.append(r2)
    # text, metrics = _summarize(safe_rows)

    text = f"{text}\n\n(Window{_build_window_label(start, end, label)})"

    # Keep last summary in state (useful for follow-ups)
    tool_context.state["last_summary"] = {
        "window": {"start": start.isoformat(), "end": end.isoformat(), "label": label},
        "text": text,
        "metrics": metrics,
    }

    return {"summary": text, "window": {"start": start.isoformat(), "end": end.isoformat(), "label": label}}

# -----------------------------
# Agent wrapper
# -----------------------------

executive_summary_agent = Agent(
    name="executive_summary_agent",
    model=MODEL,
    description="Produces executive summaries for a requested date window.",
    instruction="""
You produce executive-ready summaries of recent workforce activity.

Behavior:
- If the user provides a date/window in natural language, pass it to the tool `generate_summary`.
- If the user does not provide any window, use the default window (last 14 days from TODAY).
- Always respond with the summary text returned by the tool. Do not write files.
- Keep tone concise, business-friendly. Never reveal worker IDs or PII.
""",
    tools=[generate_summary, MCP_SHEETS],
    generate_content_config=CLEAN_CFG,
)
