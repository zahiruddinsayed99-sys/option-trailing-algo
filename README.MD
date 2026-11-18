### File 1 of 2: `README.md`

Apne `~/trading-projects/option-trailing-algo` folder mein is content ko `README.md` ke naam se save karein:

```markdown
# Option Trailing SL Paper Trading Engine (`option-trailing-algo`)

A modular Python intraday option-buying execution engine designed for **manual market structure selection** paired with **automated entry triggers, strict initial stop-loss, 1:1 breakeven lock, and step-based trailing stop-loss**.

Built with a decoupled broker adapter supporting both a **local tick simulator (`SIMULATION`)** and **OpenAlgo (`OPENALGO`)** for zero-cost paper trading (`Analyze Mode`) and future live execution via **Shoonya (NorenOMS)**.

---

## Architecture Overview

```text
+-----------------------+       +-------------------------+       +------------------------+
|   Manual Analysis     | ----> |   Strategy Engine       | ----> |   Broker Adapter       |
| (Market Structure &   |       | (Observation, Entry,    |       | - SIMULATION (Local)   |
|  Strike Selection)    |       |  1:1 BE & Trail SL)     |       | - OPENALGO (Shoonya)   |
+-----------------------+       +-------------------------+       +------------------------+
                                             |
                                             v
                                +-------------------------+
                                |  paper_trades_log.csv   |
                                | (Gross/Net P&L + Slip.) |
                                +-------------------------+

```

### Project Files

* `config.py` — Daily manual strike input, quantity, initial SL points, trailing step size, and trading session window (`11:30 AM – 1:30 PM IST`).
* `broker_adapter.py` — Abstraction layer isolating the strategy state machine from broker APIs (`SIMULATION` tick generator vs. `OPENALGO` live quotes & order execution).
* `strategy_engine.py` — Core state machine handling range observation, breakout entry, 1:1 cost-to-cost breakeven shift, step trailing SL, EOD square-off, and CSV trade logging.

---

## Local Setup (WSL Ubuntu / Linux)

### 1. Clone & Activate Virtual Environment

```bash
git clone [https://github.com/zahiruddinsayed99-sys/option-trailing-algo.git](https://github.com/zahiruddinsayed99-sys/option-trailing-algo.git)
cd option-trailing-algo

python3 -m venv venv
source venv/bin/activate
pip install openalgo pandas python-dotenv

```

### 2. Configure Daily Parameters (`config.py`)

Update the strike and risk parameters before running:

```python
MODE = "SIMULATION"  # Switch to "OPENALGO" for live feed / Analyze Mode
SYMBOL = "SENSEX26NOV80800PE"
EXCHANGE = "BFO"
QTY = 20
INITIAL_SL_POINTS = 15.0
TRAIL_STEP_POINTS = 8.0

```

### 3. Run the Engine

```bash
python strategy_engine.py

```

All completed paper trades are automatically appended to `paper_trades_log.csv` with estimated slippage and charges deducted.

---

## Roadmap

* [x] Core state machine with 1:1 breakeven & step trailing SL (`SIMULATION` mode)
* [x] Local OpenAlgo server setup (`Analyze Mode` ready)
* [ ] Shoonya (NorenOMS) API integration & auto-retry resilience wrapper
* [ ] Candle-close / VWAP pullback entry filter upgrade
* [ ] Daily max-trade (2–3 trades/day) & max-loss kill switch
* [ ] Live mode transition with broker-side hard SL order modification

```

---

**Terminal Command to Save & Push `README.md`:**
```bash
cd ~/trading-projects/option-trailing-algo
# README.md save karne ke baad:
git add README.md
git commit -m "docs: add project README with architecture and setup instructions"
git push
