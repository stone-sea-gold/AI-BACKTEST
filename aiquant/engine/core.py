"""回测引擎核心：信号-执行分离，T+1 开盘撮合。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from aiquant.config.logger import logger
from aiquant.config.settings import settings
from aiquant.store.duckdb_store import DuckDBStore
from aiquant.strategy.compiler import build_backtest_query
from aiquant.strategy.models import StrategyConfig


@dataclass
class Position:
    """持仓。"""
    ticker: str
    shares: int
    avg_cost: float       # 真实成本价
    buy_date: date        # 买入日期（T+1 约束）


@dataclass
class Trade:
    """交易记录。"""
    ticker: str
    date: date
    side: str             # "buy" / "sell"
    price: float          # 真实成交价
    shares: int
    amount: float         # 成交金额
    commission: float     # 手续费


@dataclass
class DailySnapshot:
    """每日账户快照。"""
    date: date
    cash: float
    market_value: float   # 持仓市值
    total_value: float    # cash + market_value
    positions: dict       # ticker -> shares


@dataclass
class BacktestResult:
    """回测结果。"""
    trades: list[Trade]
    daily_snapshots: list[DailySnapshot]
    signals: pd.DataFrame
    config: StrategyConfig


def _calc_commission(amount: float, side: str) -> float:
    """计算手续费：佣金 + 印花税(仅卖出) + 过户费。"""
    commission = amount * settings.commission_rate
    commission = max(commission, settings.min_commission)
    if side == "sell":
        commission += amount * settings.stamp_tax_rate
    commission += amount * settings.transfer_fee_rate
    return round(commission, 2)


def _is_limit_up(open_price: float, high: float, low: float, pre_close: float, limit_pct: float) -> bool:
    """一字涨停判断：开盘=最高=最低=涨停价。"""
    limit_price = round(pre_close * (1 + limit_pct), 2)
    return (open_price == high == low == limit_price)


def _is_limit_down(open_price: float, high: float, low: float, pre_close: float, limit_pct: float) -> bool:
    """一字跌停判断：开盘=最高=最低=跌停价。"""
    limit_price = round(pre_close * (1 - limit_pct), 2)
    return (open_price == high == low == limit_price)


def _get_limit_pct(ticker: str) -> float:
    """根据代码判断涨跌停幅度。"""
    if ticker.startswith("688") or ticker.startswith("300"):
        return 0.20  # 科创板/创业板 20%
    return 0.10  # 主板 10%


def run_backtest(
    config: StrategyConfig,
    store: DuckDBStore,
) -> BacktestResult:
    """执行回测。"""
    # 1. 获取标的池
    from aiquant.strategy.universe import resolve_stock_pool
    tickers = resolve_stock_pool(config.stock_pool, store, config.custom_tickers)
    if not tickers:
        raise ValueError("标的池为空，无法回测")

    logger.info(f"标的池: {len(tickers)} 只, 区间: {config.start_date} ~ {config.end_date}")

    # 2. 编译并执行 SQL 获取信号
    sql = build_backtest_query(config, tickers)
    logger.debug(f"回测 SQL:\n{sql}")
    signals_df = store.conn.execute(sql).fetchdf()

    if signals_df.empty:
        logger.warning("无任何信号生成")
        return BacktestResult(trades=[], daily_snapshots=[], signals=signals_df, config=config)

    logger.info(f"信号数: {len(signals_df)} (买: {(signals_df['buy_signal']==1).sum()}, 卖: {(signals_df['sell_signal']==1).sum()})")

    # 3. 获取全量日线数据用于撮合
    all_klines = store.get_batch_klines(tickers, config.start_date, config.end_date)
    if all_klines.empty:
        raise ValueError("无日线数据")

    # 4. 构建日期索引
    all_klines["date"] = pd.to_datetime(all_klines["date"]).dt.date
    trading_dates = sorted(all_klines["date"].unique())

    # 构建每日行情字典: {date: {ticker: row}}
    kline_map: dict[date, dict[str, dict]] = {}
    for _, row in all_klines.iterrows():
        d = row["date"]
        t = row["ticker"]
        if d not in kline_map:
            kline_map[d] = {}
        kline_map[d][t] = row.to_dict()

    # 5. 构建信号字典: {date: {ticker: (buy, sell)}}
    signals_df["date"] = pd.to_datetime(signals_df["date"]).dt.date
    signal_map: dict[date, dict[str, tuple[int, int]]] = {}
    for _, row in signals_df.iterrows():
        d = row["date"]
        t = row["ticker"]
        if d not in signal_map:
            signal_map[d] = {}
        signal_map[d][t] = (int(row["buy_signal"]), int(row["sell_signal"]))

    # 6. 逐日循环
    cash = config.initial_cash
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    snapshots: list[DailySnapshot] = []
    pending_signals: dict[str, tuple[int, int]] = {}  # T日信号，T+1执行

    for i, today in enumerate(trading_dates):
        today_kline = kline_map.get(today, {})

        # ── 卖出检查：执行昨天的卖出信号 ──
        for ticker, (buy_sig, sell_sig) in list(pending_signals.items()):
            if sell_sig == 1 and ticker in positions:
                pos = positions[ticker]
                if today > pos.buy_date:  # T+1 约束
                    row = today_kline.get(ticker)
                    if row:
                        open_price = row["open"]
                        pre_close = row.get("close", open_price)  # 近似
                        limit_pct = _get_limit_pct(ticker)
                        if not _is_limit_down(open_price, row["high"], row["low"], pre_close, limit_pct):
                            sell_amount = open_price * pos.shares
                            commission = _calc_commission(sell_amount, "sell")
                            cash += sell_amount - commission
                            trades.append(Trade(ticker, today, "sell", open_price, pos.shares, sell_amount, commission))
                            del positions[ticker]
                        else:
                            logger.debug(f"{today} {ticker} 一字跌停无法卖出")

        # ── 买入检查：执行昨天的买入信号 ──
        for ticker, (buy_sig, sell_sig) in list(pending_signals.items()):
            if buy_sig == 1 and ticker not in positions:
                row = today_kline.get(ticker)
                if row:
                    open_price = row["open"]
                    pre_close = row.get("close", open_price)
                    limit_pct = _get_limit_pct(ticker)
                    if not _is_limit_up(open_price, row["high"], row["low"], pre_close, limit_pct):
                        # 计算可买股数
                        max_buy_amount = cash * config.position_sizing.pct
                        shares = int(max_buy_amount / open_price / 100) * 100
                        if shares >= 100:
                            buy_amount = open_price * shares
                            commission = _calc_commission(buy_amount, "buy")
                            if cash >= buy_amount + commission:
                                cash -= buy_amount + commission
                                positions[ticker] = Position(ticker, shares, open_price, today)
                                trades.append(Trade(ticker, today, "buy", open_price, shares, buy_amount, commission))
                    else:
                        logger.debug(f"{today} {ticker} 一字涨停无法买入")

        # ── 止损检查 ──
        for ticker in list(positions.keys()):
            pos = positions[ticker]
            row = today_kline.get(ticker)
            if row and config.stop_loss.type != "none":
                current_price = row["close"]
                if config.stop_loss.type == "fixed":
                    loss_pct = (pos.avg_cost - current_price) / pos.avg_cost
                    if loss_pct >= config.stop_loss.pct:
                        open_price = row["open"]
                        sell_amount = open_price * pos.shares
                        commission = _calc_commission(sell_amount, "sell")
                        cash += sell_amount - commission
                        trades.append(Trade(ticker, today, "sell_stop", open_price, pos.shares, sell_amount, commission))
                        del positions[ticker]

        # ── 分红检查 ──
        for ticker, pos in positions.items():
            row = today_kline.get(ticker)
            if row and row.get("dividend_cash", 0) > 0:
                dividend = pos.shares * row["dividend_cash"] * (1 - settings.dividend_tax_rate)
                cash += dividend
                logger.debug(f"{today} {ticker} 分红 {dividend:.2f}")

        # ── 更新持仓市值 ──
        market_value = 0.0
        for ticker, pos in positions.items():
            row = today_kline.get(ticker)
            if row:
                market_value += row["close"] * pos.shares

        total_value = cash + market_value
        snapshots.append(DailySnapshot(today, cash, market_value, total_value, {t: p.shares for t, p in positions.items()}))

        # ── 保存今日信号作为待执行信号 ──
        pending_signals = signal_map.get(today, {})

    return BacktestResult(
        trades=trades,
        daily_snapshots=snapshots,
        signals=signals_df,
        config=config,
    )
