"""Player ratings per format (ODI, T20) from ball-by-ball data, with opponent adjustment, shrinkage and era adjustment.

Model (fitted separately for ODI and for T20 = T20Is + franchise leagues):

    expected count on a ball = era_baseline[competition, year, phase, metric] * bat_index[batter] * bowl_index[bowler]

for metrics runs (off the bat), wkt (bowler-credited dismissals), dot, four, six. Indexes are fitted by alternating
updates (each batter against the bowlers he actually faced and vice versa), so playing weak opposition doesn't inflate
a rating. Each update is an empirical-Bayes shrink toward a prior = role-group mean x team effect, with the prior's
strength estimated from the data (tau^2 = observed spread - sampling noise). Indexes are relative to the player's own
era, which is the era adjustment: an index of 1.2 means "20% above his contemporaries" in any year.

Phase indexes (powerplay / middle / death) are the overall index adjusted by the player's own phase record, shrunk the
same way. Bowlers also get wide / no-ball indexes; batters a run-out (non-bowler dismissal) index.

Reads   data/raw/*.zip (via a cache in data/cache/), data/raw_stats/players_*.json, styles.json (optional)
Writes  data/ratings_odi.json, data/ratings_t20.json (+ .csv)

    python scripts/build_ratings.py
    python scripts/build_ratings.py --format t20 --until 2023   # only data up to 2023 (used by validation)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

from build_raw_stats import BOWLER_WICKETS, FORMATS as RAW_FORMATS, NOT_OUT_KINDS, phase_of

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STATS = ROOT / "data" / "raw_stats"
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data"

CELL_VERSION = 2
# International matches are split into tiers so that associate-only games get their own baseline. Otherwise the
# fitted T20I/ODI baseline absorbs whatever the (heavily shrunk) associate team levels can't explain, and modern
# "T20I conditions" would mean far too many wickets for a full-member game.
FULL_MEMBERS = {"Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland", "New Zealand", "Pakistan",
                "South Africa", "Sri Lanka", "West Indies", "Zimbabwe", "ICC World XI", "Asia XI", "Africa XI"}
METRICS = ("runs", "wkt", "dot", "four", "six")
PHASES = ("powerplay", "middle", "death")

MODELS = {
    "odi": {"sources": [("odi", "odis_male_json.zip")], "phases": RAW_FORMATS["odi"]["phases"],
            "quota": 60, "intl": "odi", "raw": ["odi"]},
    "t20": {"sources": [("t20i", "t20s_male_json.zip")] +
                       [(Path(z).name.split("_json")[0], z) for z in RAW_FORMATS["t20_league"]["zips"]],
            "phases": RAW_FORMATS["t20"]["phases"], "quota": 24, "intl": "t20i", "raw": ["t20", "t20_league"]},
}

MIN_BALLS_TAU = 120     # players with at least this many balls estimate the prior spread (tau^2)
TEAM_PSEUDO_BALLS = 5000  # team level shrinks toward its tier level (full/associate/league); tuned by validate_ratings.py
YEAR_PSEUDO_BALLS = 3000  # thin years borrow from neighbouring years with this weight
REF_YEARS = 5           # "reference era" for readable stats = last N complete-ish years of internationals


# ---------------------------------------------------------------------------------------------- data cells

def _signature(model: dict) -> str:
    parts = [f"v{CELL_VERSION}"]
    for _, z in model["sources"]:
        p = RAW / z
        if p.exists():
            st = p.stat()
            parts.append(f"{z}:{st.st_size}:{int(st.st_mtime)}")
    return "|".join(parts)


def load_cells(fmt: str) -> dict:
    """Per (batter, bowler, competition, year, phase) counts, plus bowler extras and batter run-outs. Cached."""
    model = MODELS[fmt]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"cells_{fmt}.pkl"
    sig = _signature(model)
    if path.exists():
        with open(path, "rb") as f:
            data = pickle.load(f)
        if data.get("signature") == sig:
            return data
    phases = model["phases"]
    cells = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0, 0])  # balls runs runs_sq wkt dot four six (spare)
    extras = defaultdict(lambda: [0, 0, 0])                 # bowler: legal balls, wides, noballs
    other = defaultdict(int)                                # batter: non-bowler dismissals (run outs etc.)
    names: dict[str, str] = {}
    n_matches = 0
    for comp, z in model["sources"]:
        if not (RAW / z).exists():
            print(f"  missing {z}, skipped", file=sys.stderr)
            continue
        with zipfile.ZipFile(RAW / z) as zf:
            for n in zf.namelist():
                if not n.endswith(".json"):
                    continue
                m = json.loads(zf.read(n).decode("utf-8"))
                info = m["info"]
                if info.get("gender") != "male" or info.get("balls_per_over", 6) != 6:
                    continue
                n_matches += 1
                reg = info["registry"]["people"]
                comp_m = comp
                if comp in ("odi", "t20i"):
                    full = sum(t in FULL_MEMBERS for t in info["teams"])
                    comp_m = comp if full == 2 else f"{comp}_mixed" if full == 1 else f"{comp}_assoc"
                for nm, pid in reg.items():
                    names.setdefault(pid, nm)
                year = int(info["dates"][0][:4])
                for inn in m.get("innings", []):
                    if inn.get("super_over"):
                        continue
                    for ov in inn.get("overs", []):
                        ph = phase_of(ov["over"], phases)
                        for d in ov["deliveries"]:
                            bat, bwl = reg[d["batter"]], reg[d["bowler"]]
                            ex = d.get("extras", {})
                            wide, nb = "wides" in ex, "noballs" in ex
                            e = extras[(bwl, comp_m, year, ph)]
                            if not wide and not nb:
                                e[0] += 1
                            if wide:
                                e[1] += 1
                            if nb:
                                e[2] += 1
                            if not wide:
                                br = d["runs"]["batter"]
                                c = cells[(bat, bwl, comp_m, year, ph)]
                                c[0] += 1
                                c[1] += br
                                c[2] += br * br
                                if br == 0:
                                    c[4] += 1
                                if not d["runs"].get("non_boundary"):
                                    if br == 4:
                                        c[5] += 1
                                    elif br == 6:
                                        c[6] += 1
                            for w in d.get("wickets", []):
                                if w["kind"] in BOWLER_WICKETS:
                                    if not wide:
                                        cells[(bat, bwl, comp_m, year, ph)][3] += 1
                                elif w["kind"] not in NOT_OUT_KINDS and w["player_out"] in reg:
                                    other[(reg[w["player_out"]], comp_m, year, ph)] += 1
    data = {"signature": sig, "cells": dict(cells), "extras": dict(extras), "other": dict(other),
            "names": names, "matches": n_matches}
    with open(path, "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
    return data


def base_comp(comp: str) -> str:
    return comp.replace("_mixed", "").replace("_assoc", "")


def merge_tiers(data: dict) -> dict:
    """Cells with the international tiers (odi / odi_mixed / odi_assoc) merged back into one competition.
    The fit uses merged competitions so that pool quality has to be explained by player and team levels; a
    separate baseline per tier would quietly absorb the associates' weakness."""
    if "merged" in data:
        return data["merged"]
    cells, extras, other = defaultdict(lambda: [0] * 8), defaultdict(lambda: [0] * 3), defaultdict(int)
    for (b, w, c, y, p), v in data["cells"].items():
        x = cells[(b, w, base_comp(c), y, p)]
        for i in range(8):
            x[i] += v[i]
    for (w, c, y, p), v in data["extras"].items():
        x = extras[(w, base_comp(c), y, p)]
        for i in range(3):
            x[i] += v[i]
    for (b, c, y, p), v in data["other"].items():
        other[(b, base_comp(c), y, p)] += v
    data["merged"] = {**data, "cells": dict(cells), "extras": dict(extras), "other": dict(other)}
    return data["merged"]


