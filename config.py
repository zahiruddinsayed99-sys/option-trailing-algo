import datetime
import json
import os

# --- EXECUTION MODE ---
# "SIMULATION" = Local dry-run with synthetic ticks (0 API calls)
# "OPENALGO"   = Live/Paper routing via local OpenAlgo server (Analyze Mode)
MODE = os.getenv("OPENALGO_MODE", "OPENALGO")
AUTO_START = os.getenv("AUTO_START", "FALSE").upper() == "TRUE"

# --- OPENALGO LOCAL GATEWAY ---
OPENALGO_HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
try:
  from config_local import OPENALGO_API_KEY
except ImportError:
  OPENALGO_API_KEY = os.getenv("OPENALGO_API_KEY", "YOUR_OPENALGO_API_KEY_HERE")

# --- DEFAULT CONTRACT & MULTI-STRIKE WATCHLIST ---

# --- DYNAMIC INDEX ROTATION (SENSEX primary -> NIFTY fallback when DTE < MIN_DTE) ---
MIN_DTE = int(os.getenv("MIN_DTE", "2"))
AUTO_INDEX_ROTATION = os.getenv("AUTO_INDEX_ROTATION", "TRUE").upper() == "TRUE"
PRIMARY_INDEX = "SENSEX"
PRIMARY_EXCHANGE = "BFO"
FALLBACK_INDEX = "NIFTY"
FALLBACK_EXCHANGE = "NFO"

# --- DEFAULT STRATEGY PARAMETERS ---
UNDERLYING = "NIFTY"
EXCHANGE = "NFO"
QTY = 65
CANDIDATE_STRIKES = [
    "NIFTY01DEC2626200CE",
    "NIFTY01DEC2626250CE",
    "NIFTY01DEC2626300CE",
    "NIFTY01DEC2626350CE",
]
SYMBOL = CANDIDATE_STRIKES[0]
EQUITY_WATCHLIST = ['BAJFINANCE', 'HINDUNILVR', 'BAJAJFINSV']
EQUITY_DIRECTION = "SHORT" # "LONG" or "SHORT"
OPTIONS_OBSERVE_START = "09:15"   # Session VWAP/EMA hydration & tick collection start (IST)
OPTIONS_WINDOW_START  = "09:30"   # Confluence entry window start (IST)
OPTIONS_WINDOW_END    = "13:30"   # Entry window cutoff (IST)
OPTIONS_EOD_EXIT      = "15:15"   # MIS square-off time (IST)

EQUITY_OBSERVE_START = "10:15"   # Freeze Box start (IST)
EQUITY_WINDOW_START  = "11:00"   # Freeze Box end & Entry window start (IST)
EQUITY_WINDOW_END    = "13:30"   # Entry window cutoff (IST)
EQUITY_EOD_EXIT      = "15:10"   # MIS square-off time (IST)
EQUITY_HARD_EXIT = "13:30"

# --- DAILY RISK & CONFLUENCE PARAMETERS ---
MAX_TRADES_PER_DAY = 3
MAX_SL_PCT = 0.25                 # Max structural SL cap = 25% of entry premium
MAX_EMA_EXTENSION_PCT = 0.08      # Block entries >8% above 9 EMA (wait for pullback)
VOLUME_SURGE_MULT = 1.3           # Require 3m candle volume >= 1.3x 20-period Volume SMA
OPTIONS_DAILY_MAX_LOSS = -1200.0  # Accommodates 1 full 25% structural SL on 1 lot
MAX_DAILY_LOSS = OPTIONS_DAILY_MAX_LOSS
ESTIMATED_CHARGES_PER_TRADE = 55.0

# --- V3.4 CAPITAL-NORMALIZED POSITION SIZING ---
# Standard Non-Expiry Days: ₹4,000 - ₹5,500 per lot (SENSEX: ₹200-₹275 | NIFTY: ₹61.55-₹84.60)
# Expiry Days (0-DTE): ₹1,500 - ₹2,500 per lot if trading 0-DTE, or switch to Next-Week Expiry
IS_EXPIRY_DAY = os.getenv("IS_EXPIRY_DAY", "FALSE").upper() == "TRUE"
if IS_EXPIRY_DAY:
  MIN_CAPITAL_PER_LOT = 1500.0
  MAX_CAPITAL_PER_LOT = 2500.0
else:
  MIN_CAPITAL_PER_LOT = 4000.0
  MAX_CAPITAL_PER_LOT = 5500.0

