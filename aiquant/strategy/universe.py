"""标的池筛选规则。"""

from __future__ import annotations

from aiquant.config.logger import logger
from aiquant.store.duckdb_store import DuckDBStore
from aiquant.strategy.models import StockPool


def resolve_stock_pool(
    pool: StockPool,
    store: DuckDBStore,
    custom_tickers: list[str] | None = None,
    date: str | None = None,
) -> list[str]:
    """解析标的池，返回股票代码列表。"""

    if pool == StockPool.CSI300:
        tickers = store.get_csi300_tickers(date)
        if not tickers:
            logger.warning("沪深300成分股列表为空，请先运行 init-data")
        return tickers

    if pool == StockPool.CUSTOM:
        if not custom_tickers:
            raise ValueError("custom 标的池必须提供 custom_tickers")
        return custom_tickers

    if pool in (StockPool.CSI500, StockPool.ALL_A):
        raise NotImplementedError(f"标的池 {pool.value} 暂未实现，v2 版本将支持")

    raise ValueError(f"未知标的池类型: {pool}")
