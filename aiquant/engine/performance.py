"""绩效计算。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from aiquant.config.settings import settings
from aiquant.engine.core import BacktestResult, DailySnapshot, Trade


@dataclass
class PerformanceReport:
    """绩效报告。"""
    # 收益
    total_return: float          # 累计收益率
    annual_return: float         # 年化收益率

    # 风险
    max_drawdown: float          # 最大回撤
    max_drawdown_start: str      # 回撤起始日
    max_drawdown_end: str        # 回撤结束日
    sharpe_ratio: float          # 夏普比率

    # 交易统计
    total_trades: int            # 总交易次数
    win_trades: int              # 盈利交易次数
    lose_trades: int             # 亏损交易次数
    win_rate: float              # 胜率
    profit_loss_ratio: float     # 盈亏比
    avg_holding_days: float      # 平均持仓天数

    # 账户
    initial_cash: float
    final_value: float
    final_cash: float
    final_market_value: float

    # 时间序列
    daily_returns: pd.Series | None = None
    equity_curve: pd.Series | None = None


def calculate_performance(result: BacktestResult) -> PerformanceReport:
    """计算回测绩效。"""
    snapshots = result.daily_snapshots
    trades = result.trades
    config = result.config
    initial_cash = config.initial_cash

    if not snapshots:
        return PerformanceReport(
            total_return=0, annual_return=0, max_drawdown=0,
            max_drawdown_start="", max_drawdown_end="",
            sharpe_ratio=0, total_trades=0, win_trades=0, lose_trades=0,
            win_rate=0, profit_loss_ratio=0, avg_holding_days=0,
            initial_cash=initial_cash, final_value=initial_cash,
            final_cash=initial_cash, final_market_value=0,
        )

    # 权益曲线
    equity = pd.Series(
        [s.total_value for s in snapshots],
        index=[s.date for s in snapshots],
    )

    # 日收益率
    daily_returns = equity.pct_change().dropna()

    # 累计收益率
    final_value = equity.iloc[-1]
    total_return = (final_value - initial_cash) / initial_cash

    # 年化收益率
    trading_days = len(equity)
    if trading_days > 1:
        annual_return = (1 + total_return) ** (252 / trading_days) - 1
    else:
        annual_return = 0.0

    # 最大回撤
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    max_drawdown = abs(drawdown.min()) if not drawdown.empty else 0.0
    max_dd_end_idx = drawdown.idxmin() if not drawdown.empty else None
    max_dd_start_idx = equity[:max_dd_end_idx].idxmax() if max_dd_end_idx else None

    # 夏普比率
    risk_free_daily = settings.risk_free_rate / 252
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe_ratio = (daily_returns.mean() - risk_free_daily) / daily_returns.std() * math.sqrt(252)
    else:
        sharpe_ratio = 0.0

    # 交易统计
    buy_trades = [t for t in trades if t.side == "buy"]
    sell_trades = [t for t in trades if t.side in ("sell", "sell_stop")]

    # 配对买卖计算胜率 (FIFO 队列)
    win_trades = 0
    lose_trades = 0
    total_profit = 0.0
    total_loss = 0.0
    holding_days_list = []

    from collections import deque
    buy_queues: dict[str, deque[Trade]] = {}
    for t in trades:
        if t.side == "buy":
            buy_queues.setdefault(t.ticker, deque()).append(t)
        elif t.side in ("sell", "sell_stop"):
            queue = buy_queues.get(t.ticker)
            if queue:
                buy_t = queue.popleft()
                pnl = (t.price - buy_t.price) * buy_t.shares
                if pnl > 0:
                    win_trades += 1
                    total_profit += pnl
                else:
                    lose_trades += 1
                    total_loss += abs(pnl)
                holding_days_list.append((t.date - buy_t.date).days)

    total_pair_trades = win_trades + lose_trades
    win_rate = win_trades / total_pair_trades if total_pair_trades > 0 else 0.0
    avg_profit = total_profit / win_trades if win_trades > 0 else 0.0
    avg_loss = total_loss / lose_trades if lose_trades > 0 else 0.0
    profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else float("inf")
    avg_holding_days = sum(holding_days_list) / len(holding_days_list) if holding_days_list else 0.0

    return PerformanceReport(
        total_return=round(total_return, 6),
        annual_return=round(annual_return, 6),
        max_drawdown=round(max_drawdown, 6),
        max_drawdown_start=str(max_dd_start_idx) if max_dd_start_idx else "",
        max_drawdown_end=str(max_dd_end_idx) if max_dd_end_idx else "",
        sharpe_ratio=round(sharpe_ratio, 4),
        total_trades=len(trades),
        win_trades=win_trades,
        lose_trades=lose_trades,
        win_rate=round(win_rate, 4),
        profit_loss_ratio=round(profit_loss_ratio, 4),
        avg_holding_days=round(avg_holding_days, 1),
        initial_cash=initial_cash,
        final_value=round(final_value, 2),
        final_cash=round(snapshots[-1].cash, 2),
        final_market_value=round(snapshots[-1].market_value, 2),
        daily_returns=daily_returns,
        equity_curve=equity,
    )


def format_report(report: PerformanceReport) -> str:
    """格式化绩效报告为可读字符串。"""
    lines = [
        "=" * 50,
        "回测绩效报告",
        "=" * 50,
        f"累计收益率:    {report.total_return:.2%}",
        f"年化收益率:    {report.annual_return:.2%}",
        f"最大回撤:      {report.max_drawdown:.2%}",
        f"  回撤区间:    {report.max_drawdown_start} ~ {report.max_drawdown_end}",
        f"夏普比率:      {report.sharpe_ratio:.4f}",
        "-" * 50,
        f"总交易次数:    {report.total_trades}",
        f"盈利交易:      {report.win_trades}",
        f"亏损交易:      {report.lose_trades}",
        f"胜率:          {report.win_rate:.2%}",
        f"盈亏比:        {report.profit_loss_ratio:.2f}",
        f"平均持仓天数:  {report.avg_holding_days:.1f}",
        "-" * 50,
        f"初始资金:      {report.initial_cash:,.2f}",
        f"最终净值:      {report.final_value:,.2f}",
        f"最终现金:      {report.final_cash:,.2f}",
        f"最终持仓市值:  {report.final_market_value:,.2f}",
        "=" * 50,
    ]
    return "\n".join(lines)