def full_member_baselines(fmt: str, r: dict, until: int | None) -> dict:
    """Conditions in full-member v full-member internationals per (year, phase): observed rate divided by the
    average bat x bowl index product of the players involved, i.e. what an average batter v an average bowler
    would do there. These are the "international conditions" for the engine and the reference era."""
    data = load_cells(fmt)
    intl = MODELS[fmt]["intl"]
    bi = {p: i for i, p in enumerate(r["bat_ids"])}
    wi = {p: i for i, p in enumerate(r["bowl_ids"])}
    col = {"runs": 1, "wkt": 3, "dot": 4, "four": 5, "six": 6}
    num = defaultdict(lambda: defaultdict(float))
    den = defaultdict(lambda: defaultdict(float))
    balls = defaultdict(float)
    sq = defaultdict(float)
    for (bat, bwl, comp, yr, ph), c in data["cells"].items():
        if comp != intl or (until is not None and yr > until) or bat not in bi or bwl not in wi:
            continue
        key = (yr, ph)
        balls[key] += c[0]
        sq[key] += c[2]
        for m, j in col.items():
            num[key][m] += c[j]
            den[key][m] += c[0] * r["bat"][m][bi[bat]] * r["bowl"][m][wi[bwl]]
    ext = defaultdict(lambda: [0.0, 0.0, 0.0])
    for (bwl, comp, yr, ph), e in data["extras"].items():
        if comp == intl and (until is None or yr <= until):
            for i in range(3):
                ext[(yr, ph)][i] += e[i]
    oth = defaultdict(float)
    for (bat, comp, yr, ph), v in data["other"].items():
        if comp == intl and (until is None or yr <= until):
            oth[(yr, ph)] += v
    out = {}
    for key, n in balls.items():
        yr, ph = key
        e = ext[key]
        rate = {m: num[key][m] / den[key][m] if den[key][m] else 0.0 for m in col}
        out[(f"{intl}_full", yr, ph)] = {
            "balls": n, **rate, "runs_sq": sq[key] / n,
            "wide": e[1] / max(e[0], 1), "noball": e[2] / max(e[0], 1), "other_out": oth[key] / n}
    return out


# ---------------------------------------------------------------------------------------------- baselines

def baselines(cells: dict, extras: dict, other: dict) -> dict:
    """(comp, year, phase) -> per-ball rates. Thin years borrow from +-2 neighbouring years."""
    tot = defaultdict(lambda: [0.0] * 7)
    for (bat, bwl, comp, yr, ph), c in cells.items():
        t = tot[(comp, yr, ph)]
        for i in range(7):
            t[i] += c[i]
    ext = defaultdict(lambda: [0.0] * 3)
    for (bwl, comp, yr, ph), e in extras.items():
        t = ext[(comp, yr, ph)]
        for i in range(3):
            t[i] += e[i]
    oth = defaultdict(float)
    for (bat, comp, yr, ph), v in other.items():
        oth[(comp, yr, ph)] += v

    def pooled(src, comp, yr, ph, width):
        acc = None
        for d in range(-width, width + 1):
            v = src.get((comp, yr + d, ph))
            if v is None:
                continue
            if acc is None:
                acc = list(v) if isinstance(v, list) else v
            elif isinstance(v, list):
                acc = [a + b for a, b in zip(acc, v)]
            else:
                acc += v
        return acc

    out = {}
    for key, t in tot.items():
        comp, yr, ph = key
        near = pooled(tot, comp, yr, ph, 2)
        balls, nballs = t[0], near[0]
        k = YEAR_PSEUDO_BALLS / max(nballs, 1)

        def rate(i, own=t, nb=near):
            return (own[i] + k * nb[i]) / (own[0] + k * nb[0])
        e = ext.get(key, [0, 0, 0])
        en = pooled(ext, comp, yr, ph, 2) or [0, 0, 0]
        ke = YEAR_PSEUDO_BALLS / max(en[0], 1)
        legal = max(e[0] + ke * en[0], 1)
        o_near = pooled(oth, comp, yr, ph, 2) or 0.0
        out[key] = {
            "balls": balls,
            "runs": rate(1), "runs_sq": rate(2), "wkt": rate(3), "dot": rate(4), "four": rate(5), "six": rate(6),
            "wide": (e[1] + ke * en[1]) / legal, "noball": (e[2] + ke * en[2]) / legal,
            "other_out": (oth.get(key, 0.0) + k * o_near) / (balls + k * nballs),
        }
    return out


# ---------------------------------------------------------------------------------------------- shrinkage

def eb_shrink(A, E, noise, prior, n, min_n=MIN_BALLS_TAU):
    """Empirical-Bayes shrink of raw = A/E toward prior. Returns (index list, tau^2, weights)."""
    raw = [a / e if e > 0 else p for a, e, p in zip(A, E, prior)]
    obs = [((r - p) ** 2, v) for r, p, v, nn, e in zip(raw, prior, noise, n, E) if nn >= min_n and e > 0]
    # Precision-weighted moment estimate (weights 1/(tau2+v)^2, iterated): an unweighted mean lets the many
    # small-sample players, whose deviations are mostly noise, swamp the signal from well-measured ones.
    tau2 = 0.02
    for _ in range(50):
        if not obs:
            break
        sw = swd = 0.0
        for d2, v in obs:
            w = 1.0 / (tau2 + v) ** 2
            sw += w
            swd += w * (d2 - v)
        new = max(swd / sw, 1e-4)
        if abs(new - tau2) < 1e-6:
            tau2 = new
            break
        tau2 = new
    idx, wts = [], []
    for r, p, v, e in zip(raw, prior, noise, E):
        w = tau2 / (tau2 + v) if e > 0 else 0.0
        idx.append(p + w * (r - p))
        wts.append(w)
    return idx, tau2, wts


# ---------------------------------------------------------------------------------------------- groups

def player_groups(fmt: str, ids: list[str], styles: dict, afghans: set[str]) -> tuple[list, list, list, dict]:
    """Batting role group, bowling role group and team for each player (used for the shrinkage prior)."""
    raw = {}
    for f in MODELS[fmt]["raw"]:
        p = STATS / f"players_{f}.json"
        if p.exists():
            raw[f] = json.loads(p.read_text(encoding="utf-8"))
    intl = raw.get(MODELS[fmt]["raw"][0], {})
    league = raw.get("t20_league", {}) if fmt == "t20" else {}
    quota_share = MODELS[fmt]["quota"] / 2  # balls per match bowled by a "specialist" (half his quota)
    bat_g, bowl_g, team, info = [], [], [], {}
    for pid in ids:
        ri, rl = intl.get(pid), league.get(pid)
        recs = [r for r in (ri, rl) if r]
        pos_n = sum(sum(r["positions"].values()) for r in recs)
        pos = (sum(int(k) * v for r in recs for k, v in r["positions"].items()) / pos_n) if pos_n else 11
        bat_g.append("top" if pos <= 3.5 else "middle" if pos <= 5.5 else "lower" if pos <= 7.5 else "tail")
        balls = sum(r["bowl"]["balls"] for r in recs)
        bowl_inns = sum(r["bowl"]["inns"] for r in recs)
        spec = "spec" if bowl_inns and balls / bowl_inns >= quota_share else "part"
        typ = (styles.get(pid) or {}).get("bowl", {}).get("type") or "unk"
        bowl_g.append(f"{spec}_{typ}")
        if ri and ri.get("team"):
            t = ri["team"]
        elif pid in afghans:
            t = "Afghanistan"
        elif rl:
            t = "league:" + max(rl["by_league"].items(), key=lambda kv: kv[1]["m"])[0]
        else:
            t = "unknown"
        team.append(t)
        info[pid] = {"position": round(pos, 1) if pos_n else None, "matches": sum(r["matches"] for r in recs)}
    return bat_g, bowl_g, team, info


def tier_of(team: str) -> str:
    """full member / associate / league-only players. (A fourth tier splitting associates with and without ODI
    status was tried: batting predictions improved slightly but bowling got clearly worse, so it was dropped.)"""
    if team in FULL_MEMBERS:
        return "full"
    if team.startswith("league:"):
        return "league"
    return "associate"


