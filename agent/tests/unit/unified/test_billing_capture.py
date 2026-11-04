"""Chuẩn hoá usage của provider + đường ghi qua ContextVar."""

from types import SimpleNamespace

from noble_agent.billing import capture, context
from noble_agent.billing.meter import UsageMeter


def test_anthropic_usage_maps_to_four_disjoint_buckets():
    u = SimpleNamespace(
        input_tokens=2140,
        output_tokens=214,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=11800,
    )
    got = capture.normalize_usage(u)
    assert got == {
        "input_tokens": 2140,
        "output_tokens": 214,
        "cache_write_tokens": 0,
        "cache_read_tokens": 11800,
        "exact": True,
    }


def test_anthropic_usage_without_output_is_inexact():
    """Khách ngắt lời → message_delta chưa về → không biết output token.

    Input vẫn chính xác vì nó đến từ message_start. KHÔNG được đoán output.
    """
    u = SimpleNamespace(
        input_tokens=1460,
        output_tokens=None,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=14100,
    )
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 1460
    assert got["output_tokens"] == 0
    assert got["exact"] is False


def test_openai_usage_subtracts_cached_from_prompt_tokens():
    """OpenAI tính prompt_tokens ĐÃ BAO GỒM phần cached; bốn cột của ta rời
    nhau nên phải trừ ra, nếu không phần cached bị đếm hai lần."""
    u = SimpleNamespace(
        prompt_tokens=5000,
        completion_tokens=120,
        prompt_tokens_details=SimpleNamespace(cached_tokens=4000),
    )
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 1000
    assert got["cache_read_tokens"] == 4000
    assert got["cache_write_tokens"] == 0
    assert got["output_tokens"] == 120
    assert got["exact"] is True


def test_openai_usage_without_cache_details():
    u = SimpleNamespace(prompt_tokens=300, completion_tokens=40)
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 300
    assert got["cache_read_tokens"] == 0


def test_hidden_thinking_tokens_are_recovered_from_total_tokens():
    """Gemini OpenAI-compat bỏ thinking token khỏi `completion_tokens` nhưng VẪN
    tính tiền chúng như output, chỉ để lại dấu ở `total_tokens`.

    Số thật đo được 2026-08-18 với thinking BẬT: prompt=36, completion=12,
    total=332 → 284 token output bị bỏ ngoài hoá đơn nếu tin `completion_tokens`.
    """
    u = SimpleNamespace(prompt_tokens=36, completion_tokens=12, total_tokens=332)
    got = capture.normalize_usage(u)
    assert got["output_tokens"] == 296  # = total - prompt, gồm cả thinking
    assert got["input_tokens"] == 36
    # Bốn cột phải cộng lại đúng bằng total — bất biến giữ hoá đơn không hụt.
    assert (
        got["input_tokens"] + got["output_tokens"] + got["cache_write_tokens"] + got["cache_read_tokens"]
    ) == 332


def test_total_tokens_never_shrinks_a_larger_completion_count():
    """Endpoint đã khớp (OpenAI/vLLM/DashScope) không được bị sửa số.

    Và nếu `total_tokens` bị báo THIẾU thì cũng không được dùng nó để cắt bớt
    output — thà giữ số provider khai còn hơn tự ý giảm doanh thu.
    """
    exact = SimpleNamespace(prompt_tokens=100, completion_tokens=40, total_tokens=140)
    assert capture.normalize_usage(exact)["output_tokens"] == 40

    understated = SimpleNamespace(prompt_tokens=100, completion_tokens=40, total_tokens=110)
    assert capture.normalize_usage(understated)["output_tokens"] == 40

    missing_total = SimpleNamespace(prompt_tokens=100, completion_tokens=40)
    assert capture.normalize_usage(missing_total)["output_tokens"] == 40