# --- NSE CASH EQUITY INTRADAY MOMENTUM ENGINE (V1.0) ---
EQUITY_EXCHANGE = os.getenv("EQUITY_EXCHANGE", "NSE")
SENSEX_30_SYMBOLS = [
    "HDFCBANK", "ICICIBANK", "RELIANCE", "BHARTIARTL", "LT",
    "SBIN", "INFY", "AXISBANK", "KOTAKBANK", "BAJFINANCE",
    "M&M", "ITC", "ETERNAL", "TCS", "SUNPHARMA",
    "TITAN", "HINDUNILVR", "TATASTEEL", "MARUTI", "NTPC",
    "ADANIPORTS", "BEL", "HCLTECH", "ULTRACEMCO", "POWERGRID",
    "INDIGO", "ASIANPAINT", "BAJAJFINSV", "TECHM", "TRENT",
]

EQUITY_MAX_RISK_PER_TRADE = float(os.getenv("EQUITY_MAX_RISK_PER_TRADE", "400.0"))
EQUITY_MAX_NOTIONAL = float(os.getenv("EQUITY_MAX_NOTIONAL", "25000.0"))
EQUITY_MAX_TRADES_PER_DAY = int(os.getenv("EQUITY_MAX_TRADES_PER_DAY", "2"))
EQUITY_MAX_DAILY_LOSS = float(os.getenv("EQUITY_MAX_DAILY_LOSS", "-800.0"))
EQUITY_ESTIMATED_CHARGES = float(os.getenv("EQUITY_ESTIMATED_CHARGES", "35.0"))
MARKET_TREND_THRESHOLD_PCT = float(os.getenv("MARKET_TREND_THRESHOLD_PCT", "0.30"))
STOCK_MIN_MOVE_PCT = float(os.getenv("STOCK_MIN_MOVE_PCT", "0.80"))

# --- DAILY TARGETS AUTO-LOADER (populated by morning_launch.py) ---
DAILY_TARGETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_targets.json")
DAILY_TARGETS_LOADED = False
DAILY_OPTIONS_LOADED = False
DAILY_EQUITY_LOADED = False


def load_daily_targets(path=DAILY_TARGETS_PATH):
  """Overrides daily strikes/watchlist/regime from daily_targets.json if dated for today."""
  global UNDERLYING, EXCHANGE, QTY, CANDIDATE_STRIKES, SYMBOL, EQUITY_WATCHLIST, EQUITY_DIRECTION
  global DAILY_TARGETS_LOADED, DAILY_OPTIONS_LOADED, DAILY_EQUITY_LOADED
  DAILY_TARGETS_LOADED = False
  DAILY_OPTIONS_LOADED = False
  DAILY_EQUITY_LOADED = False
  if not os.path.isfile(path):
    return False
  try:
    with open(path, "r", encoding="utf-8") as f:
      data = json.load(f)
    if not isinstance(data, dict):
      return False
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    if data.get("date") != today_str:
      return False

    opts = data.get("options") or {}
    strikes = opts.get("candidate_strikes")
    if isinstance(strikes, list) and strikes:
      CANDIDATE_STRIKES = [str(s).strip() for s in strikes if str(s).strip()]
      if CANDIDATE_STRIKES:
        SYMBOL = CANDIDATE_STRIKES[0]
        DAILY_OPTIONS_LOADED = True
    if DAILY_OPTIONS_LOADED:
      underlying_val = opts.get("underlying") or opts.get("index")
      if underlying_val:
        UNDERLYING = str(underlying_val).strip().upper()
      if opts.get("exchange"):
        EXCHANGE = str(opts["exchange"]).strip().upper()
      elif UNDERLYING == "SENSEX":
        EXCHANGE = "BFO"
      elif UNDERLYING == "NIFTY":
        EXCHANGE = "NFO"
      if not underlying_val:
        UNDERLYING = "SENSEX" if EXCHANGE == "BFO" else "NIFTY"
      if opts.get("qty") and int(opts["qty"]) > 0:
        QTY = int(opts["qty"])
      elif EXCHANGE == "BFO" or UNDERLYING == "SENSEX":
        QTY = 20
      elif EXCHANGE == "NFO" or UNDERLYING == "NIFTY":
        QTY = 65

    eq = data.get("equity") or {}
    wl = eq.get("watchlist")
    if isinstance(wl, list) and wl:
      EQUITY_WATCHLIST = [str(s).strip().upper() for s in wl if str(s).strip()]
      DAILY_EQUITY_LOADED = True
    eq_dir = str(eq.get("direction", "")).strip().upper()
    if eq_dir in ("LONG", "SHORT"):
      EQUITY_DIRECTION = eq_dir

    DAILY_TARGETS_LOADED = DAILY_OPTIONS_LOADED or DAILY_EQUITY_LOADED
    return DAILY_TARGETS_LOADED
  except Exception:
    return False


load_daily_targets()

