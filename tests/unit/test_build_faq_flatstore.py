"""Tests for the build_faq_flatstore script's project mapping + source override.

Pure dict/path assertions — no encoding, no markers. Guards two invariants:
1. The build script's PROJECT_MAP and the runtime flat_store.PROJECT_MAP stay
   byte-identical and cover all 15 canonical codes.
2. SOURCE_OVERRIDE points each of the 10 new codes at an existing md_v2 file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from noble_agent.agent import catalog as pc
from noble_agent.agent.rag import flat_store

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "build_faq_flatstore.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_faq_flatstore", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_project_map_has_15_entries():
    mod = _load_build_module()
    assert len(mod.PROJECT_MAP) == 15
    assert set(mod.PROJECT_MAP.values()) == set(pc.VALID_CODES)


def test_project_maps_identical():
    mod = _load_build_module()
    assert mod.PROJECT_MAP == flat_store.PROJECT_MAP


def test_flat_store_map_matches_catalog():
    assert set(flat_store.PROJECT_MAP.values()) == set(pc.VALID_CODES)


def test_source_override_paths_exist_for_all_15():
    mod = _load_build_module()
    assert set(mod.SOURCE_OVERRIDE.keys()) == set(pc.VALID_CODES)
    for code, path in mod.SOURCE_OVERRIDE.items():
        assert path.is_file(), (code, path)
