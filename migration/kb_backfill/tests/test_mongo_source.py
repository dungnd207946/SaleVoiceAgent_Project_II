from types import SimpleNamespace

from kb_backfill import mongo_source as ms


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, query=None):
        query = query or {}
        if "projectId" in query:
            return [d for d in self._docs if d.get("projectId") == query["projectId"]]
        return list(self._docs)


def _db(projects, units):
    return SimpleNamespace(nbx_projects=_Coll(projects), nbx_units=_Coll(units))


def test_read_projects_skips_empty_code():
    db = _db([{"projectCode": "NPLB"}, {"projectCode": ""}, {"projectCode": "  "}, {}], [])
    got = ms.read_projects(db)
    assert [d["projectCode"] for d in got] == ["NPLB"]


def test_read_units_by_project():
    db = _db([], [{"projectId": "a", "code": "U1"}, {"projectId": "b", "code": "U2"}])
    assert [u["code"] for u in ms.read_units(db, "a")] == ["U1"]
