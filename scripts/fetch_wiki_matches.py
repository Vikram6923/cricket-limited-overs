"""ODI match summaries from Wikipedia: top scorers' runs (balls) and top bowlers' figures per innings.

    python scripts/fetch_wiki_matches.py      -> data/raw_stats/wiki_odi_innings.json

Wikipedia's competition categories ("International cricket competitions from 1991-92 to 1994") and season pages
("International cricket in 1998-99") give the tour / series pages; those (and World Cup pages) summarise each ODI with a {{Single-innings cricket match}} template:
    runs1 = [[Neil Fairbrother]] 47 (82)     wickets1 = [[Glenn McGrath]] 2/24 (10 overs)
So for most ODIs before Cricsheet (1971-2002) we get balls faced for the top one or two scorers of each innings.
That is a biased sample (top scorers), corrected in build_ratings against 2003-12 where Cricsheet has the truth.
Pages are cached by wikiutil (data/raw/wikipedia/), so re-runs don't re-download.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wikiutil as w  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw_stats" / "wiki_odi_innings.json"
FIRST, LAST = 1971, 2012          # 2003-12 overlaps Cricsheet: used to measure the top-scorer bias

ENTRY = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]\s*(\d+)\s*(\*|\[\[not out\|\*\]\]|&#42;)?\s*\((\d+)\)")
BOWL = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]\s*(\d+)\s*/\s*(\d+)\s*\((\d+(?:\.\d)?)\s*overs?\)")


def season_titles() -> list[str]:
    out = []
    for y in range(FIRST - 1, LAST + 1):
        out += [f"International cricket in {y}", f"International cricket in {y}–{str(y + 1)[-2:]}"]
    return out


def templates(text: str) -> list[str]:
    """Bodies of the one-day match summary templates (balanced braces): {{Single-innings cricket match}},
    {{Limited overs matches}}, {{Limited overs international}} - all with runs1/wickets1 fields."""
    out = []
    for m in re.finditer(r"\{\{\s*(?:Single-innings cricket match|Limited overs match(?:es)?|Limited overs international)",
                         text, re.I):
        depth, i = 0, m.start()
        while i < len(text):
            if text.startswith("{{", i):
                depth += 1
                i += 2
            elif text.startswith("}}", i):
                depth -= 1
                i += 2
                if depth == 0:
                    break
            else:
                i += 1
        out.append(text[m.start():i])
    return out


def field(t: str, name: str) -> str:
    m = re.search(r"\|\s*" + name + r"\s*=(.*?)(?=\n\s*\||\|\s*\w+\s*=|\Z)", t, re.S)
    return m.group(1).strip() if m else ""


def parse(t: str, page: str) -> dict | None:
    date = field(t, "date")
    year = re.search(r"(19[7-9]\d|20[01]\d)", date + " " + page)
    if not year:
        return None
    inns = []
    for k in ("1", "2"):
        bats = [{"title": a.strip(), "runs": int(r), "no": bool(no), "balls": int(b)}
                for a, r, no, b in ENTRY.findall(field(t, "runs" + k))]
        bowls = [{"title": a.strip(), "wkts": int(wk), "runs": int(r), "overs": float(o)}
                 for a, wk, r, o in BOWL.findall(field(t, "wickets" + k))]
        inns.append({"bat": bats, "bowl": bowls})
    ovs = [float(o) for k in ("1", "2") for o in re.findall(r"\((\d+(?:\.\d)?)\s*overs?\)", field(t, "score" + k))]
    report = re.search(r"/(\d{5,7})(?:\.html|/)", field(t, "report"))
    teams = sorted(re.sub(r"\{\{\s*cr[-a-z]*\s*\|\s*([A-Z]{2,4}).*", r"", field(t, "team" + k)).strip()[:4]
                   for k in ("1", "2"))
    day = re.search(r"(\d{1,2})\s*(January|February|March|April|May|June|July|August|September|October|November|December)",
                    date)
    return {"page": page, "year": int(year.group(1)), "date": date, "teams": teams,
            "day": f"{day.group(1)} {day.group(2)}" if day else None, "innings": inns, "overs": max(ovs) if ovs else None,
            "key": report.group(1) if report else None}


API = "https://en.wikipedia.org/w/api.php"
CACHE = ROOT / "data" / "raw" / "wikipedia_categories.json"


def category_pages() -> set[str]:
    """Articles in Wikipedia's "International cricket competitions from/in <period>" categories (+ one level of
    subcategories), cached."""
    if CACHE.exists():
        return set(json.loads(CACHE.read_text(encoding="utf-8")))
    cats = []
    for pre in ("International cricket competitions from", "International cricket competitions in"):
        d = w._get(API, {"action": "query", "list": "allcategories", "acprefix": pre, "aclimit": "500",
                         "format": "json"})
        for c in d["query"]["allcategories"]:
            ys = [int(y) for y in re.findall(r"(?:19|20)\d\d", c["*"])]
            if ys and FIRST - 1 <= max(ys) and min(ys) <= LAST:
                cats.append("Category:" + c["*"])
    titles, seen = set(), set()
    while cats:
        c = cats.pop()
        if c in seen:
            continue
        seen.add(c)
        d = w._get(API, {"action": "query", "list": "categorymembers", "cmtitle": c, "cmlimit": "500",
                         "cmtype": "page|subcat", "format": "json"})
        for m in d.get("query", {}).get("categorymembers", []):
            if m["ns"] == 14 and c.count(":") == 1 and len(seen) < 400:
                cats.append(m["title"])
            elif m["ns"] == 0:
                titles.add(m["title"])
    CACHE.write_text(json.dumps(sorted(titles), ensure_ascii=False), encoding="utf-8")
    return titles


def main() -> int:
    seasons = w.pages(season_titles())
    series = category_pages()
    print(f"{len(series)} pages from competition categories", flush=True)
    for t, pg in seasons.items():
        for l in w.links(w.wikitext_of(pg)):
            if re.search(r"(cricket team in|Series|Cup|Trophy|Tournament|Championship|Triangular|tri-series|"
                         r"Quadrangular|Sharjah|Asia Cup|World Series|Challenge|Classic)", l, re.I):
                series.add(l)
    print(f"{sum(1 for p in seasons.values() if p)} season pages, {len(series)} linked series/tour pages", flush=True)
    pages = w.pages(sorted(series))
    matches, seen = [], {}
    for t, pg in pages.items():
        if re.search(r"ICC Trophy|ACC Trophy|Intercontinental|women|A cricket team|A team|Under-1\d|U-?1\d|Youth|Emerging|Twenty20|T20", t, re.I):
            continue
        for tp in templates(w.wikitext_of(pg)):
            m = parse(tp, t)
            if not m or not (FIRST <= m["year"] <= LAST) or not any(i["bat"] for i in m["innings"]):
                continue
            if m["year"] >= 2003 and m["overs"] is not None and m["overs"] <= 20:
                continue                       # a T20 international (same template)
            k = ((m["year"], m["day"], tuple(m["teams"])) if m["day"] and all(m["teams"]) else
                 (m["year"], tuple(sorted((b["title"], b["runs"], b["balls"]) for i in m["innings"] for b in i["bat"]))))
            if k in seen:              # the same match on a tour page and a series page: merge the top scorers
                old = seen[k]
                have = {(b["title"], b["runs"]) for i in old["innings"] for b in i["bat"]}
                for i_old, i_new in zip(old["innings"], m["innings"]):
                    i_old["bat"] += [b for b in i_new["bat"] if (b["title"], b["runs"]) not in have]
                continue
            seen[k] = m
            matches.append(m)
    OUT.write_text(json.dumps(matches, ensure_ascii=False), encoding="utf-8")
    by = {}
    for m in matches:
        by[m["year"] // 5 * 5] = by.get(m["year"] // 5 * 5, 0) + 1
    print(f"{len(matches)} matches with top scorers -> {OUT}; by 5 years: {dict(sorted(by.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