def team_levels(A: list, e0: list, cb: list, cw: list, bat_team: list, bowl_team: list, balls: list,
                pseudo: float = TEAM_PSEUDO_BALLS, iters: int = 5000) -> tuple[dict, dict]:
    """Team-vs-team strength (batting level x bowling level), solved to convergence on aggregated team pairs.

    Hierarchy: tier (full member / associate / league-only) -> team -> player. Tier levels are NOT shrunk: the
    hundreds of full-member v associate games identify them well. Each team is shrunk toward its tier level with
    `pseudo` balls of weight, and players are later shrunk toward their team. Earlier versions shrank teams toward
    1.0 or toward their opponents' average; with associates mostly playing each other, both left the associate
    pool frozen near the full-member level (Nepal and Kuwait batting like Australia)."""
    pa, pe, pn = defaultdict(float), defaultdict(float), defaultdict(float)
    for k in range(len(cb)):
        key = (bat_team[cb[k]], bowl_team[cw[k]])
        pa[key] += A[k]
        pe[key] += e0[k]
        pn[key] += balls[k]
    keys = list(pa)
    bt = sorted({k[0] for k in keys})
    wt = sorted({k[1] for k in keys})
    bix = {t: i for i, t in enumerate(bt)}
    wix = {t: i for i, t in enumerate(wt)}
    kb = [bix[k[0]] for k in keys]
    kw = [wix[k[1]] for k in keys]
    ka = [pa[k] for k in keys]
    ke = [pe[k] for k in keys]
    kn = [pn[k] for k in keys]
    tiers = {0: [tier_of(t) for t in bt], 1: [tier_of(t) for t in wt]}
    bat = [1.0] * len(bt)
    bowl = [1.0] * len(wt)
    for it in range(iters):
        delta = 0.0
        for side in (0, 1):
            own, opp = (kb, kw) if side == 0 else (kw, kb)
            cur, other = (bat, bowl) if side == 0 else (bowl, bat)
            num = [0.0] * len(cur)
            den = [0.0] * len(cur)
            nb = [0.0] * len(cur)
            for i, o, x, e, n in zip(own, opp, ka, ke, kn):
                num[i] += x
                den[i] += e * other[o]
                nb[i] += n
            tnum, tden = defaultdict(float), defaultdict(float)
            for t, tier in enumerate(tiers[side]):
                tnum[tier] += num[t]
                tden[tier] += den[t]
            tier_level = {k: (tnum[k] / tden[k] if tden[k] > 0 else 1.0) for k in tnum}
            tot_n = sum(nb) or 1
            new = []
            for t in range(len(cur)):
                prior = tier_level[tiers[side][t]]
                k_e = pseudo * (den[t] / nb[t]) if nb[t] else 0.0
                new.append((num[t] + k_e * prior) / (den[t] + k_e) if den[t] + k_e > 0 else prior)
            mean = sum(v * w for v, w in zip(new, nb)) / tot_n
            for t in range(len(cur)):
                v = new[t] / mean
                delta = max(delta, abs(v - cur[t]))
                cur[t] = v
        if delta < 1e-6:
            break
    return {t: bat[i] for t, i in bix.items()}, {t: bowl[i] for t, i in wix.items()}


def group_prior(A, E, groups, teams, teff):
    """prior_i = pooled ratio of the player's role group x his team's level (from team_levels)."""
    ga, ge = defaultdict(float), defaultdict(float)
    for a, e, g in zip(A, E, groups):
        ga[g] += a
        ge[g] += e
    gmean = {g: (ga[g] / ge[g] if ge[g] > 0 else 1.0) for g in ga}
    return [gmean[g] * teff.get(t, 1.0) for g, t in zip(groups, teams)], gmean, teff


# ---------------------------------------------------------------------------------------------- fit

