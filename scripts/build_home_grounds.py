"""Primary home ground of every national side, per format (tournament mode plays home matches there).

    python scripts/build_home_grounds.py      -> data/home_grounds.json   (after engine/fit/fit_rain.py)

Home matches are those of bilateral tours ("Australia tour of India": India at home); a nation's home ground is
the ground where it has played most of them (spellings of a ground merged). Sides with no tours in the data fall
back to the grounds data/engine/rain_{fmt}.json gives their country (the full member that plays there most). One
ground per side.
Tests ("test": the first ground, "test_grounds": the grounds a home series rotates through): a host's grounds are
those data/engine/test_conditions.json gives it (engine/fit/fit_test_conditions.py), most Tests since RECENT
first, at most MAX_TEST_GROUNDS; a ground with no Test since then is left out when the host has others.
Franchise grounds are in data/league_seasons.json (scripts/build_league_presets.py).
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.conditions import venue_key  # noqa: E402
ZIPS = {"t20": "t20s_male_json.zip", "odi": "odis_male_json.zip"}
RECENT = 2019            # not fitted: "where a side plays its home Tests now" (Pakistan left the UAE in 2019)
MAX_TEST_GROUNDS = 6     # not fitted: a five-Test series visits five grounds


def test_grounds() -> dict:
    """host -> its Test grounds (full names as Cricsheet writes them), most used since RECENT first."""
    hosts = json.loads((ROOT / "data" / "engine" / "test_conditions.json").read_text(encoding="utf-8"))["hosts"]
    recent, total, names = Counter(), Counter(), {}
    with zipfile.ZipFile(ROOT / "data" / "raw" / "tests_male_json.zip") as zf:
        for n in zf.namelist():
            if not n.endswith(".json"):
                continue
            i = json.loads(zf.read(n))["info"]
            v = i.get("venue") or ""
            k = venue_key(v)
            if k not in hosts:
                continue
            names.setdefault(k, Counter())[v] += 1
            total[k] += 1
            recent[k] += int(i["dates"][0][:4]) >= RECENT
    out: dict = {}
    for k, host in hosts.items():
        if total[k]:
            out.setdefault(host, []).append(k)
    for host, ks in out.items():
        now = [k for k in ks if recent[k]] or ks
        now.sort(key=lambda k: (-recent[k], -total[k], k))
        out[host] = [names[k].most_common(1)[0][0] for k in now[:MAX_TEST_GROUNDS]]
    return dict(sorted(out.items()))


def main() -> int:
    out = {}
    for fmt, z in ZIPS.items():
        country = json.loads((ROOT / "data" / "engine" / f"rain_{fmt}.json").read_text(encoding="utf-8"))["venue_country"]
        toured: dict = {}                     # host -> Counter of ground keys (tour matches)
        played: dict = {}                     # fallback: matches in the country rain_*.json gives the ground
        names: dict = {}                      # ground key -> Counter of full venue strings
        with zipfile.ZipFile(ROOT / "data" / "raw" / z) as zf:
            for n in zf.namelist():
                if not n.endswith(".json"):
                    continue
                i = json.loads(zf.read(n))["info"]
                v = i.get("venue") or ""
                k = venue_key(v)
                names.setdefault(k, Counter())[v] += 1
                tour = re.search(r" tour of (.+)$", (i.get("event") or {}).get("name", ""))
                if tour and tour.group(1) in i.get("teams", []):
                    toured.setdefault(tour.group(1), Counter())[k] += 1
                host = country.get(v.split(",")[0])
                if host in i.get("teams", []):
                    played.setdefault(host, Counter())[k] += 1
        out[fmt] = {}
        for t in sorted(set(toured) | set(played)):
            k = (toured.get(t) or played[t]).most_common(1)[0][0]
            out[fmt][t] = names[k].most_common(1)[0][0]
        print(fmt, out[fmt])
    out["test_grounds"] = test_grounds()
    out["test"] = {t: g[0] for t, g in out["test_grounds"].items()}
    print("test", out["test_grounds"])
    (ROOT / "data" / "home_grounds.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
