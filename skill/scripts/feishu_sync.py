"""
飞书同步脚本 - 自选表 + 持仓表一体化更新

执行流程:
  Step 1: 读取自选表全部记录
  Step 2: 过滤需要更新的记录（date < today 或 --force）
  Step 3: 爬取最新价与涨幅，并更新价格缓存
  Step 4: 批量写入自选表 (最新价、涨幅、更新日期)
  Step 5: 读取持仓表全部记录
  Step 6: 合并缓存价格 → 计算市值、持有收益、持有收益率
  Step 7: 批量写入持仓表 (市值、持有收益、持有收益率)
  Step 8: 读取现金表，汇总各账户余额

用法:
    python feishu_sync.py --dry-run     # 预览
    python feishu_sync.py               # 正式执行
    python feishu_sync.py --force       # 强制更新所有记录
    python feishu_sync.py --rate-limit 1.5
    python feishu_sync.py --on-error abort
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

import crawler
from feishu_base import LarkClient, setup_signal_handlers, add_common_args, _interrupted
from feishu_config import (
    FEISHU_BASE_TOKEN,
    WATCHLIST_TABLE_ID,
    WATCHLIST_FIELD_IDS,
    HOLDINGS_TABLE_ID,
    HOLDINGS_FIELD_IDS,
    FEISHU_CASH_TABLE_ID,
    CASH_FIELD_IDS,
    UPSERT_DELAY,
    load_price_cache,
)


# ─────────────────────────────────────────────────────────────
# 1. 自选表同步 (Step 1-4)
# ─────────────────────────────────────────────────────────────

def sync_watchlist(
    client: LarkClient,
    dry_run: bool,
    force: bool,
    rate_limit: float,
    verbose: bool,
    on_error: str,
    today: str,
):
    """
    Step 1-4: 读取自选表 → 过滤 → 爬取 → 批量写入
    返回: (更新成功的代码列表, 代码→最新价映射)
    """
    # Step 1: 读取全部记录
    if verbose:
        print("\n[Step 1/7] 读取自选表记录...")
    records = client.get_records(WATCHLIST_TABLE_ID, WATCHLIST_FIELD_IDS)
    if verbose:
        print(f"  共读取 {len(records)} 条记录")

    if not records:
        print("  [WARN] 自选表为空，退出")
        return [], {}

    # Step 2: 过滤需要更新的记录
    codes = []
    records_to_update = []
    for r in records:
        code = r.get("代码", "")
        if not code:
            continue
        if not force and r.get("更新日期") and r.get("更新日期") >= today:
            continue
        codes.append(code)
        records_to_update.append(r)

    if verbose:
        mode = "强制" if force else "增量"
        print(f"\n[Step 2/7] 提取 {today} 之前未更新的代码（{mode}模式，{len(codes)}/{len(records)} 条需更新）")
        for c in codes[:5]:
            print(f"    {c}")
        if len(codes) > 5:
            print(f"    ... 共 {len(codes)} 个")

    if not codes:
        if verbose:
            print("  [INFO] 无需更新的记录")
        return [], {}

    # Step 3: 爬取数据
    if verbose:
        print(f"\n[Step 3/7] 爬取最新价与涨幅...")
    results = crawler.crawl(codes)
    code_to_result = {r["code"]: r for r in results}
    matched_count = sum(1 for r in results if r["matched"])
    if verbose:
        print(f"  成功获取: {matched_count}/{len(results)}")

    # Step 4: 批量写入自选表
    if verbose:
        print(f"\n[Step 4/7] {'预览更新' if dry_run else '批量写入'}（自选表）...")

    # 构建批量写入列表
    batch_records = []
    for record in records_to_update:
        code = record["代码"]
        result = code_to_result.get(code)

        if not result or not result["matched"]:
            if verbose:
                print(f"  [SKIP] {code}: 未匹配数据，跳过")
            continue

        price = result["price"]
        change_pct = result["change_pct"]
        date = result.get("date")

        fields = {}
        if price is not None:
            fields[WATCHLIST_FIELD_IDS["最新价"]] = price
        if change_pct is not None:
            fields[WATCHLIST_FIELD_IDS["涨幅"]] = change_pct
        if date:
            fields[WATCHLIST_FIELD_IDS["更新日期"]] = date

        batch_records.append({
            "record_id": record["_record_id"],
            "fields": fields,
        })

        if verbose:
            price_str = f"{price:.4f}" if price is not None else "N/A"
            change_str = change_pct or "N/A"
            date_str = date or "N/A"
            print(f"  -> {code:12s} 最新价={price_str:>10s}  涨幅={change_str:>8s}  日期={date_str:>10s}")

    if not batch_records:
        if verbose:
            print("  [INFO] 无有效数据可写入")
        return [], {}

    ok_count, fail_count = client.upsert_batch(
        WATCHLIST_TABLE_ID, batch_records, dry_run=dry_run, verbose=verbose
    )

    if verbose:
        action = "预览" if dry_run else "写入"
        print(f"\n  [STATS] 自选表: 需更新 {len(batch_records)} 条 | {action}成功 {ok_count} | 失败 {fail_count}")

    # 提取价格映射（用于持仓表）
    code_to_price = {}
    for r in results:
        if r["matched"] and r["price"] is not None:
            code_to_price[r["code"]] = r["price"]

    return codes, code_to_price


# ─────────────────────────────────────────────────────────────
# 2. 持仓表同步 (Step 5-7)
# ─────────────────────────────────────────────────────────────

def sync_holdings(
    client: LarkClient,
    code_to_price: dict,
    dry_run: bool,
    force: bool,
    rate_limit: float,
    verbose: bool,
    on_error: str,
    today: str,
):
    """
    Step 5-7: 读取持仓表 → 合并缓存价格 → 计算市值/收益 → 批量写入
    """
    # Step 5: 读取持仓表
    if verbose:
        print(f"\n[Step 5/7] 读取持仓表记录...")
    holdings_records = client.get_records(HOLDINGS_TABLE_ID, HOLDINGS_FIELD_IDS)
    if verbose:
        print(f"  共读取 {len(holdings_records)} 条持仓记录")

    if not holdings_records:
        print("  [WARN] 持仓表为空，跳过持仓同步")
        return

    # 补充价格：先查缓存
    cache = load_price_cache()
    cached_prices = cache.get("prices", {})
    for code, price in cached_prices.items():
        if code not in code_to_price:
            code_to_price[code] = price

    # Step 6: 过滤需要更新的记录并计算
    batch_records = []
    skipped = 0
    for rec in holdings_records:
        code = str(rec.get("代码", "")).strip()
        if not code:
            skipped += 1
            continue

        # 尝试多种 code 格式查价格
        price = code_to_price.get(code)
        if price is None:
            for prefix in ("sz", "sh", "hk"):
                price = code_to_price.get(f"{prefix}{code}")
                if price is not None:
                    break

        if price is None:
            if verbose:
                print(f"  [SKIP] {code}: 无最新价")
            skipped += 1
            continue

        shares = rec.get("总份额")
        cost = rec.get("总成本")
        shares = float(shares) if shares is not None else 0
        cost = float(cost) if cost is not None else 0

        if shares == 0 or cost == 0:
            if verbose:
                print(f"  [SKIP] {code}: 份额或成本为0")
            skipped += 1
            continue

        # 计算
        market_value = round(price * shares, 2)
        profit = round(market_value - cost, 2)
        profit_pct = round((profit / cost) * 100, 2)  # 存为 float，飞书格式化为 % 显示

        # Step 7: 检查是否需要更新
        needs_update = force
        if not needs_update:
            old_mv = rec.get("市值")
            old_profit = rec.get("持有收益")
            old_pct = rec.get("持有收益率")
            if old_mv is None or old_profit is None:
                needs_update = True
            else:
                try:
                    if (abs(market_value - float(old_mv)) > 0.01
                            or abs(profit - float(old_profit)) > 0.01):
                        needs_update = True
                except (ValueError, TypeError):
                    needs_update = True

        if not needs_update:
            skipped += 1
            continue

        batch_records.append({
            "record_id": rec["_record_id"],
            "fields": {
                HOLDINGS_FIELD_IDS["市值"]: market_value,
                HOLDINGS_FIELD_IDS["持有收益"]: profit,
                HOLDINGS_FIELD_IDS["持有收益率"]: profit_pct,
            },
        })

        if verbose:
            name = str(rec.get("名称", ""))[:8]
            print(f"  -> {code:12s} 名称={name:8s} "
                  f"最新价={price:>10} 市值={market_value:>12} "
                  f"持有收益={profit:>10} 收益率={profit_pct:>8.2f}%")

    if verbose:
        mode = "强制" if force else "增量"
        print(f"\n[Step 6/7] 过滤{mode}模式需更新的持仓记录: {len(batch_records)} 条（跳过 {skipped} 条）")

    if not batch_records:
        if verbose:
            print("  [INFO] 无需更新的持仓记录")
        return

    # Step 7: 批量写入
    if verbose:
        print(f"\n[Step 7/7] {'预览更新' if dry_run else '批量写入'}（持仓表）...")

    ok_count, fail_count = client.upsert_batch(
        HOLDINGS_TABLE_ID, batch_records, dry_run=dry_run, verbose=verbose
    )

    if verbose:
        action = "预览" if dry_run else "写入"
        print(f"\n  [STATS] 持仓表: 需更新 {len(batch_records)} 条 | {action}成功 {ok_count} | 失败 {fail_count}")


# ─────────────────────────────────────────────────────────────
# 3. 现金表同步 (Step 8)
# ─────────────────────────────────────────────────────────────

def sync_cash(client: LarkClient, dry_run: bool, verbose: bool):
    """
    Step 8: 读取现金表，汇总各账户余额并打印
    （现金表为只读数据源，无需写入）
    """
    if not FEISHU_CASH_TABLE_ID or not CASH_FIELD_IDS:
        if verbose:
            print("\n[Step 8/8] 现金表未配置，跳过")
        return

    if verbose:
        print(f"\n[Step 8/8] 读取现金表...")

    records = client.get_records(FEISHU_CASH_TABLE_ID, CASH_FIELD_IDS)
    if not records:
        if verbose:
            print("  [WARN] 现金表为空")
        return

    # 按账户类型 + 货币分组汇总
    from collections import defaultdict
    summary: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for rec in records:
        account_type = str(rec.get("账户类型") or "未知")
        currency = str(rec.get("货币") or "CNY")
        balance = float(rec.get("余额") or 0)
        summary[account_type][currency] += balance

    if verbose:
        print("  现金汇总:")
        for acct_type, currencies in sorted(summary.items()):
            for currency, total in sorted(currencies.items()):
                print(f"    {acct_type:12s} {currency:4s} {total:>15.2f}")


# ─────────────────────────────────────────────────────────────
# 4. 主同步逻辑
# ─────────────────────────────────────────────────────────────

def sync(
    dry_run: bool = False,
    force: bool = False,
    rate_limit: float = UPSERT_DELAY,
    verbose: bool = True,
    on_error: str = "skip",
):
    """
    主流程:
      Step 1-4: 自选表同步（读取 → 过滤 → 爬取 → 批量写入）
      Step 5-7: 持仓表同步（读取 → 合并价格 → 计算 → 批量写入）
      Step 8:    现金表读取与汇总
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if verbose:
        print("=" * 60)
        title = "[DRY-RUN] 预览模式（不执行写入）" if dry_run else "同步飞书数据"
        print(f"  {title}")
        if not force:
            print(f"  增量模式：只更新 {today} 之前未更新的记录")
        else:
            print(f"  强制模式：更新所有记录")
        print("=" * 60)

    client = LarkClient(FEISHU_BASE_TOKEN, rate_limit)

    # Step 1-4: 自选表同步
    updated_codes, code_to_price = sync_watchlist(
        client, dry_run, force, rate_limit, verbose, on_error, today
    )

    # 保存最新价格到缓存（crawler.crawl() 已自动写入，此处仅打印日志）
    if not dry_run and code_to_price and verbose:
        print(f"\n  [CACHE] 已更新 {len(code_to_price)} 条价格到缓存")

    # Step 5-7: 持仓表同步
    sync_holdings(
        client, code_to_price, dry_run, force, rate_limit, verbose, on_error, today
    )

    # Step 8: 现金表汇总
    sync_cash(client, dry_run, verbose)

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"  [OK] 同步完成")
        print(f"{'=' * 60}")


