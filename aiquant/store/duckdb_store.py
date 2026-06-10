"""DuckDB 存储层。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from aiquant.config.logger import logger
from aiquant.config.settings import settings


class DuckDBStore:
    """DuckDB 行情/因子存储与查询。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or settings.duckdb_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_kline (
                ticker VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                amount DOUBLE,
                adj_factor DOUBLE,
                dividend_cash DOUBLE,
                turnover_ratio DOUBLE,
                PRIMARY KEY (ticker, date)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_info (
                ticker VARCHAR PRIMARY KEY,
                name VARCHAR,
                industry VARCHAR,
                list_date DATE,
                delist_date DATE
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS csi300_constituents (
                ticker VARCHAR,
                in_date DATE,
                out_date DATE,
                PRIMARY KEY (ticker, in_date)
            )
        """)

    def write_klines(self, df: pd.DataFrame):
        """写入日线数据（去重：主键冲突时覆盖）。"""
        if df.empty:
            return
        cols = ["ticker", "date", "open", "high", "low", "close", "volume", "amount", "adj_factor", "dividend_cash"]
        if "turnover_ratio" in df.columns:
            cols.append("turnover_ratio")
        df = df[cols].copy()
        if "turnover_ratio" not in df.columns:
            df["turnover_ratio"] = 0.0
        self.conn.execute("DELETE FROM daily_kline WHERE ticker = ? AND date BETWEEN ? AND ?",
                          [df["ticker"].iloc[0], df["date"].min(), df["date"].max()])
        self.conn.execute("INSERT INTO daily_kline SELECT * FROM df")

    def write_stock_info(self, df: pd.DataFrame):
        """写入股票基本信息。"""
        if df.empty:
            return
        tickers = df["ticker"].tolist()
        placeholders = ",".join(["?"] * len(tickers))
        self.conn.execute(f"DELETE FROM stock_info WHERE ticker IN ({placeholders})", tickers)
        self.conn.execute("INSERT INTO stock_info SELECT * FROM df")

    def write_csi300_constituents(self, df: pd.DataFrame):
        """写入沪深300成分股。"""
        if df.empty:
            return
        self.conn.execute("DELETE FROM csi300_constituents")
        self.conn.execute("INSERT INTO csi300_constituents SELECT * FROM df")

    def get_kline(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """查询单只股票日线（含前复权价）。"""
        return self.conn.execute("""
            SELECT *,
                close * adj_factor / MAX(adj_factor) OVER (PARTITION BY ticker) AS close_adj
            FROM daily_kline
            WHERE ticker = ? AND date BETWEEN ? AND ?
            ORDER BY date
        """, [ticker, start, end]).fetchdf()

    def get_batch_klines(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """批量查询多只股票日线（含前复权价）。"""
        if not tickers:
            return pd.DataFrame()
        placeholders = ",".join(["?"] * len(tickers))
        return self.conn.execute(f"""
            SELECT *,
                close * adj_factor / MAX(adj_factor) OVER (PARTITION BY ticker) AS close_adj
            FROM daily_kline
            WHERE ticker IN ({placeholders}) AND date BETWEEN ? AND ?
            ORDER BY ticker, date
        """, tickers + [start, end]).fetchdf()

    def get_latest_date(self, ticker: str) -> str | None:
        """获取某只股票本地最新日期。"""
        result = self.conn.execute(
            "SELECT MAX(date) FROM daily_kline WHERE ticker = ?", [ticker]
        ).fetchone()
        if result and result[0]:
            return str(result[0])
        return None

    def get_csi300_tickers(self, date: str | None = None) -> list[str]:
        """获取沪深300成分股列表。date=None 时返回所有有记录的成分股。"""
        if date:
            rows = self.conn.execute(
                "SELECT DISTINCT ticker FROM csi300_constituents WHERE in_date <= ? AND (out_date IS NULL OR out_date > ?)",
                [date, date]
            ).fetchdf()
        else:
            rows = self.conn.execute("SELECT DISTINCT ticker FROM csi300_constituents").fetchdf()
        return rows["ticker"].tolist() if not rows.empty else []

    def update_dividend(self, ticker: str, dividend_df: pd.DataFrame):
        """更新指定股票的分红数据（将 dividend_cash 写入对应日期的 kline 行）。"""
        if dividend_df.empty:
            return
        for _, row in dividend_df.iterrows():
            self.conn.execute(
                "UPDATE daily_kline SET dividend_cash = ? WHERE ticker = ? AND date = ?",
                [float(row["dividend_cash"]), ticker, row["date"]]
            )

    def get_trade_dates(self, start: str, end: str) -> list[str]:
        """从已存储的日线数据中提取交易日列表。"""
        rows = self.conn.execute(
            "SELECT DISTINCT date FROM daily_kline WHERE date BETWEEN ? AND ? ORDER BY date",
            [start, end]
        ).fetchdf()
        return [str(d) for d in rows["date"].tolist()] if not rows.empty else []

    def close(self):
        self.conn.close()
