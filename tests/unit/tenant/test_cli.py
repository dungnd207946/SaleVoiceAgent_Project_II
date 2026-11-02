from noble_agent.tenant import cli
from noble_agent.tenant.store import FakeTenantStore


def _write_bundle(dirpath):
    (dirpath / "manifest.toml").write_text(
        'tenant_id = "acme"\ndata_source = "nbx"\npersona_dir = "persona"\n'
        '[tools]\nenabled = ["kb_search"]\n', encoding="utf-8")
    persona = dirpath / "persona"
    persona.mkdir()
    (persona / "config.json").write_text(
        '{"name":"Ava","model":"m","temperature":0.3,"max_tokens":800}', encoding="utf-8")
    for fn in ("SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md"):
        (persona / fn).write_text("x", encoding="utf-8")


def test_cli_validate_ok(tmp_path, capsys):
    _write_bundle(tmp_path)
    rc = cli.main(["validate", "--dir", str(tmp_path)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_cli_validate_reports_errors(tmp_path, capsys):
    _write_bundle(tmp_path)
    (tmp_path / "persona" / "SOUL.md").unlink()
    rc = cli.main(["validate", "--dir", str(tmp_path)])
    assert rc == 1
    assert "SOUL.md" in capsys.readouterr().out


def test_cli_create_then_list(tmp_path, capsys):
    _write_bundle(tmp_path)
    store = FakeTenantStore()
    rc = cli.main(["create", "acme", "--dir", str(tmp_path), "--status", "active"], store=store)
    assert rc == 0
    rc = cli.main(["list"], store=store)
    assert rc == 0
    out = capsys.readouterr().out
    assert "acme" in out and "active" in out


def test_cli_disable(tmp_path, capsys):
    _write_bundle(tmp_path)
    store = FakeTenantStore()
    cli.main(["create", "acme", "--dir", str(tmp_path), "--status", "active"], store=store)
    rc = cli.main(["disable", "acme"], store=store)
    assert rc == 0
    assert store.read_meta("acme").status == "disabled"
