"""
Portfolio layer.

It knows about symbols, quantities, prices and timestamps.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from market_state import MarketSnapshot


@dataclass
class Fill:
    timestamp: dt.datetime
    symbol: str
    qty: float  # +buy, -sell
    price: float


@dataclass
class Portfolio:
    positions: dict[str, float] = field(default_factory=dict)
    avg_price: dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fills: list[Fill] = field(default_factory=list)
    # (timestamp, realized_pnl, unrealized_pnl, n_open_positions)
    mtm_history: list[tuple[dt.datetime, float, float, int]] = field(default_factory=list)

    def execute(self, symbol: str, delta_qty: float, price: float, ts: dt.datetime) -> None:
        if abs(delta_qty) < 1e-9:
            return

        cur_qty = self.positions.get(symbol, 0.0)
        cur_avg = self.avg_price.get(symbol, 0.0)
        new_qty = cur_qty + delta_qty

        if cur_qty == 0 or (cur_qty > 0) == (delta_qty > 0):
            # Opening or adding to a position
            total_cost = cur_avg * cur_qty + price * delta_qty
            self.avg_price[symbol] = total_cost / new_qty if new_qty != 0 else 0.0
        else:
            # Reducing or flipping a position: realize PnL on the part closed.
            closed_qty = min(abs(delta_qty), abs(cur_qty))
            sign = 1 if cur_qty > 0 else -1
            self.realized_pnl += sign * closed_qty * (price - cur_avg)
            if abs(new_qty) < 1e-9:
                self.avg_price[symbol] = 0.0
            elif (new_qty > 0) != (cur_qty > 0):
                # Flipped through zero: remainder opens at this fill's price.
                self.avg_price[symbol] = price

        self.positions[symbol] = new_qty
        self.fills.append(Fill(ts, symbol, delta_qty, price))

    def mark_to_market(self, snapshot: MarketSnapshot) -> None:
        unrealized = 0.0
        open_count = 0
        for symbol, qty in self.positions.items():
            if abs(qty) < 1e-9:
                continue
            open_count += 1
            px = snapshot.option_prices.get(symbol, self.avg_price.get(symbol, 0.0))
            unrealized += qty * (px - self.avg_price.get(symbol, 0.0))
        self.mtm_history.append((snapshot.timestamp, self.realized_pnl, unrealized, open_count))
