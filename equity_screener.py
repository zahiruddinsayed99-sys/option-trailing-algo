import datetime
import broker_adapter
import config

# Historical average daily volume baseline for Sensex 30 constituents
SENSEX_30_BASE_VOL = {
    "HDFCBANK": 15000000,
    "ICICIBANK": 12000000,
    "RELIANCE": 8000000,
    "BHARTIARTL": 6000000,
    "LT": 2500000,
    "SBIN": 14000000,
    "INFY": 7000000,
    "AXISBANK": 8500000,
    "KOTAKBANK": 4500000,
    "BAJFINANCE": 1200000,
    "M&M": 3000000,
    "ITC": 13000000,
    "ETERNAL": 25000000,
    "TCS": 2500000,
    "SUNPHARMA": 2500000,
    "TITAN": 1200000,
    "HINDUNILVR": 2000000,
    "TATASTEEL": 30000000,
    "MARUTI": 600000,
    "NTPC": 12000000,
    "ADANIPORTS": 4000000,
    "BEL": 15000000,
    "HCLTECH": 3000000,
    "ULTRACEMCO": 400000,
    "POWERGRID": 11000000,
    "INDIGO": 1000000,
    "ASIANPAINT": 1500000,
    "BAJAJFINSV": 1800000,
    "TECHM": 2200000,
    "TRENT": 1000000,
}


def _compute_rvol(symbol: str, volume: float) -> float:
    """Computes time-of-day normalized Relative Volume (RVOL)."""
    now = datetime.datetime.now()
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now <= market_open:
        return 1.0

    elapsed_minutes = max(1.0, (now - market_open).total_seconds() / 60.0)
    elapsed_fraction = min(1.0, elapsed_minutes / 375.0)

    base_vol = SENSEX_30_BASE_VOL.get(symbol, 3000000)
    expected_vol = base_vol * elapsed_fraction

    if expected_vol > 0 and volume > 0:
        return round(volume / expected_vol, 2)
    return 1.0


def _fetch_sensex30_quotes(broker, symbols: list[str], exchange: str) -> dict:
    """Fetches and normalizes OpenAlgo multiquotes response {'results': [{'symbol': ..., 'data': {...}}]}."""
    quotes_map = {}

    if getattr(broker, "mode", "") == "OPENALGO" and getattr(broker, "client", None) is not None:
        payload = [{"symbol": s, "exchange": exchange} for s in symbols]
        res = broker.client.multiquotes(symbols=payload)
        if isinstance(res, dict) and res.get("status") == "success":
            for item in res.get("results", []):
                sym = item.get("symbol")
                data = item.get("data") or {}
                if sym and isinstance(data, dict):
                    quotes_map[sym] = data
        if quotes_map:
            return quotes_map

    # Fallback for SIMULATION mode or custom adapter mapping
    fallback = broker.get_multiquotes(symbols, exchange)
    if isinstance(fallback, dict):
        return fallback
    return {}


