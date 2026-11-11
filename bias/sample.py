"""Synthetic but realistic data for offline demos and tests. Not real prices."""
from __future__ import annotations

import datetime as dt
import random

import numpy as np
import pandas as pd

from . import config as C
from .data import nq_levels, parse_print

DEMO_NOW = dt.datetime(2026, 11, 10, 8, 52, tzinfo=C.ET)


def synthetic_bars(now=DEMO_NOW, start=25600.0, days=14, seed=7, drift_last_on=0.0012):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(now - dt.timedelta(days=days), now, freq="15min", tz=C.ET)
    idx = idx[[not (ts.weekday() == 5 or (ts.weekday() == 4 and ts.hour >= 17)
                    or (ts.weekday() == 6 and ts.hour < 18)) for ts in idx]]
    rets = rng.normal(0, 0.0012, len(idx))
    # last overnight session drifts up (a gap-up morning)
    on_start = dt.datetime.combine(now.date() - dt.timedelta(days=1), dt.time(17), C.ET)
    mask = np.array([ts > on_start for ts in idx])
    rets[mask] += drift_last_on / max(mask.sum(), 1) * 3
    close = start * np.exp(np.cumsum(rets))
    open_ = np.r_[start, close[:-1]]
    spread = np.abs(rng.normal(0, 0.0009, len(idx))) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close}, index=idx)


def sample_snapshot() -> dict:
    nq = nq_levels(synthetic_bars(), DEMO_NOW)
    snap = {
        "asof": DEMO_NOW.isoformat(), "date": DEMO_NOW.date().isoformat(), "sample": True,
        "errors": [],
        "nq": nq,
        "es": {"last": 6890.25, "prev": 6861.5, "chg_pct": 0.42},
        "vix": {"last": 16.4, "prev": 17.3, "chg_pct": -5.2},
        "tnx": {"last": 4.08, "prev": 4.11, "chg_bp": -3.0},
        "dxy": {"last": 99.41, "prev": 99.52, "chg_pct": -0.11},
        "megacaps": [
            {"sym": s, "weight": w, "last": 0, "chg_pct": c}
            for (s, w), c in zip(C.MEGACAPS.items(),
                                 [2.8, 0.6, 0.3, 0.9, 1.7, 0.4, -0.2, -0.1, -1.1, 0.2, 0.1, 2.2, 1.4])
        ],
        "events": [
            {"time": "08:30", "title": "Core PPI m/m", "impact": "High", "forecast": "0.2%", "previous": "0.3%"},
            {"time": "10:00", "title": "Wholesale Inventories m/m", "impact": "Medium", "forecast": "0.1%", "previous": "0.0%"},
            {"time": "14:00", "title": "Fed Governor Speaks", "impact": "Medium", "forecast": "", "previous": ""},
        ],
        "earnings": [
            {"sym": "AMD", "when": "last night after close", "eps_est": 1.17, "eps_actual": None,
             "rev_est": None, "rev_actual": None},
            {"sym": "CSCO", "when": "today after close", "eps_est": 0.98, "eps_actual": None,
             "rev_est": None, "rev_actual": None},
        ],
        "squawk": [
            {"title": t, "source": "FinancialJuice", "time": DEMO_NOW.replace(hour=h, minute=mi).isoformat(),
             "url": "", "fj": True, **({"print": parse_print(t)} if parse_print(t) else {})}
            for h, mi, t in [
                (8, 31, "US Core PPI MoM Actual 0.1% (Forecast 0.2%, Previous 0.3%) (SAMPLE)"),
                (8, 30, "US PPI YoY Actual 2.4% (Forecast 2.6%, Previous 2.7%) (SAMPLE)"),
                (8, 12, "Fed's Waller: Further cuts appropriate if inflation keeps cooling (SAMPLE)"),
                (7, 45, "Nvidia +2.8% premarket, chip names firm after AMD results (SAMPLE)"),
                (6, 2, "China October exports beat expectations (SAMPLE)"),
            ]
        ],
        "headlines": [
            {"title": "Stock futures rise as chipmakers rally after AMD beat (SAMPLE)", "source": "Sample",
             "time": DEMO_NOW.isoformat(), "url": "", "relevant": True},
            {"title": "Producer prices come in softer than expected (SAMPLE)", "source": "Sample",
             "time": DEMO_NOW.isoformat(), "url": "", "relevant": True},
            {"title": "Treasury yields slip ahead of Fed speakers (SAMPLE)", "source": "Sample",
             "time": DEMO_NOW.isoformat(), "url": "", "relevant": True},
        ],
    }
    snap["prints"] = [dict(h["print"], time=h["time"]) for h in snap["squawk"] if "print" in h]
    return snap


def sample_history(n: int = 24, seed: int = 3) -> list[dict]:
    random.seed(seed)
    out, d = [], DEMO_NOW.date() - dt.timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            direction = random.choice(["long", "long", "short", "chop", "chop"])
            outcome = direction if random.random() < 0.25 else random.choice(["long", "short", "chop"])
            o = 25000 + random.uniform(-400, 600)
            mv = {"long": random.uniform(0.4, 1.4), "short": -random.uniform(0.4, 1.4),
                  "chop": random.uniform(-0.35, 0.35)}[outcome]
            sc = {"long": random.choice([1, 1.5, 2, 3]), "short": random.choice([-1, -1.5, -2.5]),
                  "chop": random.choice([0, 0.5, -0.5])}[direction]
            call = {"long": "LEAN LONG" if sc < 3 else "STRONG LONG",
                    "short": "LEAN SHORT", "chop": "CHOP / NEUTRAL"}[direction]
            out.append({"date": d.isoformat(), "call": call, "direction": direction, "score": sc,
                        "chop_score": random.choice([0, 0.5, 1, 2.5]), "confidence": random.randint(25, 70),
                        "headline_tone": "n/a", "price_at_call": o, "open": o, "close": o * (1 + mv / 100),
                        "high": o * 1.009, "low": o * 0.992, "move_pct": round(mv, 3),
                        "range_pts": round(o * 0.017, 2), "outcome": outcome, "hit": direction == outcome})
        d -= dt.timedelta(days=1)
    return sorted(out, key=lambda h: h["date"])
