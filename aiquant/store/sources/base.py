"""数据源抽象基类 + BaseScreener。"""

from abc import ABC, abstractmethod

import pandas as pd


class DataSource(ABC):
    """统一数据源接口。"""

    @abstractmethod
    def download_daily(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """下载日线数据。

        Returns:
            DataFrame，列: date, open, high, low, close, volume, amount, adj_factor, dividend_cash
        """
        ...

    @abstractmethod
    def get_all_tickers(self) -> list[str]:
        """获取全市场股票代码列表。"""
        ...

    def get_csi300_constituents(self) -> pd.DataFrame:
        """获取沪深300历史成分股。

        Returns:
            DataFrame，列: ticker, in_date, out_date
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持沪深300成分股查询")

    def download_dividend(self, ticker: str, start_year: int, end_year: int) -> pd.DataFrame:
        """下载分红数据。

        Returns:
            DataFrame，列: date, dividend_cash（每股税前现金分红）
        """
        return pd.DataFrame(columns=["date", "dividend_cash"])


class BaseScreener(ABC):
    """选股器抽象（v1: DuckDB SQL 因子选股，v2: LLM 基本面选股）。"""

    @abstractmethod
    async def screen(self, conditions: dict) -> list[str]:
        """条件选股，返回股票代码列表。"""
        ...
