from noble_agent.tenant import cli
from noble_agent.tenant import provisioning as P
from noble_agent.tenant.store import FakeTenantStore

VALID_MANIFEST = 'tenant_id="tt"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
VALID_FILES = {
    "persona/SOUL.md": "x",
    "persona/RULES.md": "escalate",
    "persona/PROMPT_TEMPLATE.md": "x",
    "persona/CUSTOMER_PROFILE.md": "x",
    "persona/config.json": "{}",
}


def _write_dir(dirpath, soul="x"):
    (dirpath / "manifest.toml").write_text(VALID_MANIFEST, encoding="utf-8")
    persona = dirpath / "persona"
    persona.mkdir()
    (persona / "config.json").write_text("{}", encoding="utf-8")
    (persona / "SOUL.md").write_text(soul, encoding="utf-8")
    (persona / "RULES.md").write_text("escalate", encoding="utf-8")
    (persona / "PROMPT_TEMPLATE.md").write_text("x", encoding="utf-8")
    (persona / "CUSTOMER_PROFILE.md").write_text("x", encoding="utf-8")


def test_cli_list_versions_and_rollback(capsys):
    store = FakeTenantStore()
    P.create_tenant(store, "tt", VALID_MANIFEST, VALID_FILES, status="active")
    P.save_draft(store, "tt", files={**VALID_FILES, "persona/SOUL.md": "v2"})
    P.publish(store, "tt")
    cli.main(["list-versions", "tt"], store=store)
    assert "1" in capsys.readouterr().out
    cli.main(["rollback", "tt", "1"], store=store)
    assert store.read_pointer("tt") == 1


def test_cli_save_draft_then_publish(tmp_path, capsys):
    store = FakeTenantStore()
    P.create_tenant(store, "tt", VALID_MANIFEST, VALID_FILES, status="active")
    edit = tmp_path / "edit"
    edit.mkdir()
    _write_dir(edit, soul="from-cli")
    assert cli.main(["save-draft", "tt", str(edit)], store=store) == 0
    assert store.read_bundle("tt").files["persona/SOUL.md"] == "x"  # published unchanged
    assert cli.main(["publish", "tt", "--by", "alice"], store=store) == 0
    assert store.read_pointer("tt") == 2
    assert store.read_bundle("tt").files["persona/SOUL.md"] == "from-cli"


def test_cli_diff_default_draft_vs_published(tmp_path, capsys):
    store = FakeTenantStore()
    P.create_tenant(store, "tt", VALID_MANIFEST, VALID_FILES, status="active")
    P.save_draft(store, "tt", files={**VALID_FILES, "persona/NEW.md": "n"})
    cli.main(["diff", "tt"], store=store)
    assert "persona/NEW.md" in capsys.readouterr().out
