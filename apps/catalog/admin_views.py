from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.parse import unquote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import AdminAccount
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok
from apps.downloads.models import Download, DownloadEntitlement, DownloadRequest
from apps.points.models import PointLedger
from apps.publishing.models import ProductDeleteRequest, PublishRequest, PublishRequestVote
from .models import AdminUploadEvent, Product, ProductPackage, ProductVersion, SystemSetting
from .upload_limits import get_upload_limit_settings

PLATFORMS = ("Windows", "macOS", "Linux")
ARCHITECTURES = ("x64", "ARM64")
ALLOWED_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}


def now_iso():
    from django.utils import timezone
    return timezone.now().isoformat()


def slugify(value):
    out = []
    for ch in str(value or "").strip().lower():
        if ch.isalnum(): out.append(ch)
        elif ch in {" ", "-", "_"}: out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug: slug = slug.replace("--", "-")
    return slug or f"product-{int(time.time())}"


def choices(value, allowed, name):
    if isinstance(value, str): value = [x.strip() for x in value.split(",") if x.strip()]
    if value is None: value = []
    if not isinstance(value, list): raise ValueError(f"{name} must be an array")
    result = list(dict.fromkeys(str(x).strip() for x in value if str(x).strip()))
    invalid = [x for x in result if x not in allowed]
    if invalid: raise ValueError(f"invalid {name}: {', '.join(invalid)}")
    return json.dumps(result, ensure_ascii=False)


def decode(value):
    try: result = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError): result = []
    return result if isinstance(result, list) else []


def package_payload(row):
    return {"id": row.pk, "product_id": row.product_id, "platform": row.platform or "", "architecture": row.architecture or "", "file_name": row.file_name, "file_path": row.file_path, "file_size": row.file_size, "file_sha256": row.file_sha256, "sort_order": int(row.sort_order or 0), "created_at": row.created_at, "updated_at": row.updated_at}


def product_payload(row):
    return {"id": row.pk, "slug": row.slug, "name": row.name, "summary": row.summary, "description": row.description, "category": row.category, "platforms": decode(row.platforms), "architectures": decode(row.architectures), "tags": row.tags, "announcement": row.announcement, "version": row.version, "changelog": row.changelog, "status": row.status, "created_by": row.created_by, "file_name": row.file_name, "file_path": row.file_path, "file_size": row.file_size, "file_sha256": row.file_sha256, "created_at": row.created_at, "updated_at": row.updated_at, "published_at": row.published_at, "point_download_cost": row.point_download_cost, "points_redemption_enabled": bool(row.points_redemption_enabled), "download_count": int(getattr(row, "download_count", 0) or 0), "download_url": f"/download/{row.slug}", "packages": []}


def snapshot(product, created_by, source):
    return ProductVersion.objects.create(product=product, name=product.name, slug=product.slug, category=product.category, platforms=product.platforms, architectures=product.architectures, tags=product.tags, announcement=product.announcement, version=product.version, summary=product.summary, description=product.description, changelog=product.changelog, status=product.status, file_name=product.file_name, file_path=product.file_path, file_size=product.file_size, file_sha256=product.file_sha256, published_at=product.published_at, created_at=now_iso(), created_by=created_by, source=source)


