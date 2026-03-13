# US Stock Momentum Dashboard

A fully automated static dashboard for a personal investor that ranks a customizable universe of US stocks using the classic **12-1 momentum** factor:

- **12M return** = `P(t) / P(t-252) - 1`
- **1M return** = `P(t) / P(t-21) - 1`
- **Momentum score** = `12M return - 1M return`

The project is designed to run on **GitHub Actions** every weekday morning and publish a **mobile-friendly dashboard** on **GitHub Pages**.

## What it does each run

1. Downloads daily historical data from Yahoo Finance
2. Computes momentum scores for the editable stock universe
3. Applies personal-investor-friendly filters
4. Ranks the universe by momentum
5. Publishes the top 20 names to a static dashboard

## Default filters

- Price > $10
- 50-day average daily volume > 1,000,000 shares
- Optional trend filter: `Price > 200-day moving average`

## Files

- `generate_dashboard.py` — fetches data, computes momentum, writes outputs
- `universe.csv` — editable list of stocks/ETFs to track
- `.github/workflows/momentum-dashboard.yml` — daily automation
- `site/index.html` — generated static dashboard
- `data/top20.csv` — generated top 20 output
- `data/ranked_momentum.csv` — generated full ranked list

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python generate_dashboard.py
```

Then open `site/index.html`.

## GitHub setup

1. Create a GitHub repo and push this project.
2. In GitHub repo settings:
   - **Pages** → Source: **GitHub Actions**
3. Ensure Actions are enabled.
4. The workflow will run on schedule and on manual dispatch.

## Editing the universe

Edit `universe.csv`:

- Set `enabled` to `1` or `0`
- Add/remove rows freely
- Keep columns: `symbol,name,theme,enabled`

## Notes

- Data source: Yahoo Finance via `yfinance`
- Downloader is intentionally conservative: sequential requests with retries to reduce rate-limit risk.
- Schedule cron is currently set to **10:30 UTC on weekdays**.
- If you want the workflow to stay exactly at **6:30 AM US/Eastern** across daylight saving changes, use two seasonal cron entries or accept a one-hour drift during DST.
- This is for personal research, not investment advice.
