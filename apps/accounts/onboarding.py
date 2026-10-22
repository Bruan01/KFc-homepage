"""Once-per-account guide invitation; existing accounts are not enrolled."""
from django.db import transaction
from django.views.decorators.http import require_http_methods

from apps.core.http import InvalidJSON, read_json
from apps.core.permissions import require_user
from apps.core.responses import json_error, json_ok
from .models import GuideOnboarding
from .services import now_iso


def enroll_guide(user, *, visited=False):
    row, _ = GuideOnboarding.objects.get_or_create(
        user=user, defaults={"state": "visited" if visited else "pending", "updated_at": now_iso()})
    if visited and row.state != "visited":
        GuideOnboarding.objects.filter(pk=row.pk).update(state="visited", updated_at=now_iso())


@require_user
@require_http_methods(["GET", "POST"])
def guide_onboarding(request):
    claimed = False
    if request.method == "POST":
        try:
            body = read_json(request)
        except InvalidJSON:
            return json_error("invalid json")
        action = body.get("action")
        if not isinstance(action, str) or action not in {"shown", "dismissed", "visited"}:
            return json_error("invalid action")
        with transaction.atomic():
            rows = GuideOnboarding.objects.filter(user=request.user)
            if action == "visited":
                enroll_guide(request.user, visited=True)
            elif action == "shown":
                # A conditional claim prevents two tabs from inviting together.
                claimed = bool(rows.filter(state="pending").update(state="shown", updated_at=now_iso()))
            else:
                rows.filter(state__in=["pending", "shown"]).update(state="dismissed", updated_at=now_iso())
    state = GuideOnboarding.objects.filter(user=request.user).values_list("state", flat=True).first()
    response = json_ok({"state": state, "should_prompt": state == "pending", "claimed": claimed})
    response["Cache-Control"] = "no-store"
    return response
