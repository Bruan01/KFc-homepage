from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus

from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Case, When, IntegerField
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import AdminAccount
from apps.catalog.admin_views import delete_graph, product_payload
from apps.catalog.models import Product
from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_admin
from apps.core.responses import json_error, json_ok
from apps.downloads.models import DownloadRequest
from .models import ProductDeleteRequest, PublishRequest, PublishRequestVote


def now_iso(): return timezone.now().isoformat()
def weight(level): return 2 if int(level)>=3 else 1


def totals(row):
    values=row.votes.aggregate(
        approve=Sum(Case(When(vote="approve",then=Case(When(reviewer_level__gte=3,then=2),default=1)),default=0,output_field=IntegerField())),
        reject=Sum(Case(When(vote="reject",then=Case(When(reviewer_level__gte=3,then=2),default=1)),default=0,output_field=IntegerField())),
    )
    return int(values["approve"] or 0),int(values["reject"] or 0)


def finalize(row):
    if row.status!="pending" or not row.expires_at:return row
    try:expired=timezone.datetime.fromisoformat(row.expires_at)<=timezone.now()
    except (ValueError,TypeError):expired=False
    if not expired:return row
    agree,_=totals(row);count=row.votes.count();row.decided_at=now_iso()
    if count and agree>=int(row.approve_threshold_weight or 0):
        row.status="approved";row.decided_note="timeout: approved by weighted majority";Product.objects.filter(pk=row.product_id).update(status="published",published_at=row.product.published_at or now_iso(),updated_at=now_iso())
    else:
        row.status="rejected";row.decided_note="timeout: no votes" if not count else "timeout: weighted majority not reached"
    row.save(update_fields=["status","decided_at","decided_note"]);return row


@require_admin()
def publish_requests(request):
    if request.method=="POST":return create_request(request)
    if request.method!="GET":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET","POST"])
    admin=request.kflow_admin;query=PublishRequest.objects.select_related("product").order_by("-id")
    if admin["admin_level"]<=1 and not admin["is_super"]:query=query.filter(requested_by=admin["username"])
    items=[]
    for row in query[:300]:
        row=finalize(row);agree,reject=totals(row);my=row.votes.filter(reviewer_username=admin["username"]).first();required=2 if row.reviewer_scope=="lv2plus" else 3
        try:expired=bool(row.expires_at and timezone.datetime.fromisoformat(row.expires_at)<=timezone.now())
        except ValueError:expired=False
        items.append({"id":row.pk,"product_id":row.product_id,"product_name":row.product.name,"product_slug":row.product.slug,"requested_by":row.requested_by,"requester_level":row.requester_level,"reviewer_scope":row.reviewer_scope,"reviewer_pool_count":row.reviewer_pool_count,"reviewer_pool_weight":row.reviewer_pool_weight,"approve_threshold_weight":row.approve_threshold_weight,"status":row.status,"created_at":row.created_at,"expires_at":row.expires_at,"decided_at":row.decided_at,"agree_weight":agree,"reject_weight":reject,"my_vote":my.vote if my else None,"expired":expired,"can_vote":row.status=="pending" and row.requested_by!=admin["username"] and admin["admin_level"]>=required and not my and not expired})
    return json_ok({"items":items})


