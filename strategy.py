"""
Static Strategy pattern:

Four things that look like generic backtest machinery but are
actually strategy-specific policy choices, and are modelled as such
below:

  1. Position sizing / risk limits (`max_abs_position`)
  2. Day-end behaviour - end-of-session is just another
     call to `get_target_positions` with `force_flat=True`, and the
     strategy decides what target that implies.
  3. Strike/contract selection
  4. Which expiry/contracts are even tradable a given day (`select_tradable`) 
"""
from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from data_loader import DateUniverse
from instruments import OptionInstrument
from market_state import MarketSnapshot


@runtime_checkable
class Strategy(Protocol):
    """
    The structural contract every strategy must satisfy.

    A strategy is a pure function of (snapshot, current_positions) ->
    desired positions. 
    """

    name: str
    max_abs_position: float

    def select_tradable(
        self, universe: DateUniverse, underlier: str
    ) -> list[OptionInstrument]:
        """
        Which contracts, for this underlier, this strategy is willing
        to trade on this date (e.g. nearest expiry only). Called once
        per underlier per date by the runner to populate
        `MarketSnapshot.tradable_options`.
        """
        ...

    def get_target_positions(
        self,
        snapshot: MarketSnapshot,
        current_positions: dict[str, float],
        force_flat: bool = False,
    ) -> dict[str, float]:
        """
        Desired positions as {symbol: target_qty}.

        `force_flat=True` is how the engine asks for end-of-session
        targets. A strategy that just wants a hard
        flatten at day end can simply `return {}` when `force_flat`
        is True (the engine's diff logic will sell out whatever is
        currently held). A strategy that wants different close-of-day
        behaviour is free to return something else.
        """
        ...


# Bound TypeVar: only types matching the Strategy protocol may be used
# to parameterize the engine. This is checked statically wherever
# `ReconciliationEngine[SomeStrategy]` is written.
StrategyT = TypeVar("StrategyT", bound=Strategy)
