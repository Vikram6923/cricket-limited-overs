"""Preset Test squads for the saved-team lists (Match / Series, Team Builder): "India Test 2025" and so on.

    python scripts/build_test_presets.py      -> data/teams_default.json (and data/teams.json if you have one)

A squad is the SIZE players with the most Tests for the nation in YEARS (engine/history.py, which keeps a
keeper), as the Classic modes pick theirs. The window and the size are choices, not fitted numbers: two years
of Tests is the shortest window in which every side here has played enough to fill a squad.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import history  # noqa: E402
from engine.data import ratings  # noqa: E402

YEARS = (2024, 2025)
SIZE = 15
NATIONS = ("India", "Australia", "England", "South Africa", "New Zealand", "Pakistan", "Sri Lanka", "West Indies",
           "Bangladesh")


def main() -> int:
    rows = ratings("test")["players"]
    presets = []
    for nation in NATIONS:
        ids = history.squad("test", nation, *YEARS, size=SIZE)
        if len(ids) < 11:
            print(f"  {nation}: only {len(ids)} players, left out")
            continue
        presets.append({"name": f"{nation} Test {YEARS[1]}",
                        "players": [{"id": p, "name": rows[p]["name"]} for p in ids]})
        print(f"  {presets[-1]['name']}: {', '.join(p['name'] for p in presets[-1]['players'])}")
    for path in (ROOT / "data" / "teams_default.json", ROOT / "data" / "teams.json"):
        if path.exists():
            teams = json.loads(path.read_text(encoding="utf-8"))
            teams = [t for t in teams if not t["name"].endswith(f" Test {YEARS[1]}")]
            at = max((i for i, t in enumerate(teams) if " ODI " in t["name"]), default=len(teams) - 1) + 1
            teams[at:at] = presets                      # after the ODI sides, before the franchises
            path.write_text(json.dumps(teams, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
