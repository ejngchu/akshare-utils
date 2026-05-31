# feishu-ledger

基于 [AKShare](https://akshare.akfamily.xyz/) 的持仓工具脚本，可自动获取 A 股、港股、ETF、开放式基金的多品种行情/净值数据。

## 安装

```bash
pip install akshare pandas pytest
lark-cli auth login --domain base   # 首次需授权飞书访问
```

## 命令

### 行情查询

```bash
# watchlist - hardcoded 持仓列表，直接输出到终端
python skill/scripts/watchlist.py

# crawler - JSON I/O，支持 --codes 或 stdin
python skill/scripts/crawler.py --codes '["sz000333","hk00700","015600"]'
echo '["sz000333","hk00700"]' | python skill/scripts/crawler.py
```

### 飞书同步

```bash
python skill/scripts/feishu_sync.py               # 增量更新（只更新日期早于今天的记录）
python skill/scripts/feishu_sync.py --dry-run    # 预览模式（不实际写入）
python skill/scripts/feishu_sync.py --force       # 强制更新所有记录
python skill/scripts/feishu_sync.py --rate-limit 1.5  # 自定义写入间隔（默认 0.8s）
python skill/scripts/feishu_sync.py --on-error abort   # 遇错立即终止（默认 skip 继续）
python skill/scripts/feishu_sync.py --quiet      # 静默模式
python skill/scripts/feishu_sync.py --verify     # 校验飞书字段 ID 与代码配置是否一致

# 配置初始化（首次运行或字段 ID 不同步时）
python skill/scripts/feishu_config.py [--dry-run]
```

### 测试

```bash
PYTHONPATH=skill/scripts pytest tests/ -v
PYTHONPATH=skill/scripts pytest tests/test_watchlist.py::TestClassifyCode -v  # 单个测试类
```

## 支持品种

| 品种 | 来源 | 示例代码 |
|------|------|---------|
| A 股股票 | 腾讯行情 → AKShare Sina | sz000333, sh600887 |
| 港股 | 腾讯行情 → AKShare Sina | hk00700, hk01810 |
| ETF | 腾讯行情 → AKShare Sina | sh512040, sz159201 |
| LOF / 开放式基金 | 东方财富全市场 → 逐只查询 | 015600, 519915 |

## 代码前缀规则

| 前缀 | 品种 |
|------|------|
| `sh` / `sz` + 6位数字（在 A 股代码范围内） | A 股股票 |
| `sh` / `sz` + 6位数字（在 A 股代码范围外） | ETF |
| `hk` + 5位数字 | 港股 |
| 无前缀，6位数字 | LOF / 开放式基金 |

A 股代码范围：
- 深圳：`000xxx`, `001xxx`, `002xxx`, `003xxx`, `300xxx`, `301xxx`
- 上海：`600xxx`, `601xxx`, `603xxx`, `605xxx`, `688xxx`

## feishu_sync.py 执行流程

```
Step 1: 读取自选表（Watchlist）全部记录
Step 2: 过滤需要更新的记录（date < today 或 --force）
Step 3: 爬取最新价与涨幅
Step 4: 写入自选表（最新价、涨幅、更新日期）
Step 5: 读取持仓表（Holdings）全部记录
Step 6: 合并自选表最新价 → 计算市值、持有收益、持有收益率
Step 7: 写入持仓表（市值、持有收益、持有收益率）
Step 8: 读取现金表，汇总各账户余额
```

**持仓表计算公式**：
- 市值 = 最新价 × 总份额
- 持有收益 = 市值 - 总成本
- 持有收益率 = 持有收益 / 总成本 × 100%

## 架构

```
skill/scripts/
├── watchlist.py          # 数据获取核心
│     ├── classify_code()     → stock_a / hk_stock / etf / fund
│     ├── strip_prefix()      → 去掉 sz/sh/hk 前缀
│     ├── to_float()          → 安全转 float（处理 %、空格、NaN）
│     ├── fetch_*_data()     → 按品种抓取（Tencent → AKShare 故障转移）
│     ├── query_*()          → 按品种匹配到 HoldingItem
│     ├── HoldingItem          → dataclass（含 price/change_pct/date/extra）
│     ├── retry()             → 指数退避重试（3 次）
│     ├── with_timeout()      → 跨平台超时装饰器（基于线程，30s）
│     └── Logger              → 时间戳日志
│
├── crawler.py            # JSON I/O 封装
│     └── crawl(codes) → [{code, name, matched, price, change_pct, date}]
│
├── feishu_base.py        # 飞书基础设施
│     └── LarkClient          # lark-cli 封装
│           ├── _run_lark()       → subprocess 调用 + 429 重试
│           ├── _decode_output()  → UTF-8/GBK 自动识别
│           ├── get_records()     → 通用分页读取
│           ├── upsert_record()   → 通用单条写入
│           ├── upsert_batch()    → 批量写入（500 条/批）
│           └── verify_fields()   → 校验字段 ID 是否匹配
│     ├── setup_signal_handlers() → SIGTERM/SIGINT 优雅退出
│     └── add_common_args()      → 共享参数 (--dry-run/--force/--rate-limit 等)
│
├── feishu_sync.py        # 同步主流程（8 步）
│
└── feishu_config.py      # 配置管理
      # ~/.config/feishu-ledger/config.json    - base_token, table/field ID
      # ~/.cache/feishu-ledger/price_cache.json - 价格缓存
      # skill/assets/config.json                - upsert_delay 调优

tests/                     # pytest 测试套件
```

## 数据源与故障转移

| 品种 | 主数据源 | 故障转移 |
|------|---------|---------|
| A 股 / 港股 / ETF | 腾讯行情 `qt.gtimg.cn`（批量请求） | AKShare Sina |
| 开放式基金 | 东方财富全市场 `fund_open_fund_daily_em()` | 逐只查询 `fund_open_fund_info_em()` |

**注意**：`fund_open_fund_daily_em()` 返回的列名是动态的（如 `2026-05-29-单位净值`），需要运行时解析。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_BASE_TOKEN` | `FlZObdBVNawsG0s9GhHch2xDnAc` | 飞书 Base token |
| `FEISHU_WATCHLIST_TABLE_ID` | `tblIP0LuVvZFMjZD` | 自选表 |
| `FEISHU_HOLDINGS_TABLE_ID` | `tblIqUClte8harRW` | 持仓表 |
| `FEISHU_TRADE_TABLE_ID` | `tblkzlJG97qsMFfK` | 交易表 |
| `FEISHU_CASH_TABLE_ID` | - | 现金表 |
| `FEISHU_UPSERT_DELAY` | `0.8` | 写入间隔（秒） |

## 性能优化（待实施）

详见 `doc/todo.md`。当前主要瓶颈：

| 优化项 | 预期收益 |
|--------|---------|
| `fund_open_fund_rank_em` 替代 `fund_open_fund_daily_em` | ~21s → ~5s |
| 四类品种 threading 并行抓取 | ~27s → ~6s |
