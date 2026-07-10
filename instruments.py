"""
Instrument identity model.

Parses raw filenames into instrument objects.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

KNOWN_UNDERLIERS: tuple[str, ...] = ("BANKNIFTY", "FINNIFTY", "NIFTY")


@dataclass(frozen=True)
class OptionInstrument:
    """Identity of a single option contract."""

    symbol: str  # file stem
    underlier: str  # NIFTY/BANKNIFTY/FINNIFTY
    expiry: dt.date
    strike: float
    option_type: str  # CE/PE


@dataclass(frozen=True)
class FutureInstrument:
    """Identity of a futures contract."""

    symbol: str  # file stem
    underlier: str
    series: str  # I/II/III


class InstrumentParseError(ValueError):
    pass


def _match_underlier(stem: str) -> str:
    for u in KNOWN_UNDERLIERS:
        if stem.startswith(u):
            return u
    raise InstrumentParseError(f"Unknown underlier in '{stem}'")


def parse_option_filename(stem: str) -> OptionInstrument:
    
    # 'NIFTY22110314550PE' -> NIFTY, 2022-11-03, 14550.0, PE
    
    underlier = _match_underlier(stem)
    rest = stem[len(underlier):]

    option_type = rest[-2:]
    if option_type not in ("CE", "PE"):
        raise InstrumentParseError(f"'{stem}' does not end in CE/PE")

    expiry_str, strike_str = rest[:6], rest[6:-2]
    try:
        expiry = dt.datetime.strptime(expiry_str, "%y%m%d").date()
        strike = float(strike_str)
    except ValueError as e:
        raise InstrumentParseError(f"Could not parse '{stem}': {e}") from e

    return OptionInstrument(stem, underlier, expiry, strike, option_type)


def parse_future_filename(stem: str) -> FutureInstrument:
    
    # 'NIFTY-I' -> NIFTY, series I
    
    if "-" not in stem:
        raise InstrumentParseError(f"'{stem}' is not a futures filename")
    underlier, series = stem.split("-", 1)
    if underlier not in KNOWN_UNDERLIERS:
        raise InstrumentParseError(f"Unknown underlier in '{stem}'")
    return FutureInstrument(stem, underlier, series)
