"""What a Test player is worth, for the fantasy draft and the auction (engine/draft.py, engine/auction.py).

Limited overs values a player by the balls his batting slot faces and the share of a quota he bowls
(engine/selection.py); a Test has neither. Here, in runs a match against an average player of the era:
- batting: his expected average (the era's runs per wicket x his runs index / his dismissal index) less the era's,
  times the innings a player has in a Test;
- bowling: the balls he usually bowls in a match x (the wickets he takes above an average bowler, each worth the
  era's runs per wicket, less the runs he concedes above one).
Not fitted: INNINGS (a side loses about 16 wickets a Test, so a player is out about one and a half times).

In an auction a player has one value, batting plus bowling. A specialist bowler takes a bowler's place in the
XI, so there his batting is measured against the average specialist bowler's, not the average player's
(bowler_batting: read from the ratings). Without it a great bowler who cannot bat is worth less than an ordinary
batter (McGrath was the 68th lot of the 1990s). The draft ranks batting and bowling apart and does not need it.
"""
from __future__ import annotations

from functools import lru_cache

from .data import Player, player, ratings
from .test_captain import group

PHASE = "all"
INNINGS = 1.5


def is_bowler(p: Player) -> bool:
    """A specialist bowler, as the Test captain groups them."""
    return bool(p.rated_bowl) and group(p) != "part"


@lru_cache(maxsize=1)
def bowler_batting() -> float:
    """The batting of the average specialist Test bowler as a share of an average player's (runs index over
    dismissal index, weighted by the balls he bowled): about 0.6."""
    num = den = 0.0
    for pid in ratings("test")["players"]:
        p = player("test", pid)
        if is_bowler(p):
            ix = p.bat[PHASE]
            num += p.bowl_balls * ix["runs"] / max(ix["wkt"], 0.2)
            den += p.bowl_balls
    return num / den if den else 1.0


def bowler_place(base: dict) -> float:
    """Runs a match to add to a specialist bowler's batting value, so that it is against a bowler's batting."""
    b0 = base[PHASE]
    return INNINGS * (b0["runs"] / max(b0["wkt"], 1e-6)) * (1.0 - bowler_batting())


def value_parts(p: Player, base: dict) -> tuple[float, float]:
    """(batting, bowling) in runs a match above an average player. base: the era's baseline (engine.data)."""
    b0 = base[PHASE]
    par = b0["runs"] / max(b0["wkt"], 1e-6)
    bat = 0.0
    if p.rated_bat:
        ix = p.bat[PHASE]
        bat = INNINGS * par * (ix["runs"] / max(ix["wkt"], 0.2) - 1.0)
    bowl = 0.0
    if p.rated_bowl:
        ix = p.bowl[PHASE]
        bowl = 6 * p.bowl_overs_per_match * b0["runs"] * (ix["wkt"] - ix["runs"])
    return bat, bowl
