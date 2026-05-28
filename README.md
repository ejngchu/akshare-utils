# akshare-utils

基于 [AKShare](https://akshare.akfamily.xyz/) 的持仓工具脚本，可自动获取 A 股、港股、ETF、开放式基金的多品种行情/净值数据。

## 功能总览

| 脚本 | 用途 |
|------|------|
| `watchlist.py` | 硬编码持仓列表，直接输出到终端 |
| `crawler.py` | **爬取模块** - 接收代码列表，返回 JSON 格式的最新价与涨幅 |
| `feishu_sync.py` | **飞书同步** - 自动更新自选表（Watchlist）和持仓表（Holdings） |
| `feishu_base.py` | 飞书操作共享基础设施（LarkClient） |
| `feishu_constants.py` | 共享常量（飞书 Base token、字段 ID 等） |

## 支持品种

| 品种 | 来源 | 示例代码 |
|------|------|---------|
| A 股股票 | 腾讯行情 → AKShare Sina | sz000333, sh600887 |
| 港股 | 腾讯行情 → AKShare Sina | hk00700, hk01810 |
| ETF | 腾讯行情 → AKShare Sina | sh512040, sz159201 |
| LOF / 开放式基金 | 东方财富全市场 → 逐只查询 | 015600, 519915 |

---

## 快速开始

### 方式一：watchlist.py（最简单）

编辑 `watchlist.py` 中的 `RAW_WATCHLIST` 常量，填入持仓代码和名称（制表符分隔）：

```bash
pip install -r requirements.txt
python watchlist.py
```

### 方式二：feishu_sync.py（推荐 - 自选表 + 持仓表一体化）

自动从飞书读取自选表代码 → 爬取最新价与涨幅 → 更新自选表 → 计算并更新持仓表市值与收益。

```bash
pip install -r requirements.txt
lark-cli auth login --domain base   # 首次需授权飞书访问
python feishu_sync.py --dry-run    # 预览
python feishu_sync.py              # 正式执行
```

### 方式三：crawler.py（独立爬取模块）

可作为 Python 模块导入或独立 CLI 使用：

```bash
echo '["sz000333","hk00700","015600"]' | python crawler.py
```

输出 JSON：
```json
[
  {"code": "sz000333", "name": "美的集团", "matched": true, "price": 82.83, "change_pct": "+0.32%", "date": "2026-05-28"},
  {"code": "hk00700", "name": "腾讯控股", "matched": true, "price": 449.2, "change_pct": "-1.58%", "date": "2026-05-28"}
]
```

---

## feishu_sync.py 详细用法

```bash
python feishu_sync.py               # 增量更新（只更新日期早于今天的记录）
python feishu_sync.py --dry-run    # 预览模式（不实际写入）
python feishu_sync.py --force       # 强制更新所有记录
python feishu_sync.py --rate-limit 1.5  # 自定义写入间隔（默认 0.8s）
python feishu_sync.py --on-error abort   # 遇错立即终止（默认 skip 继续）
python feishu_sync.py --quiet      # 静默模式
```

### 执行流程

```
Step 1: 读取自选表（Watchlist）全部记录
Step 2: 过滤需要更新的记录（date < today 或 --force）
Step 3: 爬取最新价与涨幅
Step 4: 写入自选表（最新价、涨幅、更新日期）
Step 5: 读取持仓表（Holdings）全部记录
Step 6: 合并自选表最新价 → 计算市值、持有收益、持有收益率
Step 7: 写入持仓表（市值、持有收益、持有收益率）
```

---

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

---

## 项目文件

| 文件 | 说明 |
|------|------|
| `watchlist.py` | 硬编码持仓列表，数据直接输出到终端 |
| `crawler.py` | 爬取模块，可 import 或 CLI 使用 |
| `feishu_base.py` | 飞书操作共享基础设施 |
| `feishu_sync.py` | 飞书自选表 + 持仓表一体化同步 |
| `feishu_constants.py` | 共享常量配置 |
| `requirements.txt` | Python 依赖 |
| `README.md` | 本文件 |

## 依赖

- Python ≥ 3.8
- [AKShare](https://pypi.org/project/akshare/)
- pandas
- pytest（仅测试需要）
- lark-cli（仅 feishu_sync.py 需要）

## 测试

```bash
pytest tests/ -v
```
