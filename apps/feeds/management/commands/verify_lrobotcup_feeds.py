# pyright: reportMissingImports=false
# -*- coding: utf-8 -*-
"""具身智能实时抓取链路自检：信源是否落地、是否成功抓取、条目是否入库、是否新鲜。

供 scripts/setup_lrobotcup_feeds.sh 在部署后调用，也可单独运行做巡检：
    python manage.py verify_lrobotcup_feeds
    python manage.py verify_lrobotcup_feeds --json
    python manage.py verify_lrobotcup_feeds --strict   # 不健康时退出码 1（适合 CI）

设计原则：
  - 只读，不写库、不触发抓取；
  - 逐项报告，单项失败不影响其它项输出；
  - 健康判据与前端「信源实时抓取 / 回退调研快照」的分界一致（成功抓取 + 有条目 + 2 小时内新鲜）。
"""
import json
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...models import FeedFetchRun, FeedItem, FeedSource

SLUG_PREFIX = "lrc-"
CATEGORY = "embodied-ai"
# seed_lrobotcup_sources 里 10 条信源有 1 条 api 类型被跳过，正常应落地 9 条。
EXPECTED_MIN_SOURCES = 9
FRESH_HOURS = 2


def collect_report():
    """返回 (report_dict, checks_dict)。checks 的每项为 bool。"""
    sources = FeedSource.objects.filter(slug__startswith=SLUG_PREFIX)
    total = sources.count()
    active = sources.filter(is_active=True).exclude(feed_url="").count()
    item_count = FeedItem.objects.filter(source__slug__startswith=SLUG_PREFIX).count()

    slugs = list(sources.values_list("slug", flat=True))
    runs_qs = FeedFetchRun.objects.filter(source_slug__in=slugs)
    success_runs = runs_qs.filter(status=FeedFetchRun.STATUS_SUCCESS).order_by("-finished_at")
    failed_runs = runs_qs.filter(status=FeedFetchRun.STATUS_FAILED).order_by("-started_at")
    last_success = success_runs.first()
    last_failed = failed_runs.first()
    last_success_at = last_success.finished_at if last_success else None
    fresh = bool(last_success_at and (timezone.now() - last_success_at) <= timedelta(hours=FRESH_HOURS))

    checks = {
        "sources_seeded": total >= EXPECTED_MIN_SOURCES,
        "sources_active": active >= EXPECTED_MIN_SOURCES,
        "has_success_fetch": success_runs.exists(),
        "items_ingested": item_count > 0,
        "fetch_fresh": fresh,
    }
    healthy = all(checks.values())
    report = {
        "healthy": healthy,
        "category": CATEGORY,
        "sources": {
            "total": total,
            "active_with_feed": active,
            "expected_min": EXPECTED_MIN_SOURCES,
        },
        "fetch": {
            "success_runs": success_runs.count(),
            "failed_runs": failed_runs.count(),
            "last_success_at": last_success_at.isoformat() if last_success_at else None,
            "last_failed_message": (last_failed.message[:160] if last_failed else None),
            "fresh_within_hours": FRESH_HOURS,
            "is_fresh": fresh,
        },
        "items": {"total": item_count},
        "checks": checks,
    }
    return report, checks


class Command(BaseCommand):
    help = "只读自检具身智能抓取链路（信源/抓取/入库/新鲜度），--strict 失败退出 1"

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于脚本解析）")
        parser.add_argument("--strict", action="store_true", help="任一检查不通过时退出码 1")

    def handle(self, *args, **options):
        report, checks = collect_report()
        if options["json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self._write_human(report, checks)
        if options["strict"] and not report["healthy"]:
            sys.exit(1)

    def _write_human(self, report, checks):
        s, f, items = report["sources"], report["fetch"], report["items"]
        ok = "OK" if report["healthy"] else "FAIL"
        style = self.style.SUCCESS if report["healthy"] else self.style.WARNING
        self.stdout.write(style(f"═══ 具身智能抓取链路自检：{ok} ═══"))
        self.stdout.write(f"  信源落地     : {s['total']} 条（其中可抓取 {s['active_with_feed']}，期望 ≥ {s['expected_min']}）  "
                          + self._mark(checks["sources_seeded"] and checks["sources_active"]))
        self.stdout.write(f"  成功抓取记录 : {f['success_runs']} 次 / 失败 {f['failed_runs']} 次  "
                          + self._mark(checks["has_success_fetch"]))
        self.stdout.write(f"  最近成功抓取 : {f['last_success_at'] or '无'}  "
                          + self._mark(checks["fetch_fresh"]))
        self.stdout.write(f"  入库条目     : {items['total']} 条  " + self._mark(checks["items_ingested"]))
        if not report["healthy"]:
            failed = [k for k, v in checks.items() if not v]
            self.stdout.write(self.style.WARNING(
                "  未通过项：" + ", ".join(failed)
                + "。请确认已运行 seed_lrobotcup_sources / seed_lrobotcup 并至少成功抓取一次。"))

    @staticmethod
    def _mark(passed):
        return "[通过]" if passed else "[未通过]"
