/**
 * Dữ liệu MINH HOẠ của trang `/`. Không phải dữ liệu thật, không gọi API nào.
 *
 * Để riêng một tệp chứ không rải trong JSX vì hai lẽ:
 *  · Trang `/` nằm NGOÀI `_app`, tức ngoài `SessionProvider`. Ở đó không có
 *    workspace nào, nên mọi thứ hiện ra bắt buộc phải là hằng số viết sẵn —
 *    tệp riêng làm điều đó nhìn thấy được, thay vì trông như dữ liệu đã fetch.
 *  · Đây là chỗ marketing sẽ sửa câu chữ. Họ không phải mở component ra tìm.
 *
 * ⚠ NHÃN NGHIỆP VỤ, KHÔNG PHẢI TÊN HÀM. AG_01 §II.3: không bao giờ hiện tên
 * hàm cho người dùng — xem `lib/tools.ts`. Bản nháp đầu của trang này in
 * `find_project` / `escalate` lên chip và đã phá đúng luật đó.
 */
import { KY_NANG_TAB_BDS, KY_NANG_TAB_CHUNG } from '@/features/agent/contracts'

/** Việc agent làm giữa lượt — hiện thành chip trong bản ghi. */
export interface Viec {
  readonly nhan: string
  /** Chi tiết phụ, mờ hơn. */
  readonly chiTiet?: string
  /** Bàn giao cho người thật — tô khác, vì nó là ngoại lệ chứ không phải một việc như mọi việc. */
  readonly banGiao?: boolean
}

export interface Luot {
  readonly ai: 'khach' | 'agent'
  readonly loi: string
  readonly viec?: readonly Viec[]
}

/**
 * Một cuộc gọi trong lĩnh vực BẤT ĐỘNG SẢN.
 *
 * Cố ý kết bằng câu hỏi chiết khấu: đó là chỗ agent PHẢI dừng và chuyển người
 * thật, và cũng là bản lề dẫn sang khối «Ranh giới» ngay bên dưới.
 *
 * ⚠ CHƯA AI DUYỆT câu phong thuỷ ở lượt 4. Hướng hợp tính theo cung phi chứ
 * không theo mệnh nạp âm, và người viết dòng này không tra. Ai nắm bộ xếp hạng
 * phong thuỷ duyệt lại hoặc đổi sang câu trung tính trước khi trang lên thật.
 */
export const CUOC_GOI: readonly Luot[] = [
  {
    ai: 'khach',
    loi: 'Alo em ơi, bên Noble Crystal còn căn hai phòng ngủ nào không em?',
  },
  {
    ai: 'agent',
    viec: [{ nhan: 'Nhận diện dự án', chiTiet: 'Noble Crystal' }, { nhan: 'Kiểm tra còn hàng' }],
    loi: 'Dạ còn 7 căn ạ. Từ 68 đến 74 mét vuông, tầng 12 tới 23. Anh cần hướng nào ạ?',
  },
  { ai: 'khach', loi: 'Anh tuổi Nhâm Tuất, em xem hướng nào hợp giúp anh.' },
  {
    ai: 'agent',
    viec: [{ nhan: 'Gợi ý căn hợp mệnh' }, { nhan: 'Gửi mặt bằng', chiTiet: '2 tệp' }],
    loi: 'Dạ có căn A-18-06 hướng Tây Bắc và B-15-02 hướng Tây ạ. Em gửi mặt bằng cho anh xem nhé?',
  },
  { ai: 'khach', loi: 'Ừ em gửi đi. Cuối tuần anh ghé xem được không?' },
  {
    ai: 'agent',
    viec: [{ nhan: 'Đặt lịch', chiTiet: 'T7 · 09:00' }, { nhan: 'Lưu thông tin khách' }],
    loi: 'Dạ em đặt 9 giờ sáng thứ Bảy tại nhà mẫu cho anh ạ.',
  },
  { ai: 'khach', loi: 'Thế giá thật bao nhiêu, có chiết khấu gì không em?' },
  {
    ai: 'agent',
    viec: [{ nhan: 'Chuyển người thật', chiTiet: 'Kinh doanh', banGiao: true }],
    loi: 'Dạ phần đó em xin phép nối máy anh Dũng bên kinh doanh ạ.',
  },
]

