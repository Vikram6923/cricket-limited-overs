"""Pre-2002 ODI players from Wikipedia (build-order step 6, last item).

Cricsheet's ODI ball-by-ball data starts around 2002, so players from 1971-2001 have no ball-by-ball record. This
script collects their ODI career totals from Wikipedia's "List of <nation> ODI cricketers" pages (first / last
year, matches, runs, batting average, balls, wickets, bowling average, catches, stumpings, keeper flag), links each
player to a Cricsheet ID where he also appears in Cricsheet (cricinfo ID via Wikidata P2697 -> people.csv), and
reads batting hand / bowling type from his article's infobox.

Players who also played after 2002 (Tendulkar, Lara, ...) get their **pre-Cricsheet part**: Wikipedia total minus
what Cricsheet has for them (data/raw_stats/players_odi.json), so year-range ratings before 2002 use only that.

Writes data/raw_stats/pre2002_players.json and a per-year scoring table data/raw_stats/years_odi_pre2002.json
(career totals spread evenly over each player's years, summed per year), used for era baselines.

    python scripts/build_pre2002.py          (first run fetches ~20 lists + ~2,000 articles, ~15 min; cached)
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from build_afghanistan import cell_value, cricinfo_id_in, sortname_title, split_top
from fetch_styles import classify_batting, classify_bowling
from wikiutil import claim_values, clean, infobox_fields, num, pages, wiki_wikitext, wikidata_entities, wikitext_of

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STATS = ROOT / "data" / "raw_stats"
NATIONS = ["Australia", "England", "India", "Pakistan", "New Zealand", "South Africa", "Sri Lanka", "West Indies",
           "Zimbabwe", "Bangladesh", "Kenya", "Canada", "Netherlands", "Scotland", "United Arab Emirates",
           "East Africa", "Namibia", "Ireland"]
CUTOFF = 2002          # players whose ODI career started before this year are collected


# ---------------------------------------------------------------- tables

def _attrs(cell: str) -> tuple[dict, str]:
    """('colspan=2 | Batting') -> ({'colspan': 2}, 'Batting')."""
    parts = split_top(cell, "|")
    attrs = {}
    if len(parts) > 1 and "[[" not in parts[0] and "{{" not in parts[0]:
        for k in ("rowspan", "colspan"):
            m = re.search(rf'{k}\s*=\s*"?(\d+)', parts[0])
            if m:
                attrs[k] = int(m.group(1))
        body = parts[-1]
    else:
        body = cell
    return attrs, body


def classify(label: str, seen: set) -> str | None:
    """Header cell (raw wikitext) -> our key. Runs / Avg: the first is batting, the second bowling."""
    raw = label.lower()
    txt = cell_value(label).lower().strip()
    if txt == "name":
        return "name"
    if "career" in txt or "span" in txt:
        return "career"
    if txt == "first":
        return "first"
    if txt == "last":
        return "last"
    if txt in ("mat", "matches", "m"):
        return "matches"
    if "innings" in raw or txt in ("inn", "inns"):
        return "inns"
    if "not out" in raw or txt == "no":
        return "not_outs"
    if "batting average" in raw:
        return "bat_avg"
    if "bowling average" in raw:
        return "bowl_avg"
    if txt in ("avg", "ave", "average"):
        return "bat_avg" if "bat_avg" not in seen else "bowl_avg"
    if "run (cricket)" in raw or txt == "runs":
        return "runs" if "runs" not in seen else "bowl_runs"
    if "delivery" in raw or "cricket ball" in raw or txt == "balls":
        return "balls"
    if "maiden" in raw or txt == "mdn":
        return "maidens"
    if ("wicket" in raw and "keeper" not in raw) or txt in ("wkt", "wkts", "wickets"):
        return "wkts"
    if "economy" in raw or txt == "econ":
        return "econ"
    if "caught" in raw or txt in ("ca", "ct"):
        return "catches"
    if "stump" in raw or txt == "st":
        return "stumpings"
    return None


def _header_keys(header_rows: list[list[str]]) -> list[str | None]:
    """Rebuild the header grid (rowspan / colspan) and classify the lowest label of each column."""
    grid: dict[tuple[int, int], str] = {}
    for r, cells in enumerate(header_rows):
        c = 0
        for cell in cells:
            while (r, c) in grid:
                c += 1
            a, body = _attrs(cell)
            for dr in range(a.get("rowspan", 1)):
                for dc in range(a.get("colspan", 1)):
                    grid[(r + dr, c + dc)] = body if a.get("colspan", 1) == 1 else ""
            c += a.get("colspan", 1)
    ncol = max((c for _, c in grid), default=-1) + 1
    keys, seen = [], set()
    for c in range(ncol):
        label = ""
        for r in range(len(header_rows) - 1, -1, -1):
            if grid.get((r, c)):
                label = grid[(r, c)]
                break
        k = classify(label, seen) if label else None
        if k:
            seen.add(k)
        keys.append(k)
    return keys


def parse_tables(wikitext: str) -> list[dict]:
    """All player rows from the page's wikitables that have Name and Mat columns."""
    out = []
    pos = 0
    while True:
        t0 = wikitext.find("{|", pos)
        if t0 < 0:
            break
        t1 = wikitext.find("\n|}", t0)
        if t1 < 0:
            break
        pos = t1 + 3
        table = wikitext[t0:t1]
        if "wikitable" not in table[:300]:
            continue
        header_rows, keys = [], None
        for row in re.split(r"\n\|-[^\n]*", table):
            lines = [ln.strip() for ln in row.split("\n")
                     if ln.strip() and not ln.strip().startswith(("{|", "|+"))]
            if not lines:
                continue
            cells = []
            for ln in lines:
                if ln[0] not in "|!":
                    continue
                sep = "!!" if ln[0] == "!" and "!!" in ln else "||"
                cells += split_top(ln[1:], sep)
            is_header = all(ln.startswith("!") for ln in lines) and not any("scope=\"row\"" in ln or "scope=row" in ln
                                                                          for ln in lines)
            if is_header and keys is None:
                header_rows.append(cells)
                continue
            if keys is None:
                keys = _header_keys(header_rows)
                if "name" not in keys or "matches" not in keys:
                    break
            rec = {}
            for k, c in zip(keys, cells):
                if not k:
                    continue
                if k == "name":
                    st = sortname_title(c)
                    if not st:
                        break
                    rec["name"], rec["title"] = st
                    rec["captain"] = "double-dagger" in c
                    rec["keeper"] = bool(re.search(r"\{\{\s*dagger\s*\}\}", c))
                else:
                    rec[k] = cell_value(c)
            if "title" in rec:
                rec["cricinfo_id"] = cricinfo_id_in(row)
                out.append(rec)
    return out


