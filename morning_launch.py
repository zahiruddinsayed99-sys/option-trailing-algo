import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time

import broker_adapter
import config
from equity_screener import select_trending_sensex_stocks
from strike_screener import screen_strikes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_TARGETS_PATH = os.path.join(BASE_DIR, "daily_targets.json")
TMUX_SESSION = "algo_sess0"


def _python_cmd(script_name: str) -> str:
  venv_activate = os.path.join(BASE_DIR, "venv", "bin", "activate")
  if os.path.isfile(venv_activate):
    return f"source venv/bin/activate && python3 {script_name} --auto"
  return f"python3 {script_name} --auto"


def _run_tmux(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
  return subprocess.run(["tmux", *args], cwd=BASE_DIR, check=check, capture_output=True, text=True)


def save_daily_targets(options_res: dict, equity_res: dict, path: str = DAILY_TARGETS_PATH) -> dict:
  """Persists today's screener selections to daily_targets.json for config.py auto-loading."""
  now = datetime.datetime.now()
  opts_dict = options_res or {}
  strikes = opts_dict.get("candidate_strikes") or list(config.CANDIDATE_STRIKES)
  underlying = opts_dict.get("underlying") or opts_dict.get("index") or getattr(config, "UNDERLYING", "SENSEX")
  exchange = opts_dict.get("exchange") or config.EXCHANGE
  qty = opts_dict.get("qty") or opts_dict.get("lotsize") or int(config.QTY)

  payload = {
      "date": now.strftime("%Y-%m-%d"),
      "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
      "options": {
          "underlying": underlying,
          "index": underlying,
          "direction": opts_dict.get("direction", "PE"),
          "exchange": exchange,
          "qty": int(qty),
          "expiry": opts_dict.get("expiry"),
          "dte": opts_dict.get("dte"),
          "spot": opts_dict.get("spot"),
          "candidate_strikes": strikes,
      },
      "equity": {
          "regime": equity_res.get("regime", "SIDEWAYS"),
          "direction": equity_res.get("direction", "NONE"),
          "avg_move_pct": float(equity_res.get("avg_move_pct", 0.0)),
          "watchlist": equity_res.get("watchlist", []),
      },
  }
  with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
  print(f"[SAVED] Daily targets written to {path}")
  return payload


def launch_tmux_engines(launch_equity: bool, attach: bool = False):
  """Creates tmux session algo_sess0 with options (win 0) and conditional equity (win 1)."""
  if not shutil.which("tmux"):
    print("[ERROR] tmux binary not found in PATH; skipping tmux launch.")
    return False

  _run_tmux(["kill-session", "-t", TMUX_SESSION], check=False)

  opt_cmd = _python_cmd("v3_momentum_engine.py")
  _run_tmux(["new-session", "-d", "-s", TMUX_SESSION, "-n", "options", "-c", BASE_DIR, opt_cmd])
  print(f"[TMUX] Started {TMUX_SESSION}:0 (options) -> {opt_cmd}")

  if launch_equity:
    eq_cmd = _python_cmd("equity_intraday_engine.py")
    _run_tmux(["new-window", "-t", f"{TMUX_SESSION}:1", "-n", "equity", "-c", BASE_DIR, eq_cmd])
    print(f"[TMUX] Started {TMUX_SESSION}:1 (equity)  -> {eq_cmd}")
  else:
    print(f"[TMUX] Skipped {TMUX_SESSION}:1 (equity) — Sensex-30 breadth within ±{getattr(config, 'MARKET_TREND_THRESHOLD_PCT', 0.30):.2f}%.")

  _run_tmux(["select-window", "-t", f"{TMUX_SESSION}:0"], check=False)

  if attach and sys.stdout.isatty():
    os.execvp("tmux", ["tmux", "attach", "-t", TMUX_SESSION])
  return True


def main():
  parser = argparse.ArgumentParser(description="Hands-free Morning Screener & Tmux Launcher")
  parser.add_argument(
      "--index",
      default="AUTO",
      choices=["AUTO", "SENSEX", "NIFTY"],
      help="Options index (default: AUTO dynamic rotation by MIN_DTE)",
  )
  parser.add_argument("--direction", default=None, choices=["CE", "PE"], help="Options CE/PE (defaults to regime-aligned)")
  parser.add_argument("--spot", type=float, default=None, help="Optional manual spot override")
  parser.add_argument("--dry-run", action="store_true", help="Run screeners and save daily_targets.json without launching tmux")
  parser.add_argument("--attach", action="store_true", help="Attach to tmux session algo_sess0 after launch")
  args = parser.parse_args()

  print("\n=== MORNING LAUNCH AUTOMATION ===")
  broker = broker_adapter.BrokerAdapter()
  try:
    equity_res = select_trending_sensex_stocks(broker, return_details=True)
    time.sleep(1.5)
    opt_dir = args.direction
    if not opt_dir:
      if equity_res.get("regime") == "BULLISH":
        opt_dir = "CE"
      elif equity_res.get("regime") == "BEARISH":
        opt_dir = "PE"
      else:
        opt_dir = "CE" if equity_res.get("avg_move_pct", 0.0) >= 0 else "PE"

    options_res = screen_strikes(
        index_name=args.index,
        opt_type=opt_dir,
        spot=args.spot,
        auto=True,
        broker=broker,
    )
  finally:
    broker.shutdown()

  valid_equity_quotes = int((equity_res or {}).get("valid_quotes", 0) or 0)
  live_quotes_ok = bool((options_res or {}).get("live_quotes_ok", False))
  if config.MODE.upper() != "SIMULATION" and valid_equity_quotes == 0 and not live_quotes_ok:
    print("[ABORT] OpenAlgo broker session not returning live quotes. Log in at http://127.0.0.1:5000 and retry.")
    sys.exit(1)

  if not options_res or not options_res.get("candidate_strikes"):
    print("[WARNING] Strike screener returned no sweet-spot strikes; falling back to config.CANDIDATE_STRIKES.")

  payload = save_daily_targets(options_res, equity_res)

  threshold = getattr(config, "MARKET_TREND_THRESHOLD_PCT", 0.30)
  avg_move = abs(payload["equity"]["avg_move_pct"])
  launch_equity = (
      avg_move > threshold
      and payload["equity"]["regime"] in ("BULLISH", "BEARISH")
      and bool(payload["equity"]["watchlist"])
  )

  if args.dry_run:
    print(f"[DRY RUN] Would launch {TMUX_SESSION}: options=True, equity={launch_equity} (|breadth|={avg_move:.2f}%).")
    return

  launch_tmux_engines(launch_equity=launch_equity, attach=args.attach)


if __name__ == "__main__":
  main()
