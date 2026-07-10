"""
Analytics & reporting - works purely off Portfolio.mtm_history and
Portfolio.fills; this module only reads.

Three kinds of output:
  - DataFrames (`mtm_dataframe`, `fills_dataframe`, `trade_log_dataframe`,
    `daily_pnl_dataframe`).
  - `summary_stats`, a flat dict of scalar backtest metrics.
  - `plot_*` functions, each saving one PNG.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from portfolio import Portfolio


def mtm_dataframe(portfolio: Portfolio) -> pd.DataFrame:
    """Mark-to-market PnL and open-position count at every timestep."""
    df = pd.DataFrame(
        portfolio.mtm_history,
        columns=["timestamp", "realized_pnl", "unrealized_pnl", "open_positions"],
    )
    df["total_pnl"] = df["realized_pnl"] + df["unrealized_pnl"]
    return df


def fills_dataframe(portfolio: Portfolio) -> pd.DataFrame:
    """Every individual trade the engine executed."""
    return pd.DataFrame(
        [(f.timestamp, f.symbol, f.qty, f.price) for f in portfolio.fills],
        columns=["timestamp", "symbol", "qty", "price"],
    )


def trade_log_dataframe(portfolio: Portfolio) -> pd.DataFrame:
    """
    One row per completed holding period (flat -> open -> flat again),
    derived from `portfolio.fills`. This is the "which instrument was
    held, from when to when, at what size, with what P&L" view.
    """
    fills_by_symbol: dict[str, list] = {}
    for f in portfolio.fills:
        fills_by_symbol.setdefault(f.symbol, []).append(f)

    rows: list[dict] = []
    for symbol, fills in fills_by_symbol.items():
        qty = 0.0
        avg_price = 0.0
        entry_time = None
        trade_realized = 0.0

        for f in sorted(fills, key=lambda x: x.timestamp):
            if qty == 0:
                entry_time = f.timestamp
                trade_realized = 0.0

            if qty == 0 or (qty > 0) == (f.qty > 0):
                total_cost = avg_price * qty + f.price * f.qty
                qty += f.qty
                avg_price = total_cost / qty if qty != 0 else 0.0
            else:
                entry_avg_price = avg_price
                held_qty = qty
                closed = min(abs(f.qty), abs(qty))
                sign = 1 if qty > 0 else -1
                trade_realized += sign * closed * (f.price - avg_price)
                qty += f.qty
                if abs(qty) < 1e-9:
                    rows.append(
                        {
                            "symbol": symbol,
                            "entry_time": entry_time,
                            "exit_time": f.timestamp,
                            "qty": held_qty,
                            "entry_price": entry_avg_price,
                            "exit_price": f.price,
                            "realized_pnl": trade_realized,
                            "holding_seconds": (f.timestamp - entry_time).total_seconds(),
                        }
                    )
                    avg_price = 0.0
                    qty = 0.0

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("entry_time").reset_index(drop=True)
    return df


def daily_pnl_dataframe(portfolio: Portfolio) -> pd.DataFrame:
    """One row per date: that date's PnL contribution and running total."""
    df = mtm_dataframe(portfolio)
    if df.empty:
        return pd.DataFrame(columns=["date", "daily_pnl", "total_pnl"])
    df = df.copy()
    df["date"] = df["timestamp"].dt.date
    day_end = df.groupby("date", as_index=False).last()
    day_end["daily_pnl"] = day_end["total_pnl"].diff()
    day_end.loc[day_end.index[0], "daily_pnl"] = day_end["total_pnl"].iloc[0]
    return day_end[["date", "daily_pnl", "total_pnl"]]


def summary_stats(portfolio: Portfolio) -> dict:
    """Flat dict of scalar backtest metrics."""
    df = mtm_dataframe(portfolio)
    if df.empty:
        return {}

    running_max = df["total_pnl"].cummax()
    drawdown = df["total_pnl"] - running_max
    trades = trade_log_dataframe(portfolio)
    fills = fills_dataframe(portfolio)
    daily = daily_pnl_dataframe(portfolio)

    stats = {
        "final_pnl": float(df["total_pnl"].iloc[-1]),
        "max_pnl": float(df["total_pnl"].max()),
        "max_drawdown": float(drawdown.min()),
        "n_fills": len(portfolio.fills),
        "n_distinct_instruments_traded": int(fills["symbol"].nunique()) if not fills.empty else 0,
        "n_trading_days": int(daily.shape[0]),
        "n_round_trip_trades": int(trades.shape[0]),
        "total_traded_notional": float((fills["qty"].abs() * fills["price"]).sum()) if not fills.empty else 0.0,
    }
    if not trades.empty:
        stats["win_rate"] = float((trades["realized_pnl"] > 0).mean())
        stats["avg_trade_pnl"] = float(trades["realized_pnl"].mean())
        stats["avg_holding_seconds"] = float(trades["holding_seconds"].mean())
    if not daily.empty:
        stats["avg_daily_pnl"] = float(daily["daily_pnl"].mean())
        stats["best_day_pnl"] = float(daily["daily_pnl"].max())
        stats["worst_day_pnl"] = float(daily["daily_pnl"].min())
    return stats


