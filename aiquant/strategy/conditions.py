"""策略枚举定义。"""

from enum import Enum


class IndicatorType(str, Enum):
    """技术指标类型。"""
    MA = "MA"               # 简单移动平均线
    EMA = "EMA"             # 指数移动平均线
    MACD = "MACD"           # MACD
    RSI = "RSI"             # 相对强弱指数
    KDJ = "KDJ"             # KDJ
    BOLL = "BOLL"           # 布林带
    VOLUME = "VOLUME"       # 成交量
    AMOUNT = "AMOUNT"       # 成交额
    TURNOVER = "TURNOVER"   # 换手率
    PE = "PE"               # 市盈率
    PB = "PB"               # 市净率
    CLOSE = "CLOSE"         # 收盘价
    OPEN = "OPEN"           # 开盘价
    HIGH = "HIGH"           # 最高价
    LOW = "LOW"             # 最低价


class ComparatorType(str, Enum):
    """比较运算符。"""
    GT = ">"                # 大于
    LT = "<"                # 小于
    GTE = ">="              # 大于等于
    LTE = "<="              # 小于等于
    EQ = "=="               # 等于
    CROSS_ABOVE = "cross_above"   # 上穿
    CROSS_BELOW = "cross_below"   # 下穿
    BETWEEN = "between"           # 区间


class CombineType(str, Enum):
    """条件组合逻辑。"""
    AND = "and"
    OR = "or"
    NOT = "not"


class RankType(str, Enum):
    """横截面排名类型（v1 预留，v2 接入引擎）。"""
    RANK = "RANK"
    DENSE_RANK = "DENSE_RANK"
    PERCENT_RANK = "PERCENT_RANK"
    NTILE = "NTILE"


class CrossSectionIndicator(str, Enum):
    """横截面指标（v1 预留枚举，v2 对接引擎）。"""
    RANK_RSI = "RANK(RSI)"
    RANK_PE = "RANK(PE)"
    RANK_PB = "RANK(PB)"
    RANK_VOLUME = "RANK(VOLUME)"
    PERCENTILE_PE = "PERCENTILE(PE)"
    PERCENTILE_PB = "PERCENTILE(PB)"
    ZSCORE_VOLUME = "ZSCORE(VOLUME)"
