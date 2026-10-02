"""Build per-player raw career stats for ODI, T20I and franchise T20 leagues from the cached Cricsheet zips.

Reads   data/raw/odis_male_json.zip, data/raw/t20s_male_json.zip, data/raw/leagues/*.zip, data/raw/people.csv
Writes  data/raw_stats/players_<fmt>.json   full records (overall, by phase, by year, positions;
                                            t20_league also has by_league)
        data/raw_stats/players_<fmt>.csv    headline numbers, one row per player
        data/raw_stats/coverage_<fmt>.json  which official match numbers Cricsheet has / lacks
        data/raw_stats/years_<fmt>.json     scoring by calendar year (for era adjustment later)

Pure function of the raw files, so it is safe to re-run any time:

    python scripts/build_raw_stats.py            # all formats (odi, t20, t20_league)
    python scripts/build_raw_stats.py --format t20
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "raw_stats"

FORMATS = {
    "odi": {"zip": "odis_male_json.zip", "overs": 50, "missing_section": "Odi Matches",
            # 0-based over index -> phase. ODI: 1-10, 11-40, 41-50.
            "phases": (("powerplay", 0, 9), ("middle", 10, 39), ("death", 40, 49))},
    "t20": {"zip": "t20s_male_json.zip", "overs": 20, "missing_section": "T20 Matches",
            # T20: 1-6, 7-15, 16-20.
            "phases": (("powerplay", 0, 5), ("middle", 6, 14), ("death", 15, 19))},
    # Franchise/domestic T20 leagues pooled into one record per player, with a by_league split so league
    # strength can be weighted later. Codes match fetch_cricsheet.LEAGUES.
    "t20_league": {"zips": [f"leagues/{c}_json.zip" for c in
                            ("ipl", "bbl", "psl", "cpl", "sat", "ilt", "bpl", "lpl", "mlc", "ntb", "ssm")],
                   "overs": 20, "missing_section": None,
                   "phases": (("powerplay", 0, 5), ("middle", 6, 14), ("death", 15, 19))},
}

# Dismissals credited to the bowler. Everything else (run out, retired out, obstructing...) is not.
BOWLER_WICKETS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
# Not a dismissal at all: the batter is "not out" for average purposes.
NOT_OUT_KINDS = {"retired hurt", "retired not out"}


def phase_of(over: int, phases) -> str:
    for name, lo, hi in phases:
        if lo <= over <= hi:
            return name
    return phases[-1][0]  # anything past the scheduled overs (shouldn't happen) counts as death


def new_bat() -> dict:
    return {"runs": 0, "balls": 0, "outs": 0, "fours": 0, "sixes": 0, "dots": 0}


def new_bowl() -> dict:
    return {"balls": 0, "runs": 0, "wkts": 0, "dots": 0, "fours": 0, "sixes": 0, "wides": 0, "noballs": 0}


def new_player(pid: str, name: str, phases) -> dict:
    return {
        "id": pid, "name": name, "teams": Counter(),
        "first": None, "last": None, "matches": 0,
        "bat": {**new_bat(), "inns": 0, "not_outs": 0, "hs": 0, "hs_not_out": False,
                "fifties": 0, "hundreds": 0, "ducks": 0, "dismissals": Counter()},
        "bowl": {**new_bowl(), "inns": 0, "maidens": 0, "four_w": 0, "five_w": 0,
                 "best": None},  # best = [wkts, runs]
        "field": {"catches": 0, "stumpings": 0, "run_outs": 0},
        "positions": Counter(),
        "bat_phase": {p[0]: new_bat() for p in phases},
        "bowl_phase": {p[0]: new_bowl() for p in phases},
        "by_year": defaultdict(lambda: {"m": 0, "bat": new_bat(), "bowl": new_bowl()}),
        "by_league": defaultdict(lambda: {"m": 0, "bat": new_bat(), "bowl": new_bowl()}),
    }


def is_boundary(d: dict, n: int) -> bool:
    return d["runs"]["batter"] == n and not d["runs"].get("non_boundary")


def process_match(m: dict, fmt: dict, players: dict, years: dict, comp: str) -> None:
    info = m["info"]
    reg = info["registry"]["people"]
    year = info["dates"][0][:4]
    date = info["dates"][0]
    phases = fmt["phases"]

    def P(name: str) -> dict:
        pid = reg[name]
        if pid not in players:
            players[pid] = new_player(pid, name, phases)
        return players[pid]

    # Appearances: everyone named in the XIs, plus anyone who came on as a replacement.
    appeared: dict[str, str] = {}
    for team, names in info["players"].items():
        for n in names:
            appeared[n] = team
    for inn in m.get("innings", []):
        for kind in inn.get("replacements", {}).get("match", []) or []:
            appeared.setdefault(kind["in"], kind["team"])
    for n, team in appeared.items():
        p = P(n)
        p["matches"] += 1
        p["teams"][team] += 1
        p["by_year"][year]["m"] += 1
        p["by_league"][comp]["m"] += 1
        p["first"] = min(p["first"] or date, date)
        p["last"] = max(p["last"] or date, date)

    y = years.setdefault(year, {"matches": 0, "inns": 0, "runs": 0, "balls": 0, "wkts": 0,
                                "first_inns_n": 0, "first_inns_runs": 0, "first_inns_complete": 0})
    y["matches"] += 1

    for idx, inn in enumerate(m.get("innings", [])):
        if inn.get("super_over"):
            continue
        order: list[str] = []         # batting order by first appearance at the crease
        inn_bat: dict[str, dict] = {}  # name -> runs/balls/out this innings
        inn_bowl: dict[str, dict] = {}
        total = wkts = legal = 0

        def arrive(name: str) -> None:
            if name not in inn_bat:
                order.append(name)
                inn_bat[name] = {"runs": 0, "balls": 0, "out": False}

        for ov in inn.get("overs", []):
            over_no = ov["over"]
            ph = phase_of(over_no, phases)
            over_bowlers = set()
            over_conceded = 0
            over_legal = 0
            for d in ov["deliveries"]:
                bat, bwl = d["batter"], d["bowler"]
                arrive(bat)
                arrive(d["non_striker"])
                ex = d.get("extras", {})
                wide = "wides" in ex
                nb = "noballs" in ex
                br = d["runs"]["batter"]
                conceded = br + ex.get("wides", 0) + ex.get("noballs", 0)
                total += d["runs"]["total"]
                over_bowlers.add(bwl)
                over_conceded += conceded

                pb, pw = P(bat), P(bwl)
                bp, wp = pb["bat_phase"][ph], pw["bowl_phase"][ph]
                by_b, by_w = pb["by_year"][year]["bat"], pw["by_year"][year]["bowl"]
                cb, cw = pb["by_league"][comp]["bat"], pw["by_league"][comp]["bowl"]
                bw = inn_bowl.setdefault(bwl, {"balls": 0, "runs": 0, "wkts": 0})

                # --- batter ---
                if not wide:
                    for s in (pb["bat"], bp, by_b, cb):
                        s["balls"] += 1
                        s["runs"] += br
                        if br == 0:
                            s["dots"] += 1
                    inn_bat[bat]["balls"] += 1
                else:
                    for s in (pb["bat"], bp, by_b, cb):
                        s["runs"] += br  # always 0 in practice
                inn_bat[bat]["runs"] += br
                if is_boundary(d, 4):
                    for s in (pb["bat"], bp, wp, pw["bowl"]):
                        s["fours"] += 1
                if is_boundary(d, 6):
                    for s in (pb["bat"], bp, wp, pw["bowl"]):
                        s["sixes"] += 1

                # --- bowler ---
                legal_ball = not wide and not nb
                for s in (pw["bowl"], wp, by_w, cw):
                    s["runs"] += conceded
                    if legal_ball:
                        s["balls"] += 1
                        if d["runs"]["total"] == 0:
                            s["dots"] += 1
                if wide:
                    pw["bowl"]["wides"] += 1
                    wp["wides"] += 1
                if nb:
                    pw["bowl"]["noballs"] += 1
                    wp["noballs"] += 1
                bw["runs"] += conceded
                if legal_ball:
                    bw["balls"] += 1
                    legal += 1
                    over_legal += 1

                # --- wickets ---
                for w in d.get("wickets", []):
                    kind = w["kind"]
                    out = w["player_out"]
                    arrive(out)
                    po = P(out)
                    if kind not in NOT_OUT_KINDS:
                        inn_bat[out]["out"] = True
                        po["bat"]["dismissals"][kind] += 1
                        po["bat"]["outs"] += 1
                        wkts += 1
                        # phase/year dismissal belongs to the batter who was out, in this phase
                        po["bat_phase"][ph]["outs"] += 1
                        po["by_year"][year]["bat"]["outs"] += 1
                        po["by_league"][comp]["bat"]["outs"] += 1
                    if kind in BOWLER_WICKETS:
                        for s in (pw["bowl"], wp, by_w, cw):
                            s["wkts"] += 1
                        bw["wkts"] += 1
                    for f in w.get("fielders", []):
                        if f.get("substitute") or "name" not in f or f["name"] not in reg:
                            continue
                        pf = P(f["name"])
                        if kind == "caught":
                            pf["field"]["catches"] += 1
                        elif kind == "stumped":
                            pf["field"]["stumpings"] += 1
                        elif kind == "run out":
                            pf["field"]["run_outs"] += 1
                    if kind == "caught and bowled":
                        pw["field"]["catches"] += 1
            if len(over_bowlers) == 1 and over_legal >= 6 and over_conceded == 0:
                P(next(iter(over_bowlers)))["bowl"]["maidens"] += 1

        # --- close the innings: per-innings batting and bowling figures ---
        for pos, name in enumerate(order, start=1):
            st = inn_bat[name]
            b = P(name)["bat"]
            b["inns"] += 1
            P(name)["positions"][pos] += 1
            if not st["out"]:
                b["not_outs"] += 1
            r = st["runs"]
            if r > b["hs"] or (r == b["hs"] and not st["out"]):
                b["hs"], b["hs_not_out"] = r, not st["out"]
            if r >= 100:
                b["hundreds"] += 1
            elif r >= 50:
                b["fifties"] += 1
            if r == 0 and st["out"]:
                b["ducks"] += 1
        for name, st in inn_bowl.items():
            b = P(name)["bowl"]
            b["inns"] += 1
            if st["wkts"] >= 5:
                b["five_w"] += 1
            elif st["wkts"] >= 4:
                b["four_w"] += 1
            fig = [st["wkts"], st["runs"]]
            if b["best"] is None or (fig[0], -fig[1]) > (b["best"][0], -b["best"][1]):
                b["best"] = fig

        y["inns"] += 1
        y["runs"] += total
        y["balls"] += legal
        y["wkts"] += wkts
        if idx == 0:
            y["first_inns_n"] += 1
            y["first_inns_runs"] += total
            # "complete" = all out or batted the full allocation; excludes rain-shortened innings
            if wkts >= 10 or legal >= fmt["overs"] * 6:
                y["first_inns_complete"] += 1
                y.setdefault("first_inns_complete_runs", 0)
                y["first_inns_complete_runs"] += total


def finalise(p: dict) -> dict:
    """Convert Counters/defaultdicts to plain JSON and add derived rates."""
    b, w = p["bat"], p["bowl"]
    out = {
        "id": p["id"], "name": p["name"],
        "team": p["teams"].most_common(1)[0][0] if p["teams"] else None,
        "teams": dict(p["teams"]), "first": p["first"], "last": p["last"], "matches": p["matches"],
        "bat": {**b, "dismissals": dict(b["dismissals"])},
        "bowl": dict(w),
        "field": p["field"],
        "positions": {str(k): v for k, v in sorted(p["positions"].items())},
        "bat_phase": p["bat_phase"], "bowl_phase": p["bowl_phase"],
        "by_year": dict(sorted(p["by_year"].items())),
    }
    if len(p["by_league"]) > 1 or "intl" not in p["by_league"]:
        out["by_league"] = dict(p["by_league"])
        for s in out["by_league"].values():
            add_bat_rates(s["bat"])
            add_bowl_rates(s["bowl"])
    add_bat_rates(out["bat"])
    add_bowl_rates(out["bowl"])
    for s in out["bat_phase"].values():
        add_bat_rates(s)
    for s in out["bowl_phase"].values():
        add_bowl_rates(s)
    pos = p["positions"]
    out["usual_position"] = (sum(k * v for k, v in pos.items()) / sum(pos.values())) if pos else None
    return out


def rnd(x, n=2):
    return None if x is None else round(x, n)


def add_bat_rates(s: dict) -> None:
    s["avg"] = rnd(s["runs"] / s["outs"]) if s["outs"] else None
    s["sr"] = rnd(100 * s["runs"] / s["balls"]) if s["balls"] else None
    s["boundary_pct"] = rnd(100 * (s["fours"] + s["sixes"]) / s["balls"]) if s["balls"] else None
    s["dot_pct"] = rnd(100 * s["dots"] / s["balls"]) if s["balls"] else None


def add_bowl_rates(s: dict) -> None:
    s["avg"] = rnd(s["runs"] / s["wkts"]) if s["wkts"] else None
    s["econ"] = rnd(6 * s["runs"] / s["balls"]) if s["balls"] else None
    s["sr"] = rnd(s["balls"] / s["wkts"]) if s["wkts"] else None
    s["dot_pct"] = rnd(100 * s["dots"] / s["balls"]) if s["balls"] else None


def load_register() -> dict[str, dict]:
    with open(RAW / "people.csv", encoding="utf-8", newline="") as f:
        return {r["identifier"]: r for r in csv.DictReader(f)}


def build(fmt_key: str, register: dict) -> None:
    fmt = FORMATS[fmt_key]
    players: dict[str, dict] = {}
    comp_years: dict[str, dict] = {}  # competition -> year -> scoring totals
    numbers: dict[int, str] = {}
    skipped = Counter()
    n_matches = 0

    zips = fmt.get("zips") or [fmt["zip"]]
    absent = [zn for zn in zips if not (RAW / zn).exists()]
    if absent:
        print(f"  {fmt_key}: skipping missing {absent} (run fetch_cricsheet.py)", file=sys.stderr)
    for zn in zips:
        if zn in absent:
            continue
        comp = Path(zn).name.split("_json")[0] if fmt.get("zips") else "intl"
        years = comp_years.setdefault(comp, {})
        with zipfile.ZipFile(RAW / zn) as z:
            names = sorted(n for n in z.namelist() if n.endswith(".json"))
            for n in names:
                m = json.loads(z.read(n).decode("utf-8"))
                info = m["info"]
                if info.get("gender") != "male":
                    skipped["not male"] += 1
                    continue
                if info.get("balls_per_over", 6) != 6:
                    skipped["not 6-ball overs"] += 1
                    continue
                process_match(m, fmt, players, years, comp)
                n_matches += 1
                num = info.get("match_type_number")
                if num:
                    numbers[num] = info["dates"][0]

    recs = {}
    for pid, p in players.items():
        r = finalise(p)
        reg = register.get(pid, {})
        r["unique_name"] = reg.get("unique_name") or r["name"]
        r["cricinfo_id"] = reg.get("key_cricinfo") or None
        recs[pid] = r

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"players_{fmt_key}.json", "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, separators=(",", ":"))
    write_csv(recs, OUT / f"players_{fmt_key}.csv", fmt["phases"])

    pooled: dict[str, dict] = {}
    for years in comp_years.values():
        for yr, y in years.items():
            t = pooled.setdefault(yr, Counter())
            t.update(y)
    out_years = {"all": {yr: year_rates(dict(t)) for yr, t in sorted(pooled.items())}}
    if fmt.get("zips"):
        out_years.update({c: {yr: year_rates(y) for yr, y in sorted(ys.items())} for c, ys in comp_years.items()})
    with open(OUT / f"years_{fmt_key}.json", "w", encoding="utf-8") as f:
        json.dump(out_years if fmt.get("zips") else out_years["all"], f, indent=1)

    print(f"{fmt_key}: {n_matches} matches, {len(recs)} players, skipped {dict(skipped) or 'none'}")
    if fmt.get("missing_section") is not None and numbers:
        cov = coverage(numbers, listed_missing(fmt["missing_section"]))
        with open(OUT / f"coverage_{fmt_key}.json", "w", encoding="utf-8") as f:
            json.dump(cov, f, indent=1)
        print(f"    official numbers {cov['min_number']}-{cov['max_number']}, {cov['missing_count']} missing "
              f"within that range; {len(cov['listed_missing'])} listed missing by Cricsheet")


def year_rates(y: dict) -> dict:
    y = dict(y)
    y["rpo"] = rnd(6 * y["runs"] / y["balls"]) if y.get("balls") else None
    y["runs_per_wkt"] = rnd(y["runs"] / y["wkts"]) if y.get("wkts") else None
    c = y.get("first_inns_complete", 0)
    y["first_inns_avg_complete"] = rnd(y.get("first_inns_complete_runs", 0) / c, 1) if c else None
    return y


def listed_missing(section: str) -> list[dict]:
    """Male matches Cricsheet lists as missing for one match type, from the cached missing.html."""
    path = RAW / "missing.html"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<h5>\s*" + re.escape(section) + r"\s*</h5>(.*?)(?=<h5>|<h4>|$)", text, flags=re.S)
    if not m:
        return []  # no section = nothing listed missing for this type
    male = re.search(r"<h6>\s*Male matches\s*</h6>\s*<dl>(.*?)</dl>", m.group(1), flags=re.S)
    if not male:
        return []
    pairs = re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", male.group(1), flags=re.S)
    out = []
    for date, teams in pairs:
        t = [html.unescape(x).strip() for x in re.sub(r"<[^>]+>", "", teams).split(" vs ")]
        out.append({"date": date.strip(), "teams": t})
    return out


def coverage(numbers: dict[int, str], missing_listed: list[dict]) -> dict:
    lo, hi = min(numbers), max(numbers)
    missing = [n for n in range(lo, hi + 1) if n not in numbers]
    by_dec = defaultdict(lambda: {"have": 0})
    for n, d in numbers.items():
        by_dec[d[:3] + "0s"]["have"] += 1
    # Gaps from the first match of each year onward: tells you which years are patchy.
    by_year_numbers = defaultdict(list)
    for n, d in numbers.items():
        by_year_numbers[d[:4]].append(n)
    by_year = {}
    for yr, ns in sorted(by_year_numbers.items()):
        span = max(ns) - min(ns) + 1
        by_year[yr] = {"have": len(ns), "span": span, "pct": rnd(100 * len(ns) / span, 1)}
    # Cricsheet withholds all Afghanistan men's matches (https://cricsheet.org/withheld-matches),
    # so part of every gap is Afghanistan games; the rest are abandoned or not-yet-covered matches.
    return {"min_number": lo, "max_number": hi, "missing_count": len(missing),
            "note": "Afghanistan men's matches are withheld by Cricsheet and never appear here",
            "listed_missing": missing_listed,
            "missing": missing, "by_decade": dict(sorted(by_dec.items())), "by_year": by_year}


def write_csv(recs: dict, path: Path, phases) -> None:
    cols = ["id", "cricinfo_id", "name", "unique_name", "team", "first", "last", "matches",
            "bat_inns", "not_outs", "runs", "balls", "hs", "bat_avg", "bat_sr", "hundreds", "fifties",
            "fours", "sixes", "boundary_pct", "dot_pct", "usual_position",
            "bowl_inns", "bowl_balls", "bowl_runs", "wkts", "bowl_avg", "econ", "bowl_sr", "best",
            "four_w", "five_w", "bowl_dot_pct", "catches", "stumpings"]
    for ph, _, _ in phases:
        cols += [f"{ph}_bat_runs", f"{ph}_bat_balls", f"{ph}_bat_sr", f"{ph}_bowl_balls", f"{ph}_econ",
                 f"{ph}_wkts"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        for r in sorted(recs.values(), key=lambda r: -(r["bat"]["runs"] + 20 * r["bowl"]["wkts"])):
            b, w = r["bat"], r["bowl"]
            row = [r["id"], r["cricinfo_id"], r["name"], r["unique_name"], r["team"], r["first"], r["last"],
                   r["matches"], b["inns"], b["not_outs"], b["runs"], b["balls"],
                   f"{b['hs']}{'*' if b['hs_not_out'] else ''}", b["avg"], b["sr"], b["hundreds"],
                   b["fifties"], b["fours"], b["sixes"], b["boundary_pct"], b["dot_pct"],
                   rnd(r["usual_position"], 1), w["inns"], w["balls"], w["runs"], w["wkts"], w["avg"],
                   w["econ"], w["sr"], f"{w['best'][0]}/{w['best'][1]}" if w["best"] else "",
                   w["four_w"], w["five_w"], w["dot_pct"], r["field"]["catches"], r["field"]["stumpings"]]
            for ph, _, _ in phases:
                bp, wp = r["bat_phase"][ph], r["bowl_phase"][ph]
                row += [bp["runs"], bp["balls"], bp["sr"], wp["balls"], wp["econ"], wp["wkts"]]
            wr.writerow(row)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=sorted(FORMATS), action="append",
                    help="format(s) to build (default: all)")
    args = ap.parse_args(argv)
    missing = [f for f in ["people.csv"] + [FORMATS[k]["zip"] for k in FORMATS if "zip" in FORMATS[k]]
               if not (RAW / f).exists()]
    if missing:
        print(f"missing raw files {missing}; run scripts/fetch_cricsheet.py first", file=sys.stderr)
        return 1
    register = load_register()
    for k in args.format or sorted(FORMATS):
        build(k, register)
    return 0


if __name__ == "__main__":
    sys.exit(main())
