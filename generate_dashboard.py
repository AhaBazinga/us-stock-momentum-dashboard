from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
UNIVERSE_FILE = ROOT / "universe.csv"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"
TOP_N = 20
LOOKBACK_DAYS = 400
DOWNLOAD_RETRIES = 3
REQUEST_PAUSE_SECONDS = 0.6
MIN_PRICE = 10.0
MIN_AVG_DOLLAR_VOLUME = 1_000_000  # reserved if you want to switch filters later
MIN_AVG_SHARE_VOLUME = 1_000_000
USE_TREND_FILTER = False


def load_universe() -> pd.DataFrame:
    df = pd.read_csv(UNIVERSE_FILE)
    df["enabled"] = df["enabled"].fillna(1).astype(int)
    df = df[df["enabled"] == 1].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    return df.drop_duplicates(subset=["symbol"], keep="first")


def download_history(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_map: dict[str, pd.Series] = {}
    volume_map: dict[str, pd.Series] = {}

    for symbol in symbols:
        history = pd.DataFrame()
        for attempt in range(1, DOWNLOAD_RETRIES + 1):
            try:
                history = yf.Ticker(symbol).history(period="2y", interval="1d", auto_adjust=False)
            except Exception:
                history = pd.DataFrame()
            if not history.empty and "Close" in history.columns and "Volume" in history.columns:
                break
            time.sleep(attempt)

        if history.empty:
            continue

        price_col = "Adj Close" if "Adj Close" in history.columns else "Close"
        prices = history[price_col].dropna().tail(LOOKBACK_DAYS)
        volumes = history["Volume"].dropna().tail(LOOKBACK_DAYS)
        if prices.empty or volumes.empty:
            continue

        price_map[symbol] = prices.rename(symbol)
        volume_map[symbol] = volumes.rename(symbol)
        time.sleep(REQUEST_PAUSE_SECONDS)

    if not price_map:
        raise RuntimeError("No market data returned from Yahoo Finance.")

    adj_close = pd.concat(price_map.values(), axis=1).sort_index()
    volume = pd.concat(volume_map.values(), axis=1).sort_index().reindex(columns=adj_close.columns)
    return adj_close, volume


def compute_metrics(price_df: pd.DataFrame, volume_df: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for symbol in price_df.columns:
        prices = price_df[symbol].dropna()
        vols = volume_df[symbol].dropna() if symbol in volume_df.columns else pd.Series(dtype=float)

        if len(prices) < 253:
            continue

        current_price = float(prices.iloc[-1])
        price_252 = float(prices.iloc[-253])
        price_21 = float(prices.iloc[-22])
        ma_200 = float(prices.tail(200).mean()) if len(prices) >= 200 else np.nan
        avg_volume_50 = float(vols.tail(50).mean()) if len(vols) >= 20 else np.nan

        ret_12m = current_price / price_252 - 1
        ret_1m = current_price / price_21 - 1
        momentum = ret_12m - ret_1m
        trend_ok = bool(current_price > ma_200) if not np.isnan(ma_200) else False

        rows.append(
            {
                "symbol": symbol,
                "current_price": current_price,
                "return_12m": ret_12m,
                "return_1m": ret_1m,
                "momentum_score": momentum,
                "ma_200": ma_200,
                "avg_volume_50": avg_volume_50,
                "trend_ok": trend_ok,
            }
        )

    metrics = pd.DataFrame(rows)
    if metrics.empty:
        raise RuntimeError("No symbols had enough data to compute momentum.")

    metrics = metrics.merge(meta[["symbol", "name", "theme"]], on="symbol", how="left")
    metrics["passes_filters"] = (
        (metrics["current_price"] > MIN_PRICE)
        & (metrics["avg_volume_50"] > MIN_AVG_SHARE_VOLUME)
        & (~metrics["avg_volume_50"].isna())
    )
    if USE_TREND_FILTER:
        metrics["passes_filters"] = metrics["passes_filters"] & metrics["trend_ok"]

    filtered = metrics[metrics["passes_filters"]].sort_values("momentum_score", ascending=False).reset_index(drop=True)
    filtered["rank"] = np.arange(1, len(filtered) + 1)
    return filtered


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def fmt_price(x: float) -> str:
    return f"${x:,.2f}"


def build_html(df: pd.DataFrame, generated_at: str, universe_size: int) -> str:
    top = df.head(TOP_N).copy()
    cards = []
    for _, row in top.iterrows():
        cards.append(
            f"""
            <div class=\"card\">
              <div class=\"card-header\">
                <div>
                  <div class=\"symbol\">#{int(row['rank'])} {row['symbol']}</div>
                  <div class=\"name\">{row['name'] or ''}</div>
                </div>
                <div class=\"theme\">{row['theme'] or ''}</div>
              </div>
              <div class=\"metric-grid\">
                <div><span>Momentum</span><strong>{fmt_pct(row['momentum_score'])}</strong></div>
                <div><span>12M Return</span><strong>{fmt_pct(row['return_12m'])}</strong></div>
                <div><span>1M Return</span><strong>{fmt_pct(row['return_1m'])}</strong></div>
                <div><span>Price</span><strong>{fmt_price(row['current_price'])}</strong></div>
                <div><span>200D MA</span><strong>{fmt_price(row['ma_200'])}</strong></div>
                <div><span>Trend</span><strong class=\"{'up' if row['trend_ok'] else 'down'}\">{'Above 200D' if row['trend_ok'] else 'Below 200D'}</strong></div>
              </div>
            </div>
            """
        )

    table_rows = []
    for _, row in top.iterrows():
        table_rows.append(
            f"<tr><td>{int(row['rank'])}</td><td>{row['symbol']}</td><td>{fmt_pct(row['momentum_score'])}</td><td>{fmt_pct(row['return_12m'])}</td><td>{fmt_pct(row['return_1m'])}</td><td>{fmt_price(row['current_price'])}</td><td>{'✅' if row['trend_ok'] else '❌'}</td></tr>"
        )

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>US Stock Momentum Dashboard</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #121933;
      --panel-2: #192344;
      --text: #edf2ff;
      --muted: #9fb0d9;
      --accent: #7aa2ff;
      --good: #4ade80;
      --bad: #fb7185;
      --border: rgba(255,255,255,0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, Inter, Segoe UI, sans-serif; background: linear-gradient(180deg, #0b1020 0%, #10172d 100%); color: var(--text); }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 20px 14px 40px; }}
    .hero {{ background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: 20px; padding: 18px; backdrop-filter: blur(8px); }}
    h1 {{ margin: 0 0 8px; font-size: 1.7rem; }}
    p {{ margin: 6px 0; color: var(--muted); line-height: 1.45; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }}
    .stat {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 12px; }}
    .stat strong {{ display: block; margin-top: 4px; font-size: 1.1rem; }}
    .cards {{ display: grid; gap: 12px; margin-top: 18px; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 14px; }}
    .card-header {{ display: flex; justify-content: space-between; gap: 10px; align-items: start; margin-bottom: 12px; }}
    .symbol {{ font-weight: 700; font-size: 1.15rem; }}
    .name, .theme {{ color: var(--muted); font-size: 0.92rem; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .metric-grid div {{ background: var(--panel-2); border-radius: 12px; padding: 10px; }}
    .metric-grid span {{ display: block; color: var(--muted); font-size: 0.82rem; margin-bottom: 4px; }}
    .metric-grid strong {{ font-size: 1rem; }}
    .up {{ color: var(--good); }}
    .down {{ color: var(--bad); }}
    .table-wrap {{ margin-top: 20px; overflow-x: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 720px; }}
    th, td {{ padding: 12px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
    th {{ color: var(--muted); font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    .footer {{ margin-top: 16px; color: var(--muted); font-size: 0.9rem; }}
    @media (max-width: 640px) {{
      .stats {{ grid-template-columns: 1fr; }}
      .metric-grid {{ grid-template-columns: 1fr 1fr; }}
      h1 {{ font-size: 1.4rem; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"hero\">
      <h1>US Stock Momentum Dashboard</h1>
      <p>Classic 12-1 momentum for a customizable US stock universe.</p>
      <p>Formula: <strong>Momentum = P(t)/P(t-252) - 1 - (P(t)/P(t-21) - 1)</strong></p>
      <div class=\"stats\">
        <div class=\"stat\"><span>Updated</span><strong>{generated_at}</strong></div>
        <div class=\"stat\"><span>Universe Passing Filters</span><strong>{len(df)}</strong></div>
        <div class=\"stat\"><span>Total Symbols Tracked</span><strong>{universe_size}</strong></div>
      </div>
    </section>

    <section class=\"cards\">{''.join(cards)}</section>

    <section class=\"table-wrap\">
      <table>
        <thead>
          <tr><th>Rank</th><th>Symbol</th><th>Momentum</th><th>12M</th><th>1M</th><th>Price</th><th>Trend</th></tr>
        </thead>
        <tbody>
          {''.join(table_rows)}
        </tbody>
      </table>
    </section>

    <div class=\"footer\">
      Filters: price &gt; $10, 50-day average volume &gt; 1,000,000 shares, trend filter currently <strong>{'on' if USE_TREND_FILTER else 'off'}</strong>.
    </div>
  </div>
</body>
</html>
"""


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SITE_DIR.mkdir(exist_ok=True)

    universe = load_universe()
    symbols = universe["symbol"].tolist()
    price_df, volume_df = download_history(symbols)
    ranked = compute_metrics(price_df, volume_df, universe)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    top20 = ranked.head(TOP_N).copy()
    top20.to_csv(DATA_DIR / "top20.csv", index=False)
    ranked.to_csv(DATA_DIR / "ranked_momentum.csv", index=False)

    payload = {
        "generated_at": generated_at,
        "universe_size": len(symbols),
        "passing_filters": int(len(ranked)),
        "top20": top20.to_dict(orient="records"),
    }
    (SITE_DIR / "data.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (SITE_DIR / "index.html").write_text(build_html(ranked, generated_at, len(symbols)), encoding="utf-8")


if __name__ == "__main__":
    main()
