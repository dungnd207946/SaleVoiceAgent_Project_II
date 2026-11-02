"""Bản ghi phiên ở Redis.

Redis chỉ trả lời "ai đang đăng nhập". Nó KHÔNG BAO GIỜ trả lời "được làm gì" —
quyền đọc từ control.memberships mỗi request (PQ_01 §BR-Q04). Nếu bạn thấy mình
muốn nhét `role` hay `actions` vào bản ghi này, dừng lại: đó chính là lỗi mà
BR-Q04 tồn tại để chặn.
"""

import pytest

from portal.core.auth import session as ss

pytestmark = pytest.mark.integration


async def test_tao_roi_doc_lai_duoc(redis_client):
    sid = await ss.tao(redis_client, user_id="u_dang", tenant_id="anphu")
    ban_ghi = await ss.doc(redis_client, sid)

    assert ban_ghi is not None
    assert (ban_ghi.user_id, ban_ghi.tenant_id) == ("u_dang", "anphu")


async def test_session_id_khong_doan_duoc(redis_client):
    """Hai lần tạo phải ra hai id khác nhau và đủ dài. Id đoán được là phiên
    của người khác đoán được."""
    a = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")
    b = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")

    assert a != b
    assert len(a) >= 40  # 32 byte base64url ≈ 43 ký tự


async def test_doc_id_rac_tra_None(redis_client):
    assert await ss.doc(redis_client, "khong-ton-tai") is None


async def test_doc_id_rong_tra_None(redis_client):
    """Cookie vắng mặt tới đây là chuỗi rỗng. Không chặn sớm thì nó thành một
    lượt GET `sess:` — một khoá mà bất kỳ ai cũng đặt được."""
    assert await ss.doc(redis_client, "") is None


async def test_xoa_thi_doc_khong_ra(redis_client):
    """Đăng xuất phải THẬT SỰ thu hồi, không chỉ xoá cookie phía client."""
    sid = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")
    await ss.xoa(redis_client, sid)

    assert await ss.doc(redis_client, sid) is None


async def test_doi_workspace_ghi_de_tenant(redis_client):
    sid = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")
    await ss.doi_workspace(redis_client, sid, "sunrise")
    ban_ghi = await ss.doc(redis_client, sid)

    assert ban_ghi is not None and ban_ghi.tenant_id == "sunrise"


async def test_doi_workspace_khong_doi_user(redis_client):
    """Đổi workspace là đổi ĐÚNG MỘT trường. Ghi đè cả bản ghi là cách dễ nhất để
    một phiên tự nhiên đổi chủ."""
    sid = await ss.tao(redis_client, user_id="u_dang", tenant_id="anphu")
    await ss.doi_workspace(redis_client, sid, "sunrise")
    ban_ghi = await ss.doc(redis_client, sid)

    assert ban_ghi is not None and ban_ghi.user_id == "u_dang"


async def test_doc_gia_han_ttl(redis_client):
    """TTL sliding: mỗi request có phiên hợp lệ đẩy hạn ra xa. Không có bước này
    thì người đang làm việc bị đăng xuất giữa buổi."""
    sid = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")
    await redis_client.expire(f"sess:{sid}", 60)  # giả lập phiên gần hết hạn

    await ss.doc(redis_client, sid)

    assert await redis_client.ttl(f"sess:{sid}") > 60


async def test_doi_workspace_giu_ttl_dang_co(redis_client):
    """Đổi workspace KHÔNG được là một lần gia hạn ngầm — nếu không thì bấm qua
    lại giữa hai workspace là một phiên không bao giờ hết hạn."""
    sid = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")
    await redis_client.expire(f"sess:{sid}", 60)

    await ss.doi_workspace(redis_client, sid, "sunrise")

    assert 0 < await redis_client.ttl(f"sess:{sid}") <= 60


async def test_doi_workspace_tren_phien_khong_ton_tai_la_loi(redis_client):
    """Im lặng bỏ qua nghĩa là người dùng bấm đổi workspace, không có gì xảy ra,
    và không ai biết vì sao."""
    with pytest.raises(KeyError):
        await ss.doi_workspace(redis_client, "khong-ton-tai", "sunrise")


async def test_ban_ghi_khong_chua_quyen(redis_client):
    """BR-Q04 viết thành test. Thêm `role`/`actions` vào bản ghi phiên là làm cho
    việc gỡ membership không có hiệu lực tới khi phiên hết hạn — và không ai thấy.
    """
    sid = await ss.tao(redis_client, user_id="u_a", tenant_id="anphu")
    tho = await redis_client.get(f"sess:{sid}")

    assert "role" not in tho and "action" not in tho
