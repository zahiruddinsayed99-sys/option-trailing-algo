import random
import time
from openalgo import api
import config


class BrokerAdapter:

  def __init__(self):
    self.mode = config.MODE
    self.sim_prices = {}
    self.sim_tick_count = 0

    if self.mode == "OPENALGO":
      self.client = api(
          api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST
      )

  def _execute_with_retry(self, func, *args, retries=3, delay=0.5, **kwargs):
    last_err = None
    for attempt in range(1, retries + 1):
      try:
        return func(*args, **kwargs)
      except Exception as e:
        last_err = e
        print(
            f"\n[API WARNING] Attempt {attempt}/{retries} failed: {e}."
            f" Retrying in {delay}s..."
        )
        time.sleep(delay)
        delay *= 2
    print(f"\n[API ERROR] All {retries} attempts failed: {last_err}")
    return None

  def get_quote(self, symbol, exchange):
    if self.mode == "OPENALGO":

      def _fetch():
        quote = self.client.quotes(symbol=symbol, exchange=exchange)
        data = quote["data"]
        ltp = float(data["ltp"])
        bid = float(data.get("bid", ltp))
        ask = float(data.get("ask", ltp))
        spread = round(max(0.0, ask - bid), 2)
        return {"ltp": ltp, "bid": bid, "ask": ask, "spread": spread}

      return self._execute_with_retry(_fetch)

    # SIMULATION MODE: Multi-strike realistic price simulation
    if symbol not in self.sim_prices:
      idx = len(self.sim_prices)
      self.sim_prices[symbol] = round(290.0 - (idx * 45.0), 2)

    self.sim_tick_count += 1
    p = self.sim_prices[symbol]
    if self.sim_tick_count <= 20:
      p = round(p + random.uniform(-2.0, 2.2), 2)
    elif self.sim_tick_count <= 80:
      p = round(p + random.uniform(-1.0, 4.5), 2)
    else:
      p = round(p - random.uniform(0.5, 3.5), 2)

    p = max(15.0, p)
    self.sim_prices[symbol] = p
    return {"ltp": p, "bid": round(p - 0.25, 2), "ask": round(p + 0.25, 2), "spread": 0.50}

  def get_ltp(self, symbol, exchange):
    q = self.get_quote(symbol, exchange)
    return q["ltp"] if q else None

  def place_order(self, symbol, exchange, action, qty, price):
    if self.mode == "OPENALGO":

      def _order():
        return self.client.placeorder(
            strategy="Intraday_Option_Trail",
            symbol=symbol,
            action=action,
            exchange=exchange,
            price_type="MARKET",
            product="MIS",
            quantity=qty,
        )

      return self._execute_with_retry(_order)

    print(f"\n[SIM ORDER] {action} {qty} qty of {symbol} @ ₹{price:.2f}")
    return {"status": "success", "mode": "SIMULATION"}