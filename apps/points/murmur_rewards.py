"""One lifetime first-murmur reward, using the existing points ledger."""
from .models import PointAccount, PointLedger
from .services import apply_ledger, get_rules


def first_murmur_reward_status(user):
    from apps.murmurs.models import Murmur
    rules = get_rules()
    eligible = bool(user and not user.is_system_generated and rules['murmur_first_post_reward'] > 0)
    if eligible:
        eligible = not (Murmur.objects.filter(author_username=user.username).exists()
                        or PointLedger.objects.filter(idempotency_key=f'murmur_first_post:{user.pk}').exists()
                        or PointAccount.objects.filter(user=user).exclude(status='active').exists())
    return {'eligible': eligible, 'points': rules['murmur_first_post_reward'],
            'imaging_cost': rules['image_generation_default_cost'], 'imaging_url': '/imaging'}


def award_first_murmur(user, post):
    """Called inside the posting transaction, after reserving SQLite's writer."""
    from apps.murmurs.models import Murmur
    if not user or user.is_system_generated:
        return
    if Murmur.objects.filter(author_username=user.username).exclude(pk=post.pk).exists():
        return
    if PointAccount.objects.filter(user=user).exclude(status='active').exists():
        return
    amount = get_rules()['murmur_first_post_reward']
    if amount <= 0:
        return
    apply_ledger(user=user, event_type='murmur_first_post', points_delta=amount,
                 idempotency_key=f'murmur_first_post:{user.pk}', description='首次发布碎碎念奖励',
                 reference_type='murmur', reference_id=post.pk)


def first_murmur_receipt(user, post):
    if not user:
        return None
    row = PointLedger.objects.filter(user=user, idempotency_key=f'murmur_first_post:{user.pk}',
                                    reference_type='murmur', reference_id=str(post.pk)).first()
    if not row or row.delta <= 0:
        return None
    return {'points': row.delta, 'balance': row.balance_after, 'imaging_url': '/imaging',
            'imaging_cost': get_rules()['image_generation_default_cost']}
