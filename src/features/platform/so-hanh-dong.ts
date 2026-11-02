/**
 * Sổ mã hành động của nhật ký → nhãn tiếng Việt + nhóm lọc.
 *
 * Mã là chuỗi kỹ thuật BE ghi vào `control.audit_log.hanh_dong` (hai lối đặt
 * tên lẫn nhau: `thanh_vien.go` · `realestate.project.update`). Nguồn danh sách:
 * `contracts/audit-actions.json` (copy từ BE, sinh từ `core/nhat_ky_ma.py`).
 * Cổng `tests/audit-actions-parity.test.ts` giữ ba điều: mọi mã có nhãn · sổ
 * không có mã lạ · tiền tố của mọi mã thuộc đúng một nhóm dưới đây.
 *
 * NHÓM LỌC gộp NHIỀU tiền tố (thành viên = `thanh_vien` + `user` + `role` +
 * `owner`): người dùng hỏi «ai đụng vào thành viên», không hỏi theo tên module.
 * API nhận danh sách tiền tố cách nhau dấu phẩy (`?nhom=a,b`), nên gộp ở đây
 * không tốn gì phía BE.
 */

export const NHAN_HANH_DONG: Readonly<Record<string, string>> = {
  'agent.cap_phat': 'Cấp phát agent',
  'agent.dat_trang_thai_khoa': 'Bật/tắt khoá agent',
  'agent.feedback': 'Gửi phản hồi về agent',
  'agent.phat_khoa': 'Tạo khoá agent',
  'agent.runtime_credentials': 'Agent lấy credential',
  'agent.thu_hoi_khoa': 'Thu hồi khoá agent',
  'agent.xoay_bi_mat': 'Xoay bí mật agent',
  'agent.xoay_khoa': 'Xoay khoá agent',
  'agent_config.luu': 'Lưu cấu hình agent',
  'agent_config.publish': 'Xuất bản cấu hình agent',
  'agent_config.rollback': 'Quay lui cấu hình agent',
  'billing.price_version_kich_hoat': 'Kích hoạt bảng giá',
  'conflict.dismiss': 'Bỏ qua cảnh báo mâu thuẫn',
  'conflict.scan': 'Kiểm tra mâu thuẫn dữ liệu',
  'ingest.nghi_mat_tich': 'Bản ghi nghi mất tích (đối soát cổng nạp)',
  'ingest.tenant_im_lang': 'Cổng nạp im lặng (cảnh báo)',
  'ingest.token_tao': 'Tạo token nạp dữ liệu',
  'ingest.token_xoa': 'Xoá token nạp dữ liệu',
  'kb.delete': 'Xoá tài liệu kiến thức',
  'kb.upload': 'Tải lên tài liệu kiến thức',
  'kb_web.chay': 'Chạy cập nhật dữ liệu ngoài',
  'kb_web.chu_de_sua': 'Sửa chủ đề dữ liệu ngoài',
  'kb_web.chu_de_them': 'Thêm chủ đề dữ liệu ngoài',
  'kb_web.chu_de_xoa': 'Xoá chủ đề dữ liệu ngoài',
  'kb_web.gioi_han_sua': 'Sửa giới hạn chi phí dữ liệu ngoài',
  'kb_web.ho_so_sua': 'Ẩn mục / loại bài trong hồ sơ dự án',
  'kb_web.lich_sua': 'Sửa lịch dữ liệu ngoài',
  'kb_web.nguon_sua': 'Sửa nguồn dữ liệu ngoài',
  'kb_web.nguon_them': 'Thêm nguồn dữ liệu ngoài',
  'kb_web.nguon_xoa': 'Xoá nguồn dữ liệu ngoài',
  'linh_vuc.bat': 'Bật lĩnh vực',
  'linh_vuc.tat': 'Tắt lĩnh vực',
  'nhan_vat.chon': 'Đổi người dẫn',
  'nhan_vat.tao': 'Tạo người dẫn',
  'nhan_vat.thu_lai': 'Dựng lại người dẫn',
  'nhan_vat.xoa': 'Xoá người dẫn',
  'owner.bootstrap': 'Khởi tạo chủ workspace',
  'playbook.ap_dung': 'Áp dụng mẫu kịch bản',
  'playbook.luu': 'Lưu kịch bản',
  'playbook.role_dung': 'Đổi role dùng kịch bản',
  'realestate.building.create': 'Thêm toà',
  'realestate.building.delete': 'Xoá toà',
  'realestate.building.update': 'Sửa toà',
  'realestate.document.approve': 'Duyệt tài liệu dự án',
  'realestate.document.create': 'Thêm tài liệu dự án',
  'realestate.document.delete': 'Xoá tài liệu dự án',
  'realestate.document.update': 'Sửa tài liệu dự án',
  'realestate.knowledge.sync': 'Đồng bộ kiến thức dự án',
  'realestate.media.create': 'Thêm media',
  'realestate.media.delete': 'Xoá media',
  'realestate.media.draft_caption': 'Soạn caption media',
  'realestate.media.update': 'Sửa media',
  'realestate.project.create': 'Thêm dự án',
  'realestate.project.delete': 'Xoá dự án',
  'realestate.project.update': 'Sửa dự án',
  'realestate.unit.create': 'Thêm căn',
  'realestate.unit.delete': 'Xoá căn',
  'realestate.unit.update': 'Sửa căn',
  'realestate.upload': 'Nhập tệp dữ liệu BĐS',
  'realestate.zone.create': 'Thêm phân khu',
  'realestate.zone.delete': 'Xoá phân khu',
  'realestate.zone.update': 'Sửa phân khu',
  'role.sua': 'Sửa vai trò',
  'role.tao': 'Tạo vai trò',
  'role.xoa': 'Xoá vai trò',
  // Role NGƯỜI DÙNG AGENT (backend `0967`) — khác `role.*` ở trên (vai trò thành viên).
  'role_config.sua': 'Sửa role agent',
  'role_config.tao': 'Thêm role agent',
  'role_config.xoa': 'Xoá role agent',
  'thanh_vien.doi_vai_tro': 'Đổi vai trò thành viên',
  'thanh_vien.go': 'Gỡ thành viên',
  'thanh_vien.gui_lai_moi': 'Gửi lại lời mời',
  'thanh_vien.moi': 'Mời thành viên',
  'thanh_vien.moi_lai': 'Mời lại thành viên',
  'thanh_vien.thu_hoi_moi': 'Thu hồi lời mời',
  'user.dang_ky': 'Đăng ký tài khoản',
  'user.dang_ky_google': 'Đăng ký bằng Google',
  'user.dang_nhap_google': 'Đăng nhập bằng Google',
  'user.doi_mat_khau': 'Đổi mật khẩu',
  'user.lien_ket_google': 'Liên kết Google',
  'user.moi_lai': 'Mời lại người dùng',
  'user.nhan_moi': 'Nhận lời mời',
  'user.nhan_moi_ws': 'Nhận lời mời vào workspace',
  'user.sua': 'Sửa người dùng',
  'user.sua_ho_so': 'Sửa hồ sơ',
  'user.tao': 'Tạo người dùng',
  'user.tao_tu_loi_moi': 'Tạo tài khoản từ lời mời',
  'user.xoa_loi_moi': 'Xoá lời mời',
  'workspace.doi_ten': 'Đổi tên workspace',
  'workspace.tao': 'Tạo workspace',
  'workspace.xoa': 'Xoá workspace',
  // ── Mã ĐÃ NGHỈ HƯU (BE `MA_DA_NGHI_HUU`): không còn điểm ghi nhưng còn hàng trong
  // lịch sử audit_log — vẫn phải dịch. Hậu tố «(cũ)» để người đọc biết đây là
  // luồng đã bỏ, không đi tìm màn tương ứng.
  'agent.bat_khoa': 'Bật khoá agent (cũ)',
  'agent.tat_khoa': 'Tắt khoá agent (cũ)',
  'realestate.import.mapping.create': 'Tạo ánh xạ nhập tệp (cũ)',
  'realestate.import.preview': 'Xem trước nhập tệp (cũ)',
  'realestate.import.probe': 'Dò tệp nhập (cũ)',
  'realestate.import.push': 'Đẩy dữ liệu nhập tệp (cũ)',
  'realestate.import.run': 'Chạy nhập tệp (cũ)',
  'workspace.token.create': 'Tạo token nạp (cũ)',
  'workspace.token.revoke': 'Thu hồi token nạp (cũ)',
}

