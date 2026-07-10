"""
Drives a single date through the engine: builds the 1-second snapshot
stream from raw files, calls engine.step() at every tick, and finally
does one last `engine.step(..., force_flat=True)` call at day end.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import (
    DateUniverse,
    discover_date_universe,
    load_tick_series,
    resample_to_1s_last,
    resample_to_1s_sum,
)
from engine import ReconciliationEngine
from instruments import OptionInstrument
from market_state import MarketSnapshot

MARKET_OPEN = dt.time(9, 15)
DEFAULT_MARKET_CLOSE = dt.time(15, 30)  # extended per-date if data runs later


def _session_index(
    universe: DateUniverse,
    raw_options: dict[str, pd.DataFrame],
    raw_futures: dict[str, pd.DataFrame],
) -> pd.DatetimeIndex:
    """
    Build the 1s grid for this date. The close time is max(15:30, last
    tick actually seen in any relevant file for this date). 
    raw_option here is the tradable-restricted set, raw_futures is always the full
    front-month futures set.
    """
    latest_ts: pd.Timestamp | None = None
    for raw in list(raw_options.values()) + list(raw_futures.values()):
        if raw.empty:
            continue
        candidate = raw.index.max()
        if latest_ts is None or candidate > latest_ts:
            latest_ts = candidate

    close_time = DEFAULT_MARKET_CLOSE
    if latest_ts is not None and latest_ts.time() > close_time:
        close_time = latest_ts.time()

    return pd.date_range(
        start=dt.datetime.combine(universe.date, MARKET_OPEN),
        end=dt.datetime.combine(universe.date, close_time),
        freq="1s",
    )


def _build_price_grid(
    universe: DateUniverse,
    tradable_option_symbols: set[str],
) -> tuple[
    pd.DatetimeIndex,
    dict[str, pd.Series],
    dict[str, pd.Series],
    dict[str, pd.Series],
    dict[str, pd.Series],
]:
    """
    Resample every tradable option file, plus every futures file, for the date onto a common 1s grid.

    Returns (index, option_price_series, future_price_series,
    option_oi_series, option_volume_series). Price and OI are state
    fields (last-value-then-ffill); Volume is a flow field (summed per
    second).
    """
    option_paths = {
        sym: path for sym, path in universe.option_paths.items() if sym in tradable_option_symbols
    }
    raw_options = {sym: load_tick_series(path) for sym, path in option_paths.items()}
    raw_futures = {sym: load_tick_series(path) for sym, path in universe.future_paths.items()}

    index = _session_index(universe, raw_options, raw_futures)

    option_price_series = {sym: resample_to_1s_last(df, index, "Price") for sym, df in raw_options.items()}
    future_price_series = {sym: resample_to_1s_last(df, index, "Price") for sym, df in raw_futures.items()}
    option_oi_series = {sym: resample_to_1s_last(df, index, "OI") for sym, df in raw_options.items()}
    option_volume_series = {sym: resample_to_1s_sum(df, index, "Volume") for sym, df in raw_options.items()}

    return index, option_price_series, future_price_series, option_oi_series, option_volume_series


def _to_matrix(series_map: dict[str, pd.Series]) -> tuple[np.ndarray, np.ndarray]:
    """
    symbols (dtype=object, shape (n,)), values (dtype=float64, shape
    (n, n_ticks)).
    """
    symbols = np.array(list(series_map.keys()), dtype=object)
    if len(symbols) == 0:
        return symbols, np.empty((0, 0), dtype=float)
    values = np.vstack([s.to_numpy(dtype=float) for s in series_map.values()])
    return symbols, values


def _tick_dict(symbols: np.ndarray, column: np.ndarray) -> dict[str, float]:
    """One tick's worth of a (symbols, values) matrix -> {symbol: value}, NaNs dropped."""
    if column.size == 0:
        return {}
    mask = ~np.isnan(column)
    if not mask.any():
        return {}
    return dict(zip(symbols[mask].tolist(), column[mask].tolist()))


def run_date(
    root: Path,
    date: dt.date,
    engine: ReconciliationEngine,  # Generic[StrategyT]
    underlier_to_future_symbol: dict[str, str],
) -> None:
    universe = discover_date_universe(root, date)
    if not universe.options or not universe.futures:
        return  # no data for this date

    tradable_by_underlier: dict[str, list[OptionInstrument]] = {
        u: engine.strategy.select_tradable(universe, u) for u in underlier_to_future_symbol
    }
    tradable_symbols = {
        opt.symbol for opts in tradable_by_underlier.values() for opt in opts
    }

    index, option_price_series, future_price_series, option_oi_series, option_volume_series = (
        _build_price_grid(universe, tradable_symbols)
    )

    opt_price_symbols, opt_price_matrix = _to_matrix(option_price_series)
    opt_oi_symbols, opt_oi_matrix = _to_matrix(option_oi_series)
    opt_vol_symbols, opt_vol_matrix = _to_matrix(option_volume_series)
    fut_symbols, fut_matrix = _to_matrix(future_price_series)
    fut_symbol_to_underlier = {v: k for k, v in underlier_to_future_symbol.items()}

    snapshot = None
    for i, ts in enumerate(index):
        raw_futures = _tick_dict(fut_symbols, fut_matrix[:, i] if fut_matrix.size else fut_matrix)

        futures_price = {
            fut_symbol_to_underlier[sym]: px
            for sym, px in raw_futures.items()
            if sym in fut_symbol_to_underlier
        }
        option_prices = _tick_dict(opt_price_symbols, opt_price_matrix[:, i] if opt_price_matrix.size else opt_price_matrix)
        option_oi = _tick_dict(opt_oi_symbols, opt_oi_matrix[:, i] if opt_oi_matrix.size else opt_oi_matrix)
        option_volume = _tick_dict(opt_vol_symbols, opt_vol_matrix[:, i] if opt_vol_matrix.size else opt_vol_matrix)

        snapshot = MarketSnapshot(
            timestamp=ts,
            futures_price=futures_price,
            option_prices=option_prices,
            option_oi=option_oi,
            option_volume=option_volume,
            tradable_options=tradable_by_underlier,
        )
        engine.step(snapshot)

    if snapshot is not None:
        # Day-end: one more reconciliation step, flagged as the
        # session close.
        engine.step(snapshot, force_flat=True)


def run_backtest(
    root: Path,
    dates: list[dt.date],
    engine: ReconciliationEngine,
    underlier_to_future_symbol: dict[str, str],
) -> None:
    for date in dates:
        run_date(root, date, engine, underlier_to_future_symbol)