# ─────────────────────────────────────────────────────────────
# 5. CLI 入口
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="飞书同步工具 - 自选表 + 持仓表 + 现金表一体化更新",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python feishu_sync.py                         # 增量更新
  python feishu_sync.py --dry-run              # 预览模式
  python feishu_sync.py --force                # 强制更新所有记录
  python feishu_sync.py --verify               # 校验字段配置是否匹配
  python feishu_sync.py --rate-limit 1.5       # 自定义写入间隔 1.5s
  python feishu_sync.py --on-error abort        # 遇错立即终止
        """,
    )
    add_common_args(parser, UPSERT_DELAY)
    parser.add_argument(
        "--verify", action="store_true",
        help="仅校验飞书表格字段 ID 与代码配置是否一致，不执行同步"
    )
    args = parser.parse_args()

    setup_signal_handlers()

    if args.verify:
        client = LarkClient(FEISHU_BASE_TOKEN, UPSERT_DELAY)
        print("=" * 60)
        print("  校验飞书表格字段配置")
        print("=" * 60)
        ok1 = client.verify_fields(WATCHLIST_TABLE_ID, WATCHLIST_FIELD_IDS)
        ok2 = client.verify_fields(HOLDINGS_TABLE_ID, HOLDINGS_FIELD_IDS)
        ok3 = True
        if FEISHU_CASH_TABLE_ID and CASH_FIELD_IDS:
            ok3 = client.verify_fields(FEISHU_CASH_TABLE_ID, CASH_FIELD_IDS)
        print("\n" + "=" * 60)
        if ok1 and ok2 and ok3:
            print("  [OK] 字段配置校验通过")
        else:
            print("  [FAIL] 字段配置有 mismatch，请重新运行 feishu_config.py 同步")
        sys.exit(0 if (ok1 and ok2 and ok3) else 1)

    try:
        sync(
            dry_run=args.dry_run,
            force=args.force,
            rate_limit=args.rate_limit,
            verbose=not args.quiet,
            on_error=args.on_error,
        )
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户中断", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
