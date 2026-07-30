"""Small explicit route registry used by :class:`AppHandler`.

Routes are registered once at import time.  A route points at a real Python
callable (never a module/function name string), so IDE navigation and static
analysis keep working after the large ``if path == ...`` chain is removed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

PathMode = Literal["none", "path", "raw_path"]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: Callable
    path_mode: PathMode = "none"


_ROUTES: list[Route] = []


def route(method: str, pattern: str, *, path_mode: PathMode = "none"):
    """Register a callable for an HTTP method and a full-path regex.

    ``path_mode`` adapts legacy handlers while they are gradually simplified:
    ``path`` passes the parsed URL path, and ``raw_path`` passes
    ``handler.path`` including its query string.  Routes with capture groups
    receive those captures directly when no path mode is selected.
    """
    if path_mode not in {"none", "path", "raw_path"}:
        raise ValueError(f"unsupported route path mode: {path_mode}")
    compiled = re.compile(pattern)

    def decorator(func: Callable) -> Callable:
        _ROUTES.append(Route(method.upper(), compiled, func, path_mode))
        return func

    return decorator


def register(method: str, pattern: str, func: Callable, *, path_mode: PathMode = "none") -> Callable:
    """Register an existing domain handler without wrapping it in reflection."""
    return route(method, pattern, path_mode=path_mode)(func)


def resolve(method: str, path: str):
    """Return ``(route, match)`` for the first exact match, otherwise ``None``."""
    wanted = method.upper()
    for item in _ROUTES:
        if item.method != wanted:
            continue
        match = item.pattern.fullmatch(path)
        if match:
            return item, match
    return None


def dispatch(handler, method: str, path: str) -> bool:
    """Dispatch one request and report whether a route matched."""
    resolved = resolve(method, path)
    if resolved is None:
        return False
    item, match = resolved
    if item.path_mode == "path":
        item.handler(handler, path)
    elif item.path_mode == "raw_path":
        item.handler(handler, handler.path)
    else:
        named = match.groupdict()
        if named:
            item.handler(handler, **named)
        elif match.groups():
            item.handler(handler, *match.groups())
        else:
            item.handler(handler)
    return True


def registered_routes() -> tuple[Route, ...]:
    """Expose an immutable registry snapshot for diagnostics and tests."""
    return tuple(_ROUTES)
