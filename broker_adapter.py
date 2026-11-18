import random
import time
from openalgo import api
import config


class BrokerAdapter:

  def __init__(self):
    self.mode = config.MODE
    self.sim_price = 120.0  # Simulation starting option premium
    self.sim_tick_count = 0

    if self.mode == "OPENALGO":
      self.client = api(
          api_key=config.OPENALGO_API_KEY, host=config.OPENALGO_HOST
      )

  def get_ltp(self, symbol, exchange):
    if self.mode == "OPENALGO":
      quote = self.client.quotes(symbol=symbol, exchange=exchange)
      return float(quote["data"]["ltp"])

    # SIMULATION MODE: Realistic option premium movement (Range -> Breakout -> Rally -> Pullback)
    self.sim_tick_count += 1
    if self.sim_tick_count <= 10:
      # Pehle 10 ticks consolidation (118 - 125 range)
      self.sim_price = round(random.uniform(118.0, 125.0), 2)
    elif self.sim_tick_count <= 35:
      # Breakout & upward momentum (SL trail test karne ke liye)
      self.sim_price = round(self.sim_price + random.uniform(-1.5, 4.0), 2)
    else:
      # Reversal / Pullback (Trailed SL hit test karne ke liye)
      self.sim_price = round(self.sim_price - random.uniform(0.5, 3.5), 2)

    return max(5.0, self.sim_price)

  def place_order(self, symbol, exchange, action, qty, price):
    if self.mode == "OPENALGO":
      return self.client.placeorder(
          strategy="Intraday_Option_Trail",
          symbol=symbol,
          action=action,
          exchange=exchange,
          price_type="MARKET",
          product="MIS",
          quantity=qty,
      )
    else:
      print(
          f"\n[SIM ORDER] {action} {qty} qty of {symbol} @ ₹{price} (MARKET)"
      )
      return {"status": "success", "mode": "SIMULATION"}