def fit(fmt: str, until: int | None = None, iters: int = 25, opponent: bool = True, shrink: bool = True,
        verbose: bool = True, exclude: tuple = ()) -> dict:
    """exclude: calendar years left out of the fit (held-out validation)."""
    data = merge_tiers(load_cells(fmt))
    cells = {k: v for k, v in data["cells"].items() if (until is None or k[3] <= until) and k[3] not in exclude}
    extras = {k: v for k, v in data["extras"].items() if (until is None or k[2] <= until) and k[2] not in exclude}
    other = {k: v for k, v in data["other"].items() if (until is None or k[2] <= until) and k[2] not in exclude}
    base = baselines(cells, extras, other)

    bat_ids = sorted({k[0] for k in cells})
    bowl_ids = sorted({k[1] for k in cells})
    bi = {p: i for i, p in enumerate(bat_ids)}
    wi = {p: i for i, p in enumerate(bowl_ids)}
    styles = _load_json(STATS / "styles.json", {})
    afghans = {p["cricsheet_id"] for p in _load_json(STATS / "afghanistan_players.json", []) if p.get("cricsheet_id")}
    bat_role, _, bat_team, bat_info = player_groups(fmt, bat_ids, styles, afghans)
    _, bowl_role, bowl_team, bowl_info = player_groups(fmt, bowl_ids, styles, afghans)

    # flatten cells into parallel arrays
    cb, cw, cph, ckey = [], [], [], []
    A = {m: [] for m in METRICS}
    e0 = {m: [] for m in METRICS}
    var_runs, balls = [], []
    col = {"runs": 1, "wkt": 3, "dot": 4, "four": 5, "six": 6}
    for (bat, bwl, comp, yr, ph), c in cells.items():
        b = base[(comp, yr, ph)]
        cb.append(bi[bat])
        cw.append(wi[bwl])
        cph.append(ph)
        ckey.append((comp, yr, ph))
        balls.append(c[0])
        for m in METRICS:
            A[m].append(c[col[m]])
            e0[m].append(c[0] * b[m])
        var_runs.append(c[0] * max(b["runs_sq"] - b["runs"] ** 2, 0.1))
    NB, NW = len(bat_ids), len(bowl_ids)
    nb_balls, nw_balls = [0] * NB, [0] * NW
    for i, j, n in zip(cb, cw, balls):
        nb_balls[i] += n
        nw_balls[j] += n

    # anchored team strength per metric (see team_levels)
    tl = {m: team_levels(A[m], e0[m], cb, cw, bat_team, bowl_team, balls) for m in METRICS}

    def side_fit(m, side, other_idx, roles, teams, nballs):
        idx_of_cell = cb if side == "bat" else cw
        opp_of_cell = cw if side == "bat" else cb
        N = NB if side == "bat" else NW
        Aa, Ee, Vv = [0.0] * N, [0.0] * N, [0.0] * N
        for k in range(len(cb)):
            i, o = idx_of_cell[k], opp_of_cell[k]
            f = other_idx[o] if opponent else 1.0
            Aa[i] += A[m][k]
            Ee[i] += e0[m][k] * f
            if m == "runs":
                Vv[i] += var_runs[k] * f * f
        prior, gmean, teff = group_prior(Aa, Ee, roles, teams, tl[m][0 if side == "bat" else 1])
        if m == "runs":
            noise = [v / (e * e) if e > 0 else 1.0 for v, e in zip(Vv, Ee)]
        else:
            noise = [p * max(1 - e / n, 0.05) / e if e > 0 and n > 0 else 1.0
                     for p, e, n in zip(prior, Ee, nballs)]
        if shrink:
            idx, tau2, wts = eb_shrink(Aa, Ee, noise, prior, nballs)
        else:
            idx = [a / e if e > 0 else 1.0 for a, e in zip(Aa, Ee)]
            tau2, wts = float("inf"), [1.0] * N
        # normalise: exposure-weighted mean 1 (keeps bat x bowl x baseline on the data's scale)
        tot_e = sum(Ee) or 1
        mean = sum(x * e for x, e in zip(idx, Ee)) / tot_e or 1
        idx = [x / mean for x in idx]
        prior = [x / mean for x in prior]
        return {"idx": idx, "A": Aa, "E": Ee, "noise": noise, "prior": prior, "tau2": tau2, "w": wts,
                "group_mean": gmean, "team_eff": teff}

    bat = {m: [tl[m][0].get(t, 1.0) for t in bat_team] for m in METRICS}
    bowl = {m: [tl[m][1].get(t, 1.0) for t in bowl_team] for m in METRICS}
    fits = {}
    # Third factor: the baseline itself. Separately normalised bat and bowl indexes don't guarantee that
    # baseline x bat x bowl reproduces the totals (strong batters tend to meet strong bowlers), and the leftover
    # few-percent bias swamps the small real differences between bowlers. So each iteration also rescales every
    # (competition, year, phase) baseline to match its observed total.
    bfac = {m: defaultdict(lambda: 1.0) for m in METRICS}
    for it in range(iters):
        delta = 0.0
        for m in METRICS:
            fb = side_fit(m, "bat", bowl[m], bat_role, bat_team, nb_balls)
            delta = max(delta, max(abs(a - b) for a, b in zip(fb["idx"], bat[m])))
            bat[m] = fb["idx"]
            fw = side_fit(m, "bowl", bat[m], bowl_role, bowl_team, nw_balls)
            delta = max(delta, max(abs(a - b) for a, b in zip(fw["idx"], bowl[m])))
            bowl[m] = fw["idx"]
            fits[m] = (fb, fw)
            num, den = defaultdict(float), defaultdict(float)
            bm, wm, em, am = bat[m], bowl[m], e0[m], A[m]
            for k in range(len(cb)):
                num[ckey[k]] += am[k]
                den[ckey[k]] += em[k] * bm[cb[k]] * (wm[cw[k]] if opponent else 1.0)
            f = {key: (num[key] / den[key] if den[key] > 0 else 1.0) for key in num}
            for key, v in f.items():
                bfac[m][key] *= v
                delta = max(delta, abs(v - 1))
            for k in range(len(cb)):
                em[k] *= f[ckey[k]]
            if m == "runs":
                for k in range(len(cb)):
                    var_runs[k] *= f[ckey[k]]
        if verbose:
            print(f"  {fmt} iteration {it + 1}: max index change {delta:.4f}", flush=True)
        if delta < 1e-3:
            break
    raw_base = base
    base = {key: dict(b) for key, b in raw_base.items()}
    for m in METRICS:
        for key, v in bfac[m].items():
            base[key][m] *= v
    base.update(full_member_baselines(fmt, {"bat_ids": bat_ids, "bowl_ids": bowl_ids, "bat": bat, "bowl": bowl},
                                      until))
    years = year_stats(cb, cw, ckey, balls, A, e0, var_runs, bat, bowl, opponent)

    # phase indexes: overall index adjusted by the player's own phase record, shrunk toward the overall index
    phase = {"bat": {}, "bowl": {}}
    for m in METRICS:
        for side, own, opp, N, idx_cells, opp_cells in (("bat", bat[m], bowl[m], NB, cb, cw),
                                                         ("bowl", bowl[m], bat[m], NW, cw, cb)):
            per = {}
            for ph in PHASES:
                Aa, Ee, Vv, nn = [0.0] * N, [0.0] * N, [0.0] * N, [0] * N
                for k in range(len(cb)):
                    if cph[k] != ph:
                        continue
                    i, o = idx_cells[k], opp_cells[k]
                    f = opp[o] if opponent else 1.0
                    Aa[i] += A[m][k]
                    Ee[i] += e0[m][k] * f
                    nn[i] += balls[k]
                    if m == "runs":
                        Vv[i] += var_runs[k] * f * f
                if m == "runs":
                    noise = [v / (e * e) if e > 0 else 1.0 for v, e in zip(Vv, Ee)]
                else:
                    noise = [p * max(1 - e / x, 0.05) / e if e > 0 and x > 0 else 1.0
                             for p, e, x in zip(own, Ee, nn)]
                if shrink:
                    pidx, tau2, _ = eb_shrink(Aa, Ee, noise, own, nn)
                else:
                    pidx = [a / e if e > 0 else p for a, e, p in zip(Aa, Ee, own)]
                    tau2 = float("inf")
                per[ph] = {"idx": pidx, "balls": nn, "tau2": tau2}
            phase[side][m] = per

    # bowler wides / no-balls and batter non-bowler dismissals: shrink toward 1 (no opponent effect)
    simple = {}
    for name, src, ids_map, N, key_idx, rate_key, exposure in (
            ("wide", extras, wi, NW, 0, "wide", "legal"), ("noball", extras, wi, NW, 0, "noball", "legal"),
            ("other_out", other, bi, NB, 0, "other_out", "faced")):
        Aa, Ee, nn = [0.0] * N, [0.0] * N, [0] * N
        if name == "other_out":
            faced = defaultdict(int)
            for (bat_id, bwl, comp, yr, ph), c in cells.items():
                faced[(bat_id, comp, yr, ph)] += c[0]
            for (pid, comp, yr, ph), b_ in faced.items():
                i = bi[pid]
                Ee[i] += b_ * base[(comp, yr, ph)]["other_out"]
                nn[i] += b_
            for (pid, comp, yr, ph), v in other.items():
                if pid in bi:
                    Aa[bi[pid]] += v
        else:
            j = 1 if name == "wide" else 2
            for (pid, comp, yr, ph), e in extras.items():
                if pid not in wi or (comp, yr, ph) not in base:
                    continue
                i = wi[pid]
                Aa[i] += e[j]
                Ee[i] += e[0] * base[(comp, yr, ph)][rate_key]
                nn[i] += e[0]
        noise = [1 / e if e > 0 else 1.0 for e in Ee]
        idx, tau2, _ = eb_shrink(Aa, Ee, noise, [1.0] * N, nn) if shrink else (
            [a / e if e > 0 else 1.0 for a, e in zip(Aa, Ee)], float("inf"), None)
        simple[name] = {"idx": idx, "tau2": tau2}

    return {"fmt": fmt, "until": until, "base": base, "raw_base": raw_base, "base_factor": bfac,
            "bat_ids": bat_ids, "bowl_ids": bowl_ids,
            "bat": bat, "bowl": bowl, "fits": fits, "phase": phase, "simple": simple,
            "bat_role": bat_role, "bowl_role": bowl_role, "bat_team": bat_team, "bowl_team": bowl_team,
            "bat_info": bat_info, "bowl_info": bowl_info, "names": data["names"],
            "nb_balls": nb_balls, "nw_balls": nw_balls, "styles": styles, "team_levels": tl, "years": years}


YEAR_COLS = ("balls",) + tuple(f"{x}_{m}" for m in METRICS for x in ("A", "E")) + ("V_runs",)


def year_stats(cb, cw, ckey, balls, A, e0, var_runs, bat, bowl, opponent=True) -> dict:
    """Per player and calendar year, the sufficient statistics of the fit: actual (A) and expected (E) counts per
    metric, where E already includes the fitted baseline and the opponents' final indexes, plus the runs variance.
    The engine turns these into ratings for any year range (engine/periods.py) without refitting."""
    out = {"bat": defaultdict(lambda: [0.0] * len(YEAR_COLS)), "bowl": defaultdict(lambda: [0.0] * len(YEAR_COLS))}
    by_comp = {"bat": defaultdict(lambda: [0.0] * len(YEAR_COLS)), "bowl": defaultdict(lambda: [0.0] * len(YEAR_COLS))}
    for k in range(len(cb)):
        yr = ckey[k][1]
        for side, i, opp in (("bat", cb[k], bowl), ("bowl", cw[k], bat)):
            for row in (out[side][(i, yr)], by_comp[side][(i, base_comp(ckey[k][0]))]):
                _add_cell(row, k, side, cb, cw, A, e0, var_runs, bat, bowl, balls, opponent)
    out["by_comp"] = by_comp
    return out


def _add_cell(row, k, side, cb, cw, A, e0, var_runs, bat, bowl, balls, opponent):
    """Add cell k to a player's row of sufficient statistics (see YEAR_COLS)."""
    opp = bowl if side == "bat" else bat
    o = cw[k] if side == "bat" else cb[k]
    row[0] += balls[k]
    for n, m in enumerate(METRICS):
        f = opp[m][o] if opponent else 1.0
        row[1 + 2 * n] += A[m][k]
        row[2 + 2 * n] += e0[m][k] * f
        if m == "runs":
            row[-1] += var_runs[k] * f * f


def _load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


# ---------------------------------------------------------------------------------------------- readable output

def ref_baseline(base: dict, comp: str, years: int = REF_YEARS) -> tuple[dict, list[int]]:
    """Pooled per-phase rates for the last `years` years of `comp` (the "modern international" reference era)."""
    yrs = sorted({y for (c, y, ph) in base if c == comp})
    use = yrs[-years:]
    out = {}
    for ph in PHASES:
        rows = [base[(comp, y, ph)] for y in use if (comp, y, ph) in base]
        tot = sum(r["balls"] for r in rows) or 1
        out[ph] = {k: sum(r[k] * r["balls"] for r in rows) / tot
                   for k in ("runs", "wkt", "dot", "four", "six", "wide", "noball", "other_out")}
        out[ph]["share"] = tot
    s_all = sum(out[ph]["share"] for ph in PHASES) or 1
    for ph in PHASES:
        out[ph]["share"] /= s_all
    return out, use


