"""Batting hand, bowling type, date of birth and domestic career totals for every player who matters.

Cricsheet has no player attributes, so:
  ESPNcricinfo ID (Cricsheet register) -> Wikidata (SPARQL on P2697) -> English Wikipedia article + date of birth
  -> {{Infobox cricketer}}: batting / bowling style, List A and T20 career columns (used as priors in the ratings).

Everything is cached (data/raw/wikidata_sparql/, data/raw/wikipedia/), so re-runs only fetch new players.

Reads   data/raw_stats/players_{odi,t20,t20_league}.json
Writes  data/raw_stats/styles.json   {cricsheet_id: {...}}

    python scripts/fetch_styles.py                 # players with >=10 matches / 120 balls bowled / 200 faced
    python scripts/fetch_styles.py --min-matches 3 # widen the net
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

from wikiutil import HEADERS, clean, infobox_fields, pages, wiki_career, wikitext_of

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "data" / "raw_stats"
SPARQL_CACHE = ROOT / "data" / "raw" / "wikidata_sparql"
SPARQL = "https://query.wikidata.org/sparql"


def sparql_batch(cids: list[str]) -> list[dict]:
    key = hashlib.sha1(",".join(sorted(cids)).encode()).hexdigest()[:16]
    path = SPARQL_CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    values = " ".join(f'"{c}"' for c in cids)
    q = f"""SELECT ?cid ?item ?article ?dob WHERE {{
      VALUES ?cid {{ {values} }}
      ?item wdt:P2697 ?cid .
      OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
      OPTIONAL {{ ?item wdt:P569 ?dob . }}
    }}"""
    for attempt in range(5):
        r = requests.post(SPARQL, data={"query": q, "format": "json"}, headers=HEADERS, timeout=120)
        if r.status_code not in (429, 500, 502, 503, 504):
            break
        time.sleep(20 * (attempt + 1))
    r.raise_for_status()
    rows = [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]
    SPARQL_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    time.sleep(2)
    return rows


def classify_bowling(text: str) -> dict:
    """'Right-arm fast-medium' -> {'type': 'pace', 'kind': 'fast_medium', 'arm': 'right'}."""
    t = text.lower().replace("–", "-")
    first = re.split(r"<br\s*/?>|\n|;|,| / | and ", t)[0] if t else ""
    s = first or t
    if not s.strip():
        return {"type": None, "kind": None, "arm": None}
    arm = "left" if "left" in s else ("right" if "right" in s else None)
    if re.search(r"wrist|chinaman|unorthodox", s) and (arm == "left" or "chinaman" in s):
        kind, typ, arm = "left_arm_wrist", "spin", "left"
    elif re.search(r"orthodox|slow left|left-arm spin|left arm spin|slow-left", s):
        kind, typ, arm = "left_arm_orthodox", "spin", "left"
    elif re.search(r"leg[- ]?break|leg[- ]?spin|googly|wrist", s):
        kind, typ = "leg_spin", "spin"
    elif re.search(r"off[- ]?break|off[- ]?spin|offbreak", s):
        kind, typ = "off_spin", "spin"
    elif re.search(r"\bspin|slow\b", s):
        kind, typ = "spin", "spin"
    elif re.search(r"fast[- ]?medium", s):
        kind, typ = "fast_medium", "pace"
    elif re.search(r"medium[- ]?fast", s):
        kind, typ = "medium_fast", "pace"
    elif "fast" in s:
        kind, typ = "fast", "pace"
    elif re.search(r"medium|seam|swing", s):
        kind, typ = "medium", "pace"
    else:
        kind, typ = None, None
    if typ == "spin" and arm is None:
        arm = "right"
    return {"type": typ, "kind": kind, "arm": arm}


def classify_batting(text: str) -> str | None:
    t = text.lower()
    if "left" in t:
        return "left"
    if "right" in t:
        return "right"
    return None


def candidates(min_matches: int) -> dict[str, str]:
    """cricsheet_id -> cricinfo_id for players worth looking up."""
    out = {}
    for f in ("odi", "t20", "t20_league"):
        P = json.loads((STATS / f"players_{f}.json").read_text(encoding="utf-8"))
        for k, r in P.items():
            if r.get("cricinfo_id") and (r["matches"] >= min_matches or r["bowl"]["balls"] >= 120
                                         or r["bat"]["balls"] >= 200):
                out[k] = r["cricinfo_id"]
    afg = STATS / "afghanistan_players.json"
    if afg.exists():
        for p in json.loads(afg.read_text(encoding="utf-8")):
            if p.get("cricsheet_id") and p.get("cricinfo_id"):
                out[p["cricsheet_id"]] = p["cricinfo_id"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-matches", type=int, default=10)
    args = ap.parse_args(argv)

    want = candidates(args.min_matches)
    print(f"{len(want)} players to describe")
    by_ci: dict[str, list[dict]] = {}
    cis = sorted(set(want.values()))
    for i in range(0, len(cis), 400):
        rows = sparql_batch(cis[i:i + 400])
        print(f"  wikidata: {min(i + 400, len(cis))}/{len(cis)} ids", flush=True)
        for row in rows:
            by_ci.setdefault(row["cid"], []).append(row)

    title_of: dict[str, str] = {}
    dob_of: dict[str, str] = {}
    for cs, ci in want.items():
        rows = by_ci.get(ci, [])
        arts = sorted({r["article"] for r in rows if r.get("article")})
        dobs = sorted({r["dob"][:10] for r in rows if r.get("dob")})
        if len({r["item"] for r in rows}) == 1:  # ambiguous mappings are skipped rather than guessed
            if arts:
                title_of[cs] = requests.utils.unquote(arts[0].rsplit("/wiki/", 1)[1]).replace("_", " ")
            if dobs:
                dob_of[cs] = dobs[0]
    print(f"  {len(title_of)} have an English Wikipedia article")

    arts = pages(sorted(set(title_of.values())))
    out = {}
    for cs, ci in want.items():
        rec = {"cricinfo_id": ci, "wiki_title": title_of.get(cs), "dob": dob_of.get(cs),
               "bat_hand": None, "bowl": {"type": None, "kind": None, "arm": None}, "bowling_text": None,
               "role": None, "list_a": None, "t20": None, "first_class": None, "odi": None, "t20i": None}
        fb = infobox_fields(wikitext_of(arts.get(title_of.get(cs, ""))))
        if fb:
            rec["bat_hand"] = classify_batting(clean(fb.get("batting")))
            rec["bowling_text"] = clean(fb.get("bowling")) or None
            # classify the displayed text: "Right-arm [[Fast bowling|medium]]" is a medium pacer
            rec["bowl"] = classify_bowling(clean(re.sub(r"<br\s*/?>", "; ", fb.get("bowling", ""))))
            rec["role"] = clean(fb.get("role")) or None
            rec["list_a"] = wiki_career(fb, "List A")
            rec["t20"] = wiki_career(fb, "T20")
            rec["first_class"] = wiki_career(fb, "FC")
            rec["odi"] = wiki_career(fb, "ODI")    # needed to subtract ODIs from List A totals
            rec["t20i"] = wiki_career(fb, "T20I")
        out[cs] = rec
    (STATS / "styles.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    n_b = sum(1 for r in out.values() if r["bowl"]["type"])
    n_h = sum(1 for r in out.values() if r["bat_hand"])
    unk = sorted({r["bowling_text"] for r in out.values() if r["bowling_text"] and not r["bowl"]["type"]})
    print(f"styles.json: {len(out)} players, batting hand for {n_h}, bowling type for {n_b}")
    if unk:
        print(f"  unclassified bowling texts ({len(unk)}): {unk[:25]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
