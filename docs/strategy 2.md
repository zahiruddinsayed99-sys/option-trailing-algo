```python
import pandas as pd
df = pd.read_csv('1_Lot_Momentum_Option_Trading_System_V3 - Emotion_Discipline_Protocol.csv')
for idx, row in df.iterrows():
    print(f"Row {idx}: {row.dropna().to_dict()}")


```

```text
Row 0: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Strict psychological protocols to eliminate early profit booking, fear of drawdown, revenge trading, and screen staring'}
Row 1: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Stage / Time Window', 'Unnamed: 1': 'Rule / Technical Condition', 'Unnamed: 2': 'Exact Broker Order Action', 'Unnamed: 3': 'Emotional Pitfall to Neutralize'}
Row 2: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Pre-Market (09:15 - 09:30)', 'Unnamed: 1': 'Macro Regime & VIX Verification', 'Unnamed: 2': 'Check India VIX. Check Sensex 15m VWAP. Commit to ONLY CE or ONLY PE for the day.', 'Unnamed: 3': 'Trying to trade both sides or jumping into early opening tick chop.'}
Row 3: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Screening (09:30 - 10:30)', 'Unnamed: 1': 'Sensex Constituent Radar (Volume >= 1.5x, Spot/Fut > VWAP)', 'Unnamed: 2': 'Pick 1-2 candidate stocks max. Add ATM strike to watchlist. Check bid-ask spread <= ₹0.10.', 'Unnamed: 3': 'FOMO - Chasing extended stocks that are already up 4-5%.'}
Row 4: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Freeze Hour (10:30 - 11:30)', 'Unnamed: 1': 'No-Trade Inventory Observation Window', 'Unnamed: 2': 'STRICTLY NO ORDERS. Observe 3-minute option chart for 4-6 candle horizontal base.', 'Unnamed: 3': 'Impatience, boredom trading, or forcing trades during mid-day consolidation.'}
Row 5: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Execution (11:30 - 13:30)', 'Unnamed: 1': 'Pre-Condition & Risk Filter (<15%)', 'Unnamed: 2': 'Calculate: (Entry - Base Low) / Entry. If >15-20%, CANCEL trade instantly.', 'Unnamed: 3': "Greed - Entering with high risk because 'the setup looks too good to pass'.", 'Unnamed: 4': 20.0, 'Unnamed: 5': 14.0, 'Unnamed: 6': 30.0}
Row 6: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Entry Execution', 'Unnamed: 1': 'Breakout Candle Close Confirmation', 'Unnamed: 2': 'Place Limit Buy order at breakout candle close. IMMEDIATELY place hard GTT Stop Loss at base low.', 'Unnamed: 3': 'Hesitation at the breakout point or buying with wide market orders.'}
Row 7: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Stage 1 (+25% to +30%)', 'Unnamed: 1': 'First Milestone Reached', 'Unnamed: 2': 'Modify GTT SL immediately to exact Entry Price (Cost-to-Cost). Trade is 100% Risk-Free.', 'Unnamed: 3': 'Fear of losing floating green profit leading to premature +10% exit.'}
Row 8: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Stage 2 (+50% Move)', 'Unnamed: 1': 'Second Milestone Reached', 'Unnamed: 2': 'Modify SL order to the low of the last 2 candles on the 3m chart. Lock in +25% profit.', 'Unnamed: 3': 'Greedily hoping for 2x without securing guaranteed bankable profit.'}
Row 9: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Stage 3 (Riding Trend)', 'Unnamed: 1': 'Hold Above 9 EMA', 'Unnamed: 2': 'DO NOT TOUCH the trade while 3m candle closes remain above the 9 EMA.', 'Unnamed: 3': 'Screen anxiety - staring at intra-candle red wicks and panicking before candle close.'}
Row 10: {'EMOTION-FREE EXECUTION BLUEPRINT & PSYCHOLOGICAL FIREWALL': 'Stage 4 (Climax / 2x)', 'Unnamed: 1': 'Double Target OR Climax Rejection', 'Unnamed: 2': "Hit 2x limit order OR exit immediately when a candle breaks previous candle's low after an extended wick.", 'Unnamed: 3': 'Holding through a complete trend reversal hoping for a dead-cat bounce.'}


```

