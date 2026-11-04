from evals.bench.results import aggregate_runs, flatten


def test_aggregate_and_flatten():
    samples = [{"ttfb_ms": 100.0, "total_ms": 500.0}, {"ttfb_ms": 200.0, "total_ms": 600.0}]
    res = aggregate_runs("stt", samples, errors=1)
    assert res.stats["ttfb_ms"]["p50"] == 100.0
    assert res.runs == 2 and res.errors == 1
    flat = flatten([res])
    assert flat["stt_ttfb_p50_ms"] == 100.0
    assert flat["stt_total_p95_ms"] == 600.0
    assert abs(flat["stt_error_rate"] - 1 / 3) < 1e-9  # errors / (runs + errors)


def test_flatten_does_not_fabricate_ms_suffix_on_non_time_metric():
    # audio_bytes isn't a time metric — flatten must not rename it to *_ms.
    samples = [{"ttfb_ms": 100.0, "audio_bytes": 1000.0}, {"ttfb_ms": 200.0, "audio_bytes": 2000.0}]
    res = aggregate_runs("tts", samples, errors=0)
    flat = flatten([res])
    assert flat["tts_ttfb_p50_ms"] == 100.0
    assert flat["tts_audio_bytes_p50"] == 1000.0
    assert "tts_audio_bytes_p50_ms" not in flat


def test_aggregate_empty():
    res = aggregate_runs("tts", [], errors=3)
    assert res.stats == {} and flatten([res])["tts_error_rate"] == 1.0
