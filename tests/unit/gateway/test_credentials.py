from noble_agent.tenant import credentials as c


def test_generate_verify_roundtrip():
    plaintext, entry = c.generate_credential(now="2026-07-29T00:00:00+00:00")
    assert plaintext.startswith("tnt_")
    assert entry.hash and entry.salt and entry.key_id
    assert c.verify(plaintext, [entry]) is entry


def test_verify_rejects_wrong_and_revoked():
    good, e = c.generate_credential(now="t")
    other, _ = c.generate_credential(now="t")
    assert c.verify(other, [e]) is None          # wrong secret
    assert c.verify("no-prefix", [e]) is None     # bad format
    revoked = c.CredentialEntry(e.key_id, e.salt, e.hash, e.created_at, revoked_at="t2")
    assert c.verify(good, [revoked]) is None      # revoked


def test_hash_never_contains_plaintext_and_roundtrips_serialization():
    plaintext, e = c.generate_credential(now="t")
    raw = c.serialize_creds([e])
    assert plaintext not in raw and "tnt_" not in raw
    assert c.parse_creds(raw) == [e]
    assert c.verify(plaintext, c.parse_creds(raw)) is not None
