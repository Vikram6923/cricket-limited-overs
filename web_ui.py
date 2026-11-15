"""Browser UI for the limited-overs simulator (build-order step 5).

    python web_ui.py              # opens http://localhost:5070
    python web_ui.py --no-browser --port 5071
    python web_ui.py --lan        # also reachable from other devices on the same Wi-Fi
    python web_ui.py --public     # a hosted site: every visitor gets their own runs (see README "Hosting it")

Plain Flask, a background job per visitor, the page polls /api/status (no websockets, no CDN scripts, works
offline). The engine is called directly as a library. Modes: Match / Series, Tournament, Classic Series and
Classic Tournament (a nation over a year range, rated on those years), League Season, Fantasy Draft, Auction,
Career (a league season after season, engine/career.py, or a Mushtaq Ali Trophy state, engine/state_career.py,
optionally with the IPL played alongside, engine/ipl_link.py;
kept in results/careers/<id>/), Team Builder.
Two players (docs/multiplayer_design.md): one match, each side captained by a person on their own device; any
number of rooms at once.
On your own computer there is one user: saved teams live in data/teams.json (created from data/teams_default.json
on first run) and the last results in results/last/, so they survive a restart. With --public each browser is a
visitor (a cookie) with its own job, draft, auction, teams and results under results/visitors/<id>/.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import types
import webbrowser

from server import core
from server.core import *  # noqa: F401,F403
from server.runs import *  # noqa: F401,F403
from server.draft import *  # noqa: F401,F403
from server.auction import *  # noqa: F401,F403
from server.rooms import *  # noqa: F401,F403
from server.careers import *  # noqa: F401,F403
from server.saved import *  # noqa: F401,F403


class _Settings(types.ModuleType):
    """web_ui.LAST = folder (and the other folders in server/core.py) changes where the server keeps things, as it
    did when the server was this one file: the new value is passed on to core.py, which is what the server reads."""

    def __setattr__(self, name, value):
        if hasattr(core, name):
            setattr(core, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Settings


def serve_public(host: str, port: int, password: str | None, max_jobs: int) -> None:
    """--public: a hosted site. Every browser is its own visitor; one process (the runs live in memory) with a
    thread per request, behind a proxy that terminates HTTPS (Cloudflare Tunnel, Fly.io, Render...)."""
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.config.update(MULTI=True, PASSWORD=password or None, MAX_JOBS=max_jobs,
                      LIMITS={"teams": 100, "saved": 30, "careers": 10}, MAX_CONTENT_LENGTH=2 << 20)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # https links and secure cookies
    threading.Thread(target=_reaper, daemon=True).start()
    print(f"Limited-overs simulator, public mode, on http://{host}:{port}  (Ctrl+C to stop)")
    print(f"  every visitor gets their own runs (in {VISITORS_DIR}); at most {max_jobs} simulations at once; "
          + ("password required" if password else "NO password: set SITE_PASSWORD to require one"), flush=True)
    try:
        from waitress import serve
    except ImportError:
        print("  (waitress is not installed: using Flask's own server. pip install waitress)")
        app.run(host=host, port=port, threaded=True)
        return
    # waitress would drop the proxy's X-Forwarded-* headers; ProxyFix above reads them (one proxy in front)
    serve(app, host=host, port=port, threads=32, ident=None, clear_untrusted_proxy_headers=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 5070))  # 5060/5061: blocked (SIP)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--lan", action="store_true",
                    help="also accept connections from other devices on the local network (no login: "
                         "anyone on the same network can use it)")
    ap.add_argument("--public", action="store_true",
                    help="run as a hosted site: each visitor gets their own runs, saved teams and careers; "
                         "password from SITE_PASSWORD, simulation limit from MAX_JOBS (default 6)")
    ap.add_argument("--host", default=None,
                    help="address to listen on (--public: 0.0.0.0, e.g. in Docker; use 127.0.0.1 behind a tunnel "
                         "on the same computer)")
    ap.add_argument("--jobs", type=int, default=None,
                    help="processes for league matches nobody captains (same results for any number). Default: "
                         "up to 4 on your own computer, 1 with --public (each process holds the ratings, about "
                         "150 MB)")
    args = ap.parse_args(argv)
    from engine.tournament import set_jobs
    set_jobs(args.jobs if args.jobs is not None else 1 if args.public else min(4, (os.cpu_count() or 2) - 1))
    if args.public:
        serve_public(args.host or "0.0.0.0", args.port, os.environ.get("SITE_PASSWORD"),
                     int(os.environ.get("MAX_JOBS") or 6))
        return 0
    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Limited-overs simulator UI on {url}  (Ctrl+C to stop)")
    if args.lan:
        ips = lan_addresses()
        if ips:
            print("Other devices on this network can open: "
                  + ", ".join(f"http://{ip}:{args.port}" for ip in ips))
        else:
            print("No network address found; is this computer connected to a network?")
        print("If they can't connect, allow Python through Windows Firewall for Private networks "
              "and make sure the Wi-Fi is set to Private.")
    app.config["LAN"] = args.lan            # two-player rooms show join links only when others can connect
    app.run(host=args.host or ("0.0.0.0" if args.lan else "127.0.0.1"), port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
