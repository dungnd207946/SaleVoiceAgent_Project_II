"""CLI credential commands (slice #2, task 5)."""

from noble_agent.tenant import cli
from noble_agent.tenant import provisioning as prov
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta


def _store():
    st = FakeTenantStore()
    st.write_bundle(Bundle("t1", "tenant_id='t1'", {}, TenantMeta("t1", "active", 1, "sha256:x")))
    return st


def test_issue_cred_prints_plaintext(capsys):
    st = _store()
    rc = cli.main(["issue-cred", "t1"], store=st)
    out = capsys.readouterr().out
    assert rc == 0 and "tnt_" in out
    assert st.read_creds_raw("t1") is not None


def test_list_and_revoke_cred(capsys):
    st = _store()
    cli.main(["issue-cred", "t1"], store=st)
    capsys.readouterr()  # drain the issue-cred plaintext so it doesn't contaminate the next capture
    cli.main(["list-creds", "t1"], store=st)
    # parse the REAL key_id from the first (tab-separated) field of the list-creds line
    key_id = capsys.readouterr().out.strip().split("\t")[0]
    rc = cli.main(["revoke-cred", "t1", key_id], store=st)
    assert rc == 0
    # non-vacuous post-condition: the credential is now actually revoked
    assert prov.list_credentials(st, "t1")[0]["revoked_at"] != ""
