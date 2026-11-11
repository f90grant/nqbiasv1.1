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


def test_change_since_close_uses_4pm_reference_and_freshness():
    from bias.data import change_since_close
    bars = synthetic_bars()
    r = change_since_close(bars, DEMO_NOW)
    t = bars.index.time
    prev = bars[(bars.index.date == dt.date(2026, 11, 9)) & (t < dt.time(16, 0))]["Close"].iloc[-1]
    assert r["fresh"] and abs(r["prev"] - prev) < 1e-9
    # no bar from today yet -> not fresh, and no fake 0.00% "move" is claimed as real
    old = bars[bars.index.date < DEMO_NOW.date()]
    r2 = change_since_close(old, DEMO_NOW)
    assert r2["fresh"] is False and r2["chg_pct"] == 0.0


def test_fed_speaker_is_not_a_fed_event():
    s = base()
    s["events"] = [{"time": "13:00", "title": "FOMC Member Waller Speaks", "impact": "Medium",
                    "forecast": "", "previous": ""}]
    assert "Fed event" not in {f["name"] for f in decide(s)["chop_factors"]}
    s["events"] = [{"time": "14:00", "title": "Federal Funds Rate", "impact": "High", "forecast": "", "previous": ""}]
    assert "Fed event" in {f["name"] for f in decide(s)["chop_factors"]}


def test_stale_quote_and_holiday_are_flagged():
    s = base()
    s["nq"]["stale_min"] = 600
    s["events"] = [{"time": "00:00", "title": "Bank Holiday", "impact": "Holiday", "forecast": "", "previous": ""}]
    r = decide(s)
    assert any("min old" in f for f in s["flags"])
    assert "US holiday" in {f["name"] for f in r["chop_factors"]}


def test_unfresh_macro_scores_zero():
    s = base()
    s["vix"] = {"last": 17.3, "prev": 17.3, "chg_pct": 0.0, "fresh": False}
    f = next(f for f in decide(s)["factors"] if f["name"] == "VIX")
    assert f["points"] == 0 and "No VIX quote" in f["note"]


def test_playbook_levels_are_consistent():
    s = base()
    r = decide(s)
    price = s["nq"]["price"]
    import re
    hold = float(re.search(r"holds above \w+ (\d+)", r["playbook"][0]).group(1))
    wrong = float(re.search(r"back below \w+ (\d+)", " ".join(r["playbook"])).group(1))
    assert hold == wrong < price


def test_relevance_uses_word_boundaries():
    from bias.data import MOVERS, is_us_print, parse_print
    assert MOVERS.search("US CPI hotter than expected") and MOVERS.search("Nvidia guidance raised")
    assert not MOVERS.search("Thai corporate bonus plan in focus")
    assert is_us_print(parse_print("US CPI YoY Actual 3.1% (Forecast 3.0%, Previous 2.9%)"))
    assert not is_us_print(parse_print("German ZEW Actual 12.1 (Forecast 10.0, Previous 9.5)"))


def test_discord_embed_fits_limit():
    from bias.discord_post import _size, bias_embed
    s = base()
    s["squawk"] = [dict(s["squawk"][2], title="x" * 400) for _ in range(30)]
    s["events"] = [{"time": "10:00", "title": "y" * 200, "impact": "High", "forecast": "", "previous": ""}] * 12
    r = decide(s)
    e = bias_embed({"date": "2026-11-10", "snapshot": s, "result": r, "narrative": {"text": "z" * 5000}})
    assert _size(e) <= 6000 and all(0 < len(f["value"]) <= 1024 for f in e["fields"])


def test_backup_run_never_overwrites_todays_call(tmp_path, monkeypatch):
    import json, types
    import bias.__main__ as M
    monkeypatch.setattr(C, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(C, "DISCORD_WEBHOOK", "")
    today = dt.datetime.now(C.ET).date().isoformat()
    saved = {"date": today, "posted": False, "snapshot": {}, "result": {"call": "LEAN LONG"}}
    (tmp_path / "latest.json").write_text(json.dumps(saved))
    monkeypatch.setattr(M, "_in_window", lambda *a: True)
    import bias.data as D
    monkeypatch.setattr(D, "collect", lambda now: (_ for _ in ()).throw(AssertionError("must not refetch")))
    assert M.run(types.SimpleNamespace(force=False, sample=False, no_discord=False)) == 0
    assert json.loads((tmp_path / "latest.json").read_text()) == saved


def test_gemini_key_never_in_url(monkeypatch):
    import bias.narrative as N
    seen = {}

    class R:
        status_code = 403
    def post(url, **kw):
        seen["url"], seen["kw"] = url, kw
        return R()
    monkeypatch.setattr(C, "GEMINI_KEY", "SECRET123")
    monkeypatch.setattr(C, "ANTHROPIC_KEY", "")
    monkeypatch.setattr(N.requests, "post", post)
    s = base(); r = decide(s)
    out = N.write(s, r)
    assert out["source"] == "template"
    assert "SECRET123" not in seen["url"] and "params" not in seen["kw"]
    assert not any("SECRET123" in e for e in s["errors"])
