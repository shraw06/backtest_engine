"""
Reconciliation engine.

The piece of logic shared by every strategy: diff what we currently
hold against what the strategy says we should hold, and emit the
trades that close the gap.
"""

from __future__ import annotations

from typing import Generic

from market_state import MarketSnapshot
from portfolio import Portfolio
from strategy import StrategyT


class ReconciliationEngine(Generic[StrategyT]):
    def __init__(self, strategy: StrategyT, portfolio: Portfolio) -> None:
        self.strategy = strategy
        self.portfolio = portfolio

    def step(self, snapshot: MarketSnapshot, force_flat: bool = False) -> None:
        current = dict(self.portfolio.positions)
        target = self.strategy.get_target_positions(snapshot, current, force_flat=force_flat)

        limit = self.strategy.max_abs_position
        target = {
            sym: max(-limit, min(limit, qty))
            for sym, qty in target.items()
        }

        for symbol in set(current) | set(target): #REVIEW
            delta = target.get(symbol, 0.0) - current.get(symbol, 0.0)
            if abs(delta) < 1e-9:
                continue
            price = snapshot.option_prices.get(symbol)
            if price is None: #REVIEW 
                # Can't trade an instrument with no quote at this tick.
                continue
            self.portfolio.execute(symbol, delta, price, snapshot.timestamp)

        self.portfolio.mark_to_market(snapshot)
