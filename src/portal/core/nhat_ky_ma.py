"""Sổ mã hành động của `control.audit_log` — NGUỒN cho `contracts/audit-actions.json`.

Các điểm ghi (`core/nhat_ky.py` được gọi ở 9 module) vẫn dùng literal; sổ này
KHÔNG được import vào điểm ghi — nó là danh mục để FE dịch nhãn, không phải enum
cưỡng chế. `tests/unit/test_nhat_ky_ma.py` quét AST giữ hai bên khớp nhau: thêm
một điểm ghi với mã mới mà quên thêm vào đây ⇒ đỏ; xoá điểm ghi mà để mã lại ⇒ đỏ.

Thêm mã: thêm vào đúng nhóm dưới đây, chạy `make contracts`, copy artefact sang
repo FE, thêm nhãn vào `features/platform/so-hanh-dong.ts` (FE có cổng parity).

`MA_HANH_DONG` là tập SỐNG — mã còn ít nhất một điểm ghi thật trong `src/portal`
hôm nay (`test_so_khong_co_ma_chet` quét đúng tập này). Khi một điểm ghi bị BỎ
(xoá route, đổi tên mã, gộp hành động), mã của nó không được xoá khỏi sổ — bảng
`control.audit_log` chỉ ghi thêm nên hàng cũ mang mã đó CÒN NẰM LẠI mãi, và FE
vẫn phải dịch được nhãn cho những hàng lịch sử đó. Luật: CHUYỂN mã đó xuống
`MA_DA_NGHI_HUU`, đừng xoá. Hai tập này RỜI NHAU (`test_hai_tap_roi_nhau`) và
artefact `contracts/audit-actions.json` sinh từ `MA_TAT_CA` (hợp của cả hai) —
FE dịch cả lịch sử, không chỉ mã đang ghi hôm nay.
"""

from typing import Final

