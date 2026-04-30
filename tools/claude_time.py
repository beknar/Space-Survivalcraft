"""Cumulative active time spent in Claude Code sessions.

Walks ``~/.claude/projects/*/*.jsonl`` (one file per session),
sums the gap between consecutive event timestamps, and skips
gaps longer than ``IDLE_GAP_S`` so overnight idle doesn't
inflate the total.  There's no native "time-on-task" metric in
Claude Code -- this reconstructs it from the local transcripts.

Run:
    python tools/claude_time.py            # default: 5-min idle gap
    python tools/claude_time.py 600        # treat gaps < 10 min as active

Output: total active time, per-project breakdown, top 10 longest
single sessions.  All counts are wall-clock seconds derived from
the ``timestamp`` field every event carries; nothing here calls
the Anthropic API.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime


DEFAULT_IDLE_GAP_S = 300   # 5 min


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fmt(secs: float) -> str:
    h, r = divmod(int(secs), 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def main() -> None:
    idle_gap_s = (
        int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IDLE_GAP_S)
    root = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(root):
        print(f"no Claude Code projects dir at {root}")
        return

    totals: dict[str, list] = defaultdict(lambda: [0.0, 0])
    sessions: list[tuple[float, str, str]] = []

    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        project = os.path.basename(os.path.dirname(path))
        timestamps: list[datetime] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    ts = evt.get("timestamp")
                    if not ts:
                        continue
                    try:
                        timestamps.append(_parse_ts(ts))
                    except Exception:
                        pass
        except Exception:
            continue
        timestamps.sort()
        if len(timestamps) < 2:
            continue
        active = 0.0
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds()
            if 0 < gap < idle_gap_s:
                active += gap
        if active > 0:
            totals[project][0] += active
            totals[project][1] += 1
            sessions.append((active, project, os.path.basename(path)))

    grand = sum(t[0] for t in totals.values())
    sess_count = sum(t[1] for t in totals.values())

    print(f"=== Active time (gaps > {idle_gap_s // 60} min skipped) ===\n")
    print(f"Total: {_fmt(grand)}  ({sess_count} sessions, "
          f"{len(totals)} projects)\n")
    print(f"{'Project':<55} {'Sessions':>9} {'Active':>14}")
    print("-" * 80)
    for proj, (secs, n) in sorted(
            totals.items(), key=lambda kv: -kv[1][0]):
        print(f"{proj:<55} {n:>9} {_fmt(secs):>14}")
    print(f"\n--- Top 10 longest single sessions (active) ---")
    for dur, proj, fname in sorted(sessions, reverse=True)[:10]:
        print(f"  {_fmt(dur):>14}  {proj}  ({fname[:8]}...)")


if __name__ == "__main__":
    main()
