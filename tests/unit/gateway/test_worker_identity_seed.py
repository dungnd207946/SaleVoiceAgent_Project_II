from noble_agent.server.app_session import identity_to_fields


def test_identity_to_fields_maps_like_provision():
    fields = identity_to_fields(
        {"full_name": "An", "phone": "090", "gender": "nam", "is_noble_customer": True, "email": "a@b.c"}
    )
    assert fields["full_name"] == "An" and fields["name"] == "An"
    assert fields["phone"] == "090" and fields["gender"] == "M"
    assert fields["is_noble_customer"] is True and "email: a@b.c" in fields["noble_info"]


def test_identity_to_fields_empty():
    assert identity_to_fields({}) == {}
