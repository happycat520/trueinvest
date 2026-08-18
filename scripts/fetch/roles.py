"""
Shared CEO/CFO role-matching logic.

The patterns themselves live in role_patterns.json at the repo root — that
file is the single source of truth, and is also fetched directly by
index.html at runtime so the website's JS uses the exact same rules
without needing a second, hand-copied implementation.

If the matching rule ever needs to change (e.g. adding "PRINCIPAL
FINANCIAL OFFICER"), edit role_patterns.json only. Nothing in this file,
fetch_insider.py, send_email.py, or index.html should ever need to change
for a patterns-only update.
"""
import json
import os

_PATTERNS_PATH = os.path.join(os.path.dirname(__file__), "..", "role_patterns.json")

with open(_PATTERNS_PATH) as _f:
    _PATTERNS = json.load(_f)


def is_ceo(role):
    r = (role or "").upper()
    return any(p in r for p in _PATTERNS["ceo"])


def is_cfo(role):
    r = (role or "").upper()
    return any(p in r for p in _PATTERNS["cfo"])
