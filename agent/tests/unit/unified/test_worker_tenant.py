def test_job_tenant_from_metadata():
    from noble_agent.transport.livekit.worker import _job_tenant

    assert _job_tenant('{"tenant_id": "acme", "phone": "0900"}', "noble") == "acme"
    assert _job_tenant('{"phone": "0900"}', "noble") == "noble"  # no tenant → default
    assert _job_tenant("not json", "noble") == "noble"
    assert _job_tenant("", "noble") == "noble"
