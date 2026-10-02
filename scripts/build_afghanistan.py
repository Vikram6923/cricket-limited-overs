"""Afghanistan players: identity, international career totals and franchise-league T20 record.

Cricsheet withholds every Afghanistan men's match, so these players have (almost) no ball-by-ball international
data. This script gathers what we can use instead for the ratings step:

  * who they are   - "List of Afghanistan ODI / Twenty20 International cricketers" on Wikipedia
  * Cricsheet ID   - ESPNcricinfo ID from each row's reference URL (fallback: Wikidata P2697) -> people.csv register
  * intl totals    - the list tables plus each player's {{Infobox cricketer}} (ODI, T20I, List A, T20 columns,
                     batting/bowling style, date of birth)
  * league record  - pointer to data/raw_stats/players_t20_league.json (ball-by-ball, with phase splits)

Reads   data/raw/people.csv, data/raw_stats/players_{t20,t20_league}.json, Wikipedia/Wikidata (cached)
Writes  data/raw_stats/afghanistan_players.json, data/raw_stats/afghanistan_players.csv

    python scripts/build_afghanistan.py            # uses cached Wikipedia pages where present
    python scripts/build_afghanistan.py --refresh  # re-fetch the Wikipedia/Wikidata pages
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from wikiutil import claim_values, clean, infobox_fields, num, pages, wiki_career, wikidata_entities, wikitext_of

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STATS = ROOT / "data" / "raw_stats"

LISTS = {
    "odi": "List of Afghanistan ODI cricketers",
    "t20i": "List of Afghanistan Twenty20 International cricketers",
}
INFOBOX_COLUMNS = {"odi": "ODI", "t20i": "T20I", "list_a": "List A", "t20": "T20"}
# Wikipedia list-table header -> our key
HEADER_KEYS = {"no.": "cap", "cap": "cap", "name": "name", "first": "first", "last": "last", "mat": "matches",
               "inn": "inns", "no": "not_outs", "runs": "runs", "hs": "hs", "avg": "bat_avg", "50": "fifties",
               "100": "hundreds", "balls": "balls", "wkt": "wkts", "bbi": "best", "ave": "bowl_avg", "5wi": "five_w",
               "ca": "catches", "st": "stumpings"}


# ---------------------------------------------------------------- wikitext table parsing

def split_top(s: str, sep: str) -> list[str]:
    """Split at `sep` only outside {{ }} and [[ ]]."""
    out, cur, d, i = [], "", 0, 0
    while i < len(s):
        two = s[i:i + 2]
        if two in ("{{", "[["):
            d += 1
            cur += two
            i += 2
        elif two in ("}}", "]]"):
            d = max(0, d - 1)
            cur += two
            i += 2
        elif d == 0 and s.startswith(sep, i):
            out.append(cur)
            cur = ""
            i += len(sep)
        else:
            cur += s[i]
            i += 1
    out.append(cur)
    return out


def cell_value(c: str) -> str:
    # Drop a leading attribute block ("scope=row | value", 'style="..." | value').
    parts = split_top(c, "|")
    if len(parts) > 1 and "=" in parts[0] and "{{" not in parts[0] and "[[" not in parts[0]:
        c = parts[-1]
    c = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", c, flags=re.S)
    c = re.sub(r"<span[^>]*display:\s*none[^>]*>.*?</span>", "", c, flags=re.S)
    c = re.sub(r"\{\{\s*sort\s*\|[^|{}]*\|([^{}]*)\}\}", r"\1", c, flags=re.I)
    c = re.sub(r"\{\{\s*(?:nts|ntsh)\s*\|([^{}]*)\}\}", r"\1", c, flags=re.I)
    c = re.sub(r"\{\{\s*(?:double-dagger|dagger)\s*\}\}", "", c, flags=re.I)
    return clean(c).replace("–", "").strip()


def sortname_title(c: str) -> tuple[str, str] | None:
    """{{sortname|First|Last|Link|...}} -> (display name, article title)."""
    m = re.search(r"\{\{\s*sortname\s*\|([^{}]*)\}\}", c, flags=re.I)
    if m:
        args = [a.strip() for a in m.group(1).split("|")]
        pos = [a for a in args if "=" not in a]
        named = dict(a.split("=", 1) for a in args if "=" in a)
        first, last = (pos + ["", ""])[:2]
        display = " ".join(x for x in (first, last) if x)
        link = pos[2] if len(pos) > 2 and pos[2] else display
        if named.get("dab", "").strip():  # {{sortname||Zahir Khan|dab=Afghan cricketer}}
            link = f"{link} ({named['dab'].strip()})"
        return display, link
    m = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", c)
    if m:
        return (m.group(2) or m.group(1)).strip(), m.group(1).strip()
    return None


def cricinfo_id_in(s: str) -> str | None:
    for url in re.findall(r"https?://[^\s|}\]]*espncricinfo\.com[^\s|}\]]*", s):
        m = re.search(r"/player/(\d+)\.html", url) or re.search(r"/cricketers/[a-z0-9-]*?-(\d+)(?:[/?#]|$)", url)
        if m:
            return m.group(1)
    return None


def parse_list_table(wikitext: str) -> list[dict]:
    """Rows of the "Players" table: one dict per player with HEADER_KEYS fields + title + cricinfo id."""
    start = wikitext.find("==Players==")
    if start < 0:
        start = 0
    t0 = wikitext.find("{|", start)
    t1 = wikitext.find("\n|}", t0)
    table = wikitext[t0:t1]
    rows = re.split(r"\n\|-[^\n]*", table)
    headers: list[str] = []
    out = []
    for row in rows:
        cells = []
        lines = [ln for ln in row.split("\n") if ln.strip()]
        header_row = all(ln.lstrip().startswith("!") for ln in lines) and lines
        for ln in lines:
            ln = ln.strip()
            if not ln or ln[0] not in "|!" or ln.startswith("{|"):
                continue
            sep = "!!" if ln[0] == "!" and "!!" in ln else "||"
            cells += split_top(ln[1:], sep)
        if header_row:
            labels = [cell_value(c).lower() for c in cells]
            if "name" in labels:
                headers = labels
            continue
        if not headers or len(cells) < len(headers) - 1:
            continue
        rec: dict = {}
        for h, c in zip(headers, cells):
            key = HEADER_KEYS.get(h)
            if key == "name":
                st = sortname_title(c)
                if not st:
                    break
                rec["name"], rec["title"] = st
                rec["captain"] = "double-dagger" in c
                rec["keeper"] = bool(re.search(r"\{\{\s*dagger\s*\}\}", c))
            elif key:
                rec[key] = cell_value(c)
        if "title" not in rec:
            continue
        rec["cricinfo_id"] = cricinfo_id_in(row)
        out.append(rec)
    return out


# ---------------------------------------------------------------- assembly

def load_register() -> dict[str, tuple[str, str]]:
    """ESPNcricinfo ID -> (Cricsheet identifier, Cricsheet unique_name), from any of the three cricinfo columns."""
    m = {}
    with open(RAW / "people.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            for k in ("key_cricinfo", "key_cricinfo_2", "key_cricinfo_3"):
                if r.get(k):
                    m.setdefault(r[k], (r["identifier"], r["unique_name"]))
    return m


def name_tokens(s: str) -> set[str]:
    s = re.sub(r"\(.*?\)", "", s.lower()).replace("-", " ")
    return {t for t in re.findall(r"[a-z]+", s) if len(t) > 1}


def resolve_cricinfo_id(name: str, sources: dict[str, list[str]], register: dict) -> tuple[str | None, bool]:
    """Pick the cricinfo ID from the list rows + Wikidata. The Wikipedia list tables contain some copy-paste
    errors (a row's reference URL pointing at a team-mate), so: one vote per source, plus a strong bonus when the
    Cricsheet register's name for that ID shares a name token with the player. Returns (id, had_conflict)."""
    votes: dict[str, float] = {}
    for ids in sources.values():
        for i in dict.fromkeys(ids):
            votes[i] = votes.get(i, 0) + 1
    if not votes:
        return None, False
    want = name_tokens(name)
    for i in votes:
        if i in register and want & name_tokens(register[i][1]):
            votes[i] += 2
    best = max(votes, key=lambda i: votes[i])
    return best, len(votes) > 1


def summary(rec: dict | None) -> dict | None:
    if not rec:
        return None
    b, w = rec["bat"], rec["bowl"]
    return {"matches": rec["matches"], "first": rec["first"], "last": rec["last"],
            "runs": b["runs"], "balls_faced": b["balls"], "bat_avg": b["avg"], "bat_sr": b["sr"],
            "balls_bowled": w["balls"], "wkts": w["wkts"], "bowl_avg": w["avg"], "econ": w["econ"],
            "leagues": {k: v["m"] for k, v in rec.get("by_league", {}).items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-fetch Wikipedia/Wikidata pages")
    args = ap.parse_args(argv)

    league_path = STATS / "players_t20_league.json"
    if not league_path.exists():
        print("run scripts/build_raw_stats.py first", file=sys.stderr)
        return 1
    league = json.loads(league_path.read_text(encoding="utf-8"))
    t20i = json.loads((STATS / "players_t20.json").read_text(encoding="utf-8"))
    odi = json.loads((STATS / "players_odi.json").read_text(encoding="utf-8"))
    ci_to_cs = load_register()

    # 1. who: union of the two list pages, keyed by article title
    players: dict[str, dict] = {}
    list_pages = pages(list(LISTS.values()), args.refresh)
    for fmt, title in LISTS.items():
        rows = parse_list_table(wikitext_of(list_pages[title]))
        print(f"{title}: {len(rows)} players")
        for r in rows:
            p = players.setdefault(r["title"], {"name": r["name"], "wiki_title": r["title"], "cricinfo_id": None,
                                                "captain": False, "keeper": False, "lists": {}, "id_sources": {}})
            ci = r.pop("cricinfo_id")
            if ci:
                p["id_sources"][f"{fmt}_list"] = [ci]
            p["captain"] |= r.pop("captain")
            p["keeper"] |= r.pop("keeper")
            for k in ("name", "title"):
                r.pop(k, None)
            p["lists"][fmt] = r

    # 2. player articles: infobox career tables, styles, DOB, Wikidata QID
    arts = pages(list(players), args.refresh)
    for title, p in players.items():
        pg = arts.get(title)
        fb = infobox_fields(wikitext_of(pg))
        p["wikidata"] = (pg or {}).get("pageprops", {}).get("wikibase_item")
        p["full_name"] = clean(fb.get("fullname")) or None
        p["batting_style"] = clean(fb.get("batting")) or None
        p["bowling_style"] = clean(fb.get("bowling")) or None
        p["role"] = clean(fb.get("role")) or None
        p["infobox_as_of"] = clean(fb.get("date")) or None
        p["infobox"] = {k: wiki_career(fb, col) for k, col in INFOBOX_COLUMNS.items()}
        if not pg:
            print(f"  no Wikipedia article for {title!r}")

    # 3. Wikidata: DOB and a third opinion on the cricinfo ID
    ents = wikidata_entities([p["wikidata"] for p in players.values() if p["wikidata"]], args.refresh)
    for p in players.values():
        ent = ents.get(p["wikidata"] or "", {})
        ids = [str(i) for i in claim_values(ent, "P2697")]
        if ids:
            p["id_sources"]["wikidata"] = ids
        p["cricinfo_id"], conflict = resolve_cricinfo_id(p["name"], p["id_sources"], ci_to_cs)
        if conflict:
            print(f"  {p['name']}: sources disagree {p['id_sources']} -> using {p['cricinfo_id']} "
                  f"({ci_to_cs.get(p['cricinfo_id'], ('', '?'))[1]})")
        p["id_conflict"] = conflict
        if p["cricinfo_id"] and ids and p["cricinfo_id"] not in ids:
            # The list links to a different person's article (e.g. a namesake): don't trust its infobox.
            print(f"  {p['wiki_title']!r}: article is cricinfo {ids}, list row says {p['cricinfo_id']}; "
                  f"ignoring the article")
            p["infobox"] = {k: None for k in INFOBOX_COLUMNS}
            p["batting_style"] = p["bowling_style"] = p["role"] = p["full_name"] = None
            p["dob"] = None
            continue
        dob = claim_values(ent, "P569")
        p["dob"] = dob[0] if dob else None

    # The two lists sometimes spell/link the same man differently ("Nangialai Kharoti" / "Nangeyalia Kharote"):
    # merge entries that resolved to the same cricinfo ID, keeping the one with the richer Wikipedia article.
    merged: dict[str, dict] = {}
    for key, p in list(players.items()):
        ci = p["cricinfo_id"] or key
        if ci not in merged:
            merged[ci] = p
            continue
        a, b = merged[ci], p
        if sum(v is not None for v in b["infobox"].values()) > sum(v is not None for v in a["infobox"].values()):
            a, b = b, a
        a["lists"] = {**b["lists"], **a["lists"]}
        a["aliases"] = sorted({*a.get("aliases", []), b["name"], b["wiki_title"]} - {a["name"], a["wiki_title"]})
        a["captain"] |= b["captain"]
        a["keeper"] |= b["keeper"]
        merged[ci] = a

    # 4. join to Cricsheet and attach the league record
    out = []
    for p in merged.values():
        cs, cs_name = ci_to_cs.get(p["cricinfo_id"] or "", (None, None))
        p["cricsheet_id"], p["cricsheet_name"] = cs, cs_name
        p["league_t20"] = summary(league.get(cs))
        # Non-Afghanistan international appearances that Cricsheet does have (e.g. World XI games)
        p["cricsheet_t20i"] = summary(t20i.get(cs))
        p["cricsheet_odi"] = summary(odi.get(cs))
        out.append(p)

    def caps(p):
        return max(num((p["lists"].get(f) or {}).get("matches")) or 0 for f in LISTS)
    out.sort(key=lambda p: -caps(p))

    STATS.mkdir(parents=True, exist_ok=True)
    (STATS / "afghanistan_players.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    write_csv(out, STATS / "afghanistan_players.csv")

    linked = sum(1 for p in out if p["cricsheet_id"])
    with_league = [p for p in out if p["league_t20"]]
    print(f"{len(out)} Afghanistan players; {linked} linked to Cricsheet; {len(with_league)} with franchise-league "
          f"T20 data ({sum(p['league_t20']['matches'] for p in with_league)} matches)")
    unlinked = [p["name"] for p in out if not p["cricsheet_id"]]
    if unlinked:
        print(f"  not in Cricsheet register: {', '.join(unlinked)}")
    return 0


def write_csv(players: list[dict], path: Path) -> None:
    cols = ["name", "wiki_title", "cricinfo_id", "cricsheet_id", "dob", "batting_style", "bowling_style", "role",
            "odi_mat", "odi_runs", "odi_bat_avg", "odi_wkts", "odi_bowl_avg",
            "t20i_mat", "t20i_runs", "t20i_bat_avg", "t20i_wkts", "t20i_bowl_avg",
            "league_mat", "league_runs", "league_sr", "league_wkts", "league_econ", "leagues"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in players:
            row = [p["name"], p["wiki_title"], p["cricinfo_id"], p["cricsheet_id"], p["dob"], p["batting_style"],
                   p["bowling_style"], p["role"]]
            for fmt in ("odi", "t20i"):
                c = p["infobox"].get(fmt) or {}
                lst = p["lists"].get(fmt) or {}
                row += [c.get("matches") or lst.get("matches"), c.get("runs") or lst.get("runs"),
                        c.get("bat_avg") or lst.get("bat_avg"), c.get("wkts") or lst.get("wkts"),
                        c.get("bowl_avg") or lst.get("bowl_avg")]
            lg = p["league_t20"] or {}
            row += [lg.get("matches"), lg.get("runs"), lg.get("bat_sr"), lg.get("wkts"), lg.get("econ"),
                    " ".join(f"{k}:{v}" for k, v in (lg.get("leagues") or {}).items())]
            w.writerow(row)


if __name__ == "__main__":
    sys.exit(main())
