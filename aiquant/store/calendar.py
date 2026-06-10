"""A 股交易日历。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from aiquant.config.logger import logger


class TradingCalendar:
    """A 股交易日历管理。优先从 AData 获取，可从 DuckDB 日线数据回退。"""

    def __init__(self):
        self._dates: set[date] | None = None

    def load_from_adata(self, years: list[int]):
        """从 AData 加载交易日历。"""
        import adata
        all_dates = set()
        for year in years:
            try:
                df = adata.stock.info.trade_calendar(year=year)
                if df is not None and not df.empty:
                    trading = df[df["trade_status"].astype(str) == "1"]
                    for d in trading["trade_date"]:
                        all_dates.add(pd.Timestamp(d).date())
            except Exception as e:
                logger.warning(f"获取 {year} 年交易日历失败: {e}")
        self._dates = all_dates
        logger.info(f"交易日历加载完成: {len(self._dates)} 个交易日")

    def load_from_list(self, date_list: list[str]):
        """从日期字符串列表加载。"""
        self._dates = {pd.Timestamp(d).date() for d in date_list}

    def _ensure_loaded(self):
        if self._dates is None:
            raise RuntimeError("交易日历未加载，请先调用 load_from_adata() 或 load_from_list()")

    def is_trading_day(self, d: date) -> bool:
        self._ensure_loaded()
        return d in self._dates

    def prev_trading_day(self, d: date) -> date:
        self._ensure_loaded()
        current = d - timedelta(days=1)
        while current not in self._dates:
            current -= timedelta(days=1)
            if (d - current).days > 30:
                raise ValueError(f"找不到 {d} 之前的交易日")
        return current

    def next_trading_day(self, d: date) -> date:
        self._ensure_loaded()
        current = d + timedelta(days=1)
        while current not in self._dates:
            current += timedelta(days=1)
            if (current - d).days > 30:
                raise ValueError(f"找不到 {d} 之后的交易日")
        return current

    def trading_days_between(self, start: date, end: date) -> list[date]:
        self._ensure_loaded()
        return sorted(d for d in self._dates if start <= d <= end)

    @property
    def dates(self) -> set[date]:
        self._ensure_loaded()
        return self._dates
