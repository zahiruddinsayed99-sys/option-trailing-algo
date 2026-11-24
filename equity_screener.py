import datetime
import os
import time
from broker_adapter import BrokerAdapter
import config

# Historical average daily volume baseline for Sensex 30 constituents
SENSEX_30_BASE_VOL = {
    "HDFCBANK": 15000000,
    "ICICIBANK": 12000000,
    "RELIANCE": 8000000,
    "BHARTIARTL": 6000000,
    "LT": 2500000,
    "SBIN": 18000000,
    "INFY": 7000000,
    "AXISBANK": 7000000,
    "KOTAKBANK": 3500000,
    "BAJFINANCE": 1200000,
    "M&M": 3000000,
    "ITC": 14000000,
    "ETERNAL": 1000000,
    "TCS": 2500000,
    "SUNPHARMA": 3000000,
    "TITAN": 1500000,
    "HINDUNILVR": 2000000,
    "TATASTEEL": 35000000,
    "MARUTI": 600000,
    "NTPC": 12000000,
    "ADANIPORTS": 4000000,
    "BEL": 15000000,
    "HCLTECH": 3500000,
    "ULTRACEMCO": 400000,
    "POWERGRID": 10000000,
    "INDIGO": 1500000,
    "ASIANPAINT": 1200000,
    "BAJAJFINSV": 2500000,
    "TECHM": 2800000,
    "TRENT": 1800000,
}


def compute_relative_volume(symbol, volume, ltp, all_quotes):
  """Computes RVOL vs time-weighted historical baseline or intraday turnover rank."""
  now = datetime.datetime.now()
  # Standard trading session: 09:15 to 15:30 (375 minutes)
  market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
  market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

  if now < market_open:
    elapsed_fraction = 0.10
  elif now > market_close:
    elapsed_fraction = 1.00
  else:
    elapsed_minutes = max(1.0, (now - market_open).total_seconds() / 60.0)
    elapsed_fraction = min(1.0, elapsed_minutes / 375.0)

  base_vol = SENSEX_30_BASE_VOL.get(symbol, 3000000)
  expected_vol = base_vol * elapsed_fraction

  if expected_vol > 0 and volume > 0:
    rvol = volume / expected_vol
  else:
    # Fallback to intraday turnover rank vs peer average
    turnovers = [
        float(q.get("ltp", 0) or 0) * float(q.get("volume", 0) or 0)
        for q in all_quotes.values()
        if float(q.get("ltp", 0) or 0) > 0 and float(q.get("volume", 0) or 0) > 0
    ]
    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 1.0
    turnover_stock = ltp * volume
    rvol = turnover_stock / avg_turnover if avg_turnover > 0 else 1.0

  return round(max(0.1, min(10.0, rvol)), 2)


