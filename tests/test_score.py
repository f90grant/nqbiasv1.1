import copy
import datetime as dt

from bias import config as C
from bias.__main__ import stats
from bias.data import nq_levels
from bias.sample import DEMO_NOW, sample_snapshot, synthetic_bars
from bias.score import decide


def base():
    return sample_snapshot()


def test_levels_from_bars():
    lv = nq_levels(synthetic_bars(), DEMO_NOW)
    assert lv["pdl"] <= lv["pdc"] <= lv["pdh"]
    assert lv["onl"] <= lv["price"] <= lv["onh"]
    assert lv["on_range_avg10"] and lv["on_range_avg10"] > 0
    assert lv["prev_date"] == "2026-11-09"


def test_sample_is_long():
    r = decide(base())
    assert r["direction"] == "long" and r["score"] >= 3


def test_bearish_morning():
    s = base()
    nq = s["nq"]
    nq["price"] = nq["pdl"] - 50
    nq["onl"] = nq["price"] - 10
    nq["gap_pct"] = (nq["price"] / nq["pdc"] - 1) * 100
    for m in s["megacaps"]:
        m["chg_pct"] = -1.0
    s["vix"]["chg_pct"] = 9
    s["tnx"]["chg_bp"] = 7
    s["es"]["chg_pct"] = -0.8
    r = decide(s)
    assert r["call"] == "STRONG SHORT", r


def test_chop_morning_inside_day_fomc():
    s = base()
    nq = s["nq"]
    nq["price"] = (nq["pdh"] + nq["pdl"]) / 2
    nq["pdc"] = nq["price"] - 5
    nq["gap_pct"] = 0.02
    nq["onh"], nq["onl"] = nq["price"] + 40, nq["price"] - 40
    nq["on_range_avg10"] = 300
    for m in s["megacaps"]:
        m["chg_pct"] = 0.05
    s["vix"]["chg_pct"] = 0
    s["events"] = [{"time": "14:00", "title": "FOMC Statement", "impact": "High", "forecast": "", "previous": ""}]
    r = decide(s)
    assert r["direction"] == "chop"
    assert r["chop_score"] >= 2.5
    names = {f["name"] for f in r["chop_factors"]}
    assert {"Inside day", "Tight overnight", "Fed event"} <= names


def test_chop_overrides_lean():
    s = base()
    nq = s["nq"]
    nq["price"] = nq["pdh"] - 1             # inside range
    nq["gap_pct"] = 0.35                    # +1
    for m in s["megacaps"]:
        m["chg_pct"] = 0
    s["vix"]["chg_pct"] = 0
    nq["on_range_avg10"] = nq["on_range"] * 3   # tight ON
    s["events"] = [{"time": "14:00", "title": "FOMC Statement", "impact": "High", "forecast": "", "previous": ""}]
    r = decide(s)
    assert 1 <= r["score"] < 3 and r["call"] == "CHOP / NEUTRAL"


def test_missing_sources_do_not_crash():
    s = {"date": "2026-11-10", "nq": {}, "errors": []}
    r = decide(s)
    assert r["call"] == "CHOP / NEUTRAL" and r["levels"] == []


def test_stats():
    h = [{"direction": "long", "hit": True}, {"direction": "chop", "hit": False}, {"direction": "long"}]
    st = stats(h)
    assert st["n"] == 2 and st["hits"] == 1 and st["by_direction"]["long"]["hit_rate"] == 100


def test_parse_financialjuice_prints():
    from bias.data import parse_print
    p = parse_print("US Initial Jobless Claims Actual: 221K (Forecast: 225K, Previous: 219K)")
    assert p["actual"] == 221 and p["forecast"] == 225 and p["unit"] == "K" and p["surprise"] == -4
    p = parse_print("US Core PPI YoY Actual -0.1% (Forecast 0.1%, Previous 0.2%)")
    assert p["actual"] == -0.1 and p["previous"] == 0.2
    assert parse_print("Nvidia shares up 3% premarket") is None
