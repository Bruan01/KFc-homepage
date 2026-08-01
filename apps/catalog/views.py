"""Public product, subscription and notification views."""
from __future__ import annotations

from django.db.models import Count, Q
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import UserSubscription
from apps.accounts.services import now_iso
from apps.core.permissions import get_admin_context, require_user
from apps.core.responses import json_error, json_ok
from apps.downloads.models import Download, DownloadRequest
from apps.points.services import account_payload, active_entitlement, product_download_cost
from .models import Product


def package_payload(package, slug, *, detail=False):
    data = {
        "id": package.pk,
        "platform": package.platform or "",
        "architecture": package.architecture or "",
        "file_name": package.file_name,
        "file_size": package.file_size,
    }
    if detail:
        data.update({
            "file_sha256": package.file_sha256,
            "download_url": f"/download/{slug}?pkg={package.pk}",
        })
    return data


def product_payload(product):
    return {
        "id": product.pk,
        "slug": product.slug,
        "name": product.name,
        "summary": product.summary,
        "description": product.description,
        "category": product.category,
        "platforms": [],
        "architectures": [],
        "tags": product.tags,
        "announcement": product.announcement,
        "version": product.version,
        "changelog": product.changelog,
        "status": product.status,
        "created_by": product.created_by,
        "file_name": product.file_name,
        "file_path": product.file_path,
        "file_size": product.file_size,
        "file_sha256": product.file_sha256,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "published_at": product.published_at,
        "download_count": int(getattr(product, "download_count", 0) or 0),
        "download_url": f"/download/{product.slug}",
        "packages": [],
    }


@require_GET
def products(request):
    queryset = Product.objects.filter(status="published").annotate(download_count=Count("downloads")).prefetch_related("packages")
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    version = request.GET.get("version", "").strip()
    tags = [item.strip() for item in request.GET.get("tags", "").split(",") if item.strip()]
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(summary__icontains=search) | Q(description__icontains=search)
            | Q(category__icontains=search) | Q(tags__icontains=search)
        )
    if category:
        queryset = queryset.filter(category=category)
    if version:
        queryset = queryset.filter(version=version)
    for tag in tags:
        queryset = queryset.filter(tags__icontains=tag)
    sort = request.GET.get("sort", "latest")
    order = {
        "downloads": ("-download_count",),
        "name": ("name",),
        "version": ("-version",),
    }.get(sort, ("-published_at", "-updated_at"))
    queryset = queryset.order_by(*order)

    items = []
    for product in queryset:
        item = product_payload(product)
        packages = [package_payload(pkg, product.slug) for pkg in product.packages.all().order_by("sort_order", "id")]
        item["packages"] = packages
        item["platforms"] = sorted({pkg["platform"] for pkg in packages if pkg["platform"]})
        item["architectures"] = sorted({pkg["architecture"] for pkg in packages if pkg["architecture"]})
        items.append(item)
    return json_ok({"items": items})


@require_GET
def products_meta(request):
    categories = set()
    tags = set()
    for category, raw_tags in Product.objects.filter(status="published").values_list("category", "tags"):
        if (category or "").strip():
            categories.add(category.strip())
        tags.update(item.strip() for item in (raw_tags or "").split(",") if item.strip())
    return json_ok({"categories": sorted(categories), "tags": sorted(tags)})


@require_GET
def product_detail(request, key):
    lookup = {"pk": int(key)} if key.isdigit() else {"slug": key}
    product = Product.objects.filter(status="published", **lookup).annotate(download_count=Count("downloads")).first()
    if not product:
        return json_error("not found", status=404)
    out = product_payload(product)
    out["packages"] = [package_payload(pkg, product.slug, detail=True) for pkg in product.packages.all().order_by("sort_order", "id")]
    out.update({
        "requires_login": True,
        "can_download_now": False,
        "download_rule": "one-time-per-user",
        "user_download_state": {
            "loggedIn": request.user.is_authenticated,
            "is_admin": False,
            "has_downloaded": False,
            "has_approved_request": False,
            "pending_request": False,
        },
    })
    admin = get_admin_context(request)
    if admin:
        out["requires_login"] = False
        out["can_download_now"] = bool(product.file_path)
        out["download_rule"] = "admin-unlimited"
        out["user_download_state"] = {
            "loggedIn": True,
            "is_admin": True,
            "username": admin["username"],
            "admin_level": admin["admin_level"],
            "has_downloaded": False,
            "has_approved_request": False,
            "pending_request": False,
        }
    elif request.user.is_authenticated:
        has_downloaded = Download.objects.filter(product=product, user=request.user).exists()
        approved = DownloadRequest.objects.filter(
            product=product, user=request.user, status="approved", consumed_at__isnull=True
        ).order_by("-id").first()
        pending = DownloadRequest.objects.filter(product=product, user=request.user, status="pending").exists()
        entitlement = active_entitlement(request.user, product)
        cost = product_download_cost(product)
        points = account_payload(request.user)
        out["can_download_now"] = not has_downloaded or approved is not None or entitlement is not None
        out["user_download_state"] = {
            "loggedIn": True,
            "is_admin": False,
            "has_downloaded": has_downloaded,
            "has_approved_request": approved is not None,
            "has_point_entitlement": entitlement is not None,
            "pending_request": pending,
            "points_balance": points["balance"],
            "point_download_cost": cost,
            "points_redemption_enabled": cost is not None,
        }
    return json_ok(out)


@require_POST
def subscribe(request):
    if not request.user.is_authenticated:
        if get_admin_context(request):
            return json_ok({"ok": True, "message": "admin session, no subscribe needed"})
        return json_error("user login required", status=401)
    _, created = UserSubscription.objects.get_or_create(user=request.user, defaults={"created_at": now_iso()})
    return json_ok({"ok": True} if created else {"ok": True, "message": "already subscribed"})


@require_user
@require_GET
def notifications(request):
    if not UserSubscription.objects.filter(user=request.user).exists():
        return json_ok({"subscribed": False, "items": []})
    rows = Product.objects.filter(status="published").exclude(announcement__exact="").order_by("-published_at", "-updated_at")[:20]
    return json_ok({"subscribed": True, "items": [
        {
            "product_id": row.pk,
            "product_name": row.name,
            "product_slug": row.slug,
            "version": row.version,
            "announcement": row.announcement,
            "published_at": row.published_at or row.updated_at,
        }
        for row in rows
    ]})