def _years(rec: dict) -> tuple[int | None, int | None]:
    if rec.get("career"):
        ys = [int(y) for y in re.findall(r"(?:19|20)\d\d", rec["career"])]
        if ys:
            return ys[0], ys[-1]
    f = re.findall(r"(?:19|20)\d\d", rec.get("first") or "")
    l_ = re.findall(r"(?:19|20)\d\d", rec.get("last") or "")
    f = int(f[0]) if f else None
    return f, (int(l_[0]) if l_ else f)


def _n(v) -> float | None:
    v = num(v) if isinstance(v, str) else v
    return None if v is None else float(v)


# ---------------------------------------------------------------- assembly

def load_register() -> dict[str, str]:
    """cricinfo id -> Cricsheet id."""
    out = {}
    with open(RAW / "people.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("key_cricinfo"):
                out[row["key_cricinfo"]] = row["identifier"]
    return out


def main(argv: list[str] | None = None) -> int:
    register = load_register()
    cs = json.loads((STATS / "players_odi.json").read_text(encoding="utf-8"))
    players: dict[str, dict] = {}
    for nation in NATIONS:
        rows = parse_tables(wiki_wikitext(f"List of {nation} ODI cricketers"))
        kept = 0
        for r in rows:
            first, last = _years(r)
            if not first or first >= CUTOFF:
                continue
            m = _n(r.get("matches"))
            runs, bavg = _n(r.get("runs")), _n(r.get("bat_avg"))
            balls, wkts, wavg = _n(r.get("balls")), _n(r.get("wkts")), _n(r.get("bowl_avg"))
            rec = {"name": r["name"], "title": r["title"], "nation": nation, "first": first, "last": last,
                   "matches": int(m or 0), "runs": runs, "bat_avg": bavg,
                   "outs": round(runs / bavg) if runs and bavg else (int(_n(r.get("inns")) or 0) - int(_n(r.get("not_outs")) or 0)
                                                                    if r.get("inns") else None),
                   "balls": balls, "wkts": wkts, "bowl_avg": wavg,
                   "runs_conceded": _n(r.get("bowl_runs")) or (wkts * wavg if wkts and wavg else None),
                   "catches": _n(r.get("catches")), "stumpings": _n(r.get("stumpings")),
                   "keeper": r.get("keeper") or (_n(r.get("stumpings")) or 0) > 0, "captain": r.get("captain"),
                   "cricinfo_id": r.get("cricinfo_id")}
            key = r["title"]
            if key in players:      # played for two nations (e.g. Kepler Wessels): keep both, count once each
                players[key].setdefault("also", []).append(rec)
                continue
            players[key] = rec
            kept += 1
        print(f"  {nation}: {len(rows)} rows, {kept} debuted before {CUTOFF}", flush=True)

    # articles: Wikidata QID -> cricinfo id; infobox -> styles
    titles = list(players)
    pg = pages(titles)
    qids = {t: ((pg.get(t) or {}).get("pageprops") or {}).get("wikibase_item") for t in titles}
    ents = wikidata_entities([q for q in qids.values() if q])
    linked = 0
    for t, p in players.items():
        ent = ents.get(qids.get(t) or "") or {}
        cids = [str(x) for x in claim_values(ent, "P2697")] if ent else []
        cid = p.get("cricinfo_id") or (cids[0] if cids else None)
        if cids and p.get("cricinfo_id") and p["cricinfo_id"] not in cids:
            cid = cids[0]          # list reference URLs are sometimes wrong; Wikidata wins
        p["cricinfo_id"] = cid
        p["cricsheet_id"] = register.get(cid) if cid else None
        p["id"] = p["cricsheet_id"] or (f"ci{cid}" if cid else "wp_" + re.sub(r"\W+", "_", t).strip("_").lower())
        linked += bool(p["cricsheet_id"])
        f = infobox_fields(wikitext_of(pg.get(t)))
        p["bat_hand"] = classify_batting(clean(f.get("batting")))
        bw = classify_bowling(clean(re.sub(r"<br\s*/?>", "; ", f.get("bowling", ""))))
        p["bowl_type"], p["bowl_kind"], p["bowl_arm"] = bw.get("type"), bw.get("kind"), bw.get("arm")
        # Cricsheet part (players who carried on past 2002): subtract to get the pre-Cricsheet career
        c = cs.get(p["cricsheet_id"]) if p["cricsheet_id"] else None
        if c:
            cb, cw = c["bat"], c["bowl"]
            p["cricsheet_part"] = {"matches": c["matches"], "runs": cb["runs"], "outs": cb.get("outs"),
                                   "balls": cw["balls"], "runs_conceded": cw["runs"], "wkts": cw["wkts"],
                                   "first": int(c["first"][:4])}
    pre = {}
    for p in players.values():
        q = dict(p)
        cp = p.get("cricsheet_part")
        if cp:
            def sub(a, b):
                return None if a is None else max(a - (b or 0), 0)
            q["matches"] = max(p["matches"] - cp["matches"], 0)
            q["runs"], q["outs"] = sub(p["runs"], cp["runs"]), sub(p["outs"], cp["outs"])
            q["balls"], q["wkts"] = sub(p["balls"], cp["balls"]), sub(p["wkts"], cp["wkts"])
            q["runs_conceded"] = sub(p["runs_conceded"], cp["runs_conceded"])
            q["last"] = min(p["last"], max(cp["first"] - 1, p["first"]))
        pre[p["id"]] = {k: v for k, v in q.items() if k not in ("also",)}
    STATS.mkdir(parents=True, exist_ok=True)
    (STATS / "pre2002_players.json").write_text(json.dumps(pre, ensure_ascii=False, indent=1), encoding="utf-8")

    # per-year scoring table: each player's pre-Cricsheet totals spread evenly over his years
    yr = defaultdict(lambda: {"runs": 0.0, "outs": 0.0, "balls": 0.0, "runs_conceded": 0.0, "wkts": 0.0,
                              "player_matches": 0.0})
    for q in pre.values():
        ys = list(range(q["first"], q["last"] + 1))
        if not ys:
            continue
        for y in ys:
            a = yr[y]
            a["player_matches"] += q["matches"] / len(ys)
            if q.get("runs") and q.get("outs"):
                a["runs"] += q["runs"] / len(ys)
                a["outs"] += q["outs"] / len(ys)
            if q.get("balls") and q.get("runs_conceded") is not None:
                a["balls"] += q["balls"] / len(ys)
                a["runs_conceded"] += q["runs_conceded"] / len(ys)
                a["wkts"] += (q.get("wkts") or 0) / len(ys)
    years = {}
    for y in sorted(yr):
        a = yr[y]
        years[str(y)] = {**{k: round(v, 1) for k, v in a.items()},
                         "bat_avg": round(a["runs"] / a["outs"], 2) if a["outs"] else None,
                         "rpo": round(6 * a["runs_conceded"] / a["balls"], 3) if a["balls"] else None,
                         "balls_per_wkt": round(a["balls"] / a["wkts"], 1) if a["wkts"] else None}
    (STATS / "years_odi_pre2002.json").write_text(json.dumps(years, indent=1), encoding="utf-8")
    print(f"pre-2002 ODI players: {len(pre)} ({linked} also in Cricsheet); years {min(years)}-{max(years)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
