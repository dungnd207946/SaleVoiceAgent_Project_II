"""Khối trường đã điền của một dự án — đúng các trường khối tổng quan đưa cho agent."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import asyncpg

from portal.modules.kb.conflicts.facts import block_hash, field_hash
from portal.modules.kb.directive.verticals.real_estate import BUILDINGS, REAL_ESTATE

FIELD_MAX_CHARS = 3000
_OVERVIEW_LABEL = "Tổng quan"

_PROJECT = next(s for s in REAL_ESTATE.embed_sources if s.table == "projects")
_ZONE = _PROJECT.child_block
_CACH_LY = "tenant_id = portal.current_tenant()"


@dataclass(frozen=True)
class FieldValue:
    entity: str
    record_id: int
    field: str
    label: str
    value: str
    hash: str

    @property
    def ref(self) -> str:
        return f"field:{self.entity}.{self.record_id}.{self.field}"


def _text(
    value: object,
    *,
    value_labels: Mapping[str, str],
    formatter: Callable[[object], str] | None,
) -> str:
    if value is None:
        return ""
    if formatter is not None:
        value = formatter(value)
    if isinstance(value, list | tuple):
        return ", ".join(value_labels.get(str(v), str(v)) for v in value if str(v).strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return value_labels.get(text, text)


def _collect(
    row: asyncpg.Record,
    *,
    entity: str,
    fields: tuple[str, ...],
    labels: Mapping[str, str],
    value_labels: Mapping[str, Mapping[str, str]],
    formatters: Mapping[str, Callable[[object], str]],
    prefix: str,
) -> list[FieldValue]:
    out: list[FieldValue] = []
    for name in fields:
        value = _text(row[name], value_labels=value_labels.get(name, {}), formatter=formatters.get(name))
        if not value:
            continue
        value = value[:FIELD_MAX_CHARS]
        label = labels.get(name) or (_OVERVIEW_LABEL if name == "overview" else name)
        out.append(
            FieldValue(
                entity=entity,
                record_id=int(row["id"]),
                field=name,
                label=f"{prefix} · {label}" if prefix else label,
                value=value,
                hash=field_hash(entity, int(row["id"]), name, value),
            )
        )
    return out


async def load_fields(conn: asyncpg.Connection, project_code: str) -> list[FieldValue]:
    out: list[FieldValue] = []
    project = await conn.fetchrow(
        f"SELECT id, {', '.join(_PROJECT.fields)} FROM tenant_data.projects WHERE {_CACH_LY} AND project_code = $1",
        project_code,
    )
    if project is None:
        return out
    out += _collect(
        project,
        entity="projects",
        fields=_PROJECT.fields,
        labels=_PROJECT.field_labels,
        value_labels={},
        formatters=_PROJECT.formatters,
        prefix="",
    )
    for spec in (_ZONE, BUILDINGS):
        rows = await conn.fetch(
            f"SELECT id, {spec.name_col}, {', '.join(spec.fields)} FROM tenant_data.{spec.table}"
            f" WHERE {_CACH_LY} AND project_code = $1 ORDER BY id",
            project_code,
        )
        for row in rows:
            out += _collect(
                row,
                entity=spec.table,
                fields=spec.fields,
                labels=spec.field_labels,
                value_labels=spec.value_labels,
                formatters={},
                prefix=str(row[spec.name_col] or "").strip(),
            )
    return out


def render_block(fields: list[FieldValue]) -> str:
    return "\n".join(f"[{f.ref}] {f.label}: {f.value}" for f in fields)


def fields_block_hash(fields: list[FieldValue]) -> str:
    return block_hash(f.hash for f in fields)
