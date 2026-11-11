"""Free data collectors. Every collector fails soft: a broken source returns an
empty result and an entry in `errors`, so one dead feed never kills the brief."""
from __future__ import annotations

import calendar
import datetime as dt
import re
import traceback

import feedparser
import pandas as pd
import requests
import yfinance as yf

from . import config as C

UA = {"User-Agent": "Mozilla/5.0 (nq-bias research bot)"}


def _now_et() -> dt.datetime:
    return dt.datetime.now(C.ET)


def _to_et(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(C.ET)
    return df


# ---------------------------------------------------------------- NQ structure
def nq_levels(bars: pd.DataFrame, now: dt.datetime) -> dict:
    """Prior RTH high/low/close/open, overnight high/low and 10-day overnight
    range average from intraday bars (index in ET). Pure function, unit-tested."""
    t = bars.index.time
    rth = bars[(t >= dt.time(9, 30)) & (t < dt.time(16, 0))]
    today = now.date()
    rth_dates = sorted({d for d in rth.index.date if d < today})
    if not rth_dates:
        raise ValueError("no prior RTH session in bars")
    prev = rth_dates[-1]
    p = rth[rth.index.date == prev]

    def on_window(start_date, end_date):
        start = dt.datetime.combine(start_date, dt.time(16, 59), C.ET)
        end = dt.datetime.combine(end_date, dt.time(9, 30), C.ET)
        return bars[(bars.index > start) & (bars.index < end)]

    on = on_window(prev, today)
    on_ranges = []
    for a, b in list(zip(rth_dates[:-1], rth_dates[1:]))[-10:]:
        w = on_window(a, b)
        if len(w):
            on_ranges.append(float(w["High"].max() - w["Low"].min()))

    price = float(bars["Close"].iloc[-1])
    out = {
        "price": price,
        "prev_date": prev.isoformat(),
        "pdo": float(p["Open"].iloc[0]),
        "pdh": float(p["High"].max()),
        "pdl": float(p["Low"].min()),
        "pdc": float(p["Close"].iloc[-1]),
        "onh": float(on["High"].max()) if len(on) else price,
        "onl": float(on["Low"].min()) if len(on) else price,
    }
    out["on_range"] = out["onh"] - out["onl"]
    out["on_range_avg10"] = sum(on_ranges) / len(on_ranges) if on_ranges else None
    out["prior_rth_range"] = out["pdh"] - out["pdl"]
    out["gap_pct"] = (price / out["pdc"] - 1) * 100
    return out


def get_nq(now: dt.datetime) -> dict:
    bars = yf.Ticker(C.NQ).history(period="30d", interval="15m", prepost=True)
    return nq_levels(_to_et(bars), now)


def last_vs_prev(symbol: str, now: dt.datetime) -> dict:
    """Latest (incl. pre/post market) price vs the last daily close before today."""
    tk = yf.Ticker(symbol)
    daily = tk.history(period="10d", interval="1d")
    daily = daily[[d.date() < now.date() for d in daily.index]]
    prev = float(daily["Close"].iloc[-1])
    intra = tk.history(period="2d", interval="5m", prepost=True)
    last = float(intra["Close"].dropna().iloc[-1]) if len(intra) else prev
    return {"last": last, "prev": prev, "chg_pct": (last / prev - 1) * 100}


def get_macro(now: dt.datetime) -> dict:
    out = {}
    for key, sym in (("es", C.ES), ("vix", C.VIX), ("tnx", C.TNX), ("dxy", C.DXY)):
        out[key] = last_vs_prev(sym, now)
    out["tnx"]["chg_bp"] = (out["tnx"]["last"] - out["tnx"]["prev"]) * 100
    return out


def get_megacaps(now: dt.datetime) -> list[dict]:
    rows = []
    for sym, w in C.MEGACAPS.items():
        try:
            r = last_vs_prev(sym, now)
            rows.append({"sym": sym, "weight": w, "last": r["last"], "chg_pct": r["chg_pct"]})
        except Exception:
            continue
    return rows


# ------------------------------------------------------------ economic calendar
def get_calendar(now: dt.datetime) -> list[dict]:
    """ForexFactory weekly feed (free JSON). USD high/medium-impact for today."""
    r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                     headers=UA, timeout=20)
    r.raise_for_status()
    events = []
    for e in r.json():
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        when = dt.datetime.fromisoformat(e["date"]).astimezone(C.ET)
        if when.date() != now.date():
            continue
        events.append({
            "time": when.strftime("%H:%M"),
            "title": e.get("title", ""),
            "impact": e["impact"],
            "forecast": e.get("forecast") or "",
            "previous": e.get("previous") or "",
        })
    return sorted(events, key=lambda x: x["time"])


