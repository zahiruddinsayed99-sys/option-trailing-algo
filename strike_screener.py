import argparse
import datetime
import json
import os
import sqlite3
import time
import urllib.request
import broker_adapter
import config

OPENALGO_DB_PATH = os.path.expanduser("~/trading-projects/openalgo/db/openalgo.db")


def _parse_expiry_date(expiry_str: str):
    """Parses OpenAlgo symtoken expiry formats like '26-NOV-26' or '2026-11-26'."""
    if not expiry_str:
        return None
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d", "%d%b%y"):
        try:
            return datetime.datetime.strptime(expiry_str.strip().upper(), fmt).date()
        except ValueError:
            continue
    return None


def _open_symtoken_ro(db_path: str):
    """Opens OpenAlgo SQLite DB in read-only mode, with immutable fallback for WSL/9p locks."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM symtoken LIMIT 1").fetchone()
        return conn
    except sqlite3.OperationalError:
        return sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)


def _query_index_expiries(conn, index_name: str, exchange: str, today: datetime.date):
    """Returns sorted list of (expiry_date, expiry_str, lot_size) for upcoming expiries."""
    rows = conn.execute(
        """
        SELECT DISTINCT expiry, lotsize
        FROM symtoken
        WHERE exchange = ? AND name = ? AND instrumenttype IN ('CE', 'PE')
        """,
        (exchange, index_name),
    ).fetchall()
    parsed = {}
    for exp_str, lotsize in rows:
        exp_dt = _parse_expiry_date(exp_str)
        if exp_dt is not None and exp_dt >= today:
            lot = int(lotsize or 0)
            if exp_dt not in parsed or lot > 0:
                parsed[exp_dt] = (exp_str, lot)
    return [(dt, parsed[dt][0], parsed[dt][1]) for dt in sorted(parsed)]


def resolve_active_index(db_path: str = OPENALGO_DB_PATH, min_dte: int = 2, today: datetime.date = None) -> dict:
    """Selects SENSEX (BFO) if nearest expiry DTE >= min_dte, else rotates to NIFTY (NFO)."""
    ref_today = today or datetime.date.today()
    min_dte = int(min_dte)

    def _fallback(underlying: str, sensex_dte=None, sensex_exp=None, rotated: bool = False):
        is_sensex = underlying == "SENSEX"
        return {
            "underlying": underlying,
            "exchange": "BFO" if is_sensex else "NFO",
            "spot_symbol": underlying,
            "spot_exchange": "BSE_INDEX" if is_sensex else "NSE_INDEX",
            "lot_size": 20 if is_sensex else 65,
            "expiry": None,
            "expiry_date": None,
            "dte": None,
            "sensex_dte": sensex_dte,
            "sensex_expiry": sensex_exp,
            "rotated": rotated,
            "min_dte": min_dte,
        }

    if not db_path or not os.path.isfile(db_path):
        print(f"[WARNING] OpenAlgo DB not found at {db_path}; defaulting to SENSEX (BFO).")
        return _fallback("SENSEX")

    conn = _open_symtoken_ro(db_path)
    try:
        sensex_expiries = _query_index_expiries(conn, "SENSEX", "BFO", ref_today)
        nifty_expiries = _query_index_expiries(conn, "NIFTY", "NFO", ref_today)
    finally:
        conn.close()

    sensex_dte = None
    sensex_exp_str = None
    if sensex_expiries:
        s_dt, sensex_exp_str, s_lot = sensex_expiries[0]
        sensex_dte = (s_dt - ref_today).days
        if sensex_dte >= min_dte:
            return {
                "underlying": "SENSEX",
                "exchange": "BFO",
                "spot_symbol": "SENSEX",
                "spot_exchange": "BSE_INDEX",
                "lot_size": s_lot if s_lot > 0 else 20,
                "expiry": sensex_exp_str,
                "expiry_date": s_dt,
                "dte": sensex_dte,
                "sensex_dte": sensex_dte,
                "sensex_expiry": sensex_exp_str,
                "rotated": False,
                "min_dte": min_dte,
            }

    eligible_nifty = [e for e in nifty_expiries if (e[0] - ref_today).days >= min_dte]
    chosen_nifty = eligible_nifty[0] if eligible_nifty else (nifty_expiries[-1] if nifty_expiries else None)
    if chosen_nifty:
        n_dt, n_exp_str, n_lot = chosen_nifty
        n_dte = (n_dt - ref_today).days
        return {
            "underlying": "NIFTY",
            "exchange": "NFO",
            "spot_symbol": "NIFTY",
            "spot_exchange": "NSE_INDEX",
            "lot_size": n_lot if n_lot > 0 else 65,
            "expiry": n_exp_str,
            "expiry_date": n_dt,
            "dte": n_dte,
            "sensex_dte": sensex_dte,
            "sensex_expiry": sensex_exp_str,
            "rotated": True,
            "min_dte": min_dte,
        }

    if sensex_expiries:
        s_dt, sensex_exp_str, s_lot = sensex_expiries[0]
        return {
            "underlying": "SENSEX",
            "exchange": "BFO",
            "spot_symbol": "SENSEX",
            "spot_exchange": "BSE_INDEX",
            "lot_size": s_lot if s_lot > 0 else 20,
            "expiry": sensex_exp_str,
            "expiry_date": s_dt,
            "dte": sensex_dte,
            "sensex_dte": sensex_dte,
            "sensex_expiry": sensex_exp_str,
            "rotated": False,
            "min_dte": min_dte,
        }

    return _fallback("NIFTY", sensex_dte=sensex_dte, sensex_exp=sensex_exp_str, rotated=True)


def _get_expiry_strikes(
    index_name: str,
    opt_type: str,
    spot: float,
    auto: bool = False,
    target_expiry_date: datetime.date = None,
):
    """Queries local OpenAlgo SQLite symtoken table with 0-DTE expiry guardrail."""
    exchange = "BFO" if index_name == "SENSEX" else "NFO"
    if not os.path.isfile(OPENALGO_DB_PATH):
        print(f"[ERROR] OpenAlgo SQLite master database not found at {OPENALGO_DB_PATH}")
        return exchange, None, 0, []

    now = datetime.datetime.now()
    today = now.date()
    min_valid_date = today + datetime.timedelta(days=1) if now.time() >= datetime.time(15, 30) else today

    # Read-only URI mode prevents SQLite lock contention with live OpenAlgo server
    conn = _open_symtoken_ro(OPENALGO_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT symbol, strike, expiry, lotsize
            FROM symtoken
            WHERE exchange = ? AND name = ? AND instrumenttype = ? AND symbol LIKE ?
            """,
            (exchange, index_name, opt_type, f"{index_name}%{opt_type}"),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return exchange, None, 0, []

    valid_rows = []
    for sym, strike, exp_str, lotsize in rows:
        exp_dt = _parse_expiry_date(exp_str)
        if exp_dt is not None and exp_dt >= min_valid_date and strike is not None:
            valid_rows.append((exp_dt, exp_str, float(strike), sym, int(lotsize or 1)))

    if not valid_rows:
        return exchange, None, 0, []

    distinct_expiries = sorted(set(r[0] for r in valid_rows))
    if target_expiry_date is not None and target_expiry_date in distinct_expiries:
        selected_exp = target_expiry_date
    else:
        selected_exp = distinct_expiries[0]

    # 0-DTE Expiry-Day Gamma/Theta Guardrail
    if selected_exp == today:
        min_cap = getattr(config, "MIN_CAPITAL_PER_LOT", 4000.0)
        max_cap = getattr(config, "MAX_CAPITAL_PER_LOT", 5500.0)
        is_expiry_day = getattr(config, "IS_EXPIRY_DAY", False)
        print(f"\n[0-DTE EXPIRY WARNING] Nearest expiry ({selected_exp}) is TODAY!")
        if is_expiry_day:
            print(f"  IS_EXPIRY_DAY=TRUE is active (Band: ₹{min_cap:,.0f}-₹{max_cap:,.0f}/lot); watch for 0-DTE spreads & gamma.")
        else:
            print(
                f"  On 0-DTE, ₹{min_cap/1000:.1f}K-₹{max_cap/1000:.1f}K/lot forces Deep ITM/ATM strikes "
                "with wide spreads & extreme gamma."
            )
        if len(distinct_expiries) > 1:
            next_exp = distinct_expiries[1]
            if auto:
                if not is_expiry_day:
                    selected_exp = next_exp
                    print(f"  [AUTO] Switching to Next-Week Expiry ({next_exp}).")
            else:
                choice = input(f"  Switch to Next-Week Expiry ({next_exp})? [Y/n]: ").strip().lower()
                if choice != "n":
                    selected_exp = next_exp
        else:
            print("  [NOTE] No further expiry contracts found in DB; proceeding with today's 0-DTE expiry.")

    expiry_rows = [r for r in valid_rows if r[0] == selected_exp]
    selected_exp_str = expiry_rows[0][1]
    lotsize = expiry_rows[0][4]

    # Start near ATM/1-strike OTM and scan 12 strikes outward in one single batch
    otm_offset = 100 if index_name == "SENSEX" else 50
    if opt_type == "CE":
        filtered = [r for r in expiry_rows if r[2] >= (spot + otm_offset)]
        filtered.sort(key=lambda x: x[2])
    else:
        filtered = [r for r in expiry_rows if r[2] <= (spot - otm_offset)]
        filtered.sort(key=lambda x: x[2], reverse=True)

    candidates = [(r[3], r[2], r[1], r[4]) for r in filtered[:12]]
    return exchange, selected_exp_str, lotsize, candidates


