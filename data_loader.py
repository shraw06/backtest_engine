"""
Data access layer.

Knows the on-disk folder convention:
    <root>/NSE_<YYYYMMDD>/Options/<instrument>.csv
    <root>/NSE_<YYYYMMDD>/Futures (Continuous)/<UNDERLIER>-I.csv
It discovers files and loads raw tick data into a uniform shape.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from instruments import (
    FutureInstrument,
    OptionInstrument,
    InstrumentParseError,
    parse_future_filename,
    parse_option_filename,
)

TICK_COLUMNS = ["Date", "Time", "Price", "Volume", "OI"]


@dataclass
class DateUniverse:
    """Everything discovered on disk for a single date."""

    date: dt.date
    options: dict[str, OptionInstrument] = field(default_factory=dict)
    futures: dict[str, FutureInstrument] = field(default_factory=dict)
    option_paths: dict[str, Path] = field(default_factory=dict)
    future_paths: dict[str, Path] = field(default_factory=dict)


def discover_date_universe(root: Path, date: dt.date) -> DateUniverse:
    """Scan <root>/NSE_<YYYYMMDD>/{Options,Futures (Continuous)} and build the universe."""
    day_dir = root / f"NSE_{date:%Y%m%d}"
    options_dir = day_dir / "Options"
    futures_dir = day_dir / "Futures (Continuous)"

    universe = DateUniverse(date=date)

    if options_dir.exists():
        for path in sorted(options_dir.glob("*.csv")):
            try:
                opt_inst = parse_option_filename(path.stem)
            except InstrumentParseError:
                continue
            universe.options[opt_inst.symbol] = opt_inst
            universe.option_paths[opt_inst.symbol] = path

    if futures_dir.exists():
        for path in sorted(futures_dir.glob("*-I.csv")):  # series I only
            try:
                fut_inst = parse_future_filename(path.stem)
            except InstrumentParseError:
                continue
            universe.futures[fut_inst.symbol] = fut_inst
            universe.future_paths[fut_inst.symbol] = path

    return universe


def load_tick_series(path: Path) -> pd.DataFrame:
    """
    Load a single instrument's raw tick file into a DataFrame indexed by
    a combined timestamp, columns: Price, Volume, OI.
    """
    df = pd.read_csv(path, header=None, names=TICK_COLUMNS)
    df["timestamp"] = pd.to_datetime(
        df["Date"].astype(str) + " " + df["Time"],
        format="%Y%m%d %H:%M:%S",
        errors="coerce",
    )
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df = df.set_index("timestamp")[["Price", "Volume", "OI"]]
    return df


def resample_to_1s_last(df: pd.DataFrame, index: pd.DatetimeIndex, column: str) -> pd.Series:
    """
    Collapse a single tick-series column onto the given 1-second grid,
    forward-filled.
    """
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float, index=index)
    s = df[column].resample("1s").last()
    s = s.reindex(index).ffill()
    return s


def resample_to_1s_sum(df: pd.DataFrame, index: pd.DatetimeIndex, column: str) -> pd.Series:
    """
    Collapse a single tick-series column onto the given 1-second grid by
    summing everything printed within each second. Seconds
    with no prints get 0.0.
    """
    if df.empty or column not in df.columns:
        return pd.Series(0.0, index=index)
    s = df[column].resample("1s").sum()
    s = s.reindex(index, fill_value=0.0)
    return s
