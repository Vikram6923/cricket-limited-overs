"""Download Cricsheet ball-by-ball zips (internationals + T20 leagues) and the player register into data/raw/.

Files that already exist are never re-downloaded unless --refresh is given
(use that once a season to pick up new matches).

    python scripts/fetch_cricsheet.py            # download whatever is missing
    python scripts/fetch_cricsheet.py --refresh  # re-download everything
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

FILES = {
    "odis_male_json.zip": "https://cricsheet.org/downloads/odis_male_json.zip",
    "t20s_male_json.zip": "https://cricsheet.org/downloads/t20s_male_json.zip",
    "people.csv": "https://cricsheet.org/register/people.csv",
    # Cricsheet's list of matches it knows it lacks (excludes the withheld Afghanistan games).
    "missing.html": "https://cricsheet.org/missing/",
}

# Men's 20-over franchise / domestic leagues (saved under data/raw/leagues/). Used for players with no usable
# international data - above all Afghanistan, whose matches Cricsheet withholds. The Hundred is left out on
# purpose: 100-ball innings with 5-ball overs don't fit the T20 phase splits.
LEAGUES = {
    "ipl": "Indian Premier League",
    "bbl": "Big Bash League",
    "psl": "Pakistan Super League",
    "cpl": "Caribbean Premier League",
    "sat": "SA20",
    "ilt": "International League T20",
    "bpl": "Bangladesh Premier League",
    "lpl": "Lanka Premier League",
    "mlc": "Major League Cricket",
    "ntb": "T20 Blast",
    "ssm": "Super Smash",
}
for _code in LEAGUES:
    FILES[f"leagues/{_code}_json.zip"] = f"https://cricsheet.org/downloads/{_code}_json.zip"

HEADERS = {"User-Agent": "cricket-limited-overs-sim/0.1 (personal research project)"}


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {dest.name}: {done / 1e6:.1f} / {total / 1e6:.1f} MB", end="", flush=True)
        print()
    if dest.suffix == ".zip":
        with zipfile.ZipFile(tmp) as z:  # fail early on a truncated download
            bad = z.testzip()
            if bad:
                raise RuntimeError(f"corrupt member {bad} in {dest.name}")
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    args = ap.parse_args(argv)

    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        dest = RAW / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and not args.refresh:
            print(f"cached   {name} ({dest.stat().st_size / 1e6:.1f} MB)")
            continue
        print(f"download {url}")
        download(url, dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