def era_baseline(base: dict, comp: str, y0: int, y1: int) -> dict:
    """All-phase pooled rates for comp over [y0, y1] (nearest covered year if outside coverage)."""
    yrs = sorted({y for (c, y, ph) in base if c == comp})
    sel = [y for y in yrs if y0 <= y <= y1] or [min(yrs, key=lambda y: min(abs(y - y0), abs(y - y1)))]
    rows = [base[(comp, y, ph)] for y in sel for ph in PHASES if (comp, y, ph) in base]
    tot = sum(r["balls"] for r in rows) or 1
    return {k: sum(r[k] * r["balls"] for r in rows) / tot
            for k in ("runs", "runs_sq", "wkt", "dot", "four", "six", "wide", "noball", "other_out")}


def readable_bat(idx_ph: dict, other_idx: float, shares: dict, ref: dict) -> dict:
    """Expected batting numbers in the reference era, from phase indexes and the player's phase mix."""
    rpb = sum(shares[ph] * ref[ph]["runs"] * idx_ph[ph]["runs"] for ph in PHASES)
    opb = sum(shares[ph] * (ref[ph]["wkt"] * idx_ph[ph]["wkt"] + ref[ph]["other_out"] * other_idx) for ph in PHASES)
    four = sum(shares[ph] * ref[ph]["four"] * idx_ph[ph]["four"] for ph in PHASES)
    six = sum(shares[ph] * ref[ph]["six"] * idx_ph[ph]["six"] for ph in PHASES)
    dot = sum(shares[ph] * ref[ph]["dot"] * idx_ph[ph]["dot"] for ph in PHASES)
    return {"avg": round(rpb / opb, 1) if opb else None, "sr": round(100 * rpb, 1),
            "boundary_pct": round(100 * (four + six), 1), "dot_pct": round(100 * dot, 1),
            "sixes_per_100": round(100 * six, 2)}


def readable_bowl(idx_ph: dict, wide_idx: float, nb_idx: float, shares: dict, ref: dict) -> dict:
    rpb = sum(shares[ph] * (ref[ph]["runs"] * idx_ph[ph]["runs"] + ref[ph]["wide"] * wide_idx
                            + ref[ph]["noball"] * nb_idx) for ph in PHASES)
    wpb = sum(shares[ph] * ref[ph]["wkt"] * idx_ph[ph]["wkt"] for ph in PHASES)
    dot = sum(shares[ph] * ref[ph]["dot"] * idx_ph[ph]["dot"] for ph in PHASES)
    return {"econ": round(6 * rpb, 2), "avg": round(rpb / wpb, 1) if wpb else None,
            "sr": round(1 / wpb, 1) if wpb else None, "dot_pct": round(100 * dot, 1)}


def _phase_shares(balls_by_ph: dict, typical: dict, min_balls: int = 60) -> dict:
    tot = sum(balls_by_ph.values())
    own = {ph: balls_by_ph[ph] / tot for ph in PHASES} if tot else typical
    w = min(tot / min_balls, 1.0) if tot else 0.0
    return {ph: w * own[ph] + (1 - w) * typical[ph] for ph in PHASES}


def _r(x, n=3):
    return None if x is None else round(x, n)


def num(v) -> float | None:
    m = re.search(r"-?[\d,]+(?:\.\d+)?", str(v or ""))
    return float(m.group().replace(",", "")) if m else None


def _ref_rates(ref: dict) -> tuple[float, float, float]:
    """(batting average, bowling average, economy) of an average player in the reference era."""
    sh = {ph: ref[ph]["share"] for ph in PHASES}
    rpb_bat = sum(sh[ph] * ref[ph]["runs"] for ph in PHASES)
    opb = sum(sh[ph] * (ref[ph]["wkt"] + ref[ph]["other_out"]) for ph in PHASES)
    rpb_bowl = sum(sh[ph] * (ref[ph]["runs"] + ref[ph]["wide"] + ref[ph]["noball"]) for ph in PHASES)
    wpb = sum(sh[ph] * ref[ph]["wkt"] for ph in PHASES)
    return rpb_bat / opb, rpb_bowl / wpb, 6 * rpb_bowl


def domestic_prior(fmt: str, r: dict, ref: dict) -> dict:
    """ODI only: List A record minus ODI record (both from the Wikipedia infobox) informs the prior of players with
    small ODI samples. The domestic -> ODI mapping is calibrated by weighted regression on well-measured players,
    so it learns both the level gap and how predictive domestic numbers are. Players are then re-shrunk toward the
    domestic-informed prior (their data weight is unchanged, so established players barely move)."""
    r["prior_shift"] = {"bat": defaultdict(dict), "bowl": defaultdict(dict)}
    if fmt != "odi":
        return {}
    xs_bat, xs_bowl = {}, {}
    for pid, s in r["styles"].items():
        la = s.get("list_a")
        if not la:
            continue
        o = s.get("odi") or {}
        runs, avg = num(la.get("runs")), num(la.get("bat_avg"))
        o_runs, o_avg = num(o.get("runs")), num(o.get("bat_avg"))
        if runs and avg:
            outs = runs / avg
            if o_runs and o_avg:  # List A includes ODIs: remove them so the prior is independent of the data
                runs, outs = runs - o_runs, outs - o_runs / o_avg
            if outs >= 15 and runs > 0:
                xs_bat[pid] = (runs / outs,)
        balls, wk, bav = num(la.get("balls")), num(la.get("wkts")), num(la.get("bowl_avg"))
        if balls and wk and bav:
            rc = wk * bav
            ob, ow, oa = num(o.get("balls")), num(o.get("wkts")), num(o.get("bowl_avg"))
            if ob and ow and oa:
                balls, wk, rc = balls - ob, wk - ow, rc - ow * oa
            if wk >= 20 and balls > 600 and rc > 0:
                xs_bowl[pid] = (rc / wk, 6 * rc / balls)
    ref_avg, ref_bavg, ref_econ = _ref_rates(ref)

    def regress(pairs):
        sw = sum(w for _, _, w in pairs)
        if len(pairs) < 30 or sw <= 0:
            return None
        mx = sum(x * w for x, _, w in pairs) / sw
        my = sum(y * w for _, y, w in pairs) / sw
        sxx = sum(w * (x - mx) ** 2 for x, _, w in pairs)
        sxy = sum(w * (x - mx) * (y - my) for x, y, w in pairs)
        b = sxy / sxx if sxx else 0.0
        return {"a": round(my - b * mx, 4), "b": round(b, 4), "n": len(pairs)}

    calib = {}
    specs = [("bat", "wkt", xs_bat, lambda v: math.log(ref_avg / v[0])),    # high domestic avg -> fewer outs
             ("bowl", "wkt", xs_bowl, lambda v: math.log(ref_bavg / v[0])),  # low domestic avg -> more wickets
             ("bowl", "runs", xs_bowl, lambda v: math.log(v[1] / ref_econ))]  # domestic economy -> runs index
    for side, m, xs, fx in specs:
        f = r["fits"][m][0 if side == "bat" else 1]
        ids = r["bat_ids"] if side == "bat" else r["bowl_ids"]
        pairs = [(fx(xs[pid]), math.log(f["idx"][i] / f["prior"][i]), f["w"][i])
                 for i, pid in enumerate(ids) if pid in xs and f["w"][i] >= 0.6 and f["prior"][i] > 0]
        reg = regress(pairs)
        if not reg:
            continue
        calib[f"{side}_{m}"] = reg
        cur = r["bat" if side == "bat" else "bowl"][m]
        for i, pid in enumerate(ids):
            if pid not in xs or f["E"][i] <= 0:
                continue
            new_prior = f["prior"][i] * math.exp(reg["a"] + reg["b"] * fx(xs[pid]))
            raw = f["A"][i] / f["E"][i]
            new = new_prior + f["w"][i] * (raw - new_prior)
            r["prior_shift"][side][m][i] = new / cur[i]
            cur[i] = new
            f["prior"][i] = new_prior
    return calib


