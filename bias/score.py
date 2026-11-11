"""Transparent rule-based bias score for NQ.

Every factor returns points and a plain-English note so you can see *why* the
call is what it is, and so the rules can be graded against real outcomes.
Positive = long, negative = short. A separate chop score decides "stand aside".
"""
from __future__ import annotations

from . import config as C


def _f(name, value, pts, note, group="direction"):
    return {"name": name, "value": value, "points": pts, "note": note, "group": group}


def factors(s: dict) -> tuple[list[dict], list[dict]]:
    """Returns (direction_factors, chop_factors)."""
    d, chop = [], []
    nq = s.get("nq") or {}

    if nq:
        price, gap = nq["price"], nq["gap_pct"]
        # 1. Gap vs prior RTH close
        if gap >= C.GAP_PCT:
            d.append(_f("Gap", f"{gap:+.2f}%", 1, "Gapping up over prior close"))
        elif gap <= -C.GAP_PCT:
            d.append(_f("Gap", f"{gap:+.2f}%", -1, "Gapping down under prior close"))
        else:
            d.append(_f("Gap", f"{gap:+.2f}%", 0, "Flat open, no gap edge"))

        # 2. Location vs prior day range
        if price > nq["pdh"]:
            d.append(_f("Location", "Above PDH", 1, "Trading above prior-day high: buyers in control"))
        elif price < nq["pdl"]:
            d.append(_f("Location", "Below PDL", -1, "Trading below prior-day low: sellers in control"))
        else:
            d.append(_f("Location", "Inside prior range", 0, "Inside yesterday's range"))
            chop.append(_f("Inside day", "yes", 1, "Opening inside prior range: rotation is common", "chop"))

        # 3. Where price sits in the overnight range
        rng = nq["onh"] - nq["onl"]
        if rng > 0:
            pos = (price - nq["onl"]) / rng
            if pos >= 0.75:
                d.append(_f("Overnight trend", f"{pos:.0%} of ON range", 0.5, "Holding near overnight high"))
            elif pos <= 0.25:
                d.append(_f("Overnight trend", f"{pos:.0%} of ON range", -0.5, "Pressing overnight low"))
            else:
                d.append(_f("Overnight trend", f"{pos:.0%} of ON range", 0, "Mid overnight range"))

        # chop: compressed overnight
        avg = nq.get("on_range_avg10")
        if avg and rng < C.ON_RANGE_TIGHT * avg:
            chop.append(_f("Tight overnight", f"{rng:.0f} vs {avg:.0f} avg pts", 1,
                           "Overnight range compressed: low participation", "chop"))

    # 4. Mega-cap breadth
    mc = s.get("megacaps") or []
    if mc:
        tw = sum(m["weight"] for m in mc)
        b = sum(m["chg_pct"] * m["weight"] for m in mc) / tw
        s["breadth_pct"] = b
        up = sum(1 for m in mc if m["chg_pct"] > 0)
        val = f"{b:+.2f}% wtd, {up}/{len(mc)} green"
        if b >= C.BREADTH_PCT_STRONG:
            d.append(_f("Mega-cap breadth", val, 1, "Generals leading higher premarket"))
        elif b >= C.BREADTH_PCT_MILD:
            d.append(_f("Mega-cap breadth", val, 0.5, "Mega-caps mildly bid"))
        elif b <= -C.BREADTH_PCT_STRONG:
            d.append(_f("Mega-cap breadth", val, -1, "Generals selling off premarket"))
        elif b <= -C.BREADTH_PCT_MILD:
            d.append(_f("Mega-cap breadth", val, -0.5, "Mega-caps mildly offered"))
        else:
            d.append(_f("Mega-cap breadth", val, 0, "Mega-caps mixed"))
        movers = sorted(mc, key=lambda m: abs(m["chg_pct"]), reverse=True)
        s["top_movers"] = movers[:5]

    # 5. VIX
    vix = s.get("vix") or {}
    if vix:
        v, ch = vix["last"], vix["chg_pct"]
        val = f"{v:.1f} ({ch:+.1f}%)"
        if ch >= C.VIX_SPIKE_PCT:
            d.append(_f("VIX", val, -1, "Volatility bid: risk-off"))
        elif ch <= C.VIX_DROP_PCT:
            d.append(_f("VIX", val, 0.5, "Volatility crushed: risk-on"))
        else:
            d.append(_f("VIX", val, 0, "VIX steady"))
        if v >= C.VIX_HIGH_LEVEL:
            s.setdefault("flags", []).append("VIX above 25: expect wide, whippy ranges. Size down.")

    # 6. 10-year yield (NQ is rate-sensitive)
    tnx = s.get("tnx") or {}
    if tnx:
        bp = tnx["chg_bp"]
        val = f"{tnx['last']:.2f}% ({bp:+.1f}bp)"
        if bp >= C.YIELD_BP:
            d.append(_f("10Y yield", val, -0.5, "Yields rising: headwind for tech"))
        elif bp <= -C.YIELD_BP:
            d.append(_f("10Y yield", val, 0.5, "Yields falling: tailwind for tech"))
        else:
            d.append(_f("10Y yield", val, 0, "Yields flat"))

    # 7. Dollar
    dxy = s.get("dxy") or {}
    if dxy:
        ch = dxy["chg_pct"]
        val = f"{dxy['last']:.2f} ({ch:+.2f}%)"
        if ch >= C.DXY_PCT:
            d.append(_f("Dollar (DXY)", val, -0.5, "Strong dollar: tightening conditions"))
        elif ch <= -C.DXY_PCT:
            d.append(_f("Dollar (DXY)", val, 0.5, "Weak dollar: supportive"))
        else:
            d.append(_f("Dollar (DXY)", val, 0, "Dollar flat"))

    # chop: NQ and ES disagree
    es = s.get("es") or {}
    if es and nq:
        if es["chg_pct"] * nq["gap_pct"] < 0 and abs(es["chg_pct"]) > 0.1 and abs(nq["gap_pct"]) > 0.1:
            chop.append(_f("NQ/ES divergence", f"NQ {nq['gap_pct']:+.2f}% / ES {es['chg_pct']:+.2f}%",
                           1, "Indexes disagree: rotation, not trend", "chop"))

    # chop: signals fighting each other
    pos = sum(f["points"] for f in d if f["points"] > 0)
    neg = -sum(f["points"] for f in d if f["points"] < 0)
    if pos >= 1.5 and neg >= 1.5:
        chop.append(_f("Mixed signals", f"+{pos:g} / -{neg:g}", 1, "Bull and bear factors cancelling", "chop"))

    # chop: event risk later in the session
    for e in s.get("events") or []:
        t, title = e["time"], e["title"].lower()
        if "fomc" in title or "federal funds" in title or "fed chair" in title or "powell" in title:
            if t >= "12:00":
                chop.append(_f("Fed event", f"{t} {e['title']}", 1.5,
                               "Fed later today: chop into the release is typical", "chop"))
                break
    late = [e for e in (s.get("events") or []) if e["impact"] == "High" and "09:30" <= e["time"] <= "15:30"]
    if late and not any(c["name"] == "Fed event" for c in chop):
        e = late[0]
        chop.append(_f("Data in session", f"{e['time']} {e['title']}", 0.5,
                       "High-impact release during RTH: first move may reverse", "chop"))
    return d, chop


