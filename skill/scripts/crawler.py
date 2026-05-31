"""
爬取模块 - 从 AKShare 获取最新价（净值）与涨幅（日涨跌幅）

可独立 CLI 使用，也可被 feishu_sync.py 导入调用。

特性：
  - 支持内存缓存（基于 price_cache.json）
  - TTL 内直接返回缓存数据，减少不必要的网络请求
  - 缓存时间可配置（默认 2 分钟，见 assets/config.json 的 cache_ttl_seconds）

用法:
    echo '["sz000333","hk00700","015600"]' | python crawler.py
    python -c "import crawler; print(crawler.crawl(['sz000333','hk00700']))"
"""

import argparse
import io
import json
import sys
import time as _time

import watchlist
from feishu_config import (
    load_price_cache,
    save_price_cache,
    is_cache_valid,
    PRICE_CACHE_PATH,
)


def crawl(codes: list[str], quiet: bool = True, use_cache: bool = True) -> list[dict]:
    """
    爬取指定代码列表的最新价和涨幅。

    参数:
        codes: 代码列表，如 ["sz000333", "hk00700", "015600"]
        quiet: 是否抑制 watchlist 内部 print（默认 True）
        use_cache: 是否启用缓存（TTL 内直接返回缓存数据，默认 True）

    返回:
        [{code, matched, price, change_pct, name, date}, ...]
        其中 change_pct 已格式化为如 "-0.88%" 的字符串
    """
    if not codes:
        return []

    # 规范化输入
    codes = [c.strip() for c in codes if c.strip()]

    # 检查缓存（TTL 内直接返回缓存数据）
    if use_cache and is_cache_valid():
        cached = load_price_cache()
        cached_prices = cached.get("prices", {})
        results = []
        for raw_code in codes:
            if raw_code in cached_prices:
                entry = cached_prices[raw_code]
                results.append(entry)
            else:
                # 缓存中没有的代码，标记为未匹配
                results.append({
                    "code": raw_code,
                    "name": raw_code,
                    "matched": False,
                    "price": None,
                    "change_pct": None,
                    "date": None,
                })
        if results and any(r["matched"] for r in results):
            _log_cache_hit(len([r for r in results if r["matched"]]), len(codes))
        return results

    # 构建 HoldingItem 列表（用缓存名称，后续会被真实名称覆盖）
    items = []
    seen = set()
    for raw_code in codes:
        raw_code = raw_code.strip()
        if not raw_code or raw_code in seen:
            continue
        seen.add(raw_code)
        cat = watchlist.classify_code(raw_code)
        stripped = watchlist.strip_prefix(raw_code)
        items.append(watchlist.HoldingItem(
            raw_code=raw_code,
            name=raw_code,  # 临时，被匹配时会用真实名称
            category=cat,
            stripped=stripped,
        ))

    # 按类型分类
    stock_a_items = [it for it in items if it.category == "stock_a"]
    hk_items = [it for it in items if it.category == "hk_stock"]
    etf_items = [it for it in items if it.category == "etf"]
    fund_items = [it for it in items if it.category == "fund"]

    # 抑制 watchlist 内部 print，通过上下文管理器重定向 stdout → stderr
    _stdout = sys.stdout
    if quiet:
        sys.stdout = io.StringIO()  # 吃掉 watchlist 的 print

    try:
        if stock_a_items:
            try:
                df = watchlist.fetch_stock_a_data()
                watchlist.query_stock_a(items, df)
            except Exception as e:
                sys.stderr.write(f"  [WARN] A股数据获取失败: {e}\n")

        if hk_items:
            try:
                df = watchlist.fetch_hk_stock_data()
                watchlist.query_hk_stock(items, df)
            except Exception as e:
                sys.stderr.write(f"  [WARN] 港股数据获取失败: {e}\n")

        if etf_items:
            try:
                df = watchlist.fetch_etf_data()
                watchlist.query_etf(items, df)
            except Exception as e:
                sys.stderr.write(f"  [WARN] ETF数据获取失败: {e}\n")

        if fund_items:
            try:
                df = watchlist.fetch_open_fund_data()
                watchlist.query_fund(items, df)
            except Exception as e:
                sys.stderr.write(f"  [WARN] 基金数据获取失败: {e}\n")
    finally:
        if quiet:
            sys.stdout = _stdout

    # 组装结果
    results = []
    price_map = {}
    for it in items:
        price = watchlist.to_float(it.price)
        # 格式化涨幅为 "-0.88%" 格式
        change_raw = watchlist.to_float(it.change_pct)
        if change_raw is not None:
            change_pct = f"{change_raw:+.2f}%"
        else:
            change_pct = None

        result = {
            "code": it.raw_code,
            "name": it.name,
            "matched": it.matched,
            "price": price,
            "change_pct": change_pct,
            "date": it.date,
        }
        results.append(result)

        # 缓存价格数据
        if it.matched and price is not None:
            price_map[it.raw_code] = result

    # 写入缓存
    if use_cache and price_map:
        save_price_cache(price_map)

    return results


def _log_cache_hit(hit_count: int, total_count: int):
    """打印缓存命中日志"""
    msg = f"[CACHE] 命中 {hit_count}/{total_count} 条（TTL 内有效）"
    if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        print(f"[{_time.strftime('%H:%M:%S')}] [INFO] {msg}", file=sys.stderr)
    else:
        print(msg, file=sys.stderr)


def main():
    """CLI 入口：从 stdin 或 --codes 参数读取 JSON 数组，输出 JSON 到 stdout"""
    parser = argparse.ArgumentParser(description="爬取股票/ETF/基金数据")
    parser.add_argument("--codes", type=str, help='JSON 数组字符串，如 \'["sz000333","hk00700"]\'')
    args = parser.parse_args()

    try:
        if args.codes:
            codes = json.loads(args.codes)
        else:
            raw = sys.stdin.read()
            if not raw.strip():
                print(json.dumps([], ensure_ascii=False))
                return
            codes = json.loads(raw)

        if not isinstance(codes, list):
            print(json.dumps({"error": "输入必须是 JSON 数组"}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON 解析失败: {e}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    results = crawl(codes)
    print(json.dumps(results, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