def test_hidden_thinking_recovery_does_not_double_count_cached_input():
    """Phần chênh phải đi vào output, KHÔNG được lấn sang cột cache_read."""
    u = SimpleNamespace(
        prompt_tokens=5000,
        completion_tokens=10,
        total_tokens=5400,
        prompt_tokens_details=SimpleNamespace(cached_tokens=4000),
    )
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 1000
    assert got["cache_read_tokens"] == 4000
    assert got["output_tokens"] == 400
    assert sum(got[k] for k in ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")) == 5400


def test_normalize_returns_none_for_nothing():
    assert capture.normalize_usage(None) is None
    assert capture.normalize_usage(SimpleNamespace()) is None


def test_record_writes_into_the_current_meter():
    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        capture.record(
            "anthropic",
            "claude-x",
            SimpleNamespace(input_tokens=10, output_tokens=2, cache_creation_input_tokens=0, cache_read_input_tokens=5),
            purpose="summary",
        )
    _seq, rows = m.drain()
    assert rows[0].purpose == "summary"
    assert rows[0].provider == "anthropic"
    assert rows[0].input_tokens == 10


def test_record_without_usage_still_logs_an_inexact_call():
    """Lời gọi có xảy ra là một sự thật cần ghi, kể cả khi không đo được."""
    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        capture.record("vllm", "qwen", None, purpose="conversation")
    _seq, rows = m.drain()
    assert rows[0].exact is False
    assert rows[0].units == 1
    assert rows[0].input_tokens == 0


def test_record_without_a_meter_is_a_noop():
    capture.record("anthropic", "claude-x", None, purpose="conversation")  # không raise


def test_session_registry_returns_the_same_meter_per_session():
    a = context.get_session_meter("sess-A", "voice")
    b = context.get_session_meter("sess-A", "voice")
    assert a is b
    assert context.pop_session_meter("sess-A") is a
    assert context.pop_session_meter("sess-A") is None


def test_resumed_session_continues_the_seq_instead_of_restarting_at_zero():
    """`?session=<sid>` dựng lại đúng session_id sau khi meter đã bị pop.

    Meter mới bắt lại từ seq 0 thì mọi dòng của chặng resume trùng khoá UNIQUE
    với chặng đầu và bị `ON CONFLICT DO NOTHING` bỏ đi — mất trắng cả chặng, không
    log. Khoảng trống trong dãy seq thì không sao (contract chỉ đòi đơn điệu tăng).
    """
    m1 = context.get_session_meter("sess-RESUME", "chat")
    m1.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, _rows = m1.drain()
    m1.commit(seq)
    assert context.pop_session_meter("sess-RESUME") is m1

    m2 = context.get_session_meter("sess-RESUME", "chat")
    assert m2 is not m1
    m2.add_llm(purpose="conversation", provider="p", model="m", input_tokens=99)
    seq2, _rows2 = m2.drain()
    assert seq2 > seq
    context.pop_session_meter("sess-RESUME")


def test_lru_eviction_also_preserves_the_seq_high_water():
    """Worker đông làm tràn registry: phiên còn sống bị evict rồi dựng lại ở
    lượt kế — cùng một lỗi trùng seq như đường resume."""
    m1 = context.get_session_meter("sess-EVICT", "chat")
    m1.add_llm(purpose="conversation", provider="p", model="m", input_tokens=1)
    seq, _ = m1.drain()
    m1.commit(seq)

    # Đẩy tràn registry để "sess-EVICT" (cũ nhất) bị bỏ.
    filler = [f"sess-EVICT-filler-{i}" for i in range(context.MAX_SESSIONS)]
    for sid in filler:
        context.get_session_meter(sid, "chat")
    assert "sess-EVICT" not in context._sessions

    m2 = context.get_session_meter("sess-EVICT", "chat")
    m2.add_llm(purpose="conversation", provider="p", model="m", input_tokens=2)
    seq2, _ = m2.drain()
    assert seq2 > seq

    for sid in [*filler, "sess-EVICT"]:
        context.pop_session_meter(sid)


def test_background_task_inherits_the_meter():
    """Task summary/warm sinh ra trong lượt phải ghi vào ĐÚNG meter — nếu
    không, chi phí nền bị mất mà không ai biết."""
    import asyncio

    async def main():
        m = UsageMeter(session_id="s1", channel="voice")
        with context.use_meter(m):

            async def bg():
                capture.record("anthropic", "claude-x", None, purpose="summary")

            await asyncio.create_task(bg())
        return m

    m = asyncio.run(main())
    _seq, rows = m.drain()
    assert rows[0].purpose == "summary"


def test_record_swallows_a_provider_usage_object_that_raises_on_attribute_access():
    """Provider SDK object với property bị hỏng không được phép làm hỏng turn.
    Nếu normalize_usage hoặc add_llm raise, record() phải catch và log, không raise."""

    class BrokenUsage:
        @property
        def input_tokens(self):
            raise RuntimeError("proxy connection broken")

    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        # Không được raise — lỗi measure phải im lặng
        capture.record("anthropic", "claude-x", BrokenUsage(), purpose="conversation")

    _seq, rows = m.drain()
    # Lỗi normalize → vẫn ghi một dòng inexact với 0 token
    assert len(rows) == 1
    assert rows[0].exact is False
    assert rows[0].input_tokens == 0
    assert rows[0].purpose == "conversation"


def test_record_swallows_meter_add_llm_exceptions():
    """Nếu meter.add_llm raise, record() không được propagate nó."""
    m = UsageMeter(session_id="s1", channel="chat")

    def broken_add_llm(*args, **kwargs):
        raise RuntimeError("meter corruption")

    m.add_llm = broken_add_llm

    with context.use_meter(m):
        # Không được raise ngay cả khi add_llm bị hỏng
        capture.record("anthropic", "claude-x", None, purpose="conversation")

    # Vì add_llm bị hỏng, không có row nào được ghi, nên drain() trả None
    result = m.drain()
    assert result is None


def test_record_never_double_records_on_normalization_failure():
    """Nếu normalize fail, ghi một dòng inexact. Không được ghi hai dòng."""

    class BrokenUsage:
        @property
        def input_tokens(self):
            raise RuntimeError("boom")

    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        capture.record("anthropic", "claude-x", BrokenUsage(), purpose="conversation")

    _seq, rows = m.drain()
    # Exactly one row, not two
    assert len(rows) == 1
    assert rows[0].exact is False
    assert rows[0].units == 1
