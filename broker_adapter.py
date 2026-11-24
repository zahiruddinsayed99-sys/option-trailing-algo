import datetime
import os
import threading
import time
import config


class BrokerAdapter:
  """Unified adapter supporting SIMULATION and OpenAlgo WebSocket + REST modes."""

  def __init__(self):
    self.mode = config.MODE.upper()
    self.client = None
    self.ws_connected = False
    self.subscribed = set()
    self._sub_lock = threading.Lock()
    self.sim_step = 0
    self.sim_regime = os.getenv("SIM_REGIME", "BULLISH").upper()
    self.sim_equity_steps = {}
    self.sim_prices = [
        180.0, 182.0, 181.0, 184.0,  # Candle 1 (Observe)
        185.0, 188.0, 186.0, 189.0,  # Candle 2 (Observe)
        188.0, 190.0, 187.0, 189.5,  # Candle 3 (Observe)
        189.0, 191.0, 188.5, 190.0,  # Candle 4 (Observe -> Base High ~ 191.0, Base Low ~ 180.0)
        190.5, 192.0, 194.0, 196.5,  # Candle 5 (Breakout > 191.0 -> ENTRY @ ~196.5)
        198.0, 205.0, 212.0, 222.0,  # Candle 6 (+1.5R Breakeven)
        235.0, 250.0, 265.0, 280.0,  # Candle 7 (+2.5R -> +1R Profit Lock)
        295.0, 315.0, 335.0, 340.0,  # Candle 8 (+50% Surge -> Stage 2 Trail)
        335.0, 315.0, 295.0, 285.0,  # Candle 9 (Pullback -> Trailing SL / 9 EMA Exit)
    ]

    # Pre-configured simulated price progressions for Cash Equities (BULLISH & BEARISH)
    self.sim_equity_prices = {
        "BULLISH": {
            "TCS": [
                # Candle 1 (Breakout: Close 3525.0 > Base High 3520.0 & VWAP 3510.0)
                3515.0, 3518.0, 3522.0, 3525.0,
                # Candle 2 (Stage 1 Progression: Hits 3565.0 >= +1.5R 3562.5 -> BE Lock)
                3535.0, 3545.0, 3555.0, 3565.0,
                # Candle 3 (Stage 2 Progression: Hits 3590.0 >= +2.5R 3587.5 -> +1R Lock & Trail)
                3572.0, 3578.0, 3585.0, 3590.0,
                # Candle 4 (Hard Target: Hits 3628.0 >= +4.0R 3625.0 -> Immediate Exit)
                3600.0, 3610.0, 3620.0, 3628.0,
            ],
            "RELIANCE": [
                # Candle 1 (Breakout: Close 2505.0 > Base High 2500.0 & VWAP 2490.0)
                2498.0, 2501.0, 2503.0, 2505.0,
                # Candle 2 (Stage 1 Progression: Hits 2536.0 >= +1.5R 2535.06 -> BE Lock)
                2512.0, 2520.0, 2528.0, 2536.0,
                # Candle 3 (Stage 2 Progression: Hits 2558.0 >= +2.5R 2555.10 -> +1R Lock & Trail)
                2542.0, 2548.0, 2554.0, 2558.0,
                # Candle 4 (Hard Target: Hits 2588.0 >= +4.0R 2585.16 -> Immediate Exit)
                2565.0, 2574.0, 2582.0, 2588.0,
            ],
            "INFY": [
                1868.0, 1870.0, 1872.0, 1874.0,
                1870.0, 1872.0, 1874.0, 1876.0,
            ],
        },
        "BEARISH": {
            "TCS": [
                # Candle 1 (Breakdown: Close 3495.0 < Base Low 3500.0 & VWAP 3510.0)
                3502.0, 3498.0, 3496.0, 3495.0,
                # Candle 2 (Stage 1 Progression: Hits 3455.0 <= -1.5R 3457.5 -> BE Lock)
                3485.0, 3475.0, 3465.0, 3455.0,
                # Candle 3 (Stage 2 Progression: Hits 3430.0 <= -2.5R 3432.5 -> +1R Lock & Trail)
                3445.0, 3440.0, 3435.0, 3430.0,
                # Candle 4 (Hard Target: Hits 3390.0 <= -4.0R 3395.0 -> Immediate Exit)
                3415.0, 3406.0, 3398.0, 3390.0,
            ],
            "RELIANCE": [
                # Candle 1 (Breakdown: Close 2495.0 < Base Low 2500.0 & VWAP 2510.0)
                2502.0, 2498.0, 2496.0, 2495.0,
                # Candle 2 (Stage 1 Progression: Hits 2462.0 <= -1.5R 2465.06 -> BE Lock)
                2485.0, 2478.0, 2470.0, 2462.0,
                # Candle 3 (Stage 2 Progression: Hits 2440.0 <= -2.5R 2445.10 -> +1R Lock & Trail)
                2455.0, 2450.0, 2445.0, 2440.0,
                # Candle 4 (Hard Target: Hits 2410.0 <= -4.0R 2415.16 -> Immediate Exit)
                2430.0, 2422.0, 2415.0, 2410.0,
            ],
            "INFY": [
                1868.0, 1866.0, 1865.0, 1864.0,
                1866.0, 1864.0, 1862.0, 1860.0,
            ],
        },
    }

    if self.mode == "OPENALGO":
      from openalgo import api

      self.client = api(
          api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST
      )
      try:
        self.client.connect()
        self.ws_connected = True
        print("[BROKER] OpenAlgo WebSocket connected (Zero-429 real-time stream).")
      except Exception as e:
        self.ws_connected = False
        print(f"[BROKER WARNING:] WebSocket connect fallback to REST: {e}")

  def ensure_subscribed(self, symbol, exchange):
    if not self.ws_connected:
      return
    with self._sub_lock:
      if (symbol, exchange) in self.subscribed:
        return
      try:
        self.client.subscribe_quote([{"symbol": symbol, "exchange": exchange}])
        self.subscribed.add((symbol, exchange))
        time.sleep(0.8)  # Allow initial WebSocket snapshot to populate
      except Exception:
        pass

  @staticmethod
  def _parse_depth_payload(data):
    """Strict depth parser: prevents false ₹0.00 spread when broker sends bid=0/ask=0."""
    ltp = float(data.get("ltp", 0) or 0)
    raw_bid = float(data.get("bid", 0) or 0)
    raw_ask = float(data.get("ask", 0) or 0)
    valid_depth = raw_bid > 0 and raw_ask > 0 and raw_ask >= raw_bid
    if valid_depth:
      bid = raw_bid
      ask = raw_ask
      spread = round(ask - bid, 2)
    else:
      bid = round(ltp - 0.50, 2)
      ask = round(ltp + 0.50, 2)
      spread = 999.0  # Reject illiquid/missing-depth entries safely

    prev_close = float(data.get("prev_close") or data.get("prevclose") or data.get("close") or 0)
    open_px = float(data.get("open", 0) or 0)
    volume = float(data.get("volume", 0) or 0)
    high = float(data.get("high", 0) or 0)
    low = float(data.get("low", 0) or 0)

    return {
        "ltp": ltp,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "valid_depth": valid_depth,
        "prev_close": prev_close,
        "open": open_px,
        "volume": volume,
        "high": high,
        "low": low,
    }

  def _get_sim_history(self, symbol, exchange="NSE", interval="3m"):
    """Generates synthetic 3m morning session candles (09:15-11:30) for simulation."""
    candles = []
    base_center = 3510.0 if symbol == "TCS" else (2490.0 if symbol == "RELIANCE" else 1870.0)
    box_half = 10.0

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    current_time = datetime.datetime.strptime(f"{today_str} 09:15:00", "%Y-%m-%d %H:%M:%S")

    for i in range(45):
      ts_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
      offset = ((i % 5) - 2) * (box_half / 3.0)
      c_open = round(base_center + offset, 2)
      c_close = round(base_center + offset + 1.0, 2)
      c_high = round(max(c_open, c_close) + 2.0, 2)
      c_low = round(min(c_open, c_close) - 2.0, 2)
      if i >= 25:
        if i == 25:
          c_high = base_center + box_half
          c_low = base_center
        elif i == 26:
          c_high = base_center
          c_low = base_center - box_half
        else:
          c_high = min(c_high, base_center + box_half - 1.0)
          c_low = max(c_low, base_center - box_half + 1.0)

      vol = 30000.0 + (i % 7) * 2000.0
      candles.append({
          "timestamp": ts_str,
          "open": c_open,
          "high": c_high,
          "low": c_low,
          "close": c_close,
          "volume": vol,
      })
      current_time += datetime.timedelta(minutes=3)
    return candles

  def _get_sim_multiquotes(self, symbols, exchange="NSE"):
    """Generates deterministic mock quotes for the 30 Sensex constituent symbols in SIMULATION."""
    results = {}
    base_data = {
        "RELIANCE": (2520.0, 2485.0 if self.sim_regime == "BULLISH" else (2555.0 if self.sim_regime == "BEARISH" else 2518.0), 3800000),
        "TCS": (3545.0, 3500.0 if self.sim_regime == "BULLISH" else (3590.0 if self.sim_regime == "BEARISH" else 3542.0), 2200000),
        "INFY": (1882.0, 1860.0 if self.sim_regime == "BULLISH" else (1904.0 if self.sim_regime == "BEARISH" else 1880.0), 4500000),
        "HDFCBANK": (1720.0, 1715.0, 3100000),
        "ICICIBANK": (1280.0, 1276.0, 2900000),
        "BHARTIARTL": (1610.0, 1608.0, 1500000),
        "LT": (3650.0, 3645.0, 850000),
        "SBIN": (830.0, 828.0, 4800000),
        "AXISBANK": (1180.0, 1178.0, 1900000),
        "KOTAKBANK": (1790.0, 1788.0, 1200000),
        "BAJFINANCE": (6850.0, 6830.0, 600000),
        "M&M": (2920.0, 2915.0, 1100000),
        "ITC": (475.0, 474.0, 3800000),
        "ETERNAL": (280.0, 279.0, 500000),
        "SUNPHARMA": (1780.0, 1775.0, 900000),
        "TITAN": (3320.0, 3315.0, 750000),
        "HINDUNILVR": (2410.0, 2408.0, 800000),
        "TATASTEEL": (155.0, 154.5, 6200000),
        "MARUTI": (11400.0, 11380.0, 300000),
        "NTPC": (375.0, 374.0, 4100000),
        "ADANIPORTS": (1260.0, 1258.0, 1400000),
        "BEL": (295.0, 294.0, 3500000),
        "HCLTECH": (1840.0, 1836.0, 1100000),
        "ULTRACEMCO": (11200.0, 11180.0, 150000),
        "POWERGRID": (320.0, 319.0, 3200000),
        "INDIGO": (4150.0, 4140.0, 700000),
        "ASIANPAINT": (2520.0, 2516.0, 650000),
        "BAJAJFINSV": (1640.0, 1636.0, 850000),
        "TECHM": (1690.0, 1686.0, 920000),
        "TRENT": (6700.0, 6680.0, 800000),
    }

    for sym in symbols:
      if sym in base_data:
        ltp, prev_close, vol = base_data[sym]
      else:
        ltp, prev_close, vol = 1000.0, 1000.0, 500000

      spread = round(ltp * 0.0003, 2)
      if spread < 0.05:
        spread = 0.05
      bid = round(ltp - spread / 2.0, 2)
      ask = round(ltp + spread / 2.0, 2)
      results[sym] = {
          "symbol": sym,
          "ltp": ltp,
          "prev_close": prev_close,
          "open": prev_close,
          "high": round(max(ltp, prev_close) + 2.0, 2),
          "low": round(min(ltp, prev_close) - 2.0, 2),
          "volume": float(vol),
          "bid": bid,
          "ask": ask,
          "spread": spread,
          "valid_depth": True,
      }
    return results

  def get_quote(self, symbol, exchange, advance_sim=True):
    if self.mode == "SIMULATION":
      # 1. Sensex Index spot quote
      if symbol in ("SENSEX", "BSE:SENSEX") or (exchange == "BSE" and not any(k in symbol for k in ("PE", "CE"))):
        if self.sim_regime == "BULLISH":
          ltp = 83500.0
          prev_close = 83100.0
        elif self.sim_regime == "BEARISH":
          ltp = 82600.0
          prev_close = 83100.0
        else:  # SIDEWAYS
          ltp = 83150.0
          prev_close = 83100.0
        return {
            "symbol": symbol,
            "ltp": ltp,
            "prev_close": prev_close,
            "open": 83120.0,
            "high": max(ltp, prev_close) + 50.0,
            "low": min(ltp, prev_close) - 50.0,
            "volume": 0.0,
            "bid": round(ltp - 1.0, 2),
            "ask": round(ltp + 1.0, 2),
            "spread": 2.0,
            "valid_depth": True,
        }

      # 2. Equity simulated stock series
      regime_stocks = self.sim_equity_prices.get(self.sim_regime, self.sim_equity_prices["BULLISH"])
      if symbol in regime_stocks:
        series = regime_stocks[symbol]
        idx = self.sim_equity_steps.get(symbol, 0)
        price = series[min(idx, len(series) - 1)]
        if advance_sim:
          self.sim_equity_steps[symbol] = idx + 1
        return {
            "symbol": symbol,
            "ltp": price,
            "bid": round(price - 0.10, 2),
            "ask": round(price + 0.10, 2),
            "spread": 0.20,
            "valid_depth": True,
            "volume": 100000.0 + (idx * 20000.0),
            "prev_close": series[0] * (0.985 if self.sim_regime == "BULLISH" else 1.015),
            "open": series[0],
            "high": round(price + 0.50, 2),
            "low": round(price - 0.50, 2),
        }

      # 3. Default Options simulation series (preserves V3.4 behavior)
      idx = min(self.sim_step, len(self.sim_prices) - 1)
      price = self.sim_prices[idx]
      if advance_sim:
        self.sim_step += 1
      return {
          "symbol": symbol,
          "ltp": price,
          "bid": round(price - 0.15, 2),
          "ask": round(price + 0.15, 2),
          "spread": 0.30,
          "valid_depth": True,
          "volume": 50000.0,
          "prev_close": price - 1.0,
          "open": price,
      }

    # 1. Primary: Zero-REST OpenAlgo WebSocket cache
    if self.ws_connected:
      self.ensure_subscribed(symbol, exchange)
      try:
        ws_q = self.client.get_quotes(symbol=symbol, exchange=exchange)
        data = ws_q.get("data", ws_q) if isinstance(ws_q, dict) else None
        if isinstance(data, dict) and float(data.get("ltp", 0) or 0) > 0:
          return self._parse_depth_payload(data)
      except Exception:
        pass

    # 2. Fallback: Single REST quote check (no retry storms on 429)
    try:
      quote = self.client.quotes(symbol=symbol, exchange=exchange)
      if isinstance(quote, dict) and quote.get("status") == "success" and "data" in quote:
        data = quote["data"]
        if float(data.get("ltp", 0) or 0) > 0:
          return self._parse_depth_payload(data)
    except Exception as e:
      print(f"[QUOTE WARNING] {symbol}: {e}")

    return None

  def get_multiquotes(self, symbols, exchange="NSE"):
    """Fetches quotes for multiple symbols with safe chunking, fallback, and SIMULATION support."""
    norm_symbols = []
    sym_names = []
    for item in symbols:
      if isinstance(item, dict):
        s = item["symbol"]
        e = item.get("exchange", exchange)
        norm_symbols.append({"symbol": s, "exchange": e})
        sym_names.append(s)
      else:
        norm_symbols.append({"symbol": str(item), "exchange": exchange})
        sym_names.append(str(item))

    results = {}

    if self.mode == "SIMULATION":
      return self._get_sim_multiquotes(sym_names, exchange)

    # OPENALGO mode: chunk requests into batches of 10 to avoid oversized payloads
    chunk_size = 10
    chunks = [norm_symbols[i:i + chunk_size] for i in range(0, len(norm_symbols), chunk_size)]

    for chunk in chunks:
      chunk_success = False
      if self.client and hasattr(self.client, "multiquotes"):
        try:
          resp = self.client.multiquotes(symbols=chunk)
          if isinstance(resp, dict) and resp.get("status") == "success":
            data_list = resp.get("data", [])
            if isinstance(data_list, list):
              for item in data_list:
                sym = item.get("symbol")
                if sym:
                  parsed = self._parse_depth_payload(item)
                  parsed["symbol"] = sym
                  results[sym] = parsed
              chunk_success = True
        except Exception as e:
          print(f"[MULTIQUOTES WARNING] chunk failed: {e}")

      if not chunk_success:
        for item in chunk:
          sym = item["symbol"]
          ex = item.get("exchange", exchange)
          q = self.get_quote(sym, ex)
          if q:
            q["symbol"] = sym
            results[sym] = q

    return results

  def fetch_intraday_history(self, symbol, exchange="NSE", interval="3m", start_date=None, end_date=None):
    """Fetches intraday historical candles (3m) with volume, open, high, low, close, timestamp."""
    if self.mode == "SIMULATION" or not self.client:
      return self._get_sim_history(symbol, exchange, interval)

    try:
      today_str = datetime.date.today().strftime("%Y-%m-%d")
      s_date = start_date or today_str
      e_date = end_date or today_str
      hist = self.client.history(
          symbol=symbol,
          exchange=exchange,
          interval=interval,
          start_date=s_date,
          end_date=e_date,
      )
      rows = []
      if hasattr(hist, "to_dict"):
        rows = hist.reset_index().to_dict("records")
      elif isinstance(hist, dict):
        rows = hist.get("data", [])
      elif isinstance(hist, list):
        rows = hist

      candles = []
      for r in rows:
        ts_str = str(r.get("timestamp", r.get("datetime", r.get("time", ""))))
        o = float(r.get("open", 0) or 0)
        h = float(r.get("high", 0) or 0)
        l = float(r.get("low", 0) or 0)
        c = float(r.get("close", 0) or 0)
        v = float(r.get("volume", 0) or 0)
        if h <= 0 or l <= 0:
          continue
        candles.append({
            "timestamp": ts_str,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        })
      return candles
    except Exception as e:
      print(f"[HISTORY WARNING] Failed to fetch history for {symbol}: {e}")
      return []

  def fetch_freeze_hour_base(self, symbol, exchange):
    """Backfills 10:30-11:30 AM 3m candles if started late or on symbol rotation."""
    if self.mode == "SIMULATION":
      hist = self._get_sim_history(symbol, exchange, "3m")
      freeze_candles = hist[25:]
      bh = max(c["high"] for c in freeze_candles) if freeze_candles else None
      bl = min(c["low"] for c in freeze_candles) if freeze_candles else None
      return bh, bl, freeze_candles

    if not self.client:
      return None, None, []

    try:
      today_str = datetime.date.today().strftime("%Y-%m-%d")
      candles = self.fetch_intraday_history(symbol, exchange, "3m", today_str, today_str)
      base_high = None
      base_low = None
      freeze_candles = []
      for c in candles:
        ts_str = c.get("timestamp", "")
        if any(tag in ts_str for tag in ("10:3", "10:4", "10:5", "11:0", "11:1", "11:2")):
          freeze_candles.append(c)
          base_high = c["high"] if base_high is None else max(base_high, c["high"])
          base_low = c["low"] if base_low is None else min(base_low, c["low"])
      return base_high, base_low, freeze_candles or candles[-20:]
    except Exception:
      return None, None, []

  def _fetch_executed_price(self, orderid):
    """Queries OpenAlgo orderbook once to retrieve exact executed average_price."""
    if not orderid or orderid == "UNKNOWN" or not self.client:
      return 0.0
    try:
      time.sleep(0.35)
      ob = self.client.orderbook()
      orders = []
      if isinstance(ob, dict):
        data = ob.get("data", {})
        if isinstance(data, dict):
          orders = data.get("orders", [])
        elif isinstance(data, list):
          orders = data
      for o in orders:
        if str(o.get("orderid", "")) == str(orderid):
          avg_px = float(o.get("average_price", o.get("price", 0)) or 0)
          if avg_px > 0:
            return avg_px
    except Exception:
      pass
    return 0.0

  def place_market_order(self, symbol, exchange, action, qty, strategy="V3_Momentum_Engine"):
    if self.mode == "SIMULATION":
      q = self.get_quote(symbol, exchange, advance_sim=False)
      fill = q["ask"] if action == "BUY" else q["bid"]
      print(f"[SIM ORDER] {action} {qty} {symbol} @ {fill:.2f}")
      return {"status": "success", "orderid": f"SIM-{int(time.time())}", "fill_price": fill}

    try:
      resp = self.client.placeorder(
          strategy=strategy,
          symbol=symbol,
          action=action,
          exchange=exchange,
          price_type="MARKET",
          product="MIS",
          quantity=str(qty),
      )
      if not isinstance(resp, dict) or resp.get("status") != "success":
        print(f"[ORDER REJECTED] {action} {qty} {symbol} -> {resp}")
        return None
      orderid = resp.get("orderid", "UNKNOWN")
      fill_exact = self._fetch_executed_price(orderid)
      if fill_exact <= 0:
        q = self.get_quote(symbol, exchange)
        fill_exact = (q["ask"] if action == "BUY" else q["bid"]) if q else 0.0
      print(f"[OPENALGO ORDER] {action} {qty} {symbol} @ ₹{fill_exact:.2f} -> {resp}")
      return {
          "status": "success",
          "orderid": orderid,
          "fill_price": fill_exact,
      }
    except Exception as e:
      print(f"[ORDER ERROR] {action} {symbol} failed: {e}")
      return None

  def shutdown(self):
    if self.ws_connected and self.client:
      try:
        with self._sub_lock:
          if self.subscribed:
            self.client.unsubscribe_quote(
                [{"symbol": s, "exchange": e} for s, e in self.subscribed]
            )
        self.client.disconnect()
      except Exception:
        pass 