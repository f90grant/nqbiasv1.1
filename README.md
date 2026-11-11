# NQ Daily Bias

A free, automated pre-market bias for Nasdaq futures (NQ). Every weekday around 8:50 ET it:

1. Pulls NQ overnight structure, ES, VIX, the 10-year yield, the dollar and premarket moves of the biggest Nasdaq stocks (Yahoo Finance), today's USD economic calendar (ForexFactory), the **FinancialJuice** squawk feed (headlines plus data prints vs forecast), watchlist earnings (Nasdaq.com calendar) and backup headlines (CNBC/MarketWatch RSS).
2. Scores it with transparent rules into **STRONG/LEAN LONG**, **STRONG/LEAN SHORT** or **CHOP / NEUTRAL**, plus a separate chop-risk score.
3. Has an AI (free Gemini, optional Claude) write a short read of the news. **The AI explains the score; it doesn't change it.**
4. Posts to your Discord channel and updates the web dashboard.
5. After the close it **grades the call** against what NQ actually did and keeps a running hit rate.

Total cost: **$0** (GitHub Actions + GitHub Pages + free API tiers).

---

## Setup (about 20 minutes, once)

### 1. Put it on GitHub
1. Create a GitHub account if you don't have one, then create a **new repository** (e.g. `nq-bias`). It can be public or private. GitHub Pages on a private repo needs a paid plan, so public is easiest.
2. Upload every file in this folder, keeping the folder structure (`bias/`, `docs/`, `.github/workflows/`, `tests/`). The easiest way is GitHub Desktop or `git push`. Drag-and-drop in the browser skips the hidden `.github` folder.

### 2. Get the free keys
| Secret name | Where | Needed? |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | Discord: Server Settings → Integrations → Webhooks → New Webhook → pick your channel → Copy URL | For Discord posts |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey (free tier) | For the AI summary (otherwise a plain template is used) |
| `ANTHROPIC_API_KEY` | console.anthropic.com (paid, about $0.01/day) | Optional instead of Gemini |

In your repo go to **Settings → Secrets and variables → Actions → New repository secret** and add each one.

### 3. Turn on the dashboard
1. Repo **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, folder `/docs` → Save.
2. After about a minute your dashboard is live at `https://<your-username>.github.io/nq-bias/`.
3. Optional: under **Settings → Secrets and variables → Actions → Variables**, add `DASHBOARD_URL` with that link so the Discord post title links to it.

**FinancialJuice:** no key is needed. The system reads FinancialJuice's public RSS feed (`https://www.financialjuice.com/feed.ashx?xy=rss`). If that URL ever changes or stops working (the dashboard will show a yellow "squawk" error), add a repo variable `FINANCIALJUICE_RSS` with the new feed URL. The RSS feed carries headlines only. The live audio squawk is part of their paid plan and can't be pulled in.

### 4. Test it
**Actions** tab → *NQ daily bias* → **Run workflow** (cmd `run`, force `true`). Within about a minute you should get a Discord post, and the dashboard updates after Pages redeploys (around 1 to 2 minutes).

From then on it runs on its own. The brief is attempted at 8:50, 9:05 and 9:20 ET, because GitHub's scheduler often starts late or skips a slot. Only the first successful attempt counts: the call is locked in once per day and never rewritten, and nothing runs after 9:28, so every graded call was made before the bell. The later attempts only retry a Discord post that failed. Grading runs around 4:20 to 6:20 ET.

---

## How the score works

| Factor | Long | Short |
|---|---|---|
| Gap vs prior RTH close (±0.30%) | +1 | −1 |
| Price above PDH / below PDL | +1 | −1 |
| Price in top/bottom 25% of overnight range | +0.5 | −0.5 |
| Weighted mega-cap premarket (±0.20% / ±0.50%) | +0.5 / +1 | −0.5 / −1 |
| VIX change (≤ −4% / ≥ +5%) | +0.5 | −1 |
| 10Y yield change (±4bp) | +0.5 (falling) | −0.5 (rising) |
| DXY change (±0.40%) | +0.5 (falling) | −0.5 (rising) |

Score ≥ 3 is STRONG, ≥ 1 is LEAN, and anything between −1 and +1 is CHOP.

**Chop score** adds up: opening inside the prior day's range (+1), overnight range under 70% of its 10-day average (+1), NQ and ES pointing different ways (+1), bull and bear factors cancelling out (+1), a Fed event later in the day (+1.5), or a high-impact release during RTH (+0.5). A US market holiday adds +1.5. A "Fed event" means a rate decision, statement, press conference, minutes or a high-impact Fed chair appearance, not an ordinary Fed speaker. A chop score of 2.5 or more overrides a LEAN call to CHOP and knocks a STRONG call down to LEAN.

All thresholds live in `bias/config.py`.

## Grading & honesty check
At the close, if RTH close vs open is ≥ +0.40% the day counts as **long**, ≤ −0.40% as **short**, otherwise **chop**. The dashboard shows the hit rate overall and by call type. Random guessing gets about 33%. **Don't tune the thresholds until you have 30+ graded days**, or you'll just be fitting noise.

## Run locally (optional)
```bash
pip install -r requirements.txt
python -m bias run --sample            # offline demo, writes docs/data/latest.json
python -m bias run --force --no-discord   # real data, no post
python -m pytest -q                    # tests
cd docs && python -m http.server       # then open http://localhost:8000
```

## Notes
- The AI read leans mainly on the FinancialJuice headlines. Data prints ("Actual X (Forecast Y)") are parsed and shown as above or below forecast. They don't move the score yet. Once we have a few weeks of graded days, we can test adding a "data surprise" factor.
- All moves (NQ gap, ES, mega-caps, VIX, yields, dollar) are measured from the same reference: yesterday's 4:00pm ET cash close. If a market has no quote yet today, its factor scores 0 and says so instead of showing a fake 0.00% move.
- Every day's per-factor points are saved in `docs/data/history.json`, so after 30+ graded days we can check which factors actually predict the day and drop the ones that don't.
- Yahoo data is free but unofficial, and futures quotes lag about 10 minutes. That's why the first run is at 8:50, not 8:31: it needs to see the reaction to 8:30 data. If it breaks, run `pip install -U yfinance` (the workflow installs the latest version every run).
- Holidays: the brief flags US holidays and stale quotes at the top and raises the chop score.
- If Google retires the Gemini model, add a repo variable `GEMINI_MODEL` with the new model name. Until then the brief falls back to the plain template summary.
- Ideas for v2: a Discord `/bias` slash command (needs an always-on host), a 9:45 "opening range" follow-up, and logging your own trades next to the bias to see whether you trade better when you follow it.

*Informational tool, not financial advice.*
