"""Central settings. Tweak thresholds here, not in the scoring code."""
import os
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# --- Instruments (Yahoo Finance symbols, free, no key) ---
NQ = "NQ=F"
ES = "ES=F"
VIX = "^VIX"
TNX = "^TNX"          # 10-year yield (in percent, e.g. 4.25)
DXY = "DX-Y.NYB"      # US dollar index

# Biggest Nasdaq-100 names and rough index weights (%). They move NQ, so their
# premarket moves are a "breadth" read. Update the weights a few times a year.
MEGACAPS = {
    "NVDA": 9.5, "MSFT": 8.5, "AAPL": 8.5, "AMZN": 5.5, "AVGO": 5.0,
    "META": 3.8, "GOOGL": 3.0, "GOOG": 2.8, "TSLA": 3.0, "NFLX": 1.8,
    "COST": 1.8, "AMD": 1.5, "PLTR": 1.5,
}
# Earnings from these names get flagged on the calendar
EARNINGS_WATCH = set(MEGACAPS) | {
    "CSCO", "ADBE", "QCOM", "INTU", "AMAT", "MU", "LRCX", "PEP", "TMUS",
    "ISRG", "BKNG", "PANW", "CRWD", "MRVL", "ARM", "SHOP", "ABNB", "SBUX",
}

# --- Scoring thresholds ---
GAP_PCT = 0.30            # NQ gap vs prior RTH close that counts as directional
BREADTH_PCT_STRONG = 0.50 # weighted mega-cap premarket move
BREADTH_PCT_MILD = 0.20
VIX_DROP_PCT = -4.0
VIX_SPIKE_PCT = 5.0
VIX_HIGH_LEVEL = 25.0
YIELD_BP = 4.0            # 10y move in basis points
DXY_PCT = 0.40
ON_RANGE_TIGHT = 0.70     # overnight range < 70% of its 10-day avg = compressed
OUTCOME_PCT = 0.40        # post-close grading: |close-open| above this = trend day

# --- Schedule guards (ET) ---
RUN_WINDOW = ("08:20", "09:45")    # pre-open run accepted in this window
GRADE_WINDOW = ("16:05", "19:00")

# --- Keys (all optional; set as GitHub Actions secrets) ---
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")        # free tier: AI narrative
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # optional paid alternative
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

# FinancialJuice squawk headlines (public RSS, no key). Primary news source.
# If they ever move the feed, set FINANCIALJUICE_RSS as a repo variable.
FINANCIALJUICE_RSS = os.getenv("FINANCIALJUICE_RSS") or "https://www.financialjuice.com/feed.ashx?xy=rss"
FJ_HOURS = 14          # look back to roughly the prior afternoon
FJ_LIMIT = 30

# Backup/extra context feeds (shown after FinancialJuice)
RSS_FEEDS = [
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "data")
