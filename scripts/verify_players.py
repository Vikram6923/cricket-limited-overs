"""Compare Cricsheet-derived career stats with the career table in each player's Wikipedia infobox.

Wikipedia responses are cached in data/raw/wikipedia/ (use --refresh to re-fetch).

    python scripts/verify_players.py
    python scripts/verify_players.py "Virat Kohli=V Kohli" "Steve Smith (cricketer)=SPD Smith"

Each argument is "<Wikipedia title>=<Cricsheet name>"; the Cricsheet name may also be a Cricsheet ID.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wikiutil import clean, infobox_fields, num, wiki_career, wiki_wikitext

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "data" / "raw_stats"

DEFAULT = ["Virat Kohli=V Kohli", "Babar Azam=Babar Azam", "Rashid Khan=5f547c8b", "Jasprit Bumrah=JJ Bumrah"]
WIKI_COLUMN = {"odi": "ODI", "t20": "T20I"}


def ours(rec: dict) -> dict:
    b, w, f = rec["bat"], rec["bowl"], rec["field"]
    return {"matches": str(rec["matches"]), "runs": str(b["runs"]), "bat_avg": f"{b['avg']}" if b["avg"] else "-",
            "100s/50s": f"{b['hundreds']}/{b['fifties']}", "hs": f"{b['hs']}{'*' if b['hs_not_out'] else ''}",
            "balls": str(w["balls"]), "wkts": str(w["wkts"]), "bowl_avg": f"{w['avg']}" if w["avg"] else "-",
            "5w": str(w["five_w"]), "best": f"{w['best'][0]}/{w['best'][1]}" if w["best"] else "-",
            "ct/st": f"{f['catches']}/{f['stumpings']}",
            "_sr": b["sr"], "_econ": w["econ"], "_last": rec["last"]}


def find(players: dict, key: str) -> dict | None:
    if key in players:
        return players[key]
    hits = [r for r in players.values() if r["name"] == key]
    return max(hits, key=lambda r: r["matches"]) if hits else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pairs", nargs="*", default=DEFAULT)
    ap.add_argument("--refresh", action="store_true", help="re-fetch Wikipedia pages")
    ap.add_argument("--json", type=Path, help="also write the comparison to this file")
    args = ap.parse_args(argv)

    players = {fmt: json.loads((STATS / f"players_{fmt}.json").read_text(encoding="utf-8")) for fmt in WIKI_COLUMN}
    listed = {fmt: json.loads((STATS / f"coverage_{fmt}.json").read_text(encoding="utf-8"))["listed_missing"]
              for fmt in WIKI_COLUMN}
    report = []
    keys = ["matches", "runs", "bat_avg", "100s/50s", "hs", "balls", "wkts", "bowl_avg", "5w", "best", "ct/st"]
    for pair in args.pairs:
        title, cs = pair.split("=", 1)
        fields = infobox_fields(wiki_wikitext(title, args.refresh))
        as_of = clean(fields.get("date"))
        for fmt, col in WIKI_COLUMN.items():
            w = wiki_career(fields, col)
            rec = find(players[fmt], cs)
            o = ours(rec) if rec else None
            print(f"\n=== {title} — {col}  (Wikipedia as of: {as_of or '?'};  Cricsheet last match: "
                  f"{o['_last'] if o else '-'})")
            if not w and not o:
                print("   no data either side")
                continue
            print(f"   {'':10}{'Wikipedia':>14}{'Cricsheet':>14}{'diff':>9}")
            row = {"player": title, "format": col, "as_of": as_of, "stats": {}}
            for k in keys:
                a, c = (w or {}).get(k, ""), (o or {}).get(k, "")
                na, nc = num(a), num(c)
                diff = "" if na is None or nc is None or "/" in k else f"{nc - na:+g}"
                print(f"   {k:10}{a or '-':>14}{c or '-':>14}{diff:>9}")
                row["stats"][k] = {"wikipedia": a, "cricsheet": c}
            if o:
                print(f"   (Cricsheet only: bat SR {o['_sr']}, economy {o['_econ']})")
                row["sr"], row["econ"] = o["_sr"], o["_econ"]
                # Matches of the player's team that Cricsheet lists as missing during the player's career span.
                # Whatever is left of the match gap is mostly withheld Afghanistan games (or later matches).
                lm = [m for m in listed[fmt] if rec["team"] in m["teams"] and rec["first"] <= m["date"] <= rec["last"]]
                print(f"   ({len(lm)} {rec['team']} matches in the player's Cricsheet span are on Cricsheet's missing list)")
                row["team_listed_missing_in_span"] = len(lm)
            report.append(row)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
