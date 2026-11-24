import datetime
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
    ltp = float(data["ltp"])
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
    return {
        "ltp": ltp,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "valid_depth": valid_depth,
    }

  def get_quote(self, symbol, exchange, advance_sim=True):
    if self.mode == "SIMULATION":
      idx = min(self.sim_step, len(self.sim_prices) - 1)
      price = self.sim_prices[idx]
      if advance_sim:
        self.sim_step += 1
      return {
          "ltp": price,
          "bid": round(price - 0.15, 2),
          "ask": round(price + 0.15, 2),
          "spread": 0.30,
          "valid_depth": True,
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

  def fetch_freeze_hour_base(self, symbol, exchange):
    """Backfills 10:30-11:30 AM 3m candles if OTM rotation switches into a new strike mid-session."""
    if self.mode == "SIMULATION" or not self.client:
      return None, None, []
    try:
      today_str = datetime.date.today().strftime("%Y-%m-%d")
      hist = self.client.history(
          symbol=symbol,
          exchange=exchange,
          interval="3m",
          start_date=today_str,
          end_date=today_str,
      )
      rows = hist.get("data", []) if isinstance(hist, dict) else []
      candles = []
      base_high = None
      base_low = None
      for r in rows:
        ts_str = str(r.get("timestamp", r.get("datetime", "")))
        h = float(r.get("high", 0) or 0)
        l = float(r.get("low", 0) or 0)
        o = float(r.get("open", 0) or 0)
        c = float(r.get("close", 0) or 0)
        if h <= 0 or l <= 0:
          continue
        candles.append({"open": o, "high": h, "low": l, "close": c})
        if any(tag in ts_str for tag in ("10:3", "10:4", "10:5", "11:0", "11:1", "11:2")):
          base_high = h if base_high is None else max(base_high, h)
          base_low = l if base_low is None else min(base_low, l)
      return base_high, base_low, candles[-20:]
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

  def place_market_order(self, symbol, exchange, action, qty):
    if self.mode == "SIMULATION":
      q = self.get_quote(symbol, exchange, advance_sim=False)
      fill = q["ask"] if action == "BUY" else q["bid"]
      print(f"[SIM ORDER] {action} {qty} {symbol} @ {fill:.2f}")
      return {"status": "success", "orderid": f"SIM-{int(time.time())}", "fill_price": fill}

    try:
      resp = self.client.placeorder(
          strategy="V3_Momentum_Engine",
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