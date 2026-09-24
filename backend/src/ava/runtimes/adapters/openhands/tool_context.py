"""Opaque SDK spec references to AVA-owned run contexts, never model inputs."""

from threading import Lock
from uuid import uuid4

from ava.execution.tool_security import ToolRunContext

_contexts: dict[str, ToolRunContext] = {}
_lock = Lock()


def register_context(context: ToolRunContext) -> str:
    key = str(uuid4())
    with _lock:
        _contexts[key] = context
    return key


def get_context(key: str) -> ToolRunContext:
    with _lock:
        return _contexts[key]


def discard_context(key: str) -> None:
    with _lock:
        _contexts.pop(key, None)