def decide(s: dict) -> dict:
    d, chop = factors(s)
    score = round(sum(f["points"] for f in d), 2)
    chop_score = round(sum(f["points"] for f in chop), 2)

    if score >= 3:
        call = "STRONG LONG"
    elif score >= 1:
        call = "LEAN LONG"
    elif score <= -3:
        call = "STRONG SHORT"
    elif score <= -1:
        call = "LEAN SHORT"
    else:
        call = "CHOP / NEUTRAL"

    # Chop overrides a weak lean; a strong lean gets downgraded one notch
    if chop_score >= 2.5 and abs(score) < 3:
        call = "CHOP / NEUTRAL"
    elif chop_score >= 2.5:
        call = call.replace("STRONG", "LEAN")

    direction = "long" if "LONG" in call else "short" if "SHORT" in call else "chop"
    confidence = max(5, min(95, round(abs(score) / 5 * 100 - chop_score * 12)))
    if direction == "chop":
        confidence = max(5, min(95, round(30 + chop_score * 15 - abs(score) * 5)))

    nq = s.get("nq") or {}
    levels = []
    if nq:
        mid = (nq["pdh"] + nq["pdl"]) / 2
        for name, v in (("PDH", nq["pdh"]), ("ONH", nq["onh"]), ("PDC", nq["pdc"]),
                        ("PD Mid", mid), ("ONL", nq["onl"]), ("PDL", nq["pdl"])):
            levels.append({"name": name, "price": round(v, 2)})
        levels.sort(key=lambda x: -x["price"])

    return {"score": score, "chop_score": chop_score, "call": call, "direction": direction,
            "confidence": confidence, "factors": d, "chop_factors": chop, "levels": levels,
            "playbook": playbook(direction, nq, s)}


def playbook(direction: str, nq: dict, s: dict) -> list[str]:
    """Plain if/then plan. Context for your own setups, not trade signals."""
    if not nq:
        return []
    p = []
    if direction == "long":
        p.append(f"Favor longs while above {max(nq['pdc'], nq['onl']):.0f}; look for pullbacks to ONH/PDH to hold as support.")
        p.append(f"Bias invalidated on acceptance back below {nq['onl']:.0f} (ONL).")
    elif direction == "short":
        p.append(f"Favor shorts while below {min(nq['pdc'], nq['onh']):.0f}; look for rallies into ONL/PDL to fail.")
        p.append(f"Bias invalidated on acceptance back above {nq['onh']:.0f} (ONH).")
    else:
        p.append(f"Expect rotation between {nq['pdl']:.0f} and {nq['pdh']:.0f}. Fade the edges or wait for a clean break plus retest.")
        p.append("Cut size or sit out the first 15 minutes. Chop days punish chasing.")
    for e in s.get("events") or []:
        if e["impact"] == "High" and e["time"] >= "09:30":
            p.append(f"{e['time']} {e['title']}: flat or reduced into the print.")
    p.extend(s.get("flags", []))
    return p
