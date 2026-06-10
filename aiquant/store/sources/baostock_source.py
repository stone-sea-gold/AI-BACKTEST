"""BaoStock 数据源适配器（备选）。"""

import baostock as bs
import pandas as pd

from aiquant.config.logger import logger
from aiquant.store.sources.base import DataSource


def _to_bs_code(ticker: str) -> str:
    """将纯数字代码转为 BaoStock 格式 (sh.600000 / sz.000001)。"""
    if ticker.startswith(("sh.", "sz.")):
        return ticker
    if ticker.startswith(("6", "9")):
        return f"sh.{ticker}"
    return f"sz.{ticker}"


def _from_bs_code(bs_code: str) -> str:
    """将 BaoStock 格式转为纯数字代码。"""
    return bs_code.split(".")[-1]


class BaoStockSource(DataSource):
    """BaoStock 数据源适配器。"""

    def __init__(self):
        self._logged_in = False

    def _login(self):
        if not self._logged_in:
            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")
            self._logged_in = True

    def _logout(self):
        if self._logged_in:
            bs.logout()
            self._logged_in = False

    def download_daily(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """下载日线数据，返回含真实收盘价和复权因子的 DataFrame。"""
        self._login()
        bs_code = _to_bs_code(ticker)

        # 不复权数据（真实价格 + 换手率）
        rs_real = bs.query_history_k_data_plus(
            bs_code, "date,open,high,low,close,volume,amount,turn",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="3",
        )
        rows_real = []
        while rs_real.error_code == "0" and rs_real.next():
            rows_real.append(rs_real.get_row_data())

        if not rows_real:
            logger.warning(f"BaoStock: {ticker} 无数据")
            return pd.DataFrame()

        df_real = pd.DataFrame(rows_real, columns=["date", "open", "high", "low", "close", "volume", "amount", "turn"])

        # 前复权数据（用于计算复权因子）
        rs_adj = bs.query_history_k_data_plus(
            bs_code, "date,close",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="1",
        )
        rows_adj = []
        while rs_adj.error_code == "0" and rs_adj.next():
            rows_adj.append(rs_adj.get_row_data())

        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df_real["date"]).dt.date
        result["open"] = df_real["open"].astype(float)
        result["high"] = df_real["high"].astype(float)
        result["low"] = df_real["low"].astype(float)
        result["close"] = df_real["close"].astype(float)
        result["volume"] = df_real["volume"].astype(float)
        result["amount"] = df_real["amount"].astype(float)
        result["turnover_ratio"] = pd.to_numeric(df_real["turn"], errors="coerce").fillna(0.0)

        if rows_adj:
            df_adj = pd.DataFrame(rows_adj, columns=["date", "adj_close"])
            adj_close = df_adj["adj_close"].astype(float)
            real_close = df_real["close"].astype(float)
            result["adj_factor"] = (adj_close / real_close).round(6)
        else:
            result["adj_factor"] = 1.0

        result["dividend_cash"] = 0.0
        result["ticker"] = ticker

        return result.reset_index(drop=True)

    def get_all_tickers(self) -> list[str]:
        """获取全市场 A 股代码列表。"""
        self._login()
        rs = bs.query_stock_basic()
        tickers = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            code = row[0]  # stockCode
            if code.startswith(("sh.", "sz.")):
                tickers.append(_from_bs_code(code))
        return tickers

    def get_csi300_constituents(self) -> pd.DataFrame:
        """获取沪深300成分股。"""
        self._login()
        rs = bs.query_hs300_stocks()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return pd.DataFrame(columns=["ticker", "in_date", "out_date"])

        df = pd.DataFrame(rows, columns=["date", "ticker_bs", "name"])
        result = pd.DataFrame()
        result["ticker"] = df["ticker_bs"].apply(_from_bs_code)
        result["in_date"] = pd.to_datetime(df["date"]).dt.date
        result["out_date"] = None
        return result

    def __del__(self):
        self._logout()
