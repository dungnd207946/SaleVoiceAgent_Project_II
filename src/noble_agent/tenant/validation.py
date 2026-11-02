"""Static tenant-bundle validation (SaaS slice #1).

Pure + side-effect-free: parses the manifest, checks persona presence, checks
every enabled tool resolves (built-in OR declared by a bundle tools/*.py via a
STATIC ast scan), and compiles custom tool files. It MUST NOT import/execute
tenant code — execution happens only at boot on the trusted loader path.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from dataclasses import dataclass, field

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
REQUIRED_PERSONA_FILES = ("config.json", "SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md")
_IMPORT_ALLOWLIST = ("noble_agent", "typing", "datetime", "json", "math", "re", "decimal", "collections", "dataclasses")
_REQUIRED_MANIFEST_KEYS = ("data_source", "persona_dir")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_manifest(text: str) -> dict:
    """Parse + minimally validate a manifest. Raises ValueError on any problem."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"manifest is not valid TOML: {e}") from e
    missing = [k for k in _REQUIRED_MANIFEST_KEYS if not data.get(k)]
    tools_tbl = data.get("tools")
    enabled = tools_tbl.get("enabled") if isinstance(tools_tbl, dict) else None
    if not enabled:
        missing.append("tools.enabled")
    if missing:
        raise ValueError(f"manifest missing required key(s): {', '.join(missing)}")
    return data


def tool_names_declared(py_src: str) -> set[str]:
    """Names declared by @tool(name="…") decorators, via a STATIC ast scan."""
    try:
        tree = ast.parse(py_src)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            is_tool = (isinstance(fn, ast.Name) and fn.id == "tool") or (
                isinstance(fn, ast.Attribute) and fn.attr == "tool"
            )
            if not is_tool:
                continue
            for kw in dec.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    names.add(str(kw.value.value))
    return names


def _imported_top_modules(py_src: str) -> set[str]:
    try:
        tree = ast.parse(py_src)
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def validate_bundle(tenant_id, manifest_text, files, *, existing_ids=()) -> ValidationReport:
    from noble_agent.agent.tools import builtins as _builtins  # ensure built-ins registered
    from noble_agent.agent.tools.registry import resolve

    _ = _builtins  # imported for its registration side effect
    report = ValidationReport()

    if not SLUG_RE.match(tenant_id or ""):
        report.errors.append(f"tenant_id is not a valid slug: {tenant_id!r}")
    if tenant_id in tuple(existing_ids):
        report.errors.append(f"tenant already exists: {tenant_id!r}")

    try:
        manifest = parse_manifest(manifest_text)
    except ValueError as e:
        report.errors.append(str(e))
        return report  # can't proceed without a manifest

    persona_dir = str(manifest.get("persona_dir") or "persona").strip("/")
    for fname in REQUIRED_PERSONA_FILES:
        key = f"{persona_dir}/{fname}"
        if key not in files:
            report.errors.append(f"missing persona file: {key}")
    cfg_key = f"{persona_dir}/config.json"
    if cfg_key in files:
        try:
            json.loads(files[cfg_key])
        except ValueError:
            report.errors.append(f"{cfg_key} is not valid JSON")

    # Custom tool files: compile + collect declared names + import warnings.
    declared: set[str] = set()
    for rel, src in files.items():
        if not (rel.startswith("tools/") and rel.endswith(".py")):
            continue
        try:
            compile(src, rel, "exec")
        except SyntaxError as e:
            report.errors.append(f"{rel} fails to compile (syntax error): {e}")
            continue
        declared |= tool_names_declared(src)
        for mod in _imported_top_modules(src):
            if mod not in _IMPORT_ALLOWLIST:
                report.warnings.append(f"{rel} imports non-allowlisted module '{mod}' (review for slice #3 sandbox)")

    tools_tbl = manifest.get("tools")
    enabled = tools_tbl.get("enabled") if isinstance(tools_tbl, dict) else None
    if enabled is None:
        enabled = []
    elif not isinstance(enabled, list):
        report.errors.append("tools.enabled must be a list")
        enabled = []
    for name in enabled:
        if resolve("*", name) is not None or name in declared:
            continue
        report.errors.append(f"enabled tool '{name}' resolves to neither a built-in nor a bundle tool")

    return report
