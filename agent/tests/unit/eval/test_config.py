from eval.config import EvalSettings


def test_defaults():
    s = EvalSettings()
    assert s.eval_file.endswith("data/synthetic_sft/eval_sft.jsonl")
    assert s.results_dir.endswith("data/eval_results")
    assert s.temperature == 0.2
    assert s.max_tokens == 1024
    assert s.workers == 8
    assert s.tfidf_threshold == 0.7


def test_env_override(monkeypatch):
    monkeypatch.setenv("EVAL_CRITIC_MODEL", "gpt-4o-mini")
    s = EvalSettings()
    assert s.critic_model == "gpt-4o-mini"
