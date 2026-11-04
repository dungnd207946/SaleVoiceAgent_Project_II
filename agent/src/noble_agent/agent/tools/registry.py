"""ToolSpec registry — the single dispatch table for built-in + custom tools.

Built-in (standard) tools register under ``tenant="*"``. A tenant's custom
tools register under their own id and shadow a built-in of the same name for
that tenant only. The dispatcher resolves ``(tenant, name)`` → ``ToolSpec`` and
calls its executor; semcache reads ``read_only``; the dispatcher reads
``dirties_customer``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict
    executor: Callable[..., Awaitable[str]]
    dirties_customer: bool = False
    read_only: bool = True
    tenant: str = "*"


_REGISTRY: dict[tuple[str, str], ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    _REGISTRY[(spec.tenant, spec.name)] = spec


def tool(*, name, schema, tenant="*", dirties_customer=False, read_only=True):
    """Decorator: register the wrapped async executor as a ToolSpec."""

    def deco(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        register(
            ToolSpec(
                name=name,
                schema=schema,
                executor=fn,
                dirties_customer=dirties_customer,
                read_only=read_only,
                tenant=tenant,
            )
        )
        return fn

    return deco


def resolve(tenant: str, name: str) -> ToolSpec | None:
    return _REGISTRY.get((tenant, name)) or _REGISTRY.get(("*", name))


def registered_names(tenant: str) -> set[str]:
    return {n for (t, n) in _REGISTRY if t in ("*", tenant)}


def clear_tenant_for_tests(tenant: str) -> None:
    if tenant == "*":
        return
    for key in [k for k in _REGISTRY if k[0] == tenant]:
        del _REGISTRY[key]
