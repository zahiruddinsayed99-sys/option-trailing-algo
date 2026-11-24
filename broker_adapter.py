import time
import config


class BrokerAdapter:
  """Unified adapter supporting SIMULATION and OpenAlgo WebSocket + REST modes."""

  def __init__(self):
    self.mode = config.MODE.upper()
    self.client = None
    self.ws_connected = False
    self.subscribed = set()
    self.sim_step = 0
    self.sim_prices = [
        180.0, 182.0, 181.0, 184.0,  # Candle 1 (Observe)
        185.0, 188.0, 186.0, 189.0,  # Candle 2 (Observe)
        188.0, 190.0, 187.0, 189.5,  # Candle 3 (Observe)
        189.0, 191.0, 188.5, 190.0,  # Candle 4 (Observe -> Base High ~ 191.0, Base Low ~ 180.0)
        190.5, 192.0, 194.0, 196.5,  # Candle 5 (Breakout > 191.0 -> ENTRY @ ~196.5)
        198.0, 205.0, 212.0, 218.0,  # Candle 6 (+10% -> Stage 1 Breakeven)
        225.0, 245.0, 275.0, 300.0,  # Candle 7 (+52% -> Stage 2 +25% Profit Lock)
        310.0, 330.0, 345.0, 340.0,  # Candle 8 (Trailing higher)
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
        print(f"[BROKER WARNING] WebSocket connect fallback to REST: {e}")

  def ensure_subscribed(self, symbol, exchange):
    if not self.ws_connected or (symbol, exchange) in self.subscribed:
      return
    try:
      self.client.subscribe_quote([{"symbol": symbol, "exchange": exchange}])
      self.subscribed.add((symbol, exchange))
      time.sleep(0.4)
    except Exception:
      pass

  def get_quote(self, symbol, exchange):
    if self.mode == "SIMULATION":
      price = self.sim_prices[min(self.sim_step, len(self.sim_prices) - 1)]
      self.sim_step += 1
      return {
          "ltp": price,
          "bid": round(price - 0.15, 2),
          "ask": round(price + 0.15, 2),
          "spread": 0.30,
      }

    # 1. Primary: Zero-REST OpenAlgo WebSocket cache
    if self.ws_connected:
      self.ensure_subscribed(symbol, exchange)
      try:
        ws_q = self.client.get_quotes(symbol=symbol, exchange=exchange)
        data = ws_q.get("data", ws_q) if isinstance(ws_q, dict) else None
        if isinstance(data, dict) and float(data.get("ltp", 0)) > 0:
          ltp = float(data["ltp"])
          bid = float(data.get("bid", ltp))
          ask = float(data.get("ask", ltp))
          spread = round(max(0.0, ask - bid), 2)
          return {"ltp": ltp, "bid": bid, "ask": ask, "spread": spread}
      except Exception:
        pass

    # 2. Fallback: Single REST quote check (no retry storms on 429)
    try:
      quote = self.client.quotes(symbol=symbol, exchange=exchange)
      if isinstance(quote, dict) and quote.get("status") == "success" and "data" in quote:
        data = quote["data"]
        ltp = float(data["ltp"])
        bid = float(data.get("bid", ltp))
        ask = float(data.get("ask", ltp))
        spread = round(max(0.0, ask - bid), 2)
        return {"ltp": ltp, "bid": bid, "ask": ask, "spread": spread}
    except Exception as e:
      print(f"[QUOTE WARNING] {symbol}: {e}")

    return None

  def place_market_order(self, symbol, exchange, action, qty):
    if self.mode == "SIMULATION":
      q = self.get_quote(symbol, exchange)
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
      q = self.get_quote(symbol, exchange)
      fill_est = (q["ask"] if action == "BUY" else q["bid"]) if q else 0.0
      print(f"[OPENALGO ORDER] {action} {qty} {symbol} -> {resp}")
      return {
          "status": "success",
          "orderid": resp.get("orderid", "UNKNOWN"),
          "fill_price": fill_est,
      }
    except Exception as e:
      print(f"[ORDER ERROR] {action} {symbol} failed: {e}")
      return None

  def shutdown(self):
    if self.ws_connected and self.client:
      try:
        if self.subscribed:
          self.client.unsubscribe_quote(
              [{"symbol": s, "exchange": e} for s, e in self.subscribed]
          )
        self.client.disconnect()
      except Exception:
        pass