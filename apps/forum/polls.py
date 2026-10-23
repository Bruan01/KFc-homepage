"""Account-bound single/multiple choice polls attached to topics."""
from django.db import transaction
from django.db.models import Count
from django.views.decorators.http import require_POST
from apps.core.http import read_json, InvalidJSON
from apps.core.responses import json_ok, json_error
from .models import ForumTopic, ForumPoll, ForumPollOption, ForumPollBallot


def validate(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("投票格式不正确")
    question, options, multiple = value.get("question", ""), value.get("options"), value.get("multiple", False)
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 200:
        raise ValueError("投票问题须为 1–200 字")
    if type(multiple) is not bool or not isinstance(options, list) or not 2 <= len(options) <= 10:
        raise ValueError("投票需设置 2–10 个选项")
    if any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 100 for v in options):
        raise ValueError("每个选项须为 1–100 字")
    options = [v.strip() for v in options]
    if len(set(options)) != len(options):
        raise ValueError("投票选项不能重复")
    return {"question": question.strip(), "options": options, "multiple": multiple}


def create(topic, value):
    if value:
        poll = ForumPoll.objects.create(topic=topic, question=value["question"], multiple=value["multiple"])
        ForumPollOption.objects.bulk_create([ForumPollOption(poll=poll, text=text, position=i) for i, text in enumerate(value["options"])])


def payload(topic_id, viewer):
    poll = ForumPoll.objects.filter(topic_id=topic_id).first()
    if not poll:
        return None
    ballots = poll.ballots.all()
    selected = set(ballots.filter(username=viewer).values_list("option_id", flat=True)) if viewer else set()
    counts = dict(ballots.values("option_id").annotate(n=Count("id")).values_list("option_id", "n"))
    return {"question": poll.question, "multiple": poll.multiple,
            "voters": ballots.values("username").distinct().count(), "voted": bool(selected),
            "options": [{"id": option.pk, "text": option.text, "votes": counts.get(option.pk, 0), "selected": option.pk in selected}
                        for option in poll.options.order_by("position", "id")]}


@require_POST
def vote(request, topic_id):
    if not request.user.is_authenticated:
        return json_error("请先登录后投票", status=401)
    try:
        ids = read_json(request).get("options")
    except InvalidJSON:
        return json_error("投票格式不正确")
    if not isinstance(ids, list) or not ids or len(ids) > 10 or any(type(v) is not int for v in ids) or len(set(ids)) != len(ids):
        return json_error("请选择有效的投票选项")
    with transaction.atomic():
        poll = ForumPoll.objects.select_for_update().filter(topic_id=topic_id, topic__status=ForumTopic.STATUS_OPEN).first()
        if not poll:
            return json_error("投票不存在或帖子已关闭", status=404)
        if not poll.multiple and len(ids) != 1:
            return json_error("这是一项单选投票")
        if poll.options.filter(pk__in=ids).count() != len(ids):
            return json_error("投票选项不存在")
        old = set(poll.ballots.filter(username=request.user.username).values_list("option_id", flat=True))
        if old and old != set(ids):
            return json_error("你已经投过票，不能重复投票或修改选择", status=409)
        if not old:
            ForumPollBallot.objects.bulk_create([ForumPollBallot(poll=poll, option_id=i, username=request.user.username) for i in ids])
    return json_ok({"poll": payload(topic_id, request.user.username)})
