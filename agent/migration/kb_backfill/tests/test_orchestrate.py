from types import SimpleNamespace

import pytest

from kb_backfill import __main__ as m


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, query=None):
        query = query or {}
        if "projectId" in query:
            return [d for d in self._docs if d.get("projectId") == query["projectId"]]
        return list(self._docs)


@pytest.mark.asyncio
async def test_run_dry_counts_and_skips_empty_code():
    projects = [
        {"_id": "oid1", "projectCode": "NPLB", "name": "N", "type": "cao_tang"},
        {"_id": "oid2", "projectCode": "", "name": "skip", "type": "cao_tang"},
    ]
    units = [{"projectId": "oid1", "code": "U1", "unitType": {"name": "2PN"},
              "price": 3.0, "area": "70", "status": "available", "direction": "Đông"}]
    db = SimpleNamespace(nbx_projects=_Coll(projects), nbx_units=_Coll(units))
    stats = await m.run(db, "noble", sink_conn=None, dry_run=True)
    assert stats["projects_migrated"] == 1
    assert stats["units_migrated"] == 1
    assert stats["projects_skipped_no_code"] == 1