Aapki CSV sheet (`1_Lot_Momentum_Option_Trading_System_V3 - Emotion_Discipline_Protocol.csv`) ke har stage ka technical audit karne par **4 critical edge-cases / tweaks** saamne aaye hain jinko fix karna zaroori hai, aur phir hum iske liye ek **dedicated, standalone file (`v3_momentum_engine.py`)** banayenge taaki aapka existing `strategy_engine.py` intact rahe.

---

### 1. Technical Audit & Required Fixes (Before Coding)

1. **Bid-Ask Spread (`<= ₹0.10` vs. SENSEX Option Liquidity):**
* *Audit:* Stock options mein `₹0.10` spread common hai, lekin **SENSEX options (BFO)** par tick size `₹0.05` hone ke bawajood normal spread **`₹0.25` se `₹1.00**` ke beech rehta hai (aapke pichle Zerodha screenshot mein bhi `85.80` vs `85.55` = **`₹0.25` spread** tha). Agar hum `<= ₹0.10` hard-code karenge toh SENSEX ke saare valid trades reject ho jayenge.
* *Fix:* `MAX_BID_ASK_SPREAD` ko configurable rakhenge—**Stock options ke liye `₹0.15**` aur **SENSEX/Index options ke liye `₹1.00**` (or `<= 1%` of LTP).


2. **Stage 2 (`+50% Move` $\rightarrow$ Last 2-Candle Low) vs. Stage 3 (`Hold Above 9 EMA`):**
* *Audit:* Agar trade `+50%` pahunch kar Stage 2 mein aa gaya (SL locked at `max(last_2_candle_lows, entry * 1.25)`), aur phir Stage 3 mein **3-min candle 9 EMA ke niche close** ho jati hai jabki SL abhi hit nahi hua—toh kya exit karna hai?
* *Fix:* Stage 2 active hone ke baad dono protections chalenge—**Tick-by-tick Hard SL** (jo kabhi `+25%` profit lock ke niche nahi jayega) **PLUS** **3-min Candle Close < 9 EMA exit**, taaki trend khatam hote hi profit secure ho jaye.


3. **9 EMA Warm-up Period (Cold Start Fix):**
* *Audit:* 9 EMA calculate karne ke liye kam se kam **9 completed 3-min candles (27 minutes)** chahiye. Agar script `11:15 AM` par start hogi, toh `11:30 AM` tak sirf 5 candles banengi.
* *Fix:* `10:30 AM` se hi observation start karein (20 candles = 60 mins) ya OpenAlgo ke `history()` API se pichle 15 candles pre-load karein taaki `11:30 AM` par 9 EMA 100% accurate ready rahe.


4. **GTT Order vs. Intraday MIS Trailing SL:**
* *Audit:* Zerodha/Fyers mein GTT orders zyada tar `NRML` overnight positions ke liye hote hain, jabki intraday option buying `MIS` product mein hoti hai jahan broker ka native **`SL` / `SL-M` order** (`modifyorder` ke saath) zyada fast aur reliable hota hai.
* *Fix:* Engine mein `MIS` Limit Entry + `SL` order modification architecture rakhenge (Analyze Mode mein virtual aur Live Mode mein broker-side `modifyorder`).



---

### 2. New Dedicated File: `v3_momentum_engine.py`

Aapke existing `config.py` aur `broker_adapter.py` ko reuse karte hue, hum ek **nayi standalone file `v3_momentum_engine.py**` banayenge (taaki aap jab chahein purana `strategy_engine.py` ya naya `v3_momentum_engine.py` chala sakein).

Apne `~/trading-projects/option-trailing-algo/` folder mein **`v3_momentum_engine.py`** ke naam se yeh complete code save karein:

