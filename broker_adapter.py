import random
import time
from openalgo import api
import config


class BrokerAdapter:

  def __init__(self):
    self.mode = config.MODE
    self.sim_price = 120.0
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
        delay *= 2  # Exponential backoff
    print(f"\n[API ERROR] All {retries} attempts failed: {last_err}")
    return None

  def get_ltp(self, symbol, exchange):
    if self.mode == "OPENALGO":

      def _fetch():
        quote = self.client.quotes(symbol=symbol, exchange=exchange)
        return float(quote["data"]["ltp"])

      return self._execute_with_retry(_fetch)

    # SIMULATION MODE: Realistic 3-min candle & breakout simulation
    self.sim_tick_count += 1
    if self.sim_tick_count <= 15:
      # Initial consolidation (118 - 124)
      self.sim_price = round(random.uniform(118.0, 124.0), 2)
    elif self.sim_tick_count <= 45:
      # Sustained breakout above range + VWAP
      self.sim_price = round(self.sim_price + random.uniform(-0.8, 3.2), 2)
    else:
      # Pullback to test trailed SL
      self.sim_price = round(self.sim_price - random.uniform(0.5, 3.0), 2)

    return max(5.0, self.sim_price)

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