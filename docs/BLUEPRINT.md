### File 2 of 2: `BLUEPRINT.md`

Apne `~/trading-projects/option-trailing-algo` folder mein is content ko `BLUEPRINT.md` ke naam se save karein:

```markdown
# Project Blueprint: Intraday Option Trailing Algo (OpenAlgo + Shoonya)

## 1. Objective & Operating Constraints
* **Core Philosophy:** Hybrid Semi-Automated Execution. Manual market structure analysis determines the high-probability strike (CE/PE), while the Python algo handles disciplined entry confirmation, strict initial stop-loss, 1:1 breakeven protection, and step-based trailing SL.
* **Trading Window:** Strictly restricted to **11:30 AM – 1:30 PM IST** (avoiding 9:15 AM open volatility spikes and protecting afternoon engineering focus).
* **Trade Frequency Cap:** Maximum **2 to 3 single-lot trades per day**.
* **Broker Stack:**
  * **Charting / Manual Analysis:** Sahi Web Scalper / TradingView.
  * **Execution & Live Feed:** OpenAlgo Local Gateway connected to **Shoonya (NorenOMS)** (`₹5/order` flat brokerage + free live tick data).

---

## 2. Phase-Wise Execution Roadmap

### Phase 1: Local Foundation & Core Engine (Completed)
- [x] Set up isolated WSL Ubuntu directories (`~/trading-projects/openalgo` and `~/trading-projects/option-trailing-algo`).
- [x] Build modular codebase (`config.py`, `broker_adapter.py`, `strategy_engine.py`).
- [x] Implement core state machine:
  - Range Observation $\rightarrow$ Buffer Breakout Entry $\rightarrow$ Strict Initial SL $\rightarrow$ 1:1 Cost-to-Cost Breakeven Lock $\rightarrow$ Step Trailing SL $\rightarrow$ CSV Trade Logger with simulated slippage.
- [x] Verify end-to-end execution in `SIMULATION` mode.
- [x] Clone and initialize local OpenAlgo server (`http://127.0.0.1:5000`) and push codebase to GitHub.

### Phase 2: Broker Onboarding & Live Paper Feed (Next Session)
- [ ] Complete **Shoonya (Finvasia)** account activation and enable TOTP 2FA.
- [ ] Generate Shoonya API credentials (`API Key`, `Vendor Code`, `IMEI/Secret`).
- [ ] Update `openalgo/.env` with `BROKER="shoonya"` and Shoonya API credentials; set redirect URL to `http://127.0.0.1:5000/shoonya/callback`.
- [ ] Switch OpenAlgo dashboard to **Analyze Mode (Paper Trading)** and copy the OpenAlgo Local API Key into `config.py`.
- [ ] Set `MODE = "OPENALGO"` in `config.py` and verify live option premium (`LTP`) polling and virtual order execution during the `11:30 AM – 1:30 PM` window.

### Phase 3: Strategy & Resilience Upgrades (Pre-Live Hardening)
- [ ] **API Resilience Wrapper:** Add `try-except` with exponential backoff / 2-retry loop in `broker_adapter.py` (`get_ltp` and `place_order`) to handle transient NorenOMS packet drops without crashing.
- [ ] **Entry Confirmation Upgrade:** Upgrade tick breakout trigger to require a **3-minute candle close above Reference High** (and optionally above session VWAP) to filter out false wicks.
- [ ] **Daily Guardrails (Kill Switch):**
  - Enforce `MAX_TRADES_PER_DAY = 3`.
  - Enforce `MAX_DAILY_LOSS` cap—automatically halt new entries for the day once breached.
- [ ] **Interactive CLI Launcher:** Prompt for `Symbol`, `SL_Points`, and `Trail_Step` at runtime instead of manually editing `config.py` before each trade.

### Phase 4: Forward Testing & Validation (2-Week Discipline Gate)
- [ ] Run **15–20 consecutive paper trades** in OpenAlgo `Analyze Mode` over 2 weeks.
- [ ] Audit `paper_trades_log.csv` against actual Shoonya option fills to measure:
  - Win rate & Expectancy after simulated slippage/charges.
  - Effectiveness of 1:1 breakeven shift vs. premature stop-outs.
  - Trailing step efficiency (capturing trend extensions vs. giving back open profit).
- [ ] Freeze strategy parameters before authorizing real capital.

### Phase 5: Transition to Live Capital Execution
- [ ] **Infrastructure & SEBI Compliance:**
  - Provision a static IP (via ISP or a local Mumbai cloud VPS) and whitelist it on the Shoonya API portal.
  - Upgrade Shoonya API permissions from Market Data/Paper to Live Order Execution.
- [ ] **Broker-Side Hard Stop-Loss:**
  - Immediately upon `BUY` fill, place an actual broker-side `SL` / `SL-M` order via OpenAlgo (`placeorder`).
  - Use `modifyorder()` dynamically whenever the trailing logic updates `current_sl` (protecting against local internet/power loss).
- [ ] **Limit Order Price Protection:** Replace `MARKET` entry/exit orders with `LIMIT` orders (`LTP + buffer`) to prevent adverse fills during sudden option spikes.
- [ ] Toggle OpenAlgo dashboard from `Analyze Mode` to **`Live Mode`** with single-lot position sizing.

---

## 3. Daily Standard Operating Procedure (SOP)

1. **11:10 AM IST — System Boot:**
   - Start OpenAlgo server (`python app.py` inside `~/trading-projects/openalgo`).
   - Log in at `http://127.0.0.1:5000`, authenticate Shoonya session (TOTP), and verify **Analyze Mode** is active.
2. **11:15 AM – 11:30 AM IST — Manual Market Structure Prep:**
   - Analyze index/stock structure on Sahi charts; identify exact ATM/ITM option strike (`SYMBOL`) and risk parameters (`INITIAL_SL_POINTS`, `TRAIL_STEP_POINTS`).
3. **11:30 AM – 1:30 PM IST — Algo Execution Window:**
   - Launch `python strategy_engine.py` for the selected strike.
   - Let the engine manage entry, strict SL, and trailing SL hands-free (max 2–3 trades).
4. **1:30 PM IST — Session Wrap:**
   - Ensure zero open positions remain; review `paper_trades_log.csv` and OpenAlgo Tradebook.

```

---

**Terminal Command to Save & Push `BLUEPRINT.md`:**

```bash
cd ~/trading-projects/option-trailing-algo
# BLUEPRINT.md save karne ke baad:
git add BLUEPRINT.md
git commit -m "docs: add complete project blueprint, roadmap, and daily SOP"
git push

```

Aaj ke sabhi setup, coding, documentation, aur GitHub push tasks complete ho gaye hain. Next session mein Shoonya credentials aur Phase 3 upgrades ke saath continue karenge!