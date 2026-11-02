"""UsageMeter — số học thuần, không I/O. Đây là lớp duy nhất chạm đường nóng."""

from noble_agent.billing.meter import UsageMeter


def _meter() -> UsageMeter:
    return UsageMeter(session_id="s1", channel="voice")


def test_llm_calls_aggregate_into_one_row_per_provider_model():
    """5 vòng tool trong một lượt phải gộp thành MỘT dòng, units = số lời gọi.

    Khoá UNIQUE của bảng là (tenant, session, seq, component, purpose, provider,
    model) — ghi từng lời gọi riêng sẽ đụng khoá và bị DO NOTHING nuốt mất.
    """
    m = _meter()
    for _ in range(5):
        m.add_llm(
            purpose="conversation",
            provider="anthropic",
            model="claude-x",
            input_tokens=100,
            output_tokens=10,
            cache_read_tokens=1000,
        )
    seq, rows = m.drain()
    assert seq == 0
    assert len(rows) == 1
    row = rows[0]
    assert row.component == "llm"
    assert row.units == 5
    assert row.input_tokens == 500
    assert row.output_tokens == 50
    assert row.cache_read_tokens == 5000


def test_different_purpose_stays_a_separate_row():
    m = _meter()
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", input_tokens=10)
    m.add_llm(purpose="summary", provider="anthropic", model="claude-x", input_tokens=20)
    _seq, rows = m.drain()
    purposes = sorted(r.purpose for r in rows)
    assert purposes == ["conversation", "summary"]


def test_mixed_exactness_merges_into_one_row_and_keeps_every_token():
    """``exact`` KHÔNG được tách dòng: nó không nằm trong khoá UNIQUE của bảng.

    Hai dòng chỉ khác ``exact`` giống nhau ở cả 7 cột khoá → dòng thứ hai đụng
    ràng buộc và bị ``ON CONFLICT DO NOTHING`` bỏ đi KHÔNG LOG. Nên gộp thành
    một dòng, cộng hết token (phần đo được vẫn là thật), và hạ ``exact=False``
    vì có phần thật sự không đo được.
    """
    m = _meter()
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", input_tokens=10, exact=True)
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", input_tokens=20, exact=False)
    _seq, rows = m.drain()
    assert len(rows) == 1
    assert rows[0].input_tokens == 30
    assert rows[0].units == 2
    assert rows[0].exact is False


def test_real_tokens_are_never_dropped_when_an_inexact_row_shares_the_seq():
    """Bẫy đã sập: lượt bị ngắt lời ghi exact=False token 0, save_all hỏng nên
    lô ở lại; lượt sau ghi exact=True với token thật. Cả hai đi cùng một seq —
    nếu tách dòng thì dòng mang token thật là dòng bị DO NOTHING nuốt, cả lượt
    không bao giờ vào hoá đơn và không có log nào."""
    m = _meter()
    # Lượt bị ngắt: provider không kịp trả output_tokens.
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", exact=False)
    # Lượt sau, cùng lô vì lô trước chưa commit được.
    m.add_llm(
        purpose="conversation",
        provider="anthropic",
        model="claude-x",
        input_tokens=4000,
        output_tokens=300,
        cache_read_tokens=12000,
        exact=True,
    )
    _seq, rows = m.drain()
    assert len(rows) == 1, "hai dòng cùng 7 cột khoá → dòng thứ hai bị DO NOTHING bỏ mất"
    assert rows[0].input_tokens == 4000
    assert rows[0].output_tokens == 300
    assert rows[0].cache_read_tokens == 12000
    assert rows[0].exact is False


def test_audio_counter_emits_only_the_delta():
    """VAD chạy liên tục nên meter giữ số tích luỹ; mỗi lần rút chỉ ghi phần
    tăng thêm. Ghi thẳng tích luỹ = tính tiền hai lần cùng một quãng audio."""
    m = _meter()
    m.add_audio("vad", audio_sec=12.4, wall_ms=41, units=380)
    seq, rows = m.drain()
    assert rows[0].audio_sec == 12.4
    m.commit(seq)

    m.add_audio("vad", audio_sec=11.0, wall_ms=36, units=340)
    seq2, rows2 = m.drain()
    assert seq2 == 1
    assert rows2[0].audio_sec == 11.0  # delta, KHÔNG phải 23.4
    assert rows2[0].units == 340


def test_audio_counter_accumulates_text_units_as_delta():
    """`text_units` = lượng text theo ký tự (transcript STT ra / ký tự vào TTS),
    tách khỏi `units` (= số lần gọi). Cũng là đồng hồ tích luỹ nên mỗi lần rút
    chỉ phát delta — và một kỳ CHỈ tăng text_units (không tăng audio/wall/units)
    vẫn phải ra dòng."""
    m = _meter()
    m.add_audio("stt", audio_sec=2.0, text_units=40)
    seq, rows = m.drain()
    assert rows[0].text_units == 40
    m.commit(seq)

    m.add_audio("stt", text_units=25)
    seq2, rows2 = m.drain()
    assert seq2 == 1
    assert rows2[0].text_units == 25  # delta, KHÔNG phải 65


