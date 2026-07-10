"""
Simple trading strategy:
buy the CE+PE closest to the futures price, in the nearest expiry,
and hold until the ATM strike changes. Flatten everything at day end.

It satisfies the Strategy Protocol purely by having matching `name`,
`max_abs_position` attributes and `select_tradable` /
`get_target_positions` methods - structural typing.

Everything strategy-specific lives on this class:
  - `max_abs_position`      - this strategy's own risk limit (the max 1 position rule here)
  - `select_tradable`       - nearest expiry only
  - ATM strike selection     - delegates to `find_atm_pair`
  - day-end behaviour        - `force_flat=True` -> return {}, i.e.
                                hold nothing; the engine's diff logic
                                does the actual selling
"""
from __future__ import annotations

from data_loader import DateUniverse
from instruments import OptionInstrument
from market_state import MarketSnapshot
from strategies.selection_utils import find_atm_pair, nearest_expiry_options, _have_prices,  _keep_current_for_underlier


class ATMStraddleStrategy:
    name = "atm_straddle_buyer"

    # Strategy-owned risk limit
    max_abs_position = 1.0

    def __init__(self, underliers: list[str]) -> None:
        self.underliers = underliers

    def select_tradable(self, universe: DateUniverse, underlier: str) -> list[OptionInstrument]:
        """This strategy only ever trades the nearest expiry."""
        return nearest_expiry_options(universe, underlier)

    def get_target_positions(
        self,
        snapshot: MarketSnapshot,
        current_positions: dict[str, float],
        force_flat: bool = False,
    ) -> dict[str, float]:
        if force_flat:
            return {}

        target: dict[str, float] = {}
        for underlier in self.underliers:
            pair = find_atm_pair(snapshot, underlier)
            if pair is None:
                _keep_current_for_underlier(target, snapshot, current_positions, underlier)
                continue

            ce, pe = pair
            if not _have_prices(snapshot, (ce.symbol, pe.symbol)):
                # Historical option quotes are timestamped independently.
                # Roll only when both legs of the target straddle have prices;
                # otherwise retain the current straddle.
                _keep_current_for_underlier(target, snapshot, current_positions, underlier)
                continue

            target[ce.symbol] = 1.0
            target[pe.symbol] = 1.0
        return target
