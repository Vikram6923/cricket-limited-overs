"""Cached Wikipedia / Wikidata access and {{Infobox cricketer}} parsing, shared by the scripts.

Every response is cached on disk (data/raw/wikipedia/, data/raw/wikidata/) so rebuilds never re-download.
Requests are batched and spaced out because Wikipedia rate-limits (HTTP 429) quickly.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
WIKI_CACHE = ROOT / "data" / "raw" / "wikipedia"
WIKIDATA_CACHE = ROOT / "data" / "raw" / "wikidata"
API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
HEADERS = {"User-Agent": "cricket-limited-overs-sim/0.1 (personal research project)"}
PAUSE = 3.5  # seconds between live API calls
BATCH = 25
CACHE_VERSION = 2


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)


def _get(url: str, params: dict) -> dict:
    for attempt in range(6):
        r = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if r.status_code != 429:
            r.raise_for_status()
            time.sleep(PAUSE)
            return r.json()
        wait = int(r.headers.get("retry-after", 0) or 0) or 15 * (attempt + 1)
        print(f"  rate-limited, sleeping {wait}s", flush=True)
        time.sleep(wait)
    r.raise_for_status()
    return {}


def _page_path(title: str) -> Path:
    return WIKI_CACHE / (_safe(title) + ".json")


def pages(titles: list[str], refresh: bool = False) -> dict[str, dict | None]:
    """title -> page dict (formatversion 2, with wikitext and wikibase_item), or None if missing.

    Each page is cached as its own file, so partial runs resume where they stopped."""
    WIKI_CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict | None] = {}
    todo = []
    for t in dict.fromkeys(titles):
        p = _page_path(t)
        cached = json.loads(p.read_text(encoding="utf-8")) if p.exists() and not refresh else None
        # v2 cache files also hold pageprops (Wikidata QID); older ones are fetched again once.
        if cached and cached.get("v") == CACHE_VERSION:
            out[t] = _page_from_cache(cached)
        else:
            todo.append(t)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        print(f"  wikipedia: fetching {i + len(chunk)}/{len(todo)} pages", flush=True)
        data = _get(API, {"action": "query", "prop": "revisions|pageprops", "rvprop": "content|timestamp",
                          "rvslots": "main", "ppprop": "wikibase_item", "titles": "|".join(chunk),
                          "redirects": 1, "format": "json", "formatversion": 2})
        q = data.get("query", {})
        alias = {}
        for kind in ("normalized", "redirects"):
            for m in q.get(kind, []):
                alias[m["from"]] = m["to"]
        by_title = {pg["title"]: pg for pg in q.get("pages", [])}
        for t in chunk:
            final = t
            while final in alias:
                final = alias[final]
            pg = by_title.get(final)
            data_t = {"v": CACHE_VERSION, "query": {"pages": [pg] if pg else []}}
            _page_path(t).write_text(json.dumps(data_t, ensure_ascii=False), encoding="utf-8")
            out[t] = _page_from_cache(data_t)
    return out


def _page_from_cache(data: dict) -> dict | None:
    ps = data.get("query", {}).get("pages", [])
    if not ps or ps[0].get("missing") or "revisions" not in ps[0]:
        return None
    return ps[0]


def wikitext_of(page: dict | None) -> str:
    return page["revisions"][0]["slots"]["main"]["content"] if page else ""


def wiki_wikitext(title: str, refresh: bool = False) -> str:
    return wikitext_of(pages([title], refresh)[title])


def wikidata_entities(qids: list[str], refresh: bool = False) -> dict[str, dict]:
    """QID -> entity claims (cached per QID)."""
    WIKIDATA_CACHE.mkdir(parents=True, exist_ok=True)
    out, todo = {}, []
    for q in dict.fromkeys(q for q in qids if q):
        p = WIKIDATA_CACHE / f"{q}.json"
        if p.exists() and not refresh:
            out[q] = json.loads(p.read_text(encoding="utf-8"))
        else:
            todo.append(q)
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        print(f"  wikidata: fetching {i + len(chunk)}/{len(todo)} entities", flush=True)
        data = _get(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims|labels",
                                   "languages": "en", "format": "json"})
        for q, ent in data.get("entities", {}).items():
            (WIKIDATA_CACHE / f"{q}.json").write_text(json.dumps(ent, ensure_ascii=False), encoding="utf-8")
            out[q] = ent
    return out


def claim_values(entity: dict, prop: str) -> list:
    vals = []
    for c in entity.get("claims", {}).get(prop, []):
        dv = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(dv, dict) and "time" in dv:
            dv = dv["time"].lstrip("+")[:10]
        if dv is not None:
            vals.append(dv)
    return vals


def links(wikitext: str) -> list[str]:
    """Targets of [[wikilinks]] (no files/categories), in order of appearance."""
    out = []
    for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", wikitext):
        t = m.group(1).strip()
        if ":" in t or not t:
            continue
        out.append(t[0].upper() + t[1:])
    return list(dict.fromkeys(out))


def infobox_fields(text: str) -> dict[str, str]:
    """Top-level `| key = value` pairs of the first {{Infobox cricketer}}."""
    start = text.lower().find("{{infobox cricketer")
    if start < 0:
        return {}
    depth, i, body = 0, start, None
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                body = text[start + 2:i - 2]
                break
            continue
        i += 1
    if body is None:
        return {}
    parts, cur, d = [], "", 0
    j = 0
    while j < len(body):
        two = body[j:j + 2]
        if two in ("{{", "[["):
            d += 1
            cur += two
            j += 2
            continue
        if two in ("}}", "]]"):
            d -= 1
            cur += two
            j += 2
            continue
        if body[j] == "|" and d == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += body[j]
        j += 1
    parts.append(cur)
    out = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def clean(v: str | None) -> str:
    if not v:
        return ""
    v = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"\{\{\s*(?:nowrap|small)\s*\|([^{}]*)\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"<[^>]+>|&nbsp;|'''?", " ", v)
    return " ".join(v.split())


def wiki_career(fields: dict, column_name: str) -> dict | None:
    """Career-table column (e.g. 'ODI', 'T20I', 'List A', 'T20') as strings, or None if absent."""
    for n in range(1, 5):
        if clean(fields.get(f"column{n}")).upper() == column_name.upper():
            g = lambda k: clean(fields.get(f"{k}{n}"))
            return {"matches": g("matches"), "runs": g("runs"), "bat_avg": g("bat avg"),
                    "100s/50s": g("100s/50s"), "hs": g("top score"), "balls": g("deliveries"),
                    "wkts": g("wickets"), "bowl_avg": g("bowl avg"), "5w": g("fivefor"),
                    "best": g("best bowling"), "ct/st": g("catches/stumpings")}
    return None


def num(s: str | None) -> float | None:
    m = re.search(r"-?[\d,]+(?:\.\d+)?", s or "")
    return float(m.group().replace(",", "")) if m else None
