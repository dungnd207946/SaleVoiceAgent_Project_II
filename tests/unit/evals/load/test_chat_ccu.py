from evals.load.chat_ccu import summarize_admission


def test_admission_pass():
    gates, ok = summarize_admission(
        {"over_cap_closed_4029": 3, "ready_503_at_saturation": True, "ready_200_after_drain": True}, cap=10)
    assert ok and gates == {"admission_4029": "pass", "ready_503": "pass", "ready_recover": "pass"}


def test_admission_fail_when_no_4029():
    gates, ok = summarize_admission(
        {"over_cap_closed_4029": 0, "ready_503_at_saturation": True, "ready_200_after_drain": True}, cap=10)
    assert not ok and gates["admission_4029"] == "fail"
