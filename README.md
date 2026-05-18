# akshare-utils

基于 [AKShare](https://akshare.akfamily.xyz/) 的持仓工具脚本，可自动获取 A 股、港股、ETF、开放式基金的多品种行情/净值数据。

## 功能

输入一个持仓列表（代码 + 名称），自动分类并批量拉取：

| 品种 | 来源 | 示例代码 |
|------|------|---------|
| A 股股票 | 新浪财经 `stock_zh_a_spot()` | sz000333, sh600887 |
| 港股 | 新浪财经 `stock_hk_spot()` | hk00700, hk01810 |
| ETF | 新浪财经 `fund_etf_category_sina()` | sh512040, sz159201 |
| LOF / 开放式基金 | 天天基金 `fund_open_fund_daily_em()` | 015600, 519915 |

## 快速开始

```bash
pip install akshare pandas
```

编辑 `watchlist.py` 中的 `RAW_WATCHLIST` 常量，填入你的持仓代码和名称（制表符分隔），然后运行：

```bash
python watchlist.py
```

### 持仓列表格式

```text
sz000333    美的集团
sh600887    伊利股份
hk00700     腾讯控股
sh512040    中证价值ETF
015600      创业板国泰(LOF)C
```

> **代码前缀规则**：A 股用 `sh`/`sz` 前缀，港股用 `hk` 前缀，ETF 用 `sh`/`sz` 前缀（与股票共用），LOF/开放式基金不用前缀。

## 输出示例

```text
      品种        代码        名称          最新价/净值    涨跌幅(%)    涨跌额   状态
      A股  sz000333      美的集团            82.4400       -0.16  -0.1300   OK
      A股  sz000651      格力电器            39.9200       -0.89  -0.3600   OK
      港股  hk00700       腾讯控股          451.0000       -1.18  -5.4000   OK
      ETF  sh512040     中证价值ETF           1.2340       -0.88  -0.0110   OK
      基金  015600  创业板国泰(LOF)C         2.1678       -0.51  -0.0110   OK
```

## 项目文件

- `watchlist.py` — 主脚本（含持仓列表定义、数据获取、匹配、输出）
- `README.md` — 本文件

## 依赖

- Python ≥ 3.8
- [AKShare](https://pypi.org/project/akshare/)
- pandas
