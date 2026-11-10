"""The T20 leagues the game uses: one list for the data scripts, the fits, the server and the browser UI.

Each code is Cricsheet's competition code (its download is https://cricsheet.org/downloads/<code>_json.zip, saved
as data/raw/leagues/<code>_json.zip). Adding a league here adds it everywhere: the download, raw stats, ratings,
league seasons, the fits that read leagues, and the UI (labels and badge, served by /api/meta).

Fields:
    label    short name ("IPL", "T20 Blast"), used for league seasons and in the UI
    long     the competition's name in the conditions menu
    home     home country: players capped by another country are "overseas"; rain fits use it too
    start    first month of a season: 1 = a calendar year, 7 = July-June ("2025-26") for leagues over the new year
    badge    UI badge: text, background, text colour, accent, country as shown under the name
    league_season  True if League Season offers it (franchise-style squads and home grounds). Domestic competitions
             with dozens of state sides and no home grounds (the Mushtaq Ali Trophy) are rated and fitted like the
             others but get their own seasons (docs/domestic_design.md)
    side_level  True if the competition's sides keep their players and differ a lot in strength for years (India's
             states, Elite to Plate). Players whose main competition it is are then shrunk toward their own side's
             level in the ratings, not the competition's (scripts/build_ratings.py). Franchise sides are rebuilt by
             auctions and drafts every few years, so the competition's level is the right prior for them.
"""
from __future__ import annotations

from typing import NamedTuple


class League(NamedTuple):
    label: str
    long: str
    home: str
    start: int
    badge: tuple[str, str, str, str, str]
    league_season: bool = True
    side_level: bool = False


LEAGUES: dict[str, League] = {
    "ipl": League("IPL", "Indian Premier League", "India", 1, ("IPL", "#1d2c6b", "#fff", "#f28b00", "India")),
    "bbl": League("BBL", "Big Bash League", "Australia", 7, ("BBL", "#f26522", "#000", "#000", "Australia")),
    "psl": League("PSL", "Pakistan Super League", "Pakistan", 1, ("PSL", "#00843d", "#fff", "#c9a227", "Pakistan")),
    "cpl": League("CPL", "Caribbean Premier League", "West Indies", 1,
                  ("CPL", "#e4002b", "#fff", "#ffd100", "West Indies")),
    "sat": League("SA20", "SA20", "South Africa", 7, ("SA20", "#00a3e0", "#000", "#1d1d1b", "South Africa")),
    "ilt": League("ILT20", "International League T20", "United Arab Emirates", 7,
                  ("ILT20", "#5b2c83", "#fff", "#f6c453", "UAE")),
    "bpl": League("BPL", "Bangladesh Premier League", "Bangladesh", 7,
                  ("BPL", "#006a4e", "#fff", "#f42a41", "Bangladesh")),
    "lpl": League("LPL", "Lanka Premier League", "Sri Lanka", 1, ("LPL", "#1b3a8a", "#fff", "#ffbe29", "Sri Lanka")),
    "mlc": League("MLC", "Major League Cricket", "United States of America", 1,
                  ("MLC", "#002868", "#fff", "#bf0a30", "USA")),
    "ntb": League("T20 Blast", "T20 Blast (England)", "England", 1,
                  ("BLAST", "#0b1e5b", "#fff", "#e30613", "England")),
    "ssm": League("Super Smash", "Super Smash (New Zealand)", "New Zealand", 7,
                  ("SMASH", "#111", "#fff", "#2ee88a", "New Zealand")),
    "sma": League("SMAT", "Syed Mushtaq Ali Trophy (India)", "India", 7,
                  ("SMAT", "#0b3d91", "#fff", "#f7a823", "India"), league_season=False, side_level=True),
}
CODES: tuple[str, ...] = tuple(LEAGUES)


def zip_name(code: str) -> str:
    """Path of a league's Cricsheet zip, relative to data/raw."""
    return f"leagues/{code}_json.zip"


ZIPS: list[str] = [zip_name(c) for c in CODES]
HOME: dict[str, str] = {c: lg.home for c, lg in LEAGUES.items()}


def ui_info() -> list[dict]:
    """For the browser (/api/meta): label, long name and badge of each league, in order."""
    return [{"id": c, "label": lg.label, "long": lg.long, "badge": list(lg.badge)} for c, lg in LEAGUES.items()]