```python
import csv
import datetime
import os
import time
from broker_adapter import BrokerAdapter
import config

# ==========================================
# V3 EMOTION-DISCIPLINE PROTOCOL PARAMETERS
# ==========================================
MAX_RISK_PCT = 0.15  # Max 15% risk: (Entry - Base Low) / Entry <= 0.15
MAX_SPREAD_INDEX = 1.00  # Max Bid-Ask spread for SENSEX/NIFTY (₹)
MAX_SPREAD_STOCK = 0.15  # Max Bid-Ask spread for Stock Options (₹)
STAGE1_TRIGGER_PCT = 0.25  # +25% move -> Shift SL to Cost-to-Cost (Breakeven)
STAGE2_TRIGGER_PCT = 0.50  # +50% move -> Trail by Last 2-Candle Low (min +25% locked)
STAGE2_LOCK_PCT = 0.25  # Minimum +25% profit floor once Stage 2 activates
TARGET_2X_MULTIPLIER = 2.0  # +100% (2x) hard profit target
EMA_PERIOD = 9  # 9 EMA on 3-minute candle closes
UPPER_WICK_RATIO = 2.0  # Upper wick > 2x body signals climax exhaustion


def calculate_ema(closes, period=9):
  if len(closes) < period:
    return None
  k = 2 / (period + 1)
  ema = sum(closes[:period]) / period
  for price in closes[period:]:
    ema = (price * k) + (ema * (1 - k))
  return round(ema, 2)


def get_today_stats(csv_file="v3_paper_trades_log.csv"):
  if not os.path.isfile(csv_file):
    return 0, 0.0
  today_str = str(datetime.date.today())
  trades = 0
  total_pnl = 0.0
  with open(csv_file, mode="r") as f:
    reader = csv.DictReader(f)
    for row in reader:
      if row.get("Date") == today_str:
        trades += 1
        total_pnl += float(row.get("Net_PnL", 0.0))
  return trades, round(total_pnl, 2)


def log_v3_trade(
    symbol,
    entry_time,
    exit_time,
    entry_p,
    exit_p,
    base_low,
    max_p,
    qty,
    stage_reached,
    reason,
):
  csv_file = "v3_paper_trades_log.csv"
  file_exists = os.path.isfile(csv_file)
  gross_pnl = round((exit_p - entry_p) * qty, 2)
  est_charges = round((entry_p + exit_p) * qty * 0.0025, 2)
  net_pnl = round(gross_pnl - est_charges, 2)
  risk_pct = round(((entry_p - base_low) / entry_p) * 100, 2)

  with open(csv_file, mode="a", newline="") as f:
    writer = csv.writer(f)
    if not file_exists:
      writer.writerow([
          "Date",
          "Symbol",
          "Entry_Time",
          "Exit_Time",
          "Entry_Price",
          "Base_Low",
          "Risk_Pct",
          "Exit_Price",
          "Highest_Price",
          "Qty",
          "Gross_PnL",
          "Net_PnL",
          "Highest_Stage",
          "Exit_Reason",
      ])
    writer.writerow([
        datetime.date.today(),
        symbol,
        entry_time,
        exit_time,
        entry_p,
        base_low,
        risk_pct,
        exit_p,
        max_p,
        qty,
        gross_pnl,
        net_pnl,
        stage_reached,
        reason,
    ])
  print(
      f"\n[V3 CSV LOGGED] Gross P&L: ₹{gross_pnl} | Net P&L: ₹{net_pnl} | Stage:"
      f" {stage_reached}"
  )


def run_v3_strategy():
  trades_today, pnl_today = get_today_stats()
  if trades_today >= config.MAX_TRADES_PER_DAY:
    print(
        f"[KILL SWITCH] Max daily trades ({config.MAX_TRADES_PER_DAY})"
        " reached. Exiting."
    )
    return
  if pnl_today <= -abs(config.MAX_DAILY_LOSS):
    print(
        f"[KILL SWITCH] Max daily loss (-₹{config.MAX_DAILY_LOSS}) breached."
        " Exiting."
    )
    return

  print("\n=== V3 EMOTION-FREE MOMENTUM ENGINE SETUP ===")
  sym_in = input(f"Candidate Strike [{config.SYMBOL}]: ").strip().upper()
  exch_in = input(f"Exchange [{config.EXCHANGE}]: ").strip().upper()
  qty_in = input(f"Quantity [{config.QTY}]: ").strip()

  symbol = sym_in if sym_in else config.SYMBOL
  exchange = exch_in if exch_in else config.EXCHANGE
  qty = int(qty_in) if qty_in else config.QTY
  max_spread = (
      MAX_SPREAD_INDEX
      if any(idx in symbol for idx in ["SENSEX", "NIFTY", "BANKNIFTY"])
      else MAX_SPREAD_STOCK
  )

  broker = BrokerAdapter()
  print(
      f"\n>>> Starting V3 Engine [{config.MODE}] | {symbol} ({exchange}) | Max"
      f" Spread: ₹{max_spread} | Trades: {trades_today}/{config.MAX_TRADES_PER_DAY}"
      " <<<"
  )

  # 3-Minute OHLC History & Base State
  candles = []  # List of dicts: {'open', 'high', 'low', 'close'}
  current_ticks = []
  ticks_per_candle = 5 if config.MODE == "SIMULATION" else 180
  base_candles_needed = 4  # 4-6 candle horizontal base observation

  base_high = 0.0
  base_low = float("inf")
  base_locked = False

  # Trade State
  in_trade = False
  entry_price = 0.0
  entry_time = ""
  current_sl = 0.0
  target_2x = 0.0
  highest_ltp = 0.0
  stage = "BASE_OBSERVATION"

  while True:
    now_dt = datetime.datetime.now()
    now_time = now_dt.time()

    # Freeze Hour & Execution Window Enforcement (Live Mode)
    if config.MODE == "OPENALGO":
      if now_time < datetime.time(10, 30):
        print("Waiting for 10:30 AM Freeze Hour observation window...", end="\r")
        time.sleep(1)
        continue
      if not in_trade and now_time > config.TRADING_END_TIME:
        print(
            "\n[SESSION END] Past 13:30 IST execution cutoff. No new trades."
        )
        break

    ltp = broker.get_ltp(symbol, exchange)
    if ltp is None:
      time.sleep(1)
      continue

    current_ticks.append(ltp)

    # ==========================================
    # 3-MINUTE CANDLE CLOSE PROCESSING
    # ==========================================
    if len(current_ticks) >= ticks_per_candle:
      candle = {
          "open": current_ticks[0],
          "high": max(current_ticks),
          "low": min(current_ticks),
          "close": current_ticks[-1],
      }
      candles.append(candle)
      current_ticks = []
      ema_9 = calculate_ema([c["close"] for c in candles], EMA_PERIOD)

      # PHASE A: FREEZE HOUR / 4-CANDLE HORIZONTAL BASE
      if len(candles) <= base_candles_needed:
        base_high = max(base_high, candle["high"])
        base_low = min(base_low, candle["low"])
        print(
            f"[BASE CANDLE {len(candles)}/{base_candles_needed}] Close:"
            f" {candle['close']:.2f} | Base Range: [{base_low:.2f} -"
            f" {base_high:.2f}]"
        )
        if len(candles) == base_candles_needed:
          base_locked = True
          print(
              f"\n>>> [BASE LOCKED] Breakout Trigger > {base_high:.2f} | Base"
              f" Low SL: {base_low:.2f} <<<\n"
          )
        continue

      # PHASE B: BREAKOUT ENTRY & <15% RISK FILTER (Execution Window 11:30 - 13:30)
      if base_locked and not in_trade:
        in_exec_window = (
            True
            if config.MODE == "SIMULATION"
            else (config.TRADING_START_TIME <= now_time <= config.TRADING_END_TIME)
        )

        if in_exec_window and candle["close"] > base_high:
          proposed_entry = candle["close"]
          risk_pct = (proposed_entry - base_low) / proposed_entry

          if risk_pct > MAX_RISK_PCT:
            print(
                f"\n[TRADE CANCELLED - RISK FILTER] Risk {risk_pct*100:.1f}% >"
                f" Max {MAX_RISK_PCT*100:.0f}% (Entry: {proposed_entry:.2f},"
                f" Base Low: {base_low:.2f}). Skipping setup!"
            )
            break

          # Place Limit Buy at Breakout Candle Close
          res = broker.place_order(
              symbol, exchange, "BUY", qty, round(proposed_entry + 0.05, 2)
          )
          if res:
            in_trade = True
            entry_price = proposed_entry
            entry_time = now_time.strftime("%H:%M:%S")
            current_sl = base_low
            target_2x = round(entry_price * TARGET_2X_MULTIPLIER, 2)
            highest_ltp = entry_price
            stage = "INITIAL_BASE_SL"
            print(
                f"\n>>> [V3 ENTRY] BUY {symbol} @ {entry_price:.2f} | Risk:"
                f" {risk_pct*100:.1f}% | Hard SL: {current_sl:.2f} | 2x Target:"
                f" {target_2x:.2f} <<<\n"
            )
        else:
          print(
              f"[SCANNING 3M] Close: {candle['close']:.2f} | Base High:"
              f" {base_high:.2f} | 9 EMA: {ema_9}"
          )

      # PHASE C: CANDLE-CLOSE EXIT CHECKS (Stage 3: 9 EMA & Stage 4: Climax Rejection)
      elif in_trade:
        # Stage 2+: Update SL to Low of Last 2 Candles (never below +25% profit floor)
        if stage in ["STAGE_2_TRAIL", "STAGE_3_EMA_RIDE"] and len(candles) >= 2:
          last_2_low = min(candles[-1]["low"], candles[-2]["low"])
          floor_25 = round(entry_price * (1 + STAGE2_LOCK_PCT), 2)
          new_sl = round(max(last_2_low, floor_25), 2)
          if new_sl > current_sl:
            current_sl = new_sl
            print(
                "\n>>> [STAGE 2 TRAIL] SL moved to 2-Candle Low / +25% Floor:"
                f" {current_sl:.2f} <<<\n"
            )

        # Stage 3: Hold Above 9 EMA (Exit if 3m candle closes below 9 EMA once in Stage 2+)
        if (
            stage in ["STAGE_2_TRAIL", "STAGE_3_EMA_RIDE"]
            and ema_9 is not None
            and candle["close"] < ema_9
        ):
          broker.place_order(symbol, exchange, "SELL", qty, ltp)
          exit_time = now_time.strftime("%H:%M:%S")
          print(
              f"\n>>> [STAGE 3 EXIT - 9 EMA BREAK] Close {candle['close']:.2f}"
              f" < 9 EMA {ema_9:.2f} | Sold @ {ltp:.2f} <<<"
          )
          log_v3_trade(
              symbol,
              entry_time,
              exit_time,
              entry_price,
              ltp,
              base_low,
              highest_ltp,
              qty,
              stage,
              "3m Close Below 9 EMA",
          )
          break

        # Stage 4: Climax Rejection (Previous candle had extended upper wick, current breaks its low)
        if len(candles) >= 2:
          prev = candles[-2]
          prev_body = abs(prev["close"] - prev["open"])
          prev_upper_wick = prev["high"] - max(prev["open"], prev["close"])
          if (
              prev_body > 0
              and prev_upper_wick >= (UPPER_WICK_RATIO * prev_body)
              and candle["low"] < prev["low"]
          ):
            broker.place_order(symbol, exchange, "SELL", qty, ltp)
            exit_time = now_time.strftime("%H:%M:%S")
            print(
                "\n>>> [STAGE 4 EXIT - CLIMAX WICK REJECTION] Broke prev low"
                f" {prev['low']:.2f} | Sold @ {ltp:.2f} <<<"
            )
            log_v3_trade(
                symbol,
                entry_time,
                exit_time,
                entry_price,
                ltp,
                base_low,
                highest_ltp,
                qty,
                "STAGE_4_CLIMAX",
                "Climax Wick Rejection",
            )
            break

    # ==========================================
    # TICK-BY-TICK MILESTONES & HARD SL CHECKS
    # ==========================================
    if in_trade:
      if ltp > highest_ltp:
        highest_ltp = ltp

      gain_pct = (highest_ltp - entry_price) / entry_price

      # Stage 1 (+25% to +30%): Move SL to Cost-to-Cost (Risk-Free)
      if gain_pct >= STAGE1_TRIGGER_PCT and stage == "INITIAL_BASE_SL":
        current_sl = entry_price
        stage = "STAGE_1_BREAKEVEN"
        print(
            "\n>>> [STAGE 1 (+25%)] SL modified to Cost-to-Cost:"
            f" {current_sl:.2f} (100% Risk-Free) <<<\n"
        )

      # Stage 2 (+50% Move): Lock +25% floor & activate 2-Candle Low + 9 EMA trail
      if gain_pct >= STAGE2_TRIGGER_PCT and stage == "STAGE_1_BREAKEVEN":
        floor_25 = round(entry_price * (1 + STAGE2_LOCK_PCT), 2)
        last_2_low = (
            min(candles[-1]["low"], candles[-2]["low"])
            if len(candles) >= 2
            else floor_25
        )
        current_sl = round(max(floor_25, last_2_low), 2)
        stage = "STAGE_2_TRAIL"
        print(
            "\n>>> [STAGE 2 (+50%)] Locked +25% / 2-Candle Low SL:"
            f" {current_sl:.2f} | Riding 9 EMA <<<\n"
        )

      # Stage 4 (2x Target Hit)
      if ltp >= target_2x:
        broker.place_order(symbol, exchange, "SELL", qty, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        print(
            "\n>>> [STAGE 4 EXIT - 2X TARGET HIT] Double target reached! Sold @"
            f" {ltp:.2f} <<<"
        )
        log_v3_trade(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            base_low,
            highest_ltp,
            qty,
            "STAGE_4_2X_TARGET",
            "2x Target Hit (+100%)",
        )
        break

      live_pnl = round((ltp - entry_price) * qty, 2)
      print(
          f"[{stage}] LTP: {ltp:.2f} (+{((ltp-entry_price)/entry_price)*100:.1f}%)"
          f" | SL: {current_sl:.2f} | 2x: {target_2x:.2f} | P&L: ₹{live_pnl}"
      )

      # Hard Stop-Loss Hit
      if ltp <= current_sl:
        broker.place_order(symbol, exchange, "SELL", qty, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        print(f"\n>>> [HARD SL EXIT] Triggered @ {ltp:.2f} (SL: {current_sl:.2f}) <<<")
        log_v3_trade(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            base_low,
            highest_ltp,
            qty,
            stage,
            f"SL Hit ({stage})",
        )
        break

      # EOD Square-Off
      if config.MODE == "OPENALGO" and now_time >= config.SQUARE_OFF_TIME:
        broker.place_order(symbol, exchange, "SELL", qty, ltp)
        exit_time = now_time.strftime("%H:%M:%S")
        log_v3_trade(
            symbol,
            entry_time,
            exit_time,
            entry_price,
            ltp,
            base_low,
            highest_ltp,
            qty,
            stage,
            "EOD Square-Off",
        )
        break

    time.sleep(0.3 if config.MODE == "SIMULATION" else 1.0)


if __name__ == "__main__":
  run_v3_strategy()

```

---

### 3. Test & Push to GitHub

WSL terminal mein `v3_momentum_engine.py` save karne ke baad run karke dekhein:

```bash
cd ~/trading-projects/option-trailing-algo
source venv/bin/activate
python v3_momentum_engine.py

```

Yeh **4 base candles** observe karega, `<15%` risk verify karega, breakout candle close par entry lega, aur `+25%` (Breakeven) $\rightarrow$ `+50%` (2-candle low + 9 EMA ride) $\rightarrow$ `2x / Climax rejection` stages execute karke `v3_paper_trades_log.csv` mein save karega. Test ke baad `git add v3_momentum_engine.py && git commit -m "feat: add V3 emotion-discipline momentum option engine" && git push` kar dein!