MA_HANH_DONG: Final[frozenset[str]] = frozenset(
    {
        # ── agent · khoá đấu nối (modules/enrollment) ──
        "agent.cap_phat",
        "agent.dat_trang_thai_khoa",
        "agent.feedback",  # actor = 'agent' — khách chấm điểm qua gateway
        "agent.phat_khoa",
        "agent.runtime_credentials",  # actor = 'agent' — hành động MÁY, màn ẩn mặc định
        "agent.thu_hoi_khoa",
        "agent.xoay_bi_mat",
        "agent.xoay_khoa",
        # ── agent_config (modules/config) ──
        "agent_config.luu",  # 0966 — Lưu = áp dụng ngay, mọi role
        # ⚠ `agent_config.publish` KHÔNG còn điểm ghi nhật ký (0966), nhưng CÙNG CHUỖI là
        # mã QUYỀN `ACTIONS.AGENT_CONFIG_PUBLISH` (`core/auth/actions.py`) — cổng quét
        # literal thấy nó và coi là còn sống. Để ở tập sống thay vì nghỉ hưu; FE dịch được
        # cả hai cách vì artefact sinh từ hợp của hai tập.
        "agent_config.publish",
        # ── billing ──
        "billing.price_version_kich_hoat",
        # ── ingest · cổng nạp ──
        "ingest.nghi_mat_tich",
        "ingest.tenant_im_lang",  # job đối soát, actor = "cron" — cảnh báo cho NGƯỜI đọc
        "ingest.token_tao",
        "ingest.token_xoa",
        # ── conflict · cảnh báo mâu thuẫn dữ liệu (modules/kb/conflicts) ──
        "conflict.dismiss",
        "conflict.scan",
        # ── kb ──
        "kb.delete",
        "kb.upload",
        # ── kb_web · màn «Dữ liệu ngoài» (modules/kb/web) ──
        "kb_web.chay",  # bấm «Chạy ngay» / «Viết lại hồ sơ» / «Áp dụng chủ đề»
        "kb_web.chu_de_sua",
        "kb_web.chu_de_them",
        "kb_web.chu_de_xoa",
        "kb_web.gioi_han_sua",
        "kb_web.ho_so_sua",  # ẩn/hiện mục, loại/dùng lại bài
        "kb_web.lich_sua",
        "kb_web.nguon_sua",
        "kb_web.nguon_them",
        "kb_web.nguon_xoa",
        # ── linh_vuc ──
        "linh_vuc.bat",
        "linh_vuc.tat",
        # ── nhan_vat (người dẫn lip sync tự tạo) ──
        "nhan_vat.chon",
        "nhan_vat.tao",
        "nhan_vat.thu_lai",
        "nhan_vat.xoa",
        # ── owner (cli/seed_owner) ──
        "owner.bootstrap",
        # ── realestate ──
        "realestate.building.create",
        "realestate.building.delete",
        "realestate.building.update",
        "realestate.document.approve",
        "realestate.document.create",
        "realestate.document.delete",
        "realestate.document.update",
        "realestate.knowledge.sync",
        "realestate.media.create",
        "realestate.media.delete",
        "realestate.media.draft_caption",
        "realestate.media.update",
        "realestate.project.create",
        "realestate.project.delete",
        "realestate.project.update",
        "realestate.unit.create",
        "realestate.unit.delete",
        "realestate.unit.update",
        "realestate.upload",
        "realestate.zone.create",
        "realestate.zone.delete",
        "realestate.zone.update",
        # ── role (modules/auth/quan_tri_vai_tro) ──
        "role.sua",
        "role.tao",
        "role.xoa",
        # ── role_config (modules/config) — role NGƯỜI DÙNG AGENT, khác `role.*` (vai trò thành viên) ──
        "role_config.sua",  # đổi tên và/hoặc icon
        "role_config.tao",
        "role_config.xoa",
        # ── playbook (modules/playbook) — kịch bản sale theo workspace (đợt 2) ──
        "playbook.ap_dung",
        "playbook.luu",
        "playbook.role_dung",
        # ── thanh_vien (modules/auth/thanh_vien) ──
        "thanh_vien.doi_vai_tro",
        "thanh_vien.go",
        "thanh_vien.gui_lai_moi",
        "thanh_vien.moi",
        "thanh_vien.moi_lai",
        "thanh_vien.thu_hoi_moi",
        # ── user (modules/auth) — phần lớn ghi_he_thong, tenant_id NULL ──
        "user.dang_ky",
        "user.dang_ky_google",
        "user.dang_nhap_google",
        "user.doi_mat_khau",
        "user.lien_ket_google",
        "user.moi_lai",
        "user.nhan_moi",
        "user.nhan_moi_ws",
        "user.sua",
        "user.sua_ho_so",
        "user.tao",
        "user.tao_tu_loi_moi",
        "user.xoa_loi_moi",
        # ── workspace ──
        "workspace.doi_ten",
        "workspace.tao",
        "workspace.xoa",
    }
)

MA_DA_NGHI_HUU: Final[frozenset[str]] = frozenset(
    {
        # ── Không còn điểm ghi nào trong src, nhưng CÒN HÀNG trong control.audit_log
        # (đo trên DB dev 2026-08-25: 9/26 mã distinct, 23/195 hàng). Bảng chỉ ghi
        # thêm nên chúng ở lại mãi; FE vẫn phải dịch được. Tập này KHÔNG bị cổng
        # «mã chết» quét, và PHẢI rời với MA_HANH_DONG (test canh). Khi bỏ một điểm
        # ghi: chuyển mã từ MA_HANH_DONG xuống đây, đừng xoá.
        "agent.bat_khoa",  # → agent.dat_trang_thai_khoa
        "agent.tat_khoa",  # → agent.dat_trang_thai_khoa
        "agent_config.rollback",  # 0966 bỏ lịch sử version, không còn quay lui
        "realestate.import.mapping.create",  # importer bỏ ~15/08/2026
        "realestate.import.preview",
        "realestate.import.probe",
        "realestate.import.push",
        "realestate.import.run",
        "workspace.token.create",  # → ingest.token_tao
        "workspace.token.revoke",  # → ingest.token_xoa
    }
)
"""Mã đã nghỉ hưu — xem chú thích trong tập."""

MA_TAT_CA: Final[frozenset[str]] = MA_HANH_DONG | MA_DA_NGHI_HUU
"""Thứ đi vào contracts/audit-actions.json: FE dịch cả lịch sử, không chỉ hiện tại."""
