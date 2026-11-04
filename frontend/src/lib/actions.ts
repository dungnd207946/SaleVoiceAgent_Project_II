/**
 * 13 nhóm hành động của PQ_01 §3.1 + 2 nhóm mọc thêm ngoài PQ_01, đặt tên máy
 * đọc được.
 *
 * VÌ SAO CÓ FILE NÀY: PQ_01 mô tả 13 nhóm bằng tiếng Việt, chưa đặt tên mã.
 * M2b là module chốt tên thật. Nếu mỗi nav item / mỗi endpoint tự viết chuỗi
 * `'projects.read'` thì lúc M2b chốt tên khác, phải rà lại 18 màn và bỏ sót
 * một cái là một mục nav hiện với người không có quyền.
 *
 * Nên: mọi chỗ tham chiếu ACTIONS.<x>. Đổi tên = sửa MỘT dòng ở đây.
 *
 * Số trong comment là **số dòng trong bảng PQ_01 §3.1** — đừng bỏ, nó là cách
 * kiểm 13 nhóm gốc không thiếu không thừa. `BILLING_READ` KHÔNG mang số: nó
 * mọc sau PQ_01 §3.1 (spec 2026-08-20 usage-billing-fe) để gác `/usage` ·
 * `/billing` · `/pricing` — 5 endpoint tenant của BE, tách khỏi
 * `WORKSPACE_ADMIN` đã gác nhầm hai màn đầu.
 *
 * ⚠ NGUỒN KHÔNG PHẢI FILE NÀY. Nguồn là `core/auth/actions.py` của repo backend —
 * tầng cưỡng chế thật. File này là bản sao cho FE, và `tests/actions-parity.test.ts`
 * canh nó khớp `contracts/actions.json` (artefact backend sinh ra rồi copy sang).
 * Đổi tên action: sửa bên Python TRƯỚC, `make contracts`, copy artefact sang đây,
 * rồi mới sửa file này. Xem `contracts/README.md`.
 *
 * ⚠ Tên là ĐỀ XUẤT của M2a; M2b chốt lần cuối.
 */
export const ACTIONS = {
  /** 1 · Xem Tổng quan · số liệu */
  OVERVIEW_READ: 'overview.read',
  /** 2 · Xem danh sách Hội thoại + tóm tắt */
  CONVOS_READ: 'convos.read',
  /** 3 · Đọc bản ghi thoại — quyền RIÊNG (BR-Q06), mỗi lần đọc vào nhật ký (BR-Q07) */
  CONVOS_TRANSCRIPT_READ: 'convos.transcript.read',
  /** 4 · Nhận chuyển tiếp · đánh dấu đã xử lý */
  CONVOS_HANDLE: 'convos.handle',
  /** 5 · Xem Lịch hẹn */
  APPTS_READ: 'appts.read',
  /** 6 · Sửa · huỷ Lịch hẹn */
  APPTS_WRITE: 'appts.write',
  /** 7 · Xem Dự án · Quỹ căn · Tài liệu · Media */
  CATALOG_READ: 'catalog.read',
  /** 8 · Thêm · sửa · nhập tệp Dự án · Quỹ căn · Tài liệu · Media */
  CATALOG_WRITE: 'catalog.write',
  /** 9 · Xoá dự án · quỹ căn · tài liệu · media */
  CATALOG_DELETE: 'catalog.delete',
  /** 10 · Xem cấu hình agent (chỉ đọc) */
  AGENT_CONFIG_READ: 'agent_config.read',
  /** 11 · Sửa bản nháp cấu hình agent */
  AGENT_CONFIG_WRITE: 'agent_config.write',
  /** 12 · Xuất bản · Quay lui */
  AGENT_CONFIG_PUBLISH: 'agent_config.publish',
  /** 13 · Khoá API · Thành viên · Cài đặt workspace · Yêu cầu của khách */
  WORKSPACE_ADMIN: 'workspace.admin',
  /**
   * Ngoài PQ_01 §3.1 · Xem Lượt dùng · Hoá đơn · Bảng giá (spec 2026-08-20
   * usage-billing-fe). BE gác 5 endpoint `/usage`·`/billing`·`/pricing` bằng
   * `require(ACTIONS.BILLING_READ)` — hai mục nav `usage`/`billing` TRƯỚC ĐÂY
   * gác bằng `WORKSPACE_ADMIN` (sai đối tượng, xem `features/billing/nav.ts`).
   */
  BILLING_READ: 'billing.read',
  /** 15 · Xem Nhật ký hoạt động (`/audit`). BE `0956_audit_action`, cấp mặc định
   *  cho Quản trị. Ngoài 13 nhóm gốc PQ_01 §3.1 như `BILLING_READ`. */
  AUDIT_READ: 'audit.read',
  /** 16 · Xem màn «Dữ liệu ngoài» (`/du-lieu-ngoai`). BE `0972_kb_web_actions`, cấp mặc
   *  định cho Quản trị · Biên tập · Người xem. */
  KB_WEB_READ: 'kb_web.read',
  /** 17 · Sửa nguồn / chủ đề / lịch, ẩn mục hồ sơ, bấm chạy ngay. Quản trị · Biên tập. */
  KB_WEB_WRITE: 'kb_web.write',
} as const

export type Action = (typeof ACTIONS)[keyof typeof ACTIONS]

/** Đúng 17 nhóm (13 của PQ_01 §3.1 + `billing.read` + `audit.read` + `kb_web.read`/`kb_web.write`) — `tests/nav-registry.test.ts` canh con số này. */
export const ALL_ACTIONS: readonly Action[] = Object.values(ACTIONS)
