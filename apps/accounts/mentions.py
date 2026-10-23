"""Resolve actual mentions from the author's followed, existing, unblocked users."""
import re
from django.db.models import Q
from .models import UserFollow

PATTERN = re.compile(r"(?<![\w@])@(?:\{([^{}\n]{1,150})\}|([\w-]{1,150}))(?![\w-])")


def names(content, *, markdown=False):
    if markdown:
        content = re.sub(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`", "", content)
    return {m.group(1) or m.group(2) for m in PATTERN.finditer(content or "")}


def resolve_many(entries):
    from apps.murmurs.models import MurmurBlock
    authors = {author for author, _ in entries}
    candidates = set().union(*(names(content) for _, content in entries)) if entries else set()
    result = {author: set() for author in authors}
    if not candidates:
        return result
    edges = list(UserFollow.objects.filter(follower__username__in=authors, following__username__in=candidates)
                 .values_list("follower__username", "following__username"))
    blocks = set(MurmurBlock.objects.filter(Q(username__in=authors, blocked_username__in=candidates) |
                                          Q(blocked_username__in=authors, username__in=candidates))
                 .values_list("username", "blocked_username"))
    for author, target in edges:
        if author != target and (author, target) not in blocks and (target, author) not in blocks:
            result[author].add(target)
    return result


def resolve(author, content, *, markdown=False):
    candidates = names(content, markdown=markdown)
    return sorted(candidates & resolve_many([(author, content)])[author])
