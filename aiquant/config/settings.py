from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """aiquant 全局配置，通过环境变量或 .env 文件加载。"""

    # 数据目录
    data_dir: Path = Path("./workspace")

    # 数据库路径
    duckdb_path: Path = Path("./workspace/aiquant.duckdb")
    sqlite_path: Path = Path("./workspace/aiquant.db")

    # 日志级别
    log_level: str = "INFO"

    # 无风险利率 (夏普比率)
    risk_free_rate: float = 0.025

    # 交易费用
    commission_rate: float = 0.00025      # 佣金费率 万2.5
    min_commission: float = 5.0           # 最低佣金 5元
    stamp_tax_rate: float = 0.001         # 印花税率 千1 (仅卖出)
    transfer_fee_rate: float = 0.00002    # 过户费率 万0.2
    dividend_tax_rate: float = 0.10       # 红利税率 10%

    model_config = {"env_prefix": "AIQUANT_", "env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
