"""Log của huggingface/httpx lúc tải model đủ để đẩy traceback thật ra khỏi journal."""

import logging

from embed.log import setup


def test_dat_level_theo_tham_so():
    setup("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    setup("INFO")
    assert logging.getLogger().level == logging.INFO


def test_tat_log_spam_cua_thu_vien():
    setup("INFO")
    for name in ("httpx", "huggingface_hub", "filelock", "urllib3"):
        assert logging.getLogger(name).level == logging.WARNING


def test_level_khong_hop_le_thi_ve_INFO():
    """Env sai chính tả không được làm service không boot được."""
    setup("KHONG_TON_TAI")
    assert logging.getLogger().level == logging.INFO