# -------------------------------------------------------------------- earnings
def _prev_weekday(now: dt.datetime) -> dt.date:
    d = now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _nasdaq_day(d: dt.date) -> list[dict]:
    r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d.isoformat()},
                     headers={**UA, "Accept": "application/json, text/plain, */*",
                              "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"},
                     timeout=20)
    r.raise_for_status()
    return ((r.json().get("data") or {}).get("rows")) or []


def _num(v):
    try:
        return float(str(v).replace("$", "").replace("(", "-").replace(")", ""))
    except (TypeError, ValueError):
        return None


def get_earnings(now: dt.datetime) -> list[dict]:
    """Nasdaq.com earnings calendar (free, no key): last night after close and
    today pre-market both hit the open; today after close is overnight risk."""
    out = []
    for day, is_today in ((_prev_weekday(now), False), (now.date(), True)):
        for e in _nasdaq_day(day):
            sym = (e.get("symbol") or "").upper()
            if sym not in C.EARNINGS_WATCH:
                continue
            t = (e.get("time") or "").lower()
            if is_today:
                when = ("today pre-market" if "pre-market" in t else
                        "today after close" if "after-hours" in t else "today (time n/a)")
            elif "after-hours" in t:
                when = "last night after close"
            else:
                continue
            out.append({"sym": sym, "when": when, "eps_est": _num(e.get("epsForecast")),
                        "eps_actual": None, "rev_est": None, "rev_actual": None})
    return out


# ------------------------------------------------------------------------ news
MOVERS = ("fed", "powell", "cpi", "inflation", "jobs", "payroll", "tariff", "rate",
          "yield", "treasury", "nvidia", "apple", "microsoft", "amazon", "meta",
          "alphabet", "google", "tesla", "broadcom", "earnings", "guidance", "nasdaq",
          "futures", "recession", "gdp", "pce", "fomc", "china", "chip", "ai ", "ppi",
          "jobless", "claims", "ism", "retail sales", "trump", "white house", "s&p", "nq", "us ")

# FinancialJuice data headlines look like:
#   "US CPI (YoY) Actual: 3.1% (Forecast 3.0%, Previous 2.9%)"
PRINT_RE = re.compile(
    r"^(?P<name>.+?)\s+Actual:?\s*(?P<actual>[-+]?[\d.,]+)\s*(?P<unit>[%KMBT]?)"
    r".*?Forecast:?\s*(?P<forecast>[-+]?[\d.,]+)\s*[%KMBT]?"
    r"(?:.*?Previous:?\s*(?P<previous>[-+]?[\d.,]+)\s*[%KMBT]?)?", re.I)


def parse_print(title: str) -> dict | None:
    m = PRINT_RE.search(title)
    if not m:
        return None
    try:
        a = float(m["actual"].replace(",", ""))
        f = float(m["forecast"].replace(",", ""))
    except ValueError:
        return None
    return {"name": m["name"].strip(" :-"), "actual": a, "forecast": f,
            "previous": float(m["previous"].replace(",", "")) if m["previous"] else None,
            "unit": m["unit"], "surprise": round(a - f, 4)}


def _entry_time(e) -> dt.datetime | None:
    ts = e.get("published_parsed") or e.get("updated_parsed")
    if not ts:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(ts), dt.timezone.utc).astimezone(C.ET)


def _fetch_feed(url: str):
    # fetch with requests (honors proxies/timeouts), then let feedparser parse the bytes
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return feedparser.parse(r.content)


def get_financialjuice(now: dt.datetime) -> list[dict]:
    feed = _fetch_feed(C.FINANCIALJUICE_RSS)
    if not feed.entries:
        raise ValueError("FinancialJuice feed returned no items")
    cutoff = now - dt.timedelta(hours=C.FJ_HOURS)
    out = []
    for e in feed.entries:
        when = _entry_time(e)
        if not when or when < cutoff:
            continue
        title = re.sub(r"^FinancialJuice:\s*", "", e.get("title", "").strip(), flags=re.I)
        item = {"title": title, "source": "FinancialJuice", "time": when.isoformat(),
                "url": e.get("link", ""), "fj": True}
        p = parse_print(title)
        if p:
            item["print"] = p
        out.append(item)
    out.sort(key=lambda x: x["time"], reverse=True)
    return out[: C.FJ_LIMIT]


def get_headlines(now: dt.datetime, hours: int = 16, limit: int = 10) -> list[dict]:
    """Backup context from CNBC/MarketWatch, ranked market-moving first."""
    cutoff = now - dt.timedelta(hours=hours)
    items = []
    for url in C.RSS_FEEDS:
        try:
            feed = _fetch_feed(url)
        except Exception:
            continue
        src = (feed.feed.get("title") or url.split("/")[2])[:40]
        for e in feed.entries:
            when = _entry_time(e)
            if not when or when < cutoff:
                continue
            items.append({"title": e.get("title", "").strip(), "source": src,
                          "time": when.isoformat(), "url": e.get("link", "")})
    seen, uniq = set(), []
    for it in items:
        k = it["title"].lower()[:60]
        if k and k not in seen:
            seen.add(k)
            it["relevant"] = any(m in k for m in MOVERS)
            uniq.append(it)
    uniq.sort(key=lambda x: (x["relevant"], x["time"]), reverse=True)
    return uniq[:limit]


# ------------------------------------------------------------------- snapshot
def collect(now: dt.datetime | None = None) -> dict:
    now = now or _now_et()
    snap = {"asof": now.isoformat(), "date": now.date().isoformat(), "errors": []}
    jobs = {
        "nq": lambda: get_nq(now),
        "macro": lambda: get_macro(now),
        "megacaps": lambda: get_megacaps(now),
        "events": lambda: get_calendar(now),
        "earnings": lambda: get_earnings(now),
        "squawk": lambda: get_financialjuice(now),
        "headlines": lambda: get_headlines(now),
    }
    for key, fn in jobs.items():
        try:
            snap[key] = fn()
        except Exception as e:
            snap[key] = {} if key in ("nq", "macro") else []
            snap["errors"].append(f"{key}: {type(e).__name__}: {e}")
            traceback.print_exc()
    snap.update(snap.pop("macro", {}) or {})
    snap["prints"] = [dict(h["print"], time=h["time"]) for h in snap.get("squawk") or [] if "print" in h]
    return snap


def rth_result(now: dt.datetime | None = None) -> dict:
    """Today's regular-session open/high/low/close for post-close grading."""
    now = now or _now_et()
    bars = _to_et(yf.Ticker(C.NQ).history(period="2d", interval="5m", prepost=True))
    t = bars.index.time
    s = bars[(bars.index.date == now.date()) & (t >= dt.time(9, 30)) & (t < dt.time(16, 0))]
    if s.empty:
        raise ValueError("no RTH bars for today (holiday?)")
    return {"open": float(s["Open"].iloc[0]), "high": float(s["High"].max()),
            "low": float(s["Low"].min()), "close": float(s["Close"].iloc[-1])}