def plot_pnl(portfolio: Portfolio, out_path: Path, title: str = "Cumulative PnL") -> None:
    """Total/realized/unrealized PnL over time, plus open-position count."""
    df = mtm_dataframe(portfolio)
    if df.empty:
        return

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, height_ratios=[2, 1])

    axes[0].plot(df["timestamp"], df["total_pnl"], label="Total PnL", linewidth=1.2)
    axes[0].plot(df["timestamp"], df["realized_pnl"], label="Realized", linewidth=0.8, alpha=0.7)
    axes[0].plot(df["timestamp"], df["unrealized_pnl"], label="Unrealized", linewidth=0.8, alpha=0.7)
    axes[0].axhline(0, color="grey", linewidth=0.6)
    axes[0].set_ylabel("PnL")
    axes[0].set_title(title)
    axes[0].legend(loc="upper left", fontsize=8)

    axes[1].plot(df["timestamp"], df["open_positions"], color="black", linewidth=1.0)
    axes[1].set_ylabel("Open positions")
    axes[1].set_xlabel("Time")

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_drawdown(portfolio: Portfolio, out_path: Path, title: str = "Drawdown from Running Peak PnL") -> None:
    """How far total PnL sits below its running high-water mark, over time."""
    df = mtm_dataframe(portfolio)
    if df.empty:
        return
    running_max = df["total_pnl"].cummax()
    drawdown = df["total_pnl"] - running_max

    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.fill_between(df["timestamp"], drawdown, 0, color="tab:red", alpha=0.35)
    ax.plot(df["timestamp"], drawdown, color="tab:red", linewidth=0.8)
    ax.axhline(0, color="grey", linewidth=0.6)
    ax.set_ylabel("Drawdown")
    ax.set_xlabel("Time")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_daily_pnl(portfolio: Portfolio, out_path: Path, title: str = "PnL by Trading Day") -> None:
    """Bar chart of each day's PnL contribution."""
    df = daily_pnl_dataframe(portfolio)
    if df.empty:
        return

    fig, ax = plt.subplots(figsize=(max(6, 0.4 * len(df)), 4))
    colors = ["tab:green" if v >= 0 else "tab:red" for v in df["daily_pnl"]]
    ax.bar(df["date"].astype(str), df["daily_pnl"], color=colors)
    ax.axhline(0, color="grey", linewidth=0.6)
    ax.set_ylabel("PnL")
    ax.set_title(title)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_positions_timeline(
    portfolio: Portfolio,
    out_path: Path,
    title: str = "Instruments Held Over Time",
    max_symbols: int = 50,
) -> None:
    """
    A Gantt-style chart: one horizontal bar per holding period, grouped
    by instrument - directly answers "which instruments were we in a
    position on, and when". If more than `max_symbols` distinct
    instruments were traded (common across a multi-week backtest, since
    the strategy rolls to a new strike whenever the ATM strike moves),
    only the `max_symbols` most-frequently-held ones are drawn, sorted
    by first entry time; the underlying `trade_log_dataframe` still has
    every holding period.
    """
    trades = trade_log_dataframe(portfolio)
    if trades.empty:
        return

    counts = trades["symbol"].value_counts()
    kept_symbols = list(counts.head(max_symbols).index)
    trades = trades[trades["symbol"].isin(kept_symbols)]
    first_entry = trades.groupby("symbol")["entry_time"].min().sort_values()
    ordered_symbols = list(first_entry.index)
    y_pos = {sym: i for i, sym in enumerate(ordered_symbols)}

    fig, ax = plt.subplots(figsize=(11, max(3.0, 0.28 * len(ordered_symbols))))
    for _, row in trades.iterrows():
        color = "tab:green" if row["qty"] > 0 else "tab:red"
        start = row["entry_time"]
        end = row["exit_time"]
        ax.barh(
            y_pos[row["symbol"]],
            width=(end - start),
            left=start,
            height=0.6,
            color=color,
            edgecolor="black",
            linewidth=0.3,
        )

    ax.set_yticks(list(y_pos.values()))
    ax.set_yticklabels(list(y_pos.keys()), fontsize=7)
    ax.set_xlabel("Time")
    ax.set_title(title + (f" (top {max_symbols} most-held)" if len(counts) > max_symbols else ""))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def generate_all_reports(portfolio: Portfolio, out_dir: Path, label: str, title_prefix: str) -> dict:
    """
    Writes every CSV + PNG this module knows how to produce for one
    portfolio, and returns `summary_stats`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    mtm_dataframe(portfolio).to_csv(out_dir / f"mtm_history_{label}.csv", index=False)
    fills_dataframe(portfolio).to_csv(out_dir / f"fills_{label}.csv", index=False)
    trade_log_dataframe(portfolio).to_csv(out_dir / f"trade_log_{label}.csv", index=False)
    daily_pnl_dataframe(portfolio).to_csv(out_dir / f"daily_pnl_{label}.csv", index=False)

    plot_pnl(portfolio, out_dir / f"pnl_{label}.png", title=f"{title_prefix} -- Cumulative PnL")
    plot_drawdown(portfolio, out_dir / f"drawdown_{label}.png", title=f"{title_prefix} -- Drawdown")
    plot_daily_pnl(portfolio, out_dir / f"daily_pnl_{label}.png", title=f"{title_prefix} -- PnL by Day")
    plot_positions_timeline(
        portfolio, out_dir / f"positions_timeline_{label}.png", title=f"{title_prefix} -- Instruments Held Over Time"
    )

    return summary_stats(portfolio)
