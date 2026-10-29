"""Incremental manual acquisition with durable source-ID and per-quarter work ledgers."""
import hashlib
import json
from datetime import date

from .catalog import safe_image
from .identity import metadata_identity
from .models import Character, CharacterDiscovery, CharacterWorkScan, PersonalitySettings, timestamp

PAGE_SIZE = 20
MAX_SEARCH_PAGES = 10


def collect(parameters, *, fetch, delay, progress=None):
    settings = PersonalitySettings.objects.filter(pk=1).first() or PersonalitySettings()
    classic = parameters.get("mode") == "classic"
    today = date.today()
    cutoff = today.year - settings.recent_years
    work_limit = min(40, max(1, int(parameters.get("work_limit", 10))))
    character_limit = min(120, max(1, int(parameters.get("character_limit", 100))))
    selected = list(dict.fromkeys(parameters.get("subject_ids", [])[:10]))
    retry_errors = parameters.get("retry_errors") is True
    job_id = str(parameters.get("source_job_id", ""))[:40]
    scope = hashlib.sha256(json.dumps([today.year, (today.month-1)//3, classic, settings.recent_years,
        settings.min_work_collects, settings.min_character_collects, settings.per_work_limit]).encode()).hexdigest()
    counts = {"works": 0, "imported": 0, "existing": 0, "skipped": 0, "remembered": 0, "failed": 0, "works_seen": 0, "pages": 0, "errors": []}

    def emit():
        if progress:
            progress(counts)

    def error(message):
        counts["failed"] += 1
        if len(counts["errors"]) < 6:
            counts["errors"].append(message[:200])
        emit()

    def search_period(start, end):
        if end < start:
            return
        latest = today.isoformat() if end == today.year else f"{end}-12-31"
        seen_ids = set()
        for page in range(MAX_SEARCH_PAGES):
            result = fetch(f"search/subjects?limit={PAGE_SIZE}&offset={page*PAGE_SIZE}", {"keyword": "", "sort": "heat", "filter": {"type": [2], "air_date": [f">={start}-01-01", f"<={latest}"], "nsfw": False}})
            counts["pages"] += 1
            items = result.get("data") if isinstance(result, dict) else None
            if not isinstance(items, list):
                raise ValueError("Bangumi 作品列表格式无效")
            fresh = [item for item in items if isinstance(item, dict) and type(item.get("id")) is int and item["id"] not in seen_ids]
            if not fresh:
                return
            for item in fresh:
                seen_ids.add(item["id"])
                yield item
            delay(0.4)
            if len(items) < PAGE_SIZE:
                return

    def works():
        if selected:
            for pk in selected:
                yield fetch(f"subjects/{int(pk)}")
            return
        if retry_errors:
            failed_works = CharacterDiscovery.objects.filter(outcome__in=["error", "fetching"]).values_list("work_id", flat=True).distinct()[:work_limit]
            for pk in failed_works:
                yield fetch(f"subjects/{pk}")
        periods = [(1960, 1979), (1980, 1989), (1990, 1999), (2000, 2009), (2010, cutoff-1)] if classic else [(cutoff, today.year)]
        streams = [iter(search_period(start, end)) for start, end in periods if start <= end]
        while streams:
            remaining = []
            for stream in streams:
                try:
                    yield next(stream)
                    remaining.append(stream)
                except StopIteration:
                    pass
            streams = remaining

    seen_works, seen_roles = set(), set()
    for work in works():
        if not isinstance(work, dict) or type(work.get("id")) is not int or work["id"] in seen_works:
            continue
        work_id = work["id"]; seen_works.add(work_id)
        if not selected and not retry_errors and CharacterWorkScan.objects.filter(work_id=work_id, scope=scope).exists():
            counts["works_seen"] += 1
            emit()
            continue
        if work.get("nsfw") or work.get("type") != 2:
            continue
        collection = work.get("collection") or {}
        popularity = sum(v for v in collection.values() if type(v) is int) if isinstance(collection, dict) else 0
        try:
            work_year = int((work.get("date") or "")[:4])
        except (ValueError, TypeError):
            counts["skipped"] += 1
            continue
        if popularity < settings.min_work_collects or (classic and work_year >= cutoff) or (not classic and work_year < cutoff) or work["date"] > today.isoformat():
            counts["skipped"] += 1
            continue
        try:
            related = fetch(f"subjects/{work_id}/characters")
            if not isinstance(related, list):
                raise ValueError("Bangumi 角色列表格式无效")
        except ValueError as exc:
            error(str(exc))
            counts["works"] += 1
            if counts["works"] >= work_limit:
                break
            continue
        counts["works"] += 1
        accepted = 0
        exhausted = True
        for item in sorted([r for r in related if isinstance(r, dict)], key=lambda r: r.get("relation") != "主角"):
            if accepted >= settings.per_work_limit or counts["imported"] >= character_limit:
                exhausted = False
                break
            pk = item.get("id")
            if type(pk) is not int or pk <= 0 or pk in seen_roles or item.get("type") != 1:
                continue
            seen_roles.add(pk)
            existing = Character.objects.filter(source_id=pk).first()
            if existing:
                counts["existing"] += 1
                CharacterDiscovery.objects.get_or_create(source_id=pk, defaults={"work_id": work_id, "name": existing.name, "outcome": "imported", "reason": "角色已收录，跳过详情", "job_id": job_id})
                continue
            record, created = CharacterDiscovery.objects.get_or_create(source_id=pk, defaults={"work_id": work_id, "name": str(item.get("name") or "")[:150], "job_id": job_id})
            if not created:
                if retry_errors and record.outcome in {"error", "fetching"}:
                    if record.outcome == "fetching" and record.job_id != job_id:
                        from django.utils import timezone
                        from datetime import timedelta
                        if record.last_attempt_at >= (timezone.now()-timedelta(minutes=15)).isoformat():
                            counts["remembered"] += 1
                            continue
                    claimed = CharacterDiscovery.objects.filter(pk=record.pk, outcome=record.outcome, last_attempt_at=record.last_attempt_at).update(outcome="fetching", job_id=job_id, last_attempt_at=timestamp())
                    if not claimed:
                        counts["remembered"] += 1
                        continue
                else:
                    counts["remembered"] += 1
                    continue
            delay(0.4)
            try:
                detail = fetch(f"characters/{pk}")
                if not isinstance(detail, dict):
                    raise ValueError("Bangumi 角色详情格式无效")
            except ValueError as exc:
                CharacterDiscovery.objects.filter(pk=record.pk).update(outcome="error", reason=str(exc)[:300], last_attempt_at=timestamp())
                error(str(exc))
                continue
            stats = detail.get("stat") or {}
            collects = stats.get("collects", 0) if isinstance(stats, dict) else 0
            collects = collects if type(collects) is int else 0
            image = (detail.get("images") or {}).get("large", "")
            summary = detail.get("summary") or ""
            reason = ""
            if detail.get("nsfw"):
                reason = "角色不在采集范围"
            elif collects < settings.min_character_collects or (item.get("relation") != "主角" and collects < settings.min_character_collects*5):
                reason = "角色关注度低于筛选要求"
            elif not safe_image(image):
                reason = "缺少受支持的角色图片"
            elif not isinstance(summary, str) or len(summary) < 40:
                reason = "人物简介不足 40 字"
            elif not isinstance(detail.get("name"), str) or not detail["name"].strip():
                reason = "缺少角色姓名"
            if reason:
                CharacterDiscovery.objects.filter(pk=record.pk).update(outcome="filtered", reason=reason, last_attempt_at=timestamp())
                counts["skipped"] += 1
                emit()
                continue
            infobox = detail.get("infobox") or []
            name = next((e.get("value") for e in infobox if isinstance(e, dict) and e.get("key") == "简体中文名" and isinstance(e.get("value"), str)), "") or detail["name"]
            row, new = Character.objects.get_or_create(source_id=pk, defaults={"name": name[:150], "work_id": work_id, "work_name": str(work.get("name_cn") or work.get("name") or "")[:250],
                "work_year": work_year, "image_url": image, "source_text": summary[:20000], "source_url": f"https://bgm.tv/character/{pk}",
                "source_stats": {"collects": collects, "work_collects": popularity, "relation": item.get("relation", ""), "identity":metadata_identity(detail,work)}, "classic_candidate": classic})
            CharacterDiscovery.objects.filter(pk=record.pk).update(name=row.name, outcome="imported", reason="已加入初选列表", last_attempt_at=timestamp())
            if new:
                accepted += 1; counts["imported"] += 1
            else:
                counts["existing"] += 1
            emit()
        if exhausted:
            CharacterWorkScan.objects.get_or_create(work_id=work_id, scope=scope)
        emit()
        if counts["works"] >= work_limit or counts["imported"] >= character_limit:
            break
    return counts