def select_trending_sensex_stocks(broker):
  """Checks SENSEX market regime and selects top 3 trending Sensex 30 stocks.

  Returns:
      tuple: (regime, direction, selected_symbols)
             regime: 'BULLISH', 'BEARISH', or 'SIDEWAYS'
             direction: 'LONG', 'SHORT', or 'NONE'
             selected_symbols: list of up to 3 stock symbols
  """
  print("\n" + "=" * 80)
  print("   NSE CASH EQUITY INTRADAY MOMENTUM ENGINE (V1.0) - SENSEX 30 SCREENER")
  print("=" * 80)

  # 1. Market Regime Check (SENSEX Index on BSE)
  trend_threshold = getattr(config, "MARKET_TREND_THRESHOLD_PCT", 0.30)
  idx_quote = broker.get_quote("SENSEX", "BSE_INDEX")

  if not idx_quote:
    # Fallback to BSE exchange if BSE_INDEX unavailable
    idx_quote = broker.get_quote("SENSEX", "BSE")

  if not idx_quote:
    print("[ERROR] Failed to fetch SENSEX index quote from broker. Standing down.")
    return "SIDEWAYS", "NONE", []

  idx_ltp = float(idx_quote.get("ltp", 0) or 0)
  idx_prev_close = float(
      idx_quote.get("prev_close")
      or idx_quote.get("close")
      or idx_quote.get("open")
      or idx_ltp
  )

  if idx_prev_close > 0:
    index_pct_change = round(((idx_ltp - idx_prev_close) / idx_prev_close) * 100.0, 2)
  else:
    index_pct_change = 0.0

  print(f"[MARKET REGIME] SENSEX Index: {idx_ltp:.2f} | Prev Close: {idx_prev_close:.2f} | Move: {index_pct_change:+.2f}%")

  if index_pct_change >= trend_threshold:
    regime = "BULLISH"
    direction = "LONG"
  elif index_pct_change <= -trend_threshold:
    regime = "BEARISH"
    direction = "SHORT"
  else:
    regime = "SIDEWAYS"
    direction = "NONE"

  print(f"[REGIME VERDICT] {regime} (Direction: {direction} | Threshold: ±{trend_threshold:.2f}%)")

  if regime == "SIDEWAYS":
    print("\n[ACTION REQUIRED] Standing down: SENSEX is sideways/non-trending (< ±0.30%). No trades recommended.")
    print("=" * 80)
    return regime, direction, []

  # 2. Fetch Multi-Quotes for all 30 Sensex Constituents on NSE
  symbols = getattr(config, "SENSEX_30_SYMBOLS", [])
  exchange = getattr(config, "EQUITY_EXCHANGE", "NSE")
  stock_min_move = getattr(config, "STOCK_MIN_MOVE_PCT", 0.80)
  max_notional = getattr(config, "EQUITY_MAX_NOTIONAL", 25000.0)
  max_stock_price = 5000.0  # At least 5 shares must fit in ₹25,000 max notional

  print(f"\n[SCANNING] Fetching live depth & volume quotes for {len(symbols)} Sensex 30 stocks on {exchange}...")
  quotes_map = broker.get_multiquotes(symbols, exchange=exchange)

  candidates = []
  rejected_count = 0

  for sym in symbols:
    q = quotes_map.get(sym)
    if not q:
      continue

    ltp = float(q.get("ltp", 0) or 0)
    raw_bid = float(q.get("bid", 0) or 0)
    raw_ask = float(q.get("ask", 0) or 0)
    volume = float(q.get("volume", 0) or 0)
    prev_close = float(q.get("prev_close") or q.get("open") or ltp)

    if ltp <= 0 or prev_close <= 0:
      continue

    pct_change = round(((ltp - prev_close) / prev_close) * 100.0, 2)

    # Depth validation: raw_bid > 0 and raw_ask > 0 and ask >= bid
    valid_depth = raw_bid > 0 and raw_ask > 0 and raw_ask >= raw_bid
    if not valid_depth:
      rejected_count += 1
      continue

    spread = round(raw_ask - raw_bid, 2)
    spread_pct = round((spread / ltp) * 100.0, 4)

    # Liquidity filter: tight spread (<= 0.10% of LTP)
    if spread_pct > 0.10:
      rejected_count += 1
      continue

    # Price ceiling filter: <= ₹5,000
    if ltp > max_stock_price:
      rejected_count += 1
      continue

    # RVOL computation
    rvol = compute_relative_volume(sym, volume, ltp, quotes_map)

    # Directional momentum filtering
    if direction == "LONG":
      if pct_change >= stock_min_move:
        score = round(pct_change * rvol, 2)
        candidates.append({
            "symbol": sym,
            "ltp": ltp,
            "pct_change": pct_change,
            "volume": int(volume),
            "spread_pct": spread_pct,
            "direction": "LONG",
            "rvol": rvol,
            "score": score,
        })
    elif direction == "SHORT":
      if pct_change <= -stock_min_move:
        score = round(abs(pct_change) * rvol, 2)
        candidates.append({
            "symbol": sym,
            "ltp": ltp,
            "pct_change": pct_change,
            "volume": int(volume),
            "spread_pct": spread_pct,
            "direction": "SHORT",
            "rvol": rvol,
            "score": score,
        })

  # Rank by composite score descending
  candidates.sort(key=lambda x: x["score"], reverse=True)
  top_selected = candidates[:3]
  selected_symbols = [c["symbol"] for c in top_selected]

  # 3. Print Clean Console Table
  print("\n" + "-" * 88)
  print(f"{'SYMBOL':<12} | {'LTP (₹)':<9} | {'% CHG':<8} | {'VOLUME':<10} | {'SPREAD %':<9} | {'DIR':<6} | {'SCORE':<7}")
  print("-" * 88)

  if not candidates:
    print(f"  No stocks qualified for {direction} with move >= ±{stock_min_move:.2f}%, price <= ₹5000, spread <= 0.10%")
  else:
    for c in candidates:
      is_top = c["symbol"] in selected_symbols
      marker = " *" if is_top else "  "
      print(
          f"{c['symbol']:<12} | ₹{c['ltp']:<8.2f} | {c['pct_change']:>+6.2f}% | {c['volume']:<10} | {c['spread_pct']:<8.4f}% | {c['direction']:<6} | {c['score']:<7.2f}{marker}"
      )

  print("-" * 88)
  print(f"Selected Candidates ({direction}): {selected_symbols if selected_symbols else 'None'}")
  print("=" * 80 + "\n")

  return regime, direction, selected_symbols


if __name__ == "__main__":
  broker = BrokerAdapter()
  regime, direction, selected = select_trending_sensex_stocks(broker)