def totals_rating(fmt: str, totals: dict, y0: int, y1: int, r: dict, bat_group: str, bowl_group: str,
                  runs_idx: float | None = None) -> dict:
    """Rating from career totals only (Wikipedia) for players with no ball-by-ball data in this format.
    Batting: balls faced are unknown, so the strike rate comes from the role prior and the average informs only
    the dismissal index. Bowling: balls, runs (wkts x avg) and wickets give economy and wicket indexes.
    Opposition is treated as average (no opponent adjustment is possible from totals)."""
    eb = era_baseline(r["base"], MODELS[fmt]["intl"] + "_full", y0, y1)
    gm = {m: r["fits"][m][0]["group_mean"].get(bat_group, 1.0) for m in METRICS}
    gw = {m: r["fits"][m][1]["group_mean"].get(bowl_group, 1.0) for m in METRICS}
    out = {"bat": None, "bowl": None}
    runs, avg = num(totals.get("runs")), num(totals.get("bat_avg"))
    if runs:
        outs = runs / avg if avg else 0.5
        n_est = runs / (eb["runs"] * (runs_idx or gm["runs"]))  # strike rate from ball-by-ball if we have it
        e_out = n_est * (eb["wkt"] + eb["other_out"])
        tau2 = r["fits"]["wkt"][0]["tau2"]
        w = tau2 / (tau2 + gm["wkt"] / e_out)
        out["bat"] = {"idx": {**gm, "wkt": gm["wkt"] + w * (outs / e_out - gm["wkt"])},
                      "balls_est": round(n_est), "w": w, "raw": {"wkt": (outs / e_out, gm["wkt"] / e_out)}}
    balls, wkts, bavg = num(totals.get("balls")), num(totals.get("wkts")), num(totals.get("bowl_avg"))
    if balls and balls >= 6:
        idx = dict(gw)
        e_w = balls * eb["wkt"]
        tau2 = r["fits"]["wkt"][1]["tau2"]
        w_w = tau2 / (tau2 + gw["wkt"] / e_w)
        idx["wkt"] = gw["wkt"] + w_w * ((wkts or 0) / e_w - gw["wkt"])
        raw = {"wkt": ((wkts or 0) / e_w, gw["wkt"] / e_w)}
        if wkts and bavg:
            exp_total = eb["runs"] + eb["wide"] + eb["noball"]
            raw_r = (wkts * bavg / balls) / exp_total
            noise = balls * max(eb["runs_sq"] - eb["runs"] ** 2, 0.1) / (balls * exp_total) ** 2
            tau2r = r["fits"]["runs"][1]["tau2"]
            idx["runs"] = gw["runs"] + tau2r / (tau2r + noise) * (raw_r - gw["runs"])
            raw["runs"] = (raw_r, noise)
        out["bowl"] = {"idx": idx, "balls": int(balls), "w": w_w, "raw": raw}
    return out


def _style_fields(st: dict) -> dict:
    b = st.get("bowl") or {}
    return {"dob": st.get("dob"), "bat_hand": st.get("bat_hand"), "bowl_type": b.get("type"),
            "bowl_kind": b.get("kind"), "bowl_arm": b.get("arm")}


def assemble(fmt: str, r: dict) -> dict:
    ref, ref_years = ref_baseline(r["base"], MODELS[fmt]["intl"] + "_full")
    calib = domestic_prior(fmt, r, ref)
    shift = r["prior_shift"]
    raw_recs = {f: _load_json(STATS / f"players_{f}.json", {}) for f in MODELS[fmt]["raw"]}
    bi = {p: i for i, p in enumerate(r["bat_ids"])}
    wi = {p: i for i, p in enumerate(r["bowl_ids"])}
    ref_share = {ph: ref[ph]["share"] for ph in PHASES}

    def typical(side, groups, ids):
        acc = defaultdict(lambda: {ph: 0 for ph in PHASES})
        for i in range(len(ids)):
            for ph in PHASES:
                acc[groups[i]][ph] += r["phase"][side]["runs"][ph]["balls"][i]
        return {g: {ph: d[ph] / (sum(d.values()) or 1) for ph in PHASES} for g, d in acc.items()}
    typ_bat = typical("bat", r["bat_role"], r["bat_ids"])
    typ_bowl = typical("bowl", r["bowl_role"], r["bowl_ids"])

    players = {}
    for pid in sorted(set(bi) | set(wi)):
        st = r["styles"].get(pid, {})
        rec = {"id": pid, "name": r["names"].get(pid, pid), "cricinfo_id": st.get("cricinfo_id"),
               "source": "ball_by_ball", **_style_fields(st), "bat": None, "bowl": None}
        car = {}
        for f, recs in raw_recs.items():
            x = recs.get(pid)
            if x:
                car[f] = {"m": x["matches"], "inns": x["bat"]["inns"], "runs": x["bat"]["runs"],
                          "bat_avg": x["bat"]["avg"], "bat_sr": x["bat"]["sr"], "hs": x["bat"]["hs"],
                          "wkts": x["bowl"]["wkts"], "bowl_avg": x["bowl"]["avg"], "econ": x["bowl"]["econ"],
                          "first": x["first"], "last": x["last"], "team": x["team"]}
                rec["cricinfo_id"] = rec["cricinfo_id"] or x.get("cricinfo_id")
        rec["career"] = car
        if pid in bi:
            i = bi[pid]
            rec["team"] = r["bat_team"][i]
            rec["position"] = r["bat_info"][pid]["position"]
            rec["bat_role"] = r["bat_role"][i]
            ph_idx = {ph: {m: r["phase"]["bat"][m][ph]["idx"][i] * shift["bat"][m].get(i, 1.0) for m in METRICS}
                      for ph in PHASES}
            balls_ph = {ph: r["phase"]["bat"]["runs"][ph]["balls"][i] for ph in PHASES}
            shares = _phase_shares(balls_ph, typ_bat.get(r["bat_role"][i], ref_share))
            other = r["simple"]["other_out"]["idx"][i]
            rec["bat"] = {"balls": r["nb_balls"][i], "confidence": _r(r["fits"]["runs"][0]["w"][i], 2),
                          "idx": {m: _r(r["bat"][m][i]) for m in METRICS}, "other_out_idx": _r(other),
                          "phase": {ph: {m: _r(v) for m, v in d.items()} for ph, d in ph_idx.items()},
                          "phase_balls": balls_ph, "ref": readable_bat(ph_idx, other, shares, ref)}
        if pid in wi:
            j = wi[pid]
            rec.setdefault("team", r["bowl_team"][j])
            rec["bowl_role"] = r["bowl_role"][j]
            ph_idx = {ph: {m: r["phase"]["bowl"][m][ph]["idx"][j] * shift["bowl"][m].get(j, 1.0) for m in METRICS}
                      for ph in PHASES}
            balls_ph = {ph: r["phase"]["bowl"]["runs"][ph]["balls"][j] for ph in PHASES}
            shares = _phase_shares(balls_ph, typ_bowl.get(r["bowl_role"][j], ref_share))
            wd, nb = r["simple"]["wide"]["idx"][j], r["simple"]["noball"]["idx"][j]
            rec["bowl"] = {"balls": r["nw_balls"][j], "confidence": _r(r["fits"]["wkt"][1]["w"][j], 2),
                           "idx": {m: _r(r["bowl"][m][j]) for m in METRICS}, "wide_idx": _r(wd),
                           "noball_idx": _r(nb),
                           "phase": {ph: {m: _r(v) for m, v in d.items()} for ph, d in ph_idx.items()},
                           "phase_balls": balls_ph, "ref": readable_bowl(ph_idx, wd, nb, shares, ref)}
        players[pid] = rec

    added = add_afghanistan(fmt, r, players, ref)
    pre_new = pre_part = 0
    if fmt == "odi" and r["until"] is None:
        r["pre2002_years"] = pre2002_baselines(r)
        pre_new, pre_part = add_pre2002(r, players, ref)
    meta = {
        "format": fmt, "data_until": r["until"], "players": len(players),
        "reference_era": {"competition": MODELS[fmt]["intl"] + "_full", "years": ref_years},
        "tau2": {m: {"bat": _r(r["fits"][m][0]["tau2"], 5), "bowl": _r(r["fits"][m][1]["tau2"], 5)}
                 for m in METRICS},
        "role_means": {m: {"bat": {g: _r(v) for g, v in r["fits"][m][0]["group_mean"].items()},
                           "bowl": {g: _r(v) for g, v in r["fits"][m][1]["group_mean"].items()}}
                       for m in METRICS},
        "team_levels": {m: {"bat": {t: _r(v) for t, v in r["team_levels"][m][0].items()},
                            "bowl": {t: _r(v) for t, v in r["team_levels"][m][1].items()}} for m in METRICS},
        "domestic_prior": calib, "afghanistan_from_totals": added,
        "afghanistan_blended_with_totals": r.get("afghan_blended", 0),
        "pre2002": {"new_players": pre_new, "with_pre2002_block": pre_part, "baseline_years": r.get("pre2002_years", [])},
        "notes": ("Indexes are relative to the player's own era after adjusting for opponents (1.0 = average). "
                  "Engine: expected rate = baselines[comp][year][phase][metric] x batter phase index x bowler "
                  "phase index. 'ref' = expected numbers in the reference era (modern internationals)."),
    }
    baselines_out: dict = {}
    for (comp, yr, ph), b in sorted(r["base"].items()):
        baselines_out.setdefault(comp, {}).setdefault(str(yr), {})[ph] = \
            {k: (_r(v, 5) if k != "balls" else v) for k, v in b.items()}
    return {"meta": meta, "reference": {ph: {k: _r(v, 5) for k, v in ref[ph].items()} for ph in PHASES},
            "baselines": baselines_out, "players": players}


