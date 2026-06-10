"""数据初始化脚本：一键下载沪深300成分股日线数据到 DuckDB。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from aiquant.config.logger import logger
from aiquant.store.duckdb_store import DuckDBStore
from aiquant.store.sources.adata_source import ADataSource


def init_data(
    years: int = 3,
    source: str = "adata",
    db_path: str | None = None,
) -> None:
    """一键初始化沪深300数据。

    Args:
        years: 下载几年的数据
        source: 数据源 ("adata" 或 "baostock")
        db_path: DuckDB 数据库路径
    """
    if source == "adata":
        ds = ADataSource()
    else:
        from aiquant.store.sources.baostock_source import BaoStockSource
        ds = BaoStockSource()

    store = DuckDBStore(db_path)

    end_date = date.today()
    start_date = end_date - timedelta(days=years * 365)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    logger.info(f"数据范围: {start_str} ~ {end_str}")

    # 1. 获取沪深300成分股
    logger.info("正在获取沪深300成分股列表...")
    csi300 = ds.get_csi300_constituents()
    if csi300.empty:
        logger.error("获取沪深300成分股失败")
        return

    store.write_csi300_constituents(csi300)
    tickers = csi300["ticker"].unique().tolist()
    logger.info(f"沪深300成分股: {len(tickers)} 只")

    # 2. 逐只下载日线数据（支持断点续传）
    success = 0
    failed = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("下载日线数据", total=len(tickers))

        for ticker in tickers:
            progress.update(task, description=f"下载 {ticker}")

            # 断点续传：检查本地最新日期
            latest = store.get_latest_date(ticker)
            dl_start = latest if latest else start_str

            try:
                df = ds.download_daily(ticker, dl_start, end_str)
                if not df.empty:
                    store.write_klines(df)
                    success += 1
                else:
                    logger.debug(f"{ticker}: 无新数据")
            except Exception as e:
                failed.append(ticker)
                logger.warning(f"{ticker} 下载失败: {e}")

            progress.advance(task)

    logger.info(f"日线数据完成: 成功 {success}/{len(tickers)}, 失败 {len(failed)}")
    if failed:
        logger.info(f"失败列表: {failed[:20]}{'...' if len(failed) > 20 else ''}")

    # 3. 下载分红数据（通过 BaoStock）
    logger.info("正在下载分红数据...")
    dividend_count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("下载分红数据", total=len(tickers))
        for ticker in tickers:
            progress.update(task, description=f"分红 {ticker}")
            try:
                div_df = ds.download_dividend(ticker, start_date.year, end_date.year)
                if not div_df.empty:
                    store.update_dividend(ticker, div_df)
                    dividend_count += 1
            except Exception as e:
                logger.debug(f"{ticker} 分红数据下载失败: {e}")
            progress.advance(task)

    logger.info(f"分红数据完成: {dividend_count} 只股票有分红记录")

    store.close()
