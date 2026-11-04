from noble_agent.data.project_matching import channels


def test_trigram_identical_is_one():
    assert channels.trigram_score("crystal", "crystal") == 1.0


def test_trigram_partial_between_zero_and_one():
    s = channels.trigram_score("crystal", "cristal")
    assert 0.0 < s < 1.0


def test_token_set_order_independent():
    a = "tay ho noble crystal"
    b = "noble crystal tay ho"
    assert channels.token_set_score(a, b) > 0.95


def test_token_set_partial_name_scores_high():
    # a single shared token against the full name
    assert channels.token_set_score("crystal", "noble crystal tay ho") > 0.7


def test_phonetic_recovers_tone_loss():
    # "tay ho" (STT no tones) vs the true diacritic name
    assert channels.phonetic_score("noble crystal tay ho", "noble crystal tây hồ") > 0.9


def test_phonetic_beats_token_on_heavy_error():
    # heavy phonetic garble: token_set collapses, phonetic holds up
    q = "san sai gon dan"
    name = "sunshine golden river"
    assert channels.phonetic_score(q, name) > channels.token_set_score(q, name)