def add_afghanistan(fmt: str, r: dict, players: dict, ref: dict) -> int:
    """Afghanistan players without (enough) ball-by-ball data in this format: rating from Wikipedia totals."""
    col = "odi" if fmt == "odi" else "t20i"
    n = n_blend = 0
    for p in _load_json(STATS / "afghanistan_players.json", []):
        pid = p.get("cricsheet_id")
        if not pid:
            continue
        have = players.get(pid)
        if have and ((have.get("bat") or {}).get("balls", 0) + (have.get("bowl") or {}).get("balls", 0)) >= 60:
            have["team"] = "Afghanistan"  # e.g. Rashid's T20I appearance for the World XI
            tot = p["infobox"].get(col) or p["lists"].get(col)
            if tot and blend_totals(fmt, r, have, tot, p["lists"].get(col) or {}, ref):
                n_blend += 1
            continue
        tot = p["infobox"].get(col) or p["lists"].get(col)
        if not tot:
            continue
        lst = p["lists"].get(col) or {}
        y0, y1 = int(num(lst.get("first")) or 2015), int(num(lst.get("last")) or 2026)
        role = (p.get("role") or "").lower()
        bat_g = ("top" if any(k in role for k in ("batter", "batsman", "opening")) else
                 "middle" if "keeper" in role or p.get("keeper") else
                 "lower" if "all" in role else "tail" if "bowler" in role else "middle")
        st = r["styles"].get(pid) or {}
        typ = (st.get("bowl") or {}).get("type") or "unk"
        balls, mat = num(tot.get("balls")) or 0, num(tot.get("matches")) or 1
        bowl_g = f"{'spec' if balls / mat >= MODELS[fmt]['quota'] / 2 else 'part'}_{typ}"
        tr = totals_rating(fmt, tot, y0, y1, r, bat_g, bowl_g)
        rec = {"id": pid, "name": p["name"], "cricinfo_id": p.get("cricinfo_id"), "source": "wikipedia_totals",
               "team": "Afghanistan", **_style_fields(st), "dob": p.get("dob") or st.get("dob"),
               "position": None, "bat_role": bat_g, "bowl_role": bowl_g, "bat": None, "bowl": None,
               "career": {f"wikipedia_{col}": {k: tot.get(k) for k in ("matches", "runs", "bat_avg", "hs", "balls",
                                                                       "wkts", "bowl_avg", "best")}}}
        shares = {ph: ref[ph]["share"] for ph in PHASES}
        if tr["bat"]:
            ix = tr["bat"]["idx"]
            ph_idx = {ph: dict(ix) for ph in PHASES}
            rec["bat"] = {"balls": tr["bat"]["balls_est"], "balls_estimated": True,
                          "confidence": _r(tr["bat"]["w"], 2), "idx": {m: _r(v) for m, v in ix.items()},
                          "other_out_idx": 1.0, "phase": {ph: {m: _r(v) for m, v in ix.items()} for ph in PHASES},
                          "ref": readable_bat(ph_idx, 1.0, shares, ref)}
        if tr["bowl"]:
            ix = tr["bowl"]["idx"]
            ph_idx = {ph: dict(ix) for ph in PHASES}
            rec["bowl"] = {"balls": tr["bowl"]["balls"], "confidence": _r(tr["bowl"]["w"], 2),
                           "idx": {m: _r(v) for m, v in ix.items()}, "wide_idx": 1.0, "noball_idx": 1.0,
                           "phase": {ph: {m: _r(v) for m, v in ix.items()} for ph in PHASES},
                           "ref": readable_bowl(ph_idx, 1.0, 1.0, shares, ref)}
        players[pid] = rec
        n += 1
    r["afghan_blended"] = n_blend
    return n


def pre2002_baselines(r: dict) -> list[int]:
    """ODI baselines for 1971-2001 (before Cricsheet): the earliest Cricsheet year's baselines scaled by the
    Wikipedia-derived era table (scripts/build_pre2002.py) relative to its 2001 row: runs, fours and sixes by the
    run-rate ratio, wickets by the balls-per-wicket ratio; other rates unchanged."""
    yt = _load_json(STATS / "years_odi_pre2002.json", {})
    if "2001" not in yt:
        return []
    added = []
    for comp in ("odi_full", "odi"):
        cy = sorted(y for (c, y, ph) in r["base"] if c == comp)
        if not cy:
            continue
        y0 = cy[0]
        ref = yt["2001"]
        for ys, row in yt.items():
            y = int(ys)
            if y >= y0 or not row.get("rpo") or not row.get("balls_per_wkt"):
                continue
            fr, fw = row["rpo"] / ref["rpo"], ref["balls_per_wkt"] / row["balls_per_wkt"]
            for ph in PHASES:
                b = dict(r["base"][(comp, y0, ph)])
                for k in ("runs", "four", "six"):
                    b[k] *= fr
                b["runs_sq"] *= fr * fr
                b["wkt"] *= fw
                r["base"][(comp, y, ph)] = b
            added.append(y)
    return sorted(set(added))


