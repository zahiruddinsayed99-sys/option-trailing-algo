import datetime

# Execution Mode: "SIMULATION" (local test) ya "OPENALGO" (live feed + paper/live orders)
MODE = "OPENALGO"

# static ip 
STATIC_IP = "103.248.74.138"
API_KEY = "IME4L2EX0U-200"  # OpenAlgo API Key- App ID
API_SECRET = "k7oGcI14njkc76e8"  # OpenAlgo - Secret ID 
# OpenAlgo Settings
OPENALGO_API_KEY = "718db67be7199f4c7884bdfd30ee9c55c36a38b2e1964949c7c2e75eb5d958d7"
OPENALGO_HOST = "http://127.0.0.1:5000"

# Default Strike & Risk Parameters (Runtime par override kar sakte hain)
SYMBOL = "SENSEX26NOV2685100CE" #"SENSEX26NOV80800PE"
EXCHANGE = "BFO"  # NFO (Nifty/BankNifty) ya BFO (Sensex)
QTY = 20  # 1 Lot Sensex = 20, Nifty = 75

# Entry & Candle Confirmation Rules
CANDLE_TIMEFRAME_SEC = 180  # 3-minute candle close confirmation
USE_VWAP_FILTER = True  # Entry sirf tab jab close >= running VWAP
ENTRY_BUFFER_POINTS = 1.0  # Reference high ke upar buffer

# Stop-Loss & Trailing Rules
INITIAL_SL_POINTS = 15.0  # Strict Initial SL (₹300 risk on 20 qty)
TRAIL_STEP_POINTS = 8.0  # Breakeven ke baad har 8 pt move par SL trail
MOVE_TO_BREAKEVEN_AT_1R = True  # 1:1 profit par Cost-to-Cost lock

# Daily Discipline Guardrails (Kill Switch)
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 800.0  # Max daily loss cap in INR
TRADING_START_TIME = datetime.time(11, 30)
TRADING_END_TIME = datetime.time(13, 30)
SQUARE_OFF_TIME = datetime.time(15, 15)