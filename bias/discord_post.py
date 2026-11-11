"""Posts to Discord through a channel webhook (free, no bot hosting needed)."""
from __future__ import annotations

import requests

from . import config as C

COLORS = {"long": 0x22C55E, "short": 0xEF4444, "chop": 0x9CA3AF}


def _trim(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def bias_embed(rep: dict) -> dict:
    r, snap = rep["result"], rep["snapshot"]
    nq = snap.get("nq") or {}
    levels = "\n".join(f"`{l['name']:<6}` {l['price']:,.2f}" for l in r["levels"]) or "n/a"
    drivers = "\n".join(f"{'🟢' if f['points'] > 0 else '🔴'} {f['name']}: {f['value']}"
                        for f in r["factors"] if f["points"]) or "No strong drivers"
    chop = "\n".join(f"⚠️ {f['name']}: {f['value']}" for f in r["chop_factors"]) or "None"
    events = "\n".join(f"**{e['time']}** {e['title']} ({e['impact']})"
                       for e in snap.get("events") or []) or "No major USD data"
    earn = ", ".join(f"{e['sym']} ({e['when']})" for e in snap.get("earnings") or []) or "None on watchlist"
    prints = "\n".join(f"{p['name']}: **{p['actual']:g}{p['unit']}** vs {p['forecast']:g}{p['unit']} fcst"
                       for p in snap.get("prints") or []) or "None yet"
    squawk = "\n".join(f"`{h['time'][11:16]}` {h['title']}" for h in (snap.get("squawk") or [])[:6]
                        if "print" not in h) or "No FinancialJuice headlines"
    fields = [
        {"name": "Key levels", "value": levels, "inline": True},
        {"name": "Drivers", "value": _trim(drivers, 1000), "inline": True},
        {"name": "Chop risk", "value": _trim(chop, 1000), "inline": False},
        {"name": "Today's events (ET)", "value": _trim(events, 1000), "inline": False},
        {"name": "Data prints (FinancialJuice)", "value": _trim(prints, 1000), "inline": False},
        {"name": "Squawk (FinancialJuice)", "value": _trim(squawk, 1000), "inline": False},
        {"name": "Earnings", "value": _trim(earn, 1000), "inline": False},
        {"name": "Plan", "value": _trim("\n".join(f"• {p}" for p in r["playbook"]), 1000) or "n/a",
         "inline": False},
    ]
    desc = _trim(rep["narrative"]["text"], 1800)
    title = f"NQ Daily Bias: {r['call']}  (score {r['score']:+g}, {r['confidence']}% conf)"
    embed = {"title": title, "description": desc, "color": COLORS[r["direction"]], "fields": fields,
             "footer": {"text": f"{rep['date']} • NQ {nq.get('price', 0):,.2f} • Context only, not trade advice"}}
    if C.DASHBOARD_URL:
        embed["url"] = C.DASHBOARD_URL
    return embed


def grade_embed(entry: dict, stats: dict) -> dict:
    ok = entry["hit"]
    return {
        "title": f"NQ Close Grade {entry['date']}: called {entry['call']} → {entry['outcome'].upper()} "
                 f"{'✅' if ok else '❌'}",
        "description": (f"RTH open {entry['open']:,.2f} → close {entry['close']:,.2f} "
                        f"({entry['move_pct']:+.2f}%), range {entry['range_pts']:.0f} pts.\n"
                        f"Track record: **{stats['hits']}/{stats['n']} ({stats['hit_rate']}%)** "
                        f"over graded days."),
        "color": 0x22C55E if ok else 0xEF4444,
    }


def send(embed: dict) -> bool:
    if not C.DISCORD_WEBHOOK:
        print("[discord] DISCORD_WEBHOOK_URL not set; skipping post")
        return False
    r = requests.post(C.DISCORD_WEBHOOK, json={"username": "NQ Bias", "embeds": [embed]}, timeout=20)
    if r.status_code >= 300:
        print("[discord] error", r.status_code, r.text[:300])
        return False
    return True
