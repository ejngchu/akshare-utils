"""
测试配置：预置 mock config，避免触发真实飞书 API 调用
"""
import json
import os
import sys
from pathlib import Path

# 预置 fake config，直接 patch 进 feishu_config 模块状态
FAKE_CONFIG = {
    "feishu_base_token": "test_token",
    "watchlist_table_id": "tblWATCHLIST",
    "holdings_table_id": "tblHOLDINGS",
    "trade_table_id": "tblTRADE",
    "cash_table_id": "tblCASH",
    "watchlist_field_ids": {
        "代码": "fldCode",
        "名称": "fldName",
        "最新价": "fldPrice",
        "涨幅": "fldPct",
        "产品类型": "fldType",
        "更新日期": "fldDate",
    },
    "holdings_field_ids": {
        "代码": "fldCode",
        "名称": "fldName",
        "产品类型": "fldType",
        "交易市场": "fldMkt",
        "组合名称": "fldPortfolio",
        "总成本": "fldCost",
        "总份额": "fldShares",
        "市值": "fldMv",
        "持有收益": "fldProfit",
        "持有收益率": "fldProfitPct",
        "年化收益率": "fldYYield",
    },
    "trade_field_ids": {
        "代码": "fldCode",
        "名称": "fldName",
        "方向": "fldDir",
        "交易日期": "fldDate",
        "成本": "fldCost",
        "金额": "fldAmt",
        "份额": "fldShares",
        "收益": "fldPnl",
        "收益率": "fldPct",
    },
    "cash_field_ids": {
        "账户": "fldAcct",
        "余额": "fldBal",
        "备注": "fldNote",
        "货币": "fldCcy",
        "账户类型": "fldAcctType",
    },
}

# 写入 fake config 文件（方便本地调试）
_config_dir = Path.home() / ".config" / "feishu-ledger"
_config_dir.mkdir(parents=True, exist_ok=True)
(_config_dir / "config.json").write_text(
    json.dumps(FAKE_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

# Patch feishu_config module state BEFORE any test code imports it
import feishu_config
feishu_config._cached_config = FAKE_CONFIG
feishu_config._cached_settings = {"upsert_delay": 0.8}
feishu_config._upsert_delay = 0.8

# 设置环境变量（防止直接运行初始化路径）
os.environ.setdefault("FEISHU_BASE_TOKEN", "test_token")
