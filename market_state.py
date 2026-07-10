"""
The single object a Strategy is allowed to see at each timestep.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from instruments import OptionInstrument


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: dt.datetime
    futures_price: dict[str, float]  # underlier: last futures price
    option_prices: dict[str, float]  # symbol: last traded price
    option_oi: dict[str, float] = field(default_factory=dict)  # symbol: open interest
    option_volume: dict[str, float] = field(default_factory=dict)  # symbol: volume traded this second
    tradable_options: dict[str, list[OptionInstrument]] = field(default_factory=dict) # underlier: contracts
