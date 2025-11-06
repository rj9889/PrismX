import re
from datetime import date, timedelta

def percent(n: float) -> str:
    try:
        return f"{float(n)*100:.1f}%"
    except Exception:
        return "0.0%"

def parse_days_window(q: str, default_days: int = 7):
    ql = q.lower()
    m = re.search(r"(last|past)\s+(\d{1,3})\s+days", ql)
    if m:
        n = int(m.group(2)); end = date.today(); start = end - timedelta(days=n)
        return (start.isoformat(), end.isoformat(), f"last {n} days")
    if "this week" in ql:
        today = date.today()
        start = today - timedelta(days=today.weekday()); end = start + timedelta(days=6)
        return (start.isoformat(), end.isoformat(), "this week")
    if "last week" in ql or "previous week" in ql:
        today = date.today()
        start = today - timedelta(days=today.weekday()+7); end = start + timedelta(days=6)
        return (start.isoformat(), end.isoformat(), "last week")
    end = date.today(); start = end - timedelta(days=default_days)
    return (start.isoformat(), end.isoformat(), f"last {default_days} days")