def test_drain_returns_none_when_nothing_to_write():
    m = _meter()
    assert m.drain() is None


def test_uncommitted_drain_replays_identical_rows_with_the_same_seq():
    """INSERT hỏng → lượt sau phải gửi lại ĐÚNG seq cũ với ĐÚNG nội dung cũ.

    Nội dung của một seq phải bất biến: nếu lần ghi trước thực ra đã landed,
    ON CONFLICT DO NOTHING giữ bản đầu — gộp thêm dữ liệu mới vào cùng seq sẽ
    làm dữ liệu mới biến mất im lặng.
    """
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, rows = m.drain()

    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=999)  # lượt sau
    seq_retry, rows_retry = m.drain()

    assert seq_retry == seq
    assert [r.input_tokens for r in rows_retry] == [r.input_tokens for r in rows] == [10]


def test_new_data_lands_on_the_next_seq_after_commit():
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, _rows = m.drain()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=999)
    m.commit(seq)

    seq2, rows2 = m.drain()
    assert seq2 == seq + 1
    assert rows2[0].input_tokens == 999


def test_commit_with_a_stale_seq_is_ignored():
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, _ = m.drain()
    m.commit(seq + 7)
    seq_again, _ = m.drain()
    assert seq_again == seq


def test_pending_events_are_capped_and_drop_the_oldest():
    """PG chết suốt một cuộc gọi dài không được phép làm phình RAM vô hạn."""
    m = UsageMeter(session_id="s1", channel="voice", max_pending=3)
    for i in range(5):
        m.add_llm(purpose="conversation", provider="p", model=f"m{i}", input_tokens=1)
    assert m.pending_count == 3
    assert m.dropped == 2
    _seq, rows = m.drain()
    assert sorted(r.model for r in rows) == ["m2", "m3", "m4"]


def test_turn_idx_is_stamped_on_llm_rows():
    m = _meter()
    m.turn_idx = 4
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=1)
    _seq, rows = m.drain()
    assert rows[0].turn_idx == 4


def test_session_level_component_has_no_turn_idx():
    """VAD và call chạy ngoài phạm vi lượt → turn_idx NULL trong bảng."""
    m = _meter()
    m.turn_idx = 4
    m.add_audio("call", purpose="session", audio_sec=38.6, units=1)
    _seq, rows = m.drain()
    assert rows[0].turn_idx is None
    assert rows[0].component == "call"


def test_session_scoping_is_keyed_by_component_and_purpose():
    """(stt, stream) là giá vốn CẢ PHIÊN (thời gian stream mở) → turn_idx NULL;
    (stt, conversation) là giây khách nói CỦA MỘT LƯỢT → giữ turn_idx.

    Scoping khoá theo component đơn thuần sẽ kéo cả hai về một phía — đúng dòng
    lai đã thấy trên bảng thật: `stt turn_idx=1 audio_sec=0 wall_ms=112748`
    (thời gian mở stream của cả cuộc gọi 112s bị đóng dấu như của lượt 1)."""
    m = _meter()
    m.turn_idx = 4
    m.add_audio("stt", audio_sec=2.0)
    m.add_audio("stt", purpose="stream", wall_ms=3000.0, units=1)
    _seq, rows = m.drain()
    by_purpose = {r.purpose: r for r in rows if r.component == "stt"}
    assert set(by_purpose) == {"conversation", "stream"}, "hai phép đo phải ra HAI dòng riêng"
    assert by_purpose["conversation"].turn_idx == 4
    assert by_purpose["conversation"].audio_sec == 2.0
    assert by_purpose["stream"].turn_idx is None
    assert by_purpose["stream"].wall_ms == 3000.0
    assert by_purpose["stream"].units == 1


def test_drained_rows_are_copies_so_callers_cannot_corrupt_the_replay():
    """Drained rows are independent copies; mutations do not affect replay.

    drain() returns fresh UsageRow objects (not live _inflight state).
    If a caller mutates a returned row before commit(), the replay at the
    next drain() must still carry the original values. ON CONFLICT DO NOTHING
    cannot tolerate silent data drift between drain calls.
    """
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, rows = m.drain()

    # Mutate the returned row object
    rows[0].input_tokens = 999

    # Re-drain without commit: must replay original content, not the mutation
    seq_retry, rows_retry = m.drain()
    assert seq_retry == seq
    assert rows_retry[0].input_tokens == 10, "Replay must carry original value, not mutation"

    # The two drain calls must return distinct objects
    assert rows is not rows_retry
    assert rows[0] is not rows_retry[0]
