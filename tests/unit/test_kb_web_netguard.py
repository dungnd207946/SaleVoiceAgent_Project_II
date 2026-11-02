"""Chặn tải URL nội bộ (loopback/private/link-local/reserved) — không mạng thật, resolver giả."""

import pytest

from portal.modules.kb.web.netguard import is_public_url


def _resolver(mapping):
    async def resolve(host):
        if host not in mapping:
            raise OSError("không phân giải được")
        return mapping[host]

    return resolve


PUBLIC = _resolver({"bao.vn": ["93.184.216.34"], "v6.vn": ["2606:4700::1111"]})


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://127.8.8.8:8080/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/x",
        "http://172.16.0.1/x",
        "http://192.168.1.1/x",
        "http://100.64.0.1/x",
        "http://0.0.0.0/x",
        "http://[::1]/x",
        "http://[fe80::1]/x",
        "http://[fd00::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://localhost/x",
        "http://api.localhost/x",
        "ftp://bao.vn/x",
        "file:///etc/passwd",
        "gopher://bao.vn/x",
        "http:///x",
        "http://khong-phan-giai.vn/x",
    ],
)
async def test_chan_url_noi_bo_hoac_khong_phai_http(url):
    assert not await is_public_url(url, PUBLIC)


async def test_ten_mien_phan_giai_ra_ip_noi_bo_bi_chan():
    assert not await is_public_url("https://noi-bo.vn/x", _resolver({"noi-bo.vn": ["10.0.0.7"]}))
    assert not await is_public_url(
        "https://lan-lon.vn/x", _resolver({"lan-lon.vn": ["93.184.216.34", "192.168.0.2"]})
    ), "một địa chỉ nội bộ trong số nhiều là đủ để chặn"


@pytest.mark.parametrize("url", ["https://bao.vn/a", "http://bao.vn:8080/a?b=1", "https://v6.vn/x", "http://8.8.8.8/x"])
async def test_cho_qua_url_cong_khai(url):
    assert await is_public_url(url, PUBLIC)


async def test_resolver_mac_dinh_localhost_bi_chan_khong_can_mang():
    assert not await is_public_url("http://localhost:8100/api")
