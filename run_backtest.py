"""
Entry point: runs the provided strategy (ATM straddle buyer, NIFTY +
BANKNIFTY) across a date range and writes backtest results - CSVs and
plots to an output directory.

Usage:
    python3 run_backtest.py                          
    python3 run_backtest.py --root /path/to/allData
    python3 run_backtest.py --root /path/to/allData --dates 20221101,20221102
    python3 run_backtest.py --out ./my_outputs
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from engine import ReconciliationEngine
from portfolio import Portfolio
from reporting import generate_all_reports
from runner import run_backtest
from strategies.atm_straddle import ATMStraddleStrategy

UNDERLIER_TO_FUTURE_SYMBOL = {"NIFTY": "NIFTY-I", "BANKNIFTY": "BANKNIFTY-I"}
UNDERLIERS = list(UNDERLIER_TO_FUTURE_SYMBOL)


def _discover_dates(root: Path) -> list[dt.date]:
    return sorted(
        dt.datetime.strptime(folder.name, "NSE_%Y%m%d").date()
        for folder in root.iterdir()
        if folder.is_dir() and folder.name.startswith("NSE_")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=str, default="./allData", help="Path to the extracted allData folder")
    parser.add_argument("--dates", type=str, default="", help="Comma-separated YYYYMMDD list; default: every date under --root")
    parser.add_argument("--out", type=str, default="./outputs", help="Where to write CSVs and plots")
    args = parser.parse_args()

    root = Path(args.root)
    out_dir = Path(args.out)

    if not root.exists():
        print(f"[info] {root} not found.")
        return
    elif args.dates:
        dates = [dt.datetime.strptime(d, "%Y%m%d").date() for d in args.dates.split(",")]
    else:
        dates = _discover_dates(root)

    print(f"Root: {root}")
    print(f"Dates: {[d.isoformat() for d in dates]}")

    strategy = ATMStraddleStrategy(UNDERLIERS)
    portfolio = Portfolio()
    engine: ReconciliationEngine = ReconciliationEngine(strategy, portfolio)
    run_backtest(root, dates, engine, UNDERLIER_TO_FUTURE_SYMBOL)

    stats = generate_all_reports(portfolio, out_dir, label=strategy.name, title_prefix="ATM Straddle")

    print(f"\n {strategy.name} ")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nCSVs and plots written to {out_dir}/")


if __name__ == "__main__":
    main()