def add_pre2002(r: dict, players: dict, ref: dict) -> tuple[int, int]:
    """ODI players from before Cricsheet (scripts/build_pre2002.py): rating from their pre-2002 career totals,
    against their own era. New players get a record (source "wikipedia_pre2002"); players already rated from
    Cricsheet get a "pre2002" block that the engine uses for year ranges before their Cricsheet record."""
    shares = {ph: ref[ph]["share"] for ph in PHASES}
    n_new = n_part = 0
    for pid, q in _load_json(STATS / "pre2002_players.json", {}).items():
        runs, outs, balls = q.get("runs"), q.get("outs"), q.get("balls")
        if not q.get("matches") or not (runs or balls):
            continue
        tot = {"runs": runs, "bat_avg": (runs / outs) if runs and outs else None, "balls": balls,
               "wkts": q.get("wkts"), "bowl_avg": (q["runs_conceded"] / q["wkts"]) if q.get("wkts") and q.get("runs_conceded") else None}
        avg = tot["bat_avg"] or 0
        bat_g = "middle" if q.get("keeper") else "top" if avg >= 30 else "middle" if avg >= 20 else "lower" if avg >= 12 else "tail"
        typ = q.get("bowl_type") or "unk"
        bowl_g = f"{'spec' if (balls or 0) / q['matches'] >= 30 else 'part'}_{typ}"
        tr = totals_rating("odi", tot, q["first"], q["last"], r, bat_g, bowl_g)
        block = {"bat": None, "bowl": None, "first": q["first"], "last": q["last"]}
        if tr["bat"]:
            ix = tr["bat"]["idx"]
            block["bat"] = {"balls": tr["bat"]["balls_est"], "balls_estimated": True, "confidence": _r(tr["bat"]["w"], 2),
                            "idx": {m: _r(v) for m, v in ix.items()}, "other_out_idx": 1.0,
                            "phase": {ph: {m: _r(v) for m, v in ix.items()} for ph in PHASES},
                            "ref": readable_bat({ph: dict(ix) for ph in PHASES}, 1.0, shares, ref)}
        if tr["bowl"]:
            ix = tr["bowl"]["idx"]
            block["bowl"] = {"balls": tr["bowl"]["balls"], "confidence": _r(tr["bowl"]["w"], 2),
                             "idx": {m: _r(v) for m, v in ix.items()}, "wide_idx": 1.0, "noball_idx": 1.0,
                             "phase": {ph: {m: _r(v) for m, v in ix.items()} for ph in PHASES},
                             "ref": readable_bowl({ph: dict(ix) for ph in PHASES}, 1.0, 1.0, shares, ref)}
        career = {"odi_pre2002": {"m": q["matches"], "runs": runs, "bat_avg": tot["bat_avg"] and round(tot["bat_avg"], 2),
                                  "wkts": q.get("wkts"), "bowl_avg": tot["bowl_avg"] and round(tot["bowl_avg"], 2),
                                  "balls": balls, "first": str(q["first"]), "last": str(q["last"]), "team": q["nation"]}}
        if pid in players:
            players[pid]["pre2002"] = block
            players[pid].setdefault("career", {}).update(career)
            n_part += 1
            continue
        players[pid] = {"id": pid, "name": q["name"], "cricinfo_id": q.get("cricinfo_id"), "source": "wikipedia_pre2002",
                        "team": q["nation"], "bat_hand": q.get("bat_hand"), "bowl_type": q.get("bowl_type"),
                        "bowl_kind": q.get("bowl_kind"), "bowl_arm": q.get("bowl_arm"), "keeper": bool(q.get("keeper")),
                        "position": None, "bat_role": bat_g, "bowl_role": bowl_g, "bat": block["bat"],
                        "bowl": block["bowl"], "career": career}
        n_new += 1
    return n_new, n_part


def blend_totals(fmt: str, r: dict, rec: dict, tot: dict, lst: dict, ref: dict) -> bool:
    """Afghanistan players rated from league ball-by-ball data also have international career totals (withheld
    from Cricsheet). Combine them: for each metric the totals inform (dismissal rate; bowling economy and
    wickets), precision-weight the ball-by-ball estimate (variance tau2 x (1 - w)) with the totals' raw index
    (its sampling variance). Phase indexes move by the same ratio as the overall index."""
    y0, y1 = int(num(lst.get("first")) or 2015), int(num(lst.get("last")) or 2026)
    b, o = rec.get("bat"), rec.get("bowl")
    tr = totals_rating(fmt, tot, y0, y1, r, rec.get("bat_role") or "middle", rec.get("bowl_role") or "part_unk",
                       runs_idx=(b or {}).get("idx", {}).get("runs"))
    changed = False
    for side, block, src in (("bat", b, tr["bat"]), ("bowl", o, tr["bowl"])):
        if not block or not src:
            continue
        for m, (raw, noise) in src.get("raw", {}).items():
            old = block["idx"][m]
            tau2 = r["fits"][m][0 if side == "bat" else 1]["tau2"]
            conf = block.get("confidence") or 0.0
            v_bb = max(tau2 * (1 - conf), 1e-6)
            new = (old / v_bb + raw / noise) / (1 / v_bb + 1 / noise)
            block["idx"][m] = _r(new)
            for ph in PHASES:
                block["phase"][ph][m] = _r(block["phase"][ph][m] * new / old)
            changed = True
        block["blended_with"] = f"wikipedia {('ODI' if fmt == 'odi' else 'T20I')} totals"
    if changed:
        rec["source"] = "ball_by_ball+wikipedia_totals"
        shares = {ph: ref[ph]["share"] for ph in PHASES}
        if b:
            sh = _phase_shares(b.get("phase_balls") or {ph: 0 for ph in PHASES}, shares)
            b["ref"] = readable_bat(b["phase"], b.get("other_out_idx") or 1.0, sh, ref)
        if o:
            sh = _phase_shares(o.get("phase_balls") or {ph: 0 for ph in PHASES}, shares)
            o["ref"] = readable_bowl(o["phase"], o.get("wide_idx") or 1.0, o.get("noball_idx") or 1.0, sh, ref)
    return changed


def write_csv(out: dict, path: Path) -> None:
    cols = ["id", "name", "team", "source", "position", "bat_role", "bowl_role", "bat_hand", "bowl_kind",
            "bat_balls", "bat_conf", "ref_avg", "ref_sr", "ref_boundary_pct", "bat_runs_idx", "bat_wkt_idx",
            "bat_six_idx", "bowl_balls", "bowl_conf", "ref_econ", "ref_bowl_avg", "ref_bowl_sr", "bowl_runs_idx",
            "bowl_wkt_idx", "career"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        rows = sorted(out["players"].values(),
                      key=lambda p: -(((p["bat"] or {}).get("balls") or 0) + ((p["bowl"] or {}).get("balls") or 0)))
        for p in rows:
            b, o = p["bat"] or {}, p["bowl"] or {}
            br, orf = b.get("ref") or {}, o.get("ref") or {}
            bi, oi = b.get("idx") or {}, o.get("idx") or {}
            car = "; ".join(f"{k}: {v.get('m', v.get('matches'))}m {v.get('runs')}r {v.get('wkts')}w"
                            for k, v in (p.get("career") or {}).items())
            w.writerow([p["id"], p["name"], p.get("team"), p["source"], p.get("position"), p.get("bat_role"),
                        p.get("bowl_role"), p.get("bat_hand"), p.get("bowl_kind"), b.get("balls"),
                        b.get("confidence"), br.get("avg"), br.get("sr"), br.get("boundary_pct"), bi.get("runs"),
                        bi.get("wkt"), bi.get("six"), o.get("balls"), o.get("confidence"), orf.get("econ"),
                        orf.get("avg"), orf.get("sr"), oi.get("runs"), oi.get("wkt"), car])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=sorted(MODELS), action="append")
    ap.add_argument("--until", type=int, help="use only data up to this year (for validation)")
    args = ap.parse_args(argv)
    for fmt in args.format or sorted(MODELS):
        print(f"fitting {fmt}...", flush=True)
        r = fit(fmt, until=args.until)
        out = assemble(fmt, r)
        suffix = f"_until{args.until}" if args.until else ""
        path = OUT / f"ratings_{fmt}{suffix}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        write_csv(out, OUT / f"ratings_{fmt}{suffix}.csv")
        yrs = {"cols": list(YEAR_COLS), "bat": {}, "bowl": {}}
        for side, ids in (("bat", r["bat_ids"]), ("bowl", r["bowl_ids"])):
            for (i, yr), row in sorted(r["years"][side].items()):
                yrs[side].setdefault(ids[i], {})[str(yr)] = [int(row[0])] + [round(x, 3) for x in row[1:]]
        (OUT / f"ratings_{fmt}_years{suffix}.json").write_text(
            json.dumps(yrs, separators=(",", ":")), encoding="utf-8")
        comps = {"cols": list(YEAR_COLS), "bat": {}, "bowl": {}}
        for side, ids in (("bat", r["bat_ids"]), ("bowl", r["bowl_ids"])):
            for (i, comp), row in sorted(r["years"]["by_comp"][side].items()):
                comps[side].setdefault(ids[i], {})[comp] = [int(row[0])] + [round(x, 3) for x in row[1:]]
        (OUT / f"ratings_{fmt}_comps{suffix}.json").write_text(
            json.dumps(comps, separators=(",", ":")), encoding="utf-8")
        m = out["meta"]
        print(f"  wrote {path.name}: {m['players']} players ({m['afghanistan_from_totals']} Afghanistan from Wikipedia totals only, "
              f"{m['afghanistan_blended_with_totals']} league ratings blended with Wikipedia totals; "
              f"reference era {m['reference_era']}")
        if m["domestic_prior"]:
            print(f"  List A prior calibration: {m['domestic_prior']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