/** Kết quả đọng lại sau cuộc gọi — hiện dần ở chân thẻ khi bản ghi diễn xong. */
export const KET_QUA: readonly { readonly nhan: string; readonly tot: boolean }[] = [
  { nhan: '✓ Đặt lịch T7 09:00', tot: true },
  { nhan: '✓ Tạo lead', tot: true },
  { nhan: '↗ Chuyển Kinh doanh', tot: false },
]

/**
 * Tên agent ĐỔI mỗi vòng.
 *
 * `tenAgent` là trường cấu hình của TỪNG workspace (xem `features/agent/api.ts`),
 * không phải tên sản phẩm. Trang bán hàng của NobleX mà gọi một cái tên riêng
 * là bán sai thứ đang bán. Đổi tên bằng chuyển động nói được điều đó mà không
 * tốn một câu giải thích nào.
 */
export const TEN_AGENT = ['Mai', 'Ngọc', 'Thảo', 'Hương', 'Vy'] as const

/** Khách nói sao → ra dự án nào. Minh hoạ bộ khớp tên theo phát âm. */
export interface MauKhop {
  readonly noi: string
  readonly ra: string
  /** 0–1. Hiện bằng chiều dài thanh, KHÔNG hiện thành số — điểm khớp là thứ nội bộ. */
  readonly chac: number
  /** Dưới ngưỡng: agent hỏi lại thay vì đoán. */
  readonly hoiLai?: boolean
}

export const MAU_KHOP: readonly MauKhop[] = [
  { noi: 'bên nâu-bồ cờ-rít-tồ ấy em', ra: 'Noble Crystal Residence', chac: 0.94 },
  { noi: 'dự án su-shai bên Long Biên', ra: 'Sunshine Long Biên', chac: 0.88 },
  { noi: 'cái a-lu-vi-a ở Sài Gòn', ra: 'Alluvia', chac: 0.96 },
  // Dòng quan trọng nhất của khối: «Sunshine» trần khớp nhiều dự án nên máy
  // KHÔNG chọn đại. Đây là chỗ bán được niềm tin.
  { noi: 'bên Sunshine ấy', ra: 'Hỏi lại cho chắc', chac: 0.41, hoiLai: true },
]

/**
 * Kỹ năng in trên trang = ĐÚNG sổ của màn `/agent` (`lib/tools.ts`, chia nhóm ở
 * `features/agent/kyNang.ts`) — không chép tay nữa: bản chép tay cũ còn «12 việc» và
 * ba tên đã nghỉ sau đợt gộp tool 09/2026. Tách nhóm chung khỏi nhóm lĩnh vực là
 * phân biệt quan trọng nhất của màn Agent (xem đầu `lib/nav-registry.ts`).
 *
 * `analyze_projects` KHÔNG lên trang công khai: sổ ghi nó chưa an toàn để bật cho
 * tenant thật — cùng lẽ lĩnh vực Tài chính không được quảng cáo.
 */
const CHUA_QUANG_CAO = new Set(['analyze_projects'])

/** Một kỹ năng chung để TẮT trong minh hoạ — cho thấy bật/tắt là quyền của người dùng. */
const TAT_MINH_HOA = 'update_customer'

export const KY_NANG_CHUNG: readonly { readonly nhan: string; readonly bat: boolean }[] =
  KY_NANG_TAB_CHUNG.map((k) => ({ nhan: k.nhan, bat: k.ten !== TAT_MINH_HOA }))

export const KY_NANG_BDS: readonly string[] = KY_NANG_TAB_BDS.filter(
  (k) => !CHUA_QUANG_CAO.has(k.ten),
).map((k) => k.nhan)

/** Số «việc agent làm được» ở dải số — đếm từ hai danh sách trên, không gõ tay. */
export const SO_KY_NANG = KY_NANG_CHUNG.length + KY_NANG_BDS.length
