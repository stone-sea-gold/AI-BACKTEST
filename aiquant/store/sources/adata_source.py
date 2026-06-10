"""AData 数据源适配器。"""

import time

import pandas as pd

from aiquant.config.logger import logger
from aiquant.store.sources.base import DataSource


def _to_bs_code(ticker: str) -> str:
    """纯数字代码转 BaoStock 格式。"""
    if ticker.startswith(("sh.", "sz.")):
        return ticker
    if ticker.startswith(("6", "9")):
        return f"sh.{ticker}"
    return f"sz.{ticker}"


class ADataSource(DataSource):
    """AData 数据源适配器。"""

    def download_daily(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        """下载日线数据，返回含真实收盘价和复权因子的 DataFrame。"""
        import adata

        # 下载不复权数据（真实价格）
        df_real = adata.stock.market.get_market(
            stock_code=ticker, start_date=start_date, end_date=end_date,
            k_type=1, adjust_type=0,
        )
        if df_real is None or df_real.empty:
            logger.warning(f"AData: {ticker} 无数据")
            return pd.DataFrame()

        # 下载前复权数据（用于计算复权因子）
        df_adj = adata.stock.market.get_market(
            stock_code=ticker, start_date=start_date, end_date=end_date,
            k_type=1, adjust_type=1,
        )

        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df_real["trade_date"]).dt.date
        result["open"] = df_real["open"].astype(float)
        result["high"] = df_real["high"].astype(float)
        result["low"] = df_real["low"].astype(float)
        result["close"] = df_real["close"].astype(float)
        result["volume"] = df_real["volume"].astype(float)
        result["amount"] = df_real["amount"].astype(float)

        # 换手率
        if "turnover_ratio" in df_real.columns:
            result["turnover_ratio"] = pd.to_numeric(df_real["turnover_ratio"], errors="coerce").fillna(0.0)
        else:
            result["turnover_ratio"] = 0.0

        # 复权因子 = 前复权收盘价 / 真实收盘价
        if df_adj is not None and not df_adj.empty:
            adj_close = df_adj["close"].astype(float)
            real_close = df_real["close"].astype(float)
            result["adj_factor"] = (adj_close / real_close).round(6)
        else:
            result["adj_factor"] = 1.0

        result["dividend_cash"] = 0.0
        result["ticker"] = ticker

        return result.reset_index(drop=True)

    def download_dividend(self, ticker: str, start_year: int, end_year: int) -> pd.DataFrame:
        """通过 BaoStock 下载分红数据。"""
        import baostock as bs

        bs_code = _to_bs_code(ticker)
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning(f"BaoStock 登录失败: {lg.error_msg}")
            return pd.DataFrame(columns=["date", "dividend_cash"])

        rows = []
        for year in range(start_year, end_year + 1):
            try:
                rs = bs.query_dividend_data(code=bs_code, year=str(year), yearType="report")
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
            except Exception:
                pass

        bs.logout()

        if not rows:
            return pd.DataFrame(columns=["date", "dividend_cash"])

        df = pd.DataFrame(rows, columns=[
            "code", "pre_notice_date", "agm_date", "plan_announce_date",
            "plan_date", "reg_date", "ex_dividend_date", "pay_date",
            "stock_market_date", "cash_before_tax", "cash_after_tax",
            "stock_per_share", "cash_stock", "reserve_to_stock",
        ])

        result = pd.DataFrame()
        result["date"] = pd.to_datetime(df["ex_dividend_date"], errors="coerce").dt.date
        result["dividend_cash"] = pd.to_numeric(df["cash_before_tax"], errors="coerce").fillna(0.0)

        # 过滤无效行（无除权日或分红为0）
        result = result.dropna(subset=["date"])
        result = result[result["dividend_cash"] > 0]

        return result.reset_index(drop=True)

    def get_all_tickers(self) -> list[str]:
        """获取全市场 A 股代码列表。"""
        import adata

        df = adata.stock.info.all_code()
        if df is None or df.empty:
            return []
        return df["stock_code"].tolist()

    def get_csi300_constituents(self) -> pd.DataFrame:
        """获取沪深300成分股（无历史调入调出日期，仅有当前列表）。"""
        import adata
        from datetime import date

        df = adata.stock.info.index_constituent(index_code="000300")
        if df is None or df.empty:
            return pd.DataFrame(columns=["ticker", "in_date", "out_date"])

        result = pd.DataFrame()
        result["ticker"] = df["stock_code"]
        result["in_date"] = date(2000, 1, 1)  # AData 不提供历史调入日期，使用默认值
        result["out_date"] = None
        return result

    def get_trade_calendar(self, year: int) -> pd.DataFrame:
        """获取交易日历。"""
        import adata

        df = adata.stock.info.trade_calendar(year=year)
        if df is None or df.empty:
            return pd.DataFrame(columns=["trade_date", "trade_status"])
        return df