def select_trending_sensex_stocks(broker):
    """Checks Sensex-30 basket market regime and selects top 3 trending stocks.

    Returns:
        tuple: (regime, direction, selected_symbols)
    """
    print("\n" + "=" * 84)
    print("   NSE CASH EQUITY INTRADAY MOMENTUM ENGINE (V1.0) - SENSEX 30 SCREENER")
    print("=" * 84)

    trend_threshold = getattr(config, "MARKET_TREND_THRESHOLD_PCT", 0.30)
    symbols = getattr(config, "SENSEX_30_SYMBOLS", list(SENSEX_30_BASE_VOL.keys()))
    exchange = getattr(config, "EQUITY_EXCHANGE", "NSE")
    stock_min_move = getattr(config, "STOCK_MIN_MOVE_PCT", 0.80)
    max_notional = getattr(config, "EQUITY_MAX_NOTIONAL", 25000.0)

    # 1. Fetch Multi-Quotes for all 30 Sensex Constituents on NSE
    quotes_map = _fetch_sensex30_quotes(broker, symbols, exchange)

    pct_moves = []
    for sym, q in quotes_map.items():
        ltp = float(q.get("ltp", 0) or 0)
        prev = float(q.get("prev_close", 0) or q.get("open", 0) or 0)
        if ltp > 0 and prev > 0:
            pct_moves.append(((ltp - prev) / prev) * 100.0)

    if not pct_moves:
        print("[ERROR] Failed to fetch Sensex-30 constituent quotes from broker. Standing down.")
        return "SIDEWAYS", "NONE", []

    index_pct_change = sum(pct_moves) / len(pct_moves)
    advancers = sum(1 for m in pct_moves if m > 0)
    decliners = sum(1 for m in pct_moves if m < 0)

    print(
        f"[MARKET REGIME] SENSEX-30 Basket ({len(pct_moves)}/30): "
        f"Avg Move {index_pct_change:+.2f}% | Adv: {advancers} / Dec: {decliners}"
    )

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
        print(f"\n[ACTION REQUIRED] Standing down: SENSEX-30 basket is sideways (< ±{trend_threshold:.2f}%). No trades.")
        print("=" * 84)
        return regime, direction, []

    # 2. Filter & Rank Top 3 Movers in Regime Direction
    max_affordable_price = max_notional / 5.0  # Ensures at least 5 shares fit inside ₹25,000 notional
    candidates = []

    for sym in symbols:
        q = quotes_map.get(sym)
        if not q:
            continue

        ltp = float(q.get("ltp", 0) or 0)
        prev_close = float(q.get("prev_close", 0) or q.get("open", 0) or 0)
        bid = float(q.get("bid", 0) or 0)
        ask = float(q.get("ask", 0) or 0)
        volume = float(q.get("volume", 0) or 0)

        if ltp <= 0 or prev_close <= 0:
            continue

        # Strict depth validation (never allow zero/uninitialized depth)
        if bid <= 0 or ask <= 0 or ask < bid:
            continue

        spread_pct = ((ask - bid) / ltp) * 100.0
        if spread_pct > 0.10:
            continue

        if ltp > max_affordable_price:
            continue

        pct_change = ((ltp - prev_close) / prev_close) * 100.0
        rvol = _compute_rvol(sym, volume)

        if regime == "BULLISH" and pct_change >= stock_min_move:
            score = round(pct_change * max(rvol, 0.5), 2)
            candidates.append({
                "symbol": sym,
                "ltp": ltp,
                "pct_change": pct_change,
                "volume": int(volume),
                "rvol": rvol,
                "spread_pct": spread_pct,
                "direction": "LONG",
                "score": score,
            })
        elif regime == "BEARISH" and pct_change <= -stock_min_move:
            score = round(abs(pct_change) * max(rvol, 0.5), 2)
            candidates.append({
                "symbol": sym,
                "ltp": ltp,
                "pct_change": pct_change,
                "volume": int(volume),
                "rvol": rvol,
                "spread_pct": spread_pct,
                "direction": "SHORT",
                "score": score,
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_3 = candidates[:3]

    if not top_3:
        print(f"\n[NOTE] No Sensex-30 stocks met >= ±{stock_min_move:.2f}% move with <= 0.10% spread & <= ₹{max_affordable_price:.0f} LTP.")
        print("=" * 84)
        return regime, direction, []

    print(f"\n{'SYMBOL':<14} | {'LTP':>9} | {'% CHG':>7} | {'VOLUME':>10} | {'RVOL':>5} | {'SPREAD %':>8} | {'DIR':<5} | {'SCORE':>6}")
    print("-" * 84)
    for c in top_3:
        print(
            f"{c['symbol']:<14} | ₹{c['ltp']:>8.2f} | {c['pct_change']:>+6.2f}% | "
            f"{c['volume']:>10,d} | {c['rvol']:>4.1f}x | {c['spread_pct']:>7.3f}% | "
            f"{c['direction']:<5} | {c['score']:>6.2f}"
        )

    selected_symbols = [c["symbol"] for c in top_3]
    print("\n" + "=" * 84)
    print(f"SELECTED TOP {len(selected_symbols)} ({direction}): {selected_symbols}")
    print("=" * 84 + "\n")

    return regime, direction, selected_symbols


if __name__ == "__main__":
    broker = broker_adapter.BrokerAdapter()
    try:
        select_trending_sensex_stocks(broker)
    finally:
        broker.shutdown()