@require_admin()
def products(request, product_id=None):
    if request.method == "GET":
        if product_id is not None:
            row = Product.objects.filter(pk=product_id).annotate(download_count=Count("downloads")).first()
            if not row: return json_error("not found", status=404)
            data = product_payload(row); data["packages"] = [package_payload(x) for x in row.packages.order_by("sort_order", "id")]
            return json_ok(data)
        query = Product.objects.annotate(download_count=Count("downloads"))
        q, status = request.GET.get("q", "").strip(), request.GET.get("status", "").strip()
        if q: query = query.filter(Q(name__icontains=q)|Q(slug__icontains=q)|Q(summary__icontains=q)|Q(tags__icontains=q)|Q(category__icontains=q))
        if status in {"draft", "published"}: query = query.filter(status=status)
        try: page=max(1,int(request.GET.get("page",1))); size=max(1,min(100,int(request.GET.get("page_size",20))))
        except ValueError: page,size=1,20
        total=query.count(); rows=query.order_by("-updated_at")[(page-1)*size:page*size]
        items=[]
        for row in rows:
            data=product_payload(row); data["packages"]=[package_payload(x) for x in row.packages.order_by("sort_order","id")]; items.append(data)
        return json_ok({"items":items,"total":total,"page":page,"page_size":size,"total_pages":max(1,(total+size-1)//size)})
    if request.method == "POST" and product_id is None:
        return create_product(request)
    if request.method == "PUT" and product_id is not None:
        return update_product(request, product_id)
    if request.method == "DELETE" and product_id is not None:
        return delete_product(request, product_id)
    from django.http import HttpResponseNotAllowed
    return HttpResponseNotAllowed(["GET","POST","PUT","DELETE"])


def create_product(request):
    try: body=read_json(request)
    except InvalidJSON: return json_error("invalid json")
    name=str(body.get("name") or "").strip()
    if not name: return json_error("name required")
    if Product.objects.filter(name__iexact=name).exists(): return json_error(f"产品名称“{name}”已存在，请修改名称或编辑已有产品。",status=409)
    try: platforms=choices(body.get("platforms",[]),PLATFORMS,"platforms"); architectures=choices(body.get("architectures",[]),ARCHITECTURES,"architectures")
    except ValueError as exc: return json_error(str(exc))
    level=request.kflow_admin["admin_level"]; status=str(body.get("status") or "draft"); review=status=="published" and level<3
    if status not in {"draft","published"} or review: status="draft"
    raw=body.get("point_download_cost")
    try: cost=None if raw in (None,"") else max(0,int(raw))
    except (TypeError,ValueError): return json_error("invalid point download cost")
    current=now_iso()
    try:
        row=Product.objects.create(slug=slugify(body.get("slug") or name),name=name,summary=str(body.get("summary") or "").strip(),description=str(body.get("description") or "").strip(),category=str(body.get("category") or "").strip(),platforms=platforms,architectures=architectures,tags=str(body.get("tags") or "").strip(),announcement=str(body.get("announcement") or "").strip(),version=str(body.get("version") or "0.1.0").strip(),changelog=str(body.get("changelog") or "").strip(),status=status,created_by=request.kflow_admin["username"],created_at=current,updated_at=current,published_at=current if status=="published" else None,point_download_cost=cost,points_redemption_enabled=1 if body.get("points_redemption_enabled",True) else 0)
    except IntegrityError: return json_error("产品链接标识已存在，请修改产品名称或 slug。",status=409)
    snapshot(row,request.kflow_admin["username"],"create"); data=product_payload(row); data["publish_requires_review"]=review
    return json_ok(data,status=201)


def update_product(request, product_id):
    try: body=read_json(request)
    except InvalidJSON: return json_error("bad request")
    row=Product.objects.filter(pk=product_id).first()
    if not row:return json_error("not found",status=404)
    admin=request.kflow_admin
    if admin["admin_level"]==1 and row.created_by!=admin["username"]:return json_error("lv1 can only edit own products",status=403)
    name=str(body.get("name",row.name)).strip()
    if not name:return json_error("name required")
    if Product.objects.filter(name__iexact=name).exclude(pk=row.pk).exists():return json_error(f"产品名称“{name}”已存在，请修改名称或编辑已有产品。",status=409)
    try:
        platforms=choices(body["platforms"],PLATFORMS,"platforms") if "platforms" in body else row.platforms
        architectures=choices(body["architectures"],ARCHITECTURES,"architectures") if "architectures" in body else row.architectures
    except ValueError as exc:return json_error(str(exc))
    snapshot(row,admin["username"],"before_update")
    status=str(body.get("status",row.status)); review=status=="published" and admin["admin_level"]<3 and row.status!="published"
    if status not in {"draft","published"}:status=row.status
    if review:status="draft"
    raw=body.get("point_download_cost",row.point_download_cost)
    try:cost=None if raw in (None,"") else max(0,int(raw))
    except (TypeError,ValueError):return json_error("invalid point download cost")
    for field,value in {"name":name,"slug":slugify(body.get("slug",row.slug)),"summary":str(body.get("summary",row.summary)).strip(),"description":str(body.get("description",row.description)).strip(),"category":str(body.get("category",row.category)).strip(),"platforms":platforms,"architectures":architectures,"tags":str(body.get("tags",row.tags)).strip(),"announcement":str(body.get("announcement",row.announcement)).strip(),"version":str(body.get("version",row.version)).strip(),"changelog":str(body.get("changelog",row.changelog)).strip(),"status":status,"point_download_cost":cost,"points_redemption_enabled":1 if body.get("points_redemption_enabled",bool(row.points_redemption_enabled)) else 0,"updated_at":now_iso()}.items():setattr(row,field,value)
    row.published_at=(row.published_at or now_iso()) if status=="published" else None
    try:row.save()
    except IntegrityError:return json_error("slug already exists",status=409)
    data=product_payload(row);data["publish_requires_review"]=review;return json_ok(data)


def delete_graph(product):
    files=[product.file_path]+list(product.packages.values_list("file_path",flat=True))
    PublishRequestVote.objects.filter(request__product=product).delete(); PublishRequest.objects.filter(product=product).delete(); ProductDeleteRequest.objects.filter(product=product).delete()
    DownloadRequest.objects.filter(product=product).delete(); Download.objects.filter(product=product).delete(); DownloadEntitlement.objects.filter(product=product).delete()
    ProductPackage.objects.filter(product=product).delete(); ProductVersion.objects.filter(product=product).delete(); AdminUploadEvent.objects.filter(product=product).delete(); product.delete()
    return [x for x in files if x]


def delete_product(request, product_id):
    row=Product.objects.filter(pk=product_id).first()
    if not row:return json_error("not found",status=404)
    admin=request.kflow_admin; owner=row.created_by or ""; owner_admin=AdminAccount.objects.filter(username=owner).first(); owner_level=3 if owner==settings.ADMIN_USERNAME else int(owner_admin.admin_level or 1) if owner_admin else 1
    if admin["admin_level"]<3 and owner_level>=3 and owner and owner!=admin["username"]:
        pending=ProductDeleteRequest.objects.filter(product=row,status="pending").first()
        if pending:return json_error("delete request already pending",status=409,request_id=pending.pk)
        req=ProductDeleteRequest.objects.create(product=row,product_name=row.name,product_slug=row.slug,requested_by=admin["username"],requester_level=admin["admin_level"],owner_username=owner,created_at=now_iso())
        return json_ok({"ok":True,"requires_owner_approval":True,"request_id":req.pk},status=202)
    with transaction.atomic():files=delete_graph(row)
    for rel in files:
        target=(settings.BASE_DIR/rel).resolve()
        try:
            target.relative_to(settings.BASE_DIR.resolve())
            target.unlink(missing_ok=True)
        except (ValueError,OSError):pass
    return json_ok()


@require_admin()
@require_GET
def versions(request, product_id):
    rows=ProductVersion.objects.filter(product_id=product_id).order_by("-id")[:300]
    return json_ok({"items":[{"id":x.pk,"product_id":x.product_id,"name":x.name,"slug":x.slug,"category":x.category,"platforms":decode(x.platforms),"architectures":decode(x.architectures),"version":x.version,"summary":x.summary,"description":x.description,"changelog":x.changelog,"status":x.status,"file_name":x.file_name,"file_path":x.file_path,"file_size":x.file_size,"file_sha256":x.file_sha256,"published_at":x.published_at,"created_at":x.created_at,"created_by":x.created_by,"source":x.source} for x in rows]})


@require_admin(level=2)
@require_POST
def rollback(request, version_id):
    snap=ProductVersion.objects.select_related("product").filter(pk=version_id).first()
    if not snap:return json_error("version not found",status=404)
    row=snap.product;snapshot(row,request.kflow_admin["username"],"before_rollback"); review=snap.status=="published" and request.kflow_admin["admin_level"]<3
    for field in ["name","slug","category","platforms","architectures","tags","announcement","version","summary","description","changelog","file_name","file_path","file_size","file_sha256"]:setattr(row,field,getattr(snap,field))
    row.status="draft" if review else snap.status;row.published_at=None if review else snap.published_at;row.updated_at=now_iso()
    try:row.save()
    except IntegrityError:return json_error("rollback conflicts with existing slug",status=409)
    data=product_payload(row);data["publish_requires_review"]=review;return json_ok(data)


@require_admin()
@require_GET
def packages(request, product_id):
    row=Product.objects.filter(pk=product_id).first()
    if not row:return json_error("product not found",status=404)
    return json_ok({"items":[package_payload(x) for x in row.packages.order_by("sort_order","id")],"product_id":row.pk,"product_created_by":row.created_by})


@require_admin()
def delete_package(request, package_id):
    if request.method!="DELETE":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["DELETE"])
    row=ProductPackage.objects.filter(pk=package_id).first()
    if not row:return json_error("package not found",status=404)
    rel=row.file_path;row.delete()
    if rel:
        target=(settings.BASE_DIR/rel).resolve()
        try:target.relative_to(settings.BASE_DIR.resolve());target.unlink(missing_ok=True)
        except (ValueError,OSError):pass
    return json_ok({"ok":True,"deleted_id":package_id})


@require_admin()
@require_POST
def direct_upload(request, product_id):
    row=Product.objects.filter(pk=product_id).first()
    if not row:return json_error("product not found",status=404)
    admin=request.kflow_admin
    if admin["admin_level"]==1 and row.created_by!=admin["username"]:return json_error("lv1 can only upload to own products",status=403)
    original=unquote(request.headers.get("X-Filename","").strip())
    if not original:return json_error("X-Filename header required")
    original="".join(ch for ch in original if ch.isalnum() or ch in {".","-","_"}).strip(".")
    ext=Path(original).suffix.lower();platform=request.headers.get("X-Platform","").strip();architecture=request.headers.get("X-Architecture","").strip()
    if ext not in ALLOWED_EXTENSIONS:return json_error(f"unsupported extension: {ext}")
    if platform not in PLATFORMS:return json_error(f"X-Platform required, must be one of: {', '.join(PLATFORMS)}")
    if architecture not in ARCHITECTURES:return json_error(f"X-Architecture required, must be one of: {', '.join(ARCHITECTURES)}")
    limit=get_upload_limit_settings()["limits"][f"lv{admin['admin_level']}"]["bytes"]
    try:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    if content_length > limit:
        return json_error(f"file too large for lv{admin['admin_level']}, max {limit//(1024*1024)}MB",status=413)
    target=settings.BASE_DIR/"uploads"/f"p{product_id}-{int(time.time())}-{secrets.token_hex(4)}{ext}"
    temporary=target.with_suffix(target.suffix+".part")
    digest=hashlib.sha256();total=0
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        with temporary.open("wb") as output:
            while block := request.read(1024 * 1024):
                total += len(block)
                if total > limit:
                    return json_error(f"file too large for lv{admin['admin_level']}, max {limit//(1024*1024)}MB",status=413)
                output.write(block);digest.update(block)
        if total == 0:
            return json_error("empty body")
        temporary.replace(target)
        rel=str(target.relative_to(settings.BASE_DIR)).replace("\\","/");snapshot(row,admin["username"],"before_upload");current=now_iso()
        with transaction.atomic():
            row.file_name=original;row.file_path=rel;row.file_size=total;row.file_sha256=digest.hexdigest();row.updated_at=current;row.save()
            max_sort=row.packages.order_by("-sort_order").values_list("sort_order",flat=True).first();ProductPackage.objects.create(product=row,platform=platform,architecture=architecture,file_name=original,file_path=rel,file_size=total,file_sha256=digest.hexdigest(),sort_order=(-1 if max_sort is None else max_sort)+1,created_at=current,updated_at=current)
            AdminUploadEvent.objects.update_or_create(admin_username=admin["username"],product=row,defaults={"uploaded_at":current,"file_size":total})
    except OSError:
        target.unlink(missing_ok=True)
        return json_error("failed to save upload",status=500)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    count=AdminUploadEvent.objects.filter(admin_username=admin["username"]).count();promoted=False
    if not admin["is_super"] and admin["admin_level"]==1 and count>=settings.LV1_AUTO_PROMOTE_PROJECT_COUNT:
        AdminAccount.objects.filter(username=admin["username"],admin_level__lt=2).update(admin_level=2);request.session["admin_level"]=2;promoted=True
    data=product_payload(row);data.update({"adminLevel":2 if promoted else admin["admin_level"],"uploadProjectCount":count,"autoPromoteTarget":settings.LV1_AUTO_PROMOTE_PROJECT_COUNT,"autoPromoted":promoted});return json_ok(data)


@require_admin()
def upload_settings(request):
    if request.method=="GET":return json_ok(get_upload_limit_settings())
    if request.method!="POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET","POST"])
    if request.kflow_admin["admin_level"]<3:return json_error("lv3 admin required",status=403)
    try:body=read_json(request);lv2=int(body.get("lv2_upload_limit_mb"));lv3=int(body.get("lv3_upload_limit_mb"))
    except (InvalidJSON,TypeError,ValueError):return json_error("valid upload limits required")
    if not 1<=lv2<=10240 or not 1<=lv3<=10240 or lv3<lv2:return json_error("invalid upload limits")
    current=now_iso()
    for key,value in [("lv2_upload_limit_mb",lv2),("lv3_upload_limit_mb",lv3)]:SystemSetting.objects.update_or_create(setting_key=key,defaults={"setting_value":str(value),"updated_at":current,"updated_by":request.kflow_admin["username"]})
    return json_ok({"ok":True,**get_upload_limit_settings()})