export interface NhomLoc {
  /** Giá trị `<option>` — chỉ sống trong FE, KHÔNG gửi lên API. */
  readonly ma: string
  readonly nhan: string
  /** Tiền tố `hanhDong` (phần trước dấu chấm đầu) gộp vào nhóm này — gửi `?nhom=a,b`. */
  readonly tienTo: readonly string[]
}

export const NHOM_LOC: readonly NhomLoc[] = [
  {
    ma: 'thanh-vien',
    nhan: 'Thành viên & vai trò',
    tienTo: ['thanh_vien', 'user', 'role', 'owner'],
  },
  { ma: 'agent', nhan: 'Agent & khoá', tienTo: ['agent'] },
  {
    ma: 'cau-hinh',
    nhan: 'Cấu hình agent',
    tienTo: ['agent_config', 'role_config', 'playbook', 'nhan_vat'],
  },
  { ma: 'kien-thuc', nhan: 'Kiến thức', tienTo: ['kb'] },
  { ma: 'du-lieu-ngoai', nhan: 'Dữ liệu ngoài', tienTo: ['kb_web'] },
  { ma: 'bds', nhan: 'Dữ liệu BĐS', tienTo: ['realestate', 'conflict'] },
  { ma: 'linh-vuc', nhan: 'Lĩnh vực', tienTo: ['linh_vuc'] },
  { ma: 'workspace', nhan: 'Workspace', tienTo: ['workspace'] },
  { ma: 'cong-nap', nhan: 'Cổng nạp', tienTo: ['ingest'] },
  { ma: 'bang-gia', nhan: 'Bảng giá', tienTo: ['billing'] },
]

/** Nhãn tiếng Việt; mã chưa có nhãn hiện NGUYÊN mã — cổng parity làm ca này không xảy ra với mã đã biết. */
export function nhanHanhDong(ma: string): string {
  return NHAN_HANH_DONG[ma] ?? ma
}

export function tienToCua(ma: string): string {
  return ma.split('.')[0] ?? ma
}
