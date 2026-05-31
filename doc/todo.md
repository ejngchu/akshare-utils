# Feishu Ledger 性能优化方案

## 当前耗时分析

| 阶段 | 当前耗时 | 说明 |
|------|---------|------|
| A股+港股+ETF (腾讯批量 API) | ~5s | 3 次批量请求，腾讯接口速度快 |
| 基金全量 (`fund_open_fund_daily_em`) | **~21s** | **最大瓶颈** — 每次抓取全市场 ~23,333 只基金 |
| 内存过滤匹配 | <1s | 几乎可忽略 |
| 飞书写入 | ~0.8s × N 条 | 受 rate-limit 控制，不受数据抓取影响 |
| **合计** | **~27s+** | |

## 优化方案

### 1. 替换基金数据源（高优先级）

**问题**：`fund_open_fund_daily_em()` 每次抓取全市场 23,333 只基金，耗时 21s，且列名是动态的（如 `2026-05-29-单位净值`），需要运行时解析。

**方案**：改用 `fund_open_fund_rank_em(symbol='全部')`

| 对比项 | `fund_open_fund_daily_em` (当前) | `fund_open_fund_rank_em` (优化后) |
|--------|----------------------------------|----------------------------------|
| 耗时 | ~21s | ~4.9s |
| 数据量 | ~23,333 只 | ~19,626 只 |
| 列名 | **动态** (`2026-05-29-单位净值`) | **固定**: 基金代码/名称/单位净值/日增长率 等 |
| 字段 | 需动态解析列名 | 直接匹配，简单可靠 |

```python
# 优化后 fund 数据获取大致代码
df_rank = ak.fund_open_fund_rank_em(symbol='全部')
# df_rank 列名固定:
# ['序号','基金代码','基金简称','日期','单位净值','累计净值',
#  '日增长率','近1月','近3月','近6月','近1年','近2年','近3年',
#  '今年来','成立来','自定义','自定义']
# 直接按基金代码匹配，无需动态列名解析
```

**预期收益**：节省 ~16s/次

---

### 2. 四类品种并行抓取（中优先级）

**问题**：当前串行执行 `fetch_stock_a_data() → fetch_hk_stock_data() → fetch_etf_data() → fetch_open_fund_data()`，总时间 = 各段时间之和。

**方案**：使用 `threading` 或 `asyncio` 并行抓取，四类品种互不依赖。

```python
import concurrent.futures

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    futures = {
        executor.submit(fetch_stock_a_data): 'stock_a',
        executor.submit(fetch_hk_stock_data): 'hk_stock',
        executor.submit(fetch_etf_data): 'etf',
        executor.submit(fetch_open_fund_data): 'fund',
    }
    results = {}
    for future in concurrent.futures.as_completed(futures):
        cat = futures[future]
        results[cat] = future.result()
```

**预期收益**：
- 串行：~27s（腾讯~5s + 基金~21s + 其他~1s）
- 并行：~6s（最慢的是基金 ~5s + 主线程汇总 ~1s）

---

### 3. 价格缓存共享（低优先级）

**现状**：`feishu_config.py` 已有 `price_cache.json` 功能，但只在持仓表同步时用于补充价格。

**方案**：将价格缓存机制提升为共享基础设施，watchlist 和 feishu_sync 共用同一份缓存，减少重复爬取。

**适用场景**：用户只运行 watchlist 输出到终端时，不会更新缓存；下次运行 feishu_sync 时需重新爬取。

---

## 优化收益汇总

| 优化项 | 实施难度 | 节省时间 | 优化后总耗时 |
|--------|---------|---------|-------------|
| 替换基金数据源 | 低 | ~16s | ~11s |
| 并行抓取四类品种 | 中 | ~16s | ~6s |
| 价格缓存共享 | 低 | 视场景 | 视场景 |
| **合计** | | **~21s** | **~6s** |

---

## 自选表增减记录的自适应能力

**已具备，无需修改。**

代码逻辑（`feishu_sync.py`）：
1. `get_records()` 读取飞书当前所有记录 → 动态构建 code 列表
2. 过滤需要更新的记录（date < today 或 --force）
3. 爬取 → 写入

增减记录只影响 Step 1 的 record 数量，Step 2-8 完全透明。

---

## 待实施任务

- [ ] `fund_open_fund_rank_em` 替换 `fund_open_fund_daily_em`
- [ ] 四类品种 `threading` 并行抓取
- [ ] 验证 `fund_open_fund_rank_em` 返回的字段完整性（单位净值、日增长率是否足够）
- [ ] 评估是否需要缓存预热机制（watchlist 运行后自动更新缓存）
