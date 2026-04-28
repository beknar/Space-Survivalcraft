"""Helper functions Claude calls between bash invocations.

The strategist (Claude in Claude Code) typically just runs:

    python bot_strategy_helper.py state              # print state
    python bot_strategy_helper.py set_intent <json>  # set an intent

Or from a one-off Bash:

    python -c "import bot_strategy_helper as h; print(h.summary())"

This script exists to keep Claude's per-invocation tool calls
short -- one bash call returns a focused string instead of a
1 KB JSON dump.
"""
from __future__ import annotations

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen, Request

API_BASE = "http://127.0.0.1:8765"


def fetch_state() -> dict | None:
    try:
        with urlopen(f"{API_BASE}/state", timeout=1.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as e:
        print(f"[helper] fetch failed: {e}", file=sys.stderr)
        return None


def set_intent(intent: dict) -> dict | None:
    body = json.dumps(intent).encode("utf-8")
    req = Request(
        f"{API_BASE}/intent",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=1.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[helper] post failed: {e}", file=sys.stderr)
        return None


def set_assist(enabled: bool) -> dict | None:
    """Toggle the in-process combat-assist defence layer."""
    body = json.dumps({"enabled": bool(enabled)}).encode("utf-8")
    req = Request(
        f"{API_BASE}/assist",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=1.0) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[helper] post failed: {e}", file=sys.stderr)
        return None


def summary(state: dict | None = None) -> str:
    """Compact one-screen text summary of the current state.
    Designed for Claude to read in a single bash response."""
    s = state if state is not None else fetch_state()
    if s is None:
        return "<no state -- is the game running with COO_BOT_API=1?>"
    p = s.get("player", {})
    w = s.get("weapon", {})
    z = s.get("zone", {})
    inv = s.get("inventory", {}).get("items", {})
    boss = s.get("boss")
    intent = s.get("intent", {})
    lines = [
        f"Player: ({p.get('x', 0):.0f}, {p.get('y', 0):.0f})  "
        f"hdg={p.get('heading', 0):.0f}  "
        f"hp={p.get('hp', 0)}/{p.get('max_hp', 0)}  "
        f"sh={p.get('shields', 0)}/{p.get('max_shields', 0)}  "
        f"abil={s.get('ability', {}).get('value', 0)}/"
        f"{s.get('ability', {}).get('max', 0)}",
        f"Ship  : {p.get('faction')}/{p.get('ship_type')} L{p.get('ship_level', 1)}  "
        f"weapon={w.get('name')}",
        f"Zone  : {z.get('id')} {z.get('world_w')}x{z.get('world_h')}",
        f"Items : {inv}",
        f"Counts: {len(s.get('asteroids', []))} asteroids, "
        f"{len(s.get('aliens', []))} aliens, "
        f"{len(s.get('buildings', []))} buildings",
        f"Boss  : {boss}",
        f"Intent: {intent}",
    ]
    return "\n".join(lines)


def cli() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("state", "summary"):
        print(summary())
        return
    if args[0] == "raw":
        s = fetch_state()
        print(json.dumps(s, indent=2) if s else "")
        return
    if args[0] == "set_intent":
        try:
            payload = json.loads(args[1])
        except (IndexError, json.JSONDecodeError) as e:
            print(f"usage: set_intent <json>  (got: {e})", file=sys.stderr)
            sys.exit(1)
        result = set_intent(payload)
        print(json.dumps(result, indent=2) if result else "<failed>")
        return
    if args[0] == "assist":
        if len(args) < 2 or args[1] not in ("on", "off"):
            print("usage: assist on|off", file=sys.stderr)
            sys.exit(1)
        result = set_assist(args[1] == "on")
        print(json.dumps(result, indent=2) if result else "<failed>")
        return
    print(f"unknown command: {args[0]!r}", file=sys.stderr)
    print("commands: state | raw | set_intent <json> | assist on|off", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    cli()