def create_request(request):
    try:body=read_json(request);product_id=int(body.get("product_id"))
    except (InvalidJSON,TypeError,ValueError):return json_error("product_id required")
    product=Product.objects.filter(pk=product_id).first()
    if not product:return json_error("product not found",status=404)
    if product.status=="published":return json_error("product already published",status=409)
    if not product.file_path:return json_error("product has no package file")
    admin=request.kflow_admin
    if admin["admin_level"]>=3:
        current=now_iso();product.status="published";product.published_at=product.published_at or current;product.updated_at=current;product.save(update_fields=["status","published_at","updated_at"]);data=product_payload(product);data["direct_published"]=True;return json_ok(data)
    if PublishRequest.objects.filter(product=product,status="pending").exists():return json_error("publish request already pending",status=409)
    min_level=2 if admin["admin_level"]<=1 else 3;scope="lv2plus" if min_level==2 else "lv3plus";reviewers=list(AdminAccount.objects.filter(admin_level__gte=min_level).exclude(username=admin["username"]));pool=sum(weight(x.admin_level) for x in reviewers)
    if not reviewers:return json_error("no eligible reviewers found",status=409)
    row=PublishRequest.objects.create(product=product,requested_by=admin["username"],requester_level=admin["admin_level"],reviewer_scope=scope,reviewer_pool_count=len(reviewers),reviewer_pool_weight=pool,approve_threshold_weight=pool//2+1,created_at=now_iso(),expires_at=(timezone.now()+timedelta(minutes=settings.PUBLISH_REVIEW_TIMEOUT_MINUTES)).isoformat())
    return json_ok({"ok":True,"request_id":row.pk})


@require_admin()
@require_POST
def vote(request,request_id):
    try:body=read_json(request)
    except InvalidJSON:return json_error("bad request")
    choice=str(body.get("vote") or "");note=str(body.get("note") or "")[:1000]
    if choice not in {"approve","reject"}:return json_error("vote must be 'approve' or 'reject'")
    with transaction.atomic():
        row=PublishRequest.objects.select_for_update().filter(pk=request_id).first()
        if not row:return json_error("request not found",status=404)
        if row.status!="pending":return json_error("request already decided",status=409)
        admin=request.kflow_admin
        if row.requested_by==admin["username"]:return json_error("cannot vote on own request",status=403)
        required=2 if row.reviewer_scope=="lv2plus" else 3
        if admin["admin_level"]<required:return json_error(f"lv{required}+ required to vote",status=403)
        if PublishRequestVote.objects.filter(request=row,reviewer_username=admin["username"]).exists():return json_error("already voted",status=409)
        PublishRequestVote.objects.create(request=row,reviewer_username=admin["username"],reviewer_level=admin["admin_level"],vote=choice,note=note,created_at=now_iso())
        agree,reject=totals(row);threshold=int(row.approve_threshold_weight or 0);possible=int(row.reviewer_pool_weight or 0)-reject
        if agree>=threshold:
            row.status="approved";row.decided_at=now_iso();row.decided_note=note;row.save(update_fields=["status","decided_at","decided_note"]);Product.objects.filter(pk=row.product_id).update(status="published",published_at=row.product.published_at or now_iso(),updated_at=now_iso())
        elif possible<threshold:
            row.status="rejected";row.decided_at=now_iso();row.decided_note=note;row.save(update_fields=["status","decided_at","decided_note"])
    return json_ok({"ok":True,"status":row.status,"agree_weight":agree,"reject_weight":reject,"threshold_weight":threshold})


@require_admin()
@require_GET
def inbox(request):
    admin=request.kflow_admin;downloads=[]
    if admin["admin_level"]>=2:
        downloads=[{"type":"download_request","id":x.pk,"username":x.user.username,"product_name":x.product.name,"product_slug":x.product.slug,"reason":x.reason,"created_at":x.created_at} for x in DownloadRequest.objects.filter(status="pending").select_related("user","product").order_by("-id")[:200]]
    publish=[]
    for row in PublishRequest.objects.filter(status="pending").select_related("product").order_by("-id")[:300]:
        row=finalize(row);required=2 if row.reviewer_scope=="lv2plus" else 3
        if row.status=="pending" and row.requested_by!=admin["username"] and admin["admin_level"]>=required and not row.votes.filter(reviewer_username=admin["username"]).exists():
            agree,_=totals(row);publish.append({"type":"publish_request","id":row.pk,"product_name":row.product.name,"product_slug":row.product.slug,"requested_by":row.requested_by,"reviewer_scope":row.reviewer_scope,"agree_weight":agree,"approve_threshold_weight":row.approve_threshold_weight,"expires_at":row.expires_at,"created_at":row.created_at})
    deletes=[{"type":"delete_request","id":x.pk,"product_id":x.product_id,"product_name":x.product_name,"product_slug":x.product_slug,"requested_by":x.requested_by,"requester_level":x.requester_level,"reason":x.reason,"created_at":x.created_at} for x in ProductDeleteRequest.objects.filter(status="pending",owner_username=admin["username"]).order_by("-id")[:200]]
    return json_ok({"download_requests":downloads,"publish_requests":publish,"delete_requests":deletes,"unread_count":len(downloads)+len(publish)+len(deletes)})


@require_admin()
@require_POST
def review_delete(request,request_id,decision):
    try:body=read_json(request)
    except InvalidJSON:body={}
    row=ProductDeleteRequest.objects.select_related("product").filter(pk=request_id).first()
    if not row:return json_error("request not found",status=404)
    if row.status!="pending":return json_error("request already reviewed",status=409)
    if row.owner_username!=request.kflow_admin["username"]:return json_error("only owner can review",status=403)
    files=[]
    with transaction.atomic():
        if decision=="approve":files=delete_graph(row.product)
        else:row.status="rejected";row.decided_at=now_iso();row.decided_by=request.kflow_admin["username"];row.decision_note=str(body.get("note") or "")[:1000];row.save()
    for rel in files:
        target=(settings.BASE_DIR/rel).resolve()
        try:target.relative_to(settings.BASE_DIR.resolve());target.unlink(missing_ok=True)
        except (ValueError,OSError):pass
    return json_ok({"ok":True,"status":"approved" if decision=="approve" else "rejected"})