def _fetch_multiquotes_direct(candidates, exchange):
    """Calls OpenAlgo /api/v1/multiquotes via stdlib urllib with a 6-second timeout."""
    host = getattr(config, "OPENALGO_HOST", "http://127.0.0.1:5000").rstrip("/")
    api_key = getattr(config, "OPENALGO_API_KEY", "")
    url = f"{host}/api/v1/multiquotes"
    body = json.dumps({
        "apikey": api_key,
        "symbols": [{"symbol": r[0], "exchange": exchange} for r in candidates],
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    mq_map = {}
    if isinstance(data, dict):
        for item in data.get("results", []):
            if isinstance(item, dict) and item.get("symbol") and isinstance(item.get("data"), dict):
                mq_map[item["symbol"]] = item["data"]
    return mq_map


def _fetch_spot_price(
    index_name: str,
    broker=None,
    spot_symbol: str = None,
    spot_exchange: str = None,
) -> float:
    """Fetches live spot price for SENSEX or NIFTY via OpenAlgo index exchanges."""
    sym = spot_symbol or index_name
    primary_exch = spot_exchange or ("BSE_INDEX" if index_name == "SENSEX" else "NSE_INDEX")
    fallback_exch = "BSE" if index_name == "SENSEX" else "NSE"
    own_broker = False
    if broker is None:
        broker = broker_adapter.BrokerAdapter()
        own_broker = True
    try:
        for exch in (primary_exch, fallback_exch):
            q = broker.get_quote(sym, exch, advance_sim=False)
            if q and float(q.get("ltp", 0) or 0) > 0:
                return float(q["ltp"])
    except Exception:
        pass
    finally:
        if own_broker:
            broker.shutdown()
    fallback_spot = 84350.0 if index_name == "SENSEX" else 26100.0
    print(f"[SPOT WARNING] Live {sym} spot unavailable; falling back to {fallback_spot:.2f}.")
    return fallback_spot


def _build_screener_result(
    underlying: str,
    opt_type: str,
    exchange: str,
    spot_symbol: str,
    spot_exchange: str,
    expiry_str,
    dte,
    lotsize: int,
    spot: float,
    candidate_strikes: list,
    live_quotes_ok: bool,
) -> dict:
    return {
        "index": underlying,
        "underlying": underlying,
        "direction": opt_type,
        "exchange": exchange,
        "spot_symbol": spot_symbol,
        "spot_exchange": spot_exchange,
        "expiry": expiry_str,
        "dte": dte,
        "lotsize": lotsize,
        "qty": lotsize,
        "spot": spot,
        "candidate_strikes": candidate_strikes,
        "live_quotes_ok": live_quotes_ok,
    }


def screen_strikes(index_name: str = None, opt_type: str = "PE", spot: float = None, auto: bool = False, broker=None):
    """Screens up to 4 OTM strikes in the target capital band and returns structured result dict."""
    opt_in = opt_type.strip().upper()
    if opt_in not in ("CE", "PE"):
        print(f"[ERROR] Unsupported direction '{opt_in}'. Use CE or PE.")
        return None

    min_dte = int(getattr(config, "MIN_DTE", 2))
    auto_rotation = getattr(config, "AUTO_INDEX_ROTATION", True)
    raw_idx = index_name.strip().upper() if isinstance(index_name, str) and index_name.strip() else "AUTO"

    resolved = None
    if raw_idx == "AUTO":
        if auto_rotation:
            resolved = resolve_active_index(OPENALGO_DB_PATH, min_dte=min_dte)
            idx_in = resolved["underlying"]
            spot_symbol = resolved["spot_symbol"]
            spot_exchange = resolved["spot_exchange"]
            s_dte_disp = str(resolved["sensex_dte"]) if resolved["sensex_dte"] is not None else "N/A"
            if resolved["rotated"]:
                print(
                    f"[INDEX ROTATION] SENSEX DTE={s_dte_disp} (< {min_dte}) -> "
                    f"Switched to {idx_in} ({resolved['exchange']} | Expiry: {resolved['expiry']} | "
                    f"{resolved['dte']} DTE | Lot: {resolved['lot_size']})"
                )
            else:
                print(
                    f"[INDEX ROTATION] SENSEX DTE={s_dte_disp} (>= {min_dte}) -> "
                    f"Active: {idx_in} ({resolved['exchange']} | Expiry: {resolved['expiry']} | "
                    f"{resolved['dte']} DTE | Lot: {resolved['lot_size']})"
                )
        else:
            idx_in = getattr(config, "PRIMARY_INDEX", "SENSEX")
            spot_symbol = idx_in
            spot_exchange = "BSE_INDEX" if idx_in == "SENSEX" else "NSE_INDEX"
            print(f"[INDEX SELECTION] AUTO_INDEX_ROTATION=False -> Active: {idx_in}")
    elif raw_idx in ("SENSEX", "NIFTY"):
        idx_in = raw_idx
        spot_symbol = idx_in
        spot_exchange = "BSE_INDEX" if idx_in == "SENSEX" else "NSE_INDEX"
        exch_disp = "BFO" if idx_in == "SENSEX" else "NFO"
        print(f"[INDEX SELECTION] Manual index={idx_in} ({exch_disp})")
    else:
        print(f"[ERROR] Unsupported index '{raw_idx}'. Use AUTO, SENSEX, or NIFTY.")
        return None

    if spot is None or spot <= 0:
        spot = _fetch_spot_price(idx_in, broker=broker, spot_symbol=spot_symbol, spot_exchange=spot_exchange)
        print(f"[SPOT AUTO-FETCH] {idx_in} Spot: {spot:.2f}")

    t0 = time.perf_counter()
    target_exp_dt = resolved["expiry_date"] if resolved else None
    exchange, expiry_str, lotsize, candidates = _get_expiry_strikes(
        idx_in,
        opt_in,
        spot,
        auto=auto,
        target_expiry_date=target_exp_dt,
    )
    db_elapsed = time.perf_counter() - t0

    if lotsize <= 0:
        lotsize = resolved["lot_size"] if resolved else (20 if idx_in == "SENSEX" else 65)
    exp_dt = _parse_expiry_date(expiry_str)
    dte = (exp_dt - datetime.date.today()).days if exp_dt else (resolved["dte"] if resolved else None)

    if not candidates:
        print(f"[ERROR] No active {idx_in} {opt_in} contracts found in {OPENALGO_DB_PATH}.")
        return _build_screener_result(
            idx_in, opt_in, exchange, spot_symbol, spot_exchange, expiry_str, dte, lotsize, spot, [], False
        )

    min_cap = getattr(config, "MIN_CAPITAL_PER_LOT", 4000.0)
    max_cap = getattr(config, "MAX_CAPITAL_PER_LOT", 5500.0)
    min_prem = min_cap / lotsize
    max_prem = max_cap / lotsize

    print(
        f"\n[DB LOOKUP: {db_elapsed:.3f}s] {idx_in} ({exchange}) | Expiry: {expiry_str} ({dte} DTE) | Lot: {lotsize} | "
        f"Band (₹{min_cap:.0f}-₹{max_cap:.0f}/lot): ₹{min_prem:.2f}-₹{max_prem:.2f} | "
        f"Checking {len(candidates)} OTM strikes...\n"
    )

    if getattr(config, "MODE", "OPENALGO").upper() == "SIMULATION":
        mid_prem = round((min_prem + max_prem) / 2.0, 2)
        mq_map = {}
        for i, (sym, _, _, _) in enumerate(candidates):
            sim_ltp = max(10.0, round(mid_prem + (2 - i) * (mid_prem * 0.10), 2))
            mq_map[sym] = {
                "ltp": sim_ltp,
                "bid": round(sim_ltp - 0.15, 2),
                "ask": round(sim_ltp + 0.15, 2),
            }
    else:
        try:
            mq_map = _fetch_multiquotes_direct(candidates, exchange)
        except Exception as e:
            print(f"[ERROR] OpenAlgo multiquotes failed or timed out: {e}")
            print("[TIP] Verify OpenAlgo server is running at http://127.0.0.1:5000 and logged in.")
            return _build_screener_result(
                idx_in, opt_in, exchange, spot_symbol, spot_exchange, expiry_str, dte, lotsize, spot, [], False
            )

    if not mq_map:
        print(f"[ERROR] OpenAlgo returned empty quotes for {exchange}. Restart OpenAlgo to refresh {exchange} master contracts.")
        return _build_screener_result(
            idx_in, opt_in, exchange, spot_symbol, spot_exchange, expiry_str, dte, lotsize, spot, [], False
        )

    sweet_spots = []
    all_valid = []
    valid_quote_count = 0

    print(f"{'SYMBOL':<24} | {'STRIKE':<8} | {'LTP':<8} | {'CAPITAL/LOT':<11} | {'SPREAD':<7} | STATUS")
    print("-" * 82)

    for sym, strike, expiry, lot in candidates:
        d = mq_map.get(sym)
        if not d:
            continue

        ltp = float(d.get("ltp", 0) or 0)
        bid = float(d.get("bid", 0) or 0)
        ask = float(d.get("ask", 0) or 0)
        if ltp <= 0:
            continue
        valid_quote_count += 1

        valid_depth = bid > 0 and ask > 0 and ask >= bid
        spread = round(ask - bid, 2) if valid_depth else 999.0
        cap_per_lot = ltp * lot
        eff_max_spread = round(ltp * 0.005, 2)

        if not valid_depth:
            status = "NO DEPTH"
        elif cap_per_lot > max_cap:
            status = f"EXPENSIVE (>₹{max_cap/1000:.1f}K)"
        elif cap_per_lot < min_cap:
            status = f"DEEP OTM (<₹{min_cap/1000:.1f}K)"
        elif spread > eff_max_spread:
            status = f"WIDE SPREAD (>₹{eff_max_spread:.2f})"
        else:
            status = "SWEET SPOT"
            sweet_spots.append(sym)

        if valid_depth and spread <= eff_max_spread:
            all_valid.append((sym, strike, cap_per_lot))

        spread_disp = f"₹{spread:<6.2f}" if valid_depth else "N/A    "
        print(
            f"{sym:<24} | {int(strike):<8} | ₹{ltp:<7.2f} | ₹{cap_per_lot:<10.0f} | "
            f"{spread_disp} | {status}"
        )

    ladder = []
    print("\n" + "=" * 82)
    if sweet_spots:
        idx_first = next((i for i, x in enumerate(all_valid) if x[0] == sweet_spots[0]), 0)
        ladder = [x[0] for x in all_valid[idx_first : idx_first + 4]]
        print("RECOMMENDED CANDIDATE_STRIKES FOR config.py (WITH AUTO-ROTATION LADDER):")
        print(f"CANDIDATE_STRIKES = {ladder}")
    else:
        print(
            f"[NOTE] No strikes fell inside ₹{min_prem:.2f}–₹{max_prem:.2f} "
            f"(₹{min_cap:.0f}-₹{max_cap:.0f}/lot) with valid depth."
        )
    print("=" * 82 + "\n")

    return _build_screener_result(
        idx_in,
        opt_in,
        exchange,
        spot_symbol,
        spot_exchange,
        expiry_str,
        dte,
        lotsize,
        spot,
        ladder,
        valid_quote_count > 0,
    )


def run_strike_screener():
    parser = argparse.ArgumentParser(description="Pre-Market Option Strike Screener")
    parser.add_argument("--auto", action="store_true", help="Run non-interactively using defaults/CLI args")
    parser.add_argument("--index", default="AUTO", choices=["AUTO", "SENSEX", "NIFTY"])
    parser.add_argument("--direction", default="PE", choices=["CE", "PE"])
    parser.add_argument("--spot", type=float, default=None)
    args, _ = parser.parse_known_args()

    is_auto = args.auto or getattr(config, "AUTO_START", False)
    print("\n=== V4.0 INSTANT PRE-MARKET STRIKE SCREENER ===")

    if is_auto:
        return screen_strikes(
            index_name=args.index,
            opt_type=args.direction,
            spot=args.spot,
            auto=True,
        )

    idx_in = input("Index [AUTO / SENSEX / NIFTY] (default AUTO): ").strip().upper() or "AUTO"
    opt_in = input("Direction [CE / PE] (default PE): ").strip().upper() or "PE"
    if idx_in == "AUTO" and getattr(config, "AUTO_INDEX_ROTATION", True):
        resolved_preview = resolve_active_index(OPENALGO_DB_PATH, min_dte=int(getattr(config, "MIN_DTE", 2)))
        preview_idx = resolved_preview["underlying"]
    else:
        preview_idx = getattr(config, "PRIMARY_INDEX", "SENSEX") if idx_in == "AUTO" else idx_in
    default_spot = "84350" if preview_idx == "SENSEX" else "26100"
    spot_str = input(f"Current {preview_idx} Spot Level (Enter for live, or e.g., {default_spot}): ").strip()
    spot = None
    if spot_str:
        try:
            spot = float(spot_str)
        except ValueError:
            print("[ERROR] Invalid spot level.")
            return None

    return screen_strikes(index_name=idx_in, opt_type=opt_in, spot=spot, auto=False)


if __name__ == "__main__":
    run_strike_screener()
