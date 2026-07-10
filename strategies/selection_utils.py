"""
Strategy-specific selection helpers.

These encode decisions that belong to a trading strategy rather than
the generic engine:

- selecting which expiry chain to trade
- selecting the ATM strike
- validating whether a desired position can be formed from the
  current market snapshot
- retaining existing positions when the strategy chooses not to roll

Different strategies may implement different helper functions or use different modules altogether.
"""
from __future__ import annotations

import bisect

from data_loader import DateUniverse
from instruments import OptionInstrument
from market_state import MarketSnapshot


def nearest_expiry_options(universe: DateUniverse, underlier: str) -> list[OptionInstrument]:
    """
    All option contracts for `underlier` expiring soonest (>= the
    date). "trade the closest expiry".
    """
    candidates = [
        o
        for o in universe.options.values()
        if o.underlier == underlier and o.expiry >= universe.date
    ]
    if not candidates:
        return []
    nearest = min(o.expiry for o in candidates)
    return [o for o in candidates if o.expiry == nearest]


# A per-(date, underlier) index cached by object identity: id(contracts)
# -> (contracts_ref, sorted_strikes, strike_to_ce, strike_to_pe).
# `contracts` (== snapshot.tradable_options[underlier]) is the exact
# same list object for every tick of a given trading day (the runner
# computes it once via `select_tradable` before the tick loop starts -
# see runner.py), so deriving the sorted strike ladder and CE/PE
# lookup tables from it is a one-time cost per day rather than
# per-tick work. `contracts_ref` is kept alongside the cached index so
# a lookup can verify object identity (`is`), not just id() equality -
# guards against the (rare) case of a garbage-collected list's address
# being reused by an unrelated list, which would otherwise silently
# serve a stale index.
_ChainIndex = tuple[list[OptionInstrument], list[float], dict[float, OptionInstrument], dict[float, OptionInstrument]]
_chain_index_cache: dict[int, _ChainIndex] = {}


def _chain_index(
    contracts: list[OptionInstrument],
) -> tuple[list[float], dict[float, OptionInstrument], dict[float, OptionInstrument]]:
    key = id(contracts)
    cached = _chain_index_cache.get(key)
    if cached is not None and cached[0] is contracts:
        return cached[1], cached[2], cached[3]

    strikes = sorted({c.strike for c in contracts})
    strike_to_ce: dict[float, OptionInstrument] = {}
    strike_to_pe: dict[float, OptionInstrument] = {}
    for c in contracts:
        if c.option_type == "CE":
            strike_to_ce[c.strike] = c
        elif c.option_type == "PE":
            strike_to_pe[c.strike] = c

    _chain_index_cache[key] = (contracts, strikes, strike_to_ce, strike_to_pe)
    return strikes, strike_to_ce, strike_to_pe


def find_atm_strike(snapshot: MarketSnapshot, underlier: str) -> float | None:
    """
    The single strike closest to the underlier's futures price, among
    whatever contracts are in `snapshot.tradable_options`.
    """
    
    fut = snapshot.futures_price.get(underlier)
    contracts = snapshot.tradable_options.get(underlier)
    if fut is None or not contracts:
        return None
    strikes, _, _ = _chain_index(contracts)
    if not strikes:
        return None

    pos = bisect.bisect_left(strikes, fut)
    candidates: list[float] = []
    if pos > 0:
        candidates.append(strikes[pos - 1])
    if pos < len(strikes):
        candidates.append(strikes[pos])
    return min(candidates, key=lambda k: abs(k - fut))


def find_strike_by_type(
    snapshot: MarketSnapshot, underlier: str, strike: float, option_type: str
) -> OptionInstrument | None:
    """The tradable contract at an exact (strike, option_type), if any."""
    contracts = snapshot.tradable_options.get(underlier)
    if not contracts:
        return None
    _, strike_to_ce, strike_to_pe = _chain_index(contracts)
    table = strike_to_ce if option_type == "CE" else strike_to_pe
    return table.get(strike)


def find_atm_pair(
    snapshot: MarketSnapshot, underlier: str
) -> tuple[OptionInstrument, OptionInstrument] | None:
    """
    The CE and PE whose strike is closest to the underlier's futures
    price, among whatever contracts the strategy already placed into
    `snapshot.tradable_options` (via its own `select_tradable`).
    """
    contracts = snapshot.tradable_options.get(underlier)
    if not contracts:
        return None
    _, strike_to_ce, strike_to_pe = _chain_index(contracts)
    atm_strike = find_atm_strike(snapshot, underlier)
    if atm_strike is None:
        return None
    ce = strike_to_ce.get(atm_strike)
    pe = strike_to_pe.get(atm_strike)
    if ce is None or pe is None:
        return None
    return ce, pe

def _current_underlier_positions(
    snapshot: MarketSnapshot,
    current_positions: dict[str, float],
    underlier: str,
) -> dict[str, float]:
    """Return only current positions belonging to one underlier's tradable chain."""
    symbols = _symbols_for_underlier(snapshot, underlier)
    return {
        symbol: qty
        for symbol, qty in current_positions.items()
        if symbol in symbols and abs(qty) > 1e-9
    }

def _symbols_for_underlier(snapshot: MarketSnapshot, underlier: str) -> set[str]:
    return {c.symbol for c in snapshot.tradable_options.get(underlier, [])}

def _have_prices(snapshot: MarketSnapshot, symbols: list[str] | tuple[str, ...]) -> bool:
    """True only when every symbol has a usable option price in this snapshot."""
    return all(snapshot.option_prices.get(symbol) is not None for symbol in symbols)

def _keep_current_for_underlier(
    target: dict[str, float],
    snapshot: MarketSnapshot,
    current_positions: dict[str, float],
    underlier: str,
) -> None:
    """Copy current underlier positions into target so the engine does nothing."""
    target.update(_current_underlier_positions(snapshot, current_positions, underlier))
