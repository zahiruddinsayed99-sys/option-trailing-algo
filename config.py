import datetime

# Execution Mode: "SIMULATION" (local test) ya "OPENALGO" (live feed + paper/live orders)
MODE = "SIMULATION"

# OpenAlgo Settings (Jab MODE = "OPENALGO" use karein)
OPENALGO_API_KEY = "AAPKI_OPENALGO_API_KEY"
OPENALGO_HOST = "http://127.0.0.1:5000"

# Daily Manual Strike & Risk Parameters
SYMBOL = "SENSEX26NOV80800PE"  # Strike symbol
EXCHANGE = "BFO"  # NFO (Nifty/BankNifty) ya BFO (Sensex)
QTY = 20  # 1 Lot Sensex = 20, Nifty = 75

# Entry & Risk Rules
ENTRY_BUFFER_POINTS = 1.0  # Reference high ke kitne points upar entry leni hai
INITIAL_SL_POINTS = 15.0  # Strict Initial Stop Loss (points)
TRAIL_STEP_POINTS = 8.0  # Breakeven ke baad har 8 point move par SL trail hoga
MOVE_TO_BREAKEVEN_AT_1R = True  # 1:1 profit milte hi SL ko Entry Price par layein

# Time Windows (Aapke disciplined trading window ke hisaab se)
START_TIME = datetime.time(9, 15)
SQUARE_OFF_TIME = datetime.time(15, 15)