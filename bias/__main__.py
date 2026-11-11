"""CLI.

  python -m bias run            pre-open brief (8:45 to 9:28 ET window, once per day)
  python -m bias grade          post-close grading (16:05 to 19:00 ET window)
  python -m bias run --sample   offline demo with built-in sample data
  add --force to ignore the time window, --no-discord to skip posting
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import config as C
from . import discord_post, narrative, score


def _in_window(now: dt.datetime, window: tuple[str, str]) -> bool:
    hm = now.strftime("%H:%M")
    return now.weekday() < 5 and window[0] <= hm <= window[1]


def _path(*p):
    return os.path.join(C.DATA_DIR, *p)


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)


def stats(history: list[dict]) -> dict:
    graded = [h for h in history if "hit" in h]
    out = {"n": len(graded), "hits": sum(h["hit"] for h in graded)}
    out["hit_rate"] = round(100 * out["hits"] / out["n"]) if out["n"] else 0
    by = {}
    for d in ("long", "short", "chop"):
        g = [h for h in graded if h["direction"] == d]
        by[d] = {"n": len(g), "hits": sum(h["hit"] for h in g),
                 "hit_rate": round(100 * sum(h["hit"] for h in g) / len(g)) if g else None}
    out["by_direction"] = by
    return out


def run(args):
    now = dt.datetime.now(C.ET)
    if not (args.force or args.sample) and not _in_window(now, C.RUN_WINDOW):
        print(f"outside run window ({now:%a %H:%M} ET); use --force to override")
        return 0
    prev = _load(_path("latest.json"), {})
    if not (args.force or args.sample) and prev.get("date") == now.date().isoformat() \
            and not prev.get("snapshot", {}).get("sample"):
        # Today's call is already locked in. Backup runs never overwrite it (that would let
        # later data leak into a graded call); they only retry a Discord post that failed.
        if not prev.get("posted") and C.DISCORD_WEBHOOK and not args.no_discord:
            prev["posted"] = discord_post.send(discord_post.bias_embed(prev))
            _save(_path("latest.json"), prev)
            print("retried Discord post:", "ok" if prev["posted"] else "failed")
        else:
            print("today's brief already exists; nothing to do")
        return 0
    if args.sample:
        from .sample import sample_snapshot
        snap = sample_snapshot()
    else:
        from . import data
        snap = data.collect(now)
        if not snap.get("nq"):
            print("NQ data unavailable; aborting", snap["errors"])
            return 1

    res = score.decide(snap)
    narr = narrative.write(snap, res)
    rep = {"date": snap["date"], "generated": now.isoformat(), "snapshot": snap,
           "result": res, "narrative": narr}

    rep["posted"] = False

    if args.sample:
        from .sample import sample_history
        history = sample_history()
    else:
        history = _load(_path("history.json"), [])
    old = next((h for h in history if h["date"] == rep["date"]), {})
    history = [h for h in history if h["date"] != rep["date"]]
    entry = {"date": rep["date"], "call": res["call"], "direction": res["direction"],
             "score": res["score"], "chop_score": res["chop_score"], "confidence": res["confidence"],
             "headline_tone": narr["headline_tone"], "price_at_call": (snap.get("nq") or {}).get("price"),
             "called_at": now.strftime("%H:%M"),
             # per-factor points, so later we can test which factors actually predict the day
             "factors": {f["name"]: f["points"] for f in res["factors"] + res["chop_factors"]}}
    entry.update({k: v for k, v in old.items() if k not in entry})  # keep grade if re-run
    if "outcome" in entry:
        entry["hit"] = entry["direction"] == entry["outcome"]
    history.append(entry)
    history.sort(key=lambda h: h["date"])

    if not (args.no_discord or args.sample):
        rep["posted"] = discord_post.send(discord_post.bias_embed(rep))
    rep["stats"] = stats(history)

    if args.sample:  # never touch the real track record with fake days
        rep["sample_history"] = history
        _save(_path("latest.json"), rep)
    else:
        _save(_path("latest.json"), rep)
        _save(_path("history.json"), history)
        _save(_path("archive", f"{rep['date']}.json"), rep)
    print(f"{rep['date']}  {res['call']}  score {res['score']:+g}  chop {res['chop_score']:g}  "
          f"conf {res['confidence']}%  narrative={narr['source']}")
    for e in snap.get("errors", []):
        print("  warn:", e)
    return 0


def grade(args):
    now = dt.datetime.now(C.ET)
    if not args.force and not _in_window(now, C.GRADE_WINDOW):
        print(f"outside grade window ({now:%a %H:%M} ET)")
        return 0
    from . import data
    history = _load(_path("history.json"), [])
    today = now.date().isoformat()
    entry = next((h for h in history if h["date"] == today), None)
    if not entry:
        print("no bias call logged for today; nothing to grade")
        return 0
    try:
        rth = data.rth_result(now)
    except Exception as e:
        print(f"could not grade today ({e}); leaving the call ungraded")
        return 0
    move = (rth["close"] / rth["open"] - 1) * 100
    outcome = "long" if move >= C.OUTCOME_PCT else "short" if move <= -C.OUTCOME_PCT else "chop"
    was_graded = "hit" in entry
    entry.update({"open": rth["open"], "close": rth["close"], "high": rth["high"], "low": rth["low"],
                  "move_pct": round(move, 3), "range_pts": round(rth["high"] - rth["low"], 2),
                  "outcome": outcome, "hit": entry["direction"] == outcome})
    _save(_path("history.json"), history)
    st = stats(history)
    latest = _load(_path("latest.json"), {})
    if latest.get("date") == today:
        latest["stats"] = st
        latest["grade"] = entry
        _save(_path("latest.json"), latest)
    if not args.no_discord and not was_graded:
        discord_post.send(discord_post.grade_embed(entry, st))
    print(f"graded {today}: called {entry['direction']} got {outcome} ({move:+.2f}%)  hit={entry['hit']}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="bias")
    ap.add_argument("cmd", choices=["run", "grade"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--no-discord", action="store_true")
    args = ap.parse_args()
    return run(args) if args.cmd == "run" else grade(args)


if __name__ == "__main__":
    sys.exit(main())
