/**
 * Fake của M7 — spec §4②: mỗi module ship kèm fake để module khác dev được mà
 * không cần backend chạy.
 *
 * Dữ liệu giả cố ý mang đủ ca biên mà màn phải chịu được: một khách không tên,
 * nhóm «Chưa có số», một phiên 0 lượt, một `role` lạ, một phiên `ketThuc` NULL,
 * và một cuộc gọi tool THẬT (chốt 07/08 — hai hàng `assistant` rỗng + `tool`,
 * ghép bằng `tool_call_id`, không phải một hàng như bản trước đó tưởng).
 * Fake chỉ có ca đẹp thì màn thật vỡ ở đúng những chỗ fake không đi tới.
 */
import { http, HttpResponse } from 'msw'
import type {
  Ca,
  ChanDung,
  ChiTietPhien,
  GhiChu,
  Luot,
  Overview,
  Phien,
  TrangKhach,
} from '@/features/ops/api'
import { avatarGia } from '@/lib/msw/avatarGia'
import { DIEM_TRUNG_BINH_GIA, PHAN_BO_SAO_GIA, TONG_DANH_GIA_GIA } from '@/lib/msw/danhGiaGia'

/** Một khách MỘT avatar ở mọi màn — mọi hàng fake mang tên 'Nguyễn Minh Anh'
 *  dùng chung giá trị này, đúng bất biến backend (seed = tên). */
const AVATAR_ANH_GIA = avatarGia('N')

const KHACH_GIA: TrangKhach = {
  tongKhach: 3,
  tongPhien: 5,
  items: [
    {
      phone: '0912448111',
      ten: 'Nguyễn Minh Anh',
      avatar: AVATAR_ANH_GIA,
      soPhien: 3,
      ganNhat: '2026-07-27T14:22:00+07:00',
      dauTien: '2026-07-14T16:40:00+07:00',
      daChuyen: true,
      summaryCuoi:
        'Hỏi căn 3PN dưới 6 tỷ ở Ocean Park 2. Đã chốt lịch xem nhà 10:00 thứ Bảy 01/08.',
      duAn: 'OCEAN_PARK_2',
      tenDuAn: 'Ocean Park 2',
      leadStage: 'hen_gap',
      leadScore: 90,
      audience: 'end_user',
    },
    {
      phone: '0987112222',
      ten: null,
      soPhien: 1,
      ganNhat: '2026-07-26T11:30:00+07:00',
      dauTien: '2026-07-26T11:30:00+07:00',
      daChuyen: false,
      summaryCuoi: null,
      duAn: null,
      tenDuAn: null,
      leadStage: 'mql',
      leadScore: 65,
      audience: null,
    },
    {
      phone: '',
      ten: null,
      soPhien: 1,
      ganNhat: '2026-07-26T09:14:00+07:00',
      dauTien: '2026-07-26T09:14:00+07:00',
      daChuyen: false,
      summaryCuoi: 'Khách chưa để lại số điện thoại.',
      duAn: null,
      tenDuAn: null,
      leadStage: null,
      leadScore: null,
      audience: null,
    },
  ],
}

// Khai TÊN cho từng phiên (không đọc lại bằng chỉ số mảng): `tsconfig` bật
// `noUncheckedIndexedAccess`, nên `PHIEN_GIA['...'][0]` có kiểu `Phien | undefined`
// — đúng cả về nghĩa (`Record` không đảm bảo khoá tồn tại). `CHI_TIET_GIA` dưới
// đây cần đúng CÙNG đối tượng `Phien` với `PHIEN_GIA` (một nguồn, không lặp hai
// bản có thể lệch nhau), nên khai hằng số riêng rồi dùng lại ở cả hai bàn.
const PHIEN_ANH_1: Phien = {
  sessionId: 's-anh-1',
  phone: '0912448111',
  ten: 'Nguyễn Minh Anh',
  avatar: AVATAR_ANH_GIA,
  batDau: '2026-07-27T14:22:00+07:00',
  ketThuc: '2026-07-27T14:23:48+07:00',
  soLuot: 6,
  // Cùng nội dung với `luot[0]` của `CHI_TIET_GIA['s-anh-1']` bên dưới — cố ý dài
  // hơn một dòng của cột 300px, để cổng bằng mắt cho `truncate` (PhienKhach.tsx)
  // có ca thật để cắt, không chỉ có ca đẹp vừa khít.
  tinNhanDau: 'Còn căn nào 3 phòng ngủ dưới 6 tỷ ở Ocean Park 2 không em?',
  summary: 'Hỏi căn 3PN dưới 6 tỷ, chốt lịch xem nhà.',
  duAn: 'OCEAN_PARK_2',
  tenDuAn: 'Ocean Park 2',
  daChuyen: true,
  runningVersion: 12,
  source: 'chat',
  leadStage: 'hen_gap',
  leadScore: 90,
  audience: 'end_user',
}

const PHIEN_ANH_2: Phien = {
  sessionId: 's-anh-2',
  phone: '0912448111',
  ten: 'Nguyễn Minh Anh',
  avatar: AVATAR_ANH_GIA,
  batDau: '2026-07-21T09:10:00+07:00',
  ketThuc: null,
  soLuot: 0,
  tinNhanDau: null,
  summary: null,
  duAn: null,
  tenDuAn: null,
  daChuyen: false,
  runningVersion: null,
  source: 'voice',
  leadStage: 'sql',
  leadScore: 70,
  audience: 'end_user',
}

const PHIEN_GIA: Record<string, Phien[]> = {
  '0912448111': [PHIEN_ANH_1, PHIEN_ANH_2],
  _: [
    {
      sessionId: 's-an-1',
      phone: null,
      ten: null,
      batDau: '2026-07-26T09:14:00+07:00',
      ketThuc: '2026-07-26T09:15:10+07:00',
      soLuot: 2,
      tinNhanDau: 'Cho em hỏi bên mình còn căn nào view hồ không ạ?',
      summary: 'Khách chưa để lại số điện thoại.',
      duAn: null,
      tenDuAn: null,
      daChuyen: false,
      runningVersion: 12,
      // `source` chưa biết — agent phiên bản cũ (trước 0916) không gửi trường
      // này. Cổng bằng mắt cho "null CHỈ hiện ở tab Tất cả" (PhienKhach.tsx).
      source: null,
    },
  ],
}

const CHI_TIET_GIA: Record<string, ChiTietPhien> = {
  's-anh-1': {
    phien: PHIEN_ANH_1,
    luot: [
      {
        seq: 0,
        role: 'user',
        content: 'Còn căn nào 3 phòng ngủ dưới 6 tỷ ở Ocean Park 2 không em?',
        taoLuc: '2026-07-27T14:22:03+07:00',
        meta: {},
      },
      // Hai hàng dưới đây là MỘT cuộc gọi tool thật, đúng hình dạng team agent
      // ghi: hàng `assistant` content RỖNG mang `meta.tool_calls` (yêu cầu gọi),
      // rồi hàng `tool` mang kết quả — khớp nhau bằng `tool_call_id` === `id`.
      // `Transcript.tsx` ghép hai hàng này thành một khối, không hiện riêng.
      {
        seq: 1,
        role: 'assistant',
        content: '',
        taoLuc: '2026-07-27T14:22:31+07:00',
        meta: {
          tool_calls: [
            {
              id: 'call-search-units-1',
              type: 'function',
              function: {
                name: 'search_units',
                arguments: '{"project":"VOP2","max_price":6000000000,"bedrooms":3}',
              },
            },
          ],
        },
      },
      {
        seq: 2,
        role: 'tool',
        content: '{"total":4,"unit_ids":[101,102,103,104]}',
        taoLuc: '2026-07-27T14:22:32+07:00',
        meta: { name: 'search_units', tool_call_id: 'call-search-units-1' },
      },
      {
        seq: 3,
        role: 'assistant',
        content:
          'Dạ hiện Ocean Park 2 còn 4 căn 3PN dưới 6 tỷ ạ. Gần nhất là NT2-1408, 78,4 m², 5,62 tỷ.',
        taoLuc: '2026-07-27T14:22:34+07:00',
        meta: {
          playbook: {
            nut: 'che_dat',
            buoc: 'b1',
            dat: false,
            thieu: ['kết nối lợi ích'],
            da_lam: ['báo giá'],
          },
        },
      },
      {
        seq: 4,
        role: 'he_thong_la',
        content: 'Một role không nằm trong ba giá trị đã biết.',
        taoLuc: '2026-07-27T14:23:00+07:00',
        meta: {},
      },
      {
        seq: 5,
        role: 'user',
        content: '10 giờ nhé em.',
        taoLuc: '2026-07-27T14:23:40+07:00',
        meta: {},
      },
    ],
    skillCalls: [],
  },
  's-anh-2': {
    phien: PHIEN_ANH_2,
    luot: [],
    // Phiên rỗng NHƯNG có skill_calls mức phiên — đúng ca mà nhánh dự phòng sinh ra
    // để phục vụ. Fake không có ca này thì nhánh đó không bao giờ chạy khi dev.
    skillCalls: ['create_appointment(slot=2026-08-01T10:00) → ok'],
  },
}

/**
 * Overview giả. Ca biên cố ý có mặt, vì màn thật vỡ ở đúng chỗ fake không đi
 * tới: một ngày 0 phiên (cuối tuần), một `kenh: null` (agent bản cũ), một mục
 * kiến thức ĐẦY (100% — nhánh nhãn "Agent đọc đủ" chỉ chạy ở đây), và
 * `danhGia.truoc = null` (kỳ trước chưa có lượt nào ⇒ ẩn mũi tên delta).
 *
 * Ngày CỐ ĐỊNH, không sinh từ `new Date()`: fake trôi theo hôm nay làm ảnh
 * chụp màn hình của hai hôm khác nhau không so được, và một test canh nhãn
 * trục sẽ đỏ vào một ngày ngẫu nhiên trong tương lai.
 *
 * ⚠️ **Thiếu `chuyenSale` là CỐ Ý** (`Omit<…>`, đổi 2026-08-14). Ô ② phải nói
 * đúng con số màn `/chuyen-sale` bày ra, mà nguồn của màn đó là `CA_GIA` —
 * khai muộn hơn trong file này. Ghép hai phần ở `OVERVIEW_DAY_DU` ngay sau
 * `CA_GIA`, thay vì gõ tay một con số thứ hai ở đây: bản cũ ghi
 * `{ chuyen: 65, tuXuLy: 237 }` trong khi `CA_GIA` chỉ có 4 ca, nên dev dưới
 * MSW thấy ô ② nói «65» rồi bấm sang màn thấy đúng 4 dòng.
 */
const OVERVIEW_GIA: Omit<Overview, 'chuyenSale'> = {
  moc: { tuNgay: '2026-08-07', tinhDen: '2026-08-13' },
  hoiThoai: {
    tong: 302,
    truoc: 266,
    theoNgay: [
      { ngay: '2026-08-07', chat: 26, voice: 17, khac: 5, tong: 48 },
      { ngay: '2026-08-08', chat: 15, voice: 22, khac: 3, tong: 40 },
      // Chủ nhật — 0 phiên. Bản trước fake không có ngày nào rỗng, nên biểu đồ
      // không bao giờ chạy qua nhánh ngày-không-có-dữ-liệu khi dev bằng fake.
      { ngay: '2026-08-09', chat: 0, voice: 0, khac: 0, tong: 0 },
      { ngay: '2026-08-10', chat: 28, voice: 17, khac: 6, tong: 51 },
      { ngay: '2026-08-11', chat: 30, voice: 17, khac: 7, tong: 54 },
      { ngay: '2026-08-12', chat: 27, voice: 16, khac: 6, tong: 49 },
      { ngay: '2026-08-13', chat: 27, voice: 17, khac: 16, tong: 60 },
    ],
    theoKenh: [
      { kenh: 'chat', n: 153 },
      { kenh: 'voice', n: 106 },
      { kenh: 'zalo_oa', n: 37 },
      { kenh: null, n: 6 },
    ],
  },
  danhGia: {
    // Ba con số này đọc NGUỒN CHUNG với fake `/agent/feedback` của module
    // `quality` — xem `lib/msw/danhGiaGia.ts`. Bản cũ gõ tay ở đây một bảng,
    // ở đó một bảng khác, và hai màn in hai điểm trung bình khác nhau.
    trungBinh: DIEM_TRUNG_BINH_GIA,
    truoc: null,
    tong: TONG_DANH_GIA_GIA,
    theoSao: PHAN_BO_SAO_GIA,
  },
  kienThuc: {
    muc: [
      { khoa: 'duAn', thay: 8, tong: 12 },
      { khoa: 'phanKhu', thay: 31, tong: 47 },
      { khoa: 'can', thay: 964, tong: 1203 },
      // `kb_files` (kho `/kb`), KHÔNG phải `documents` của từng dự án.
      { khoa: 'taiLieuTraCuu', thay: 189, tong: 214 },
      // Mẫu số 12 = `MUOI_HAI_KY_NANG.length` (`lib/tools.ts`), giống backend
      // lấy từ sổ kỹ năng chứ không viết cứng — fake nói dối con số đó thì
      // màn dev vẽ một thước đầy cho một agent chưa bật hết kỹ năng.
      { khoa: 'kyNang', thay: 7, tong: 12 },
    ],
  },
}

/**
 * Ca chuyển sale. Cố ý đủ ca biên: một ca chưa có số (sale không gọi lại được),
 * một ca `summaryLuc: null` (bản tóm tắt còn tạm), một ca hệ thống bí dữ liệu,
 * một ca `soLuot: 0` (agent ghi ca trước khi phiên chốt), và cả ba trạng thái.
 */
const CA_GIA: Ca[] = [
  {
    id: 12,
    sessionId: 's-anh-3',
    phone: '0912448111',
    ten: 'Nguyễn Minh Anh',
    avatar: AVATAR_ANH_GIA,
    duAn: 'SGI',
    tenDuAn: 'Sunshine Green Iconic',
    toolThieuDuLieu: null,
    summary:
      'Khách đã mua căn tại Sunshine Green Iconic, cần hướng dẫn thủ tục làm sổ hồng. Chưa cung cấp mã hợp đồng nên chưa tra cứu được. Khách sốt ruột vì đã chờ 3 tháng.',
    summaryLuc: '2026-07-27T14:38:11+07:00',
    messageSeq: 7,
    trangThai: 'new',
    nguoiXuLy: null,
    xuLyLuc: null,
    ghiChu: null,
    kenh: 'voice',
    soLuot: 23,
    taoLuc: '2026-07-27T14:32:11+07:00',
  },
  {
    id: 13,
    sessionId: 's-anh-3',
    phone: '0912448111',
    ten: 'Nguyễn Minh Anh',
    avatar: AVATAR_ANH_GIA,
    duAn: 'SGI',
    tenDuAn: 'Sunshine Green Iconic',
    toolThieuDuLieu: 'search_units',
    summary:
      'Khách: Nguyễn Minh Anh, SĐT: 0912448111, Dự án: SGI. Lý do chuyển: hệ thống không có dữ liệu.',
    summaryLuc: null,
    messageSeq: 15,
    trangThai: 'new',
    nguoiXuLy: null,
    xuLyLuc: null,
    ghiChu: null,
    kenh: 'voice',
    soLuot: 23,
    taoLuc: '2026-07-27T14:38:47+07:00',
  },
  {
    id: 14,
    sessionId: 's-an-1',
    phone: null,
    ten: null,
    duAn: null,
    tenDuAn: null,
    toolThieuDuLieu: null,
    summary: 'Khách hỏi chính sách vay của dự án nhưng chưa để lại tên hay số điện thoại.',
    summaryLuc: '2026-07-26T09:20:00+07:00',
    messageSeq: 4,
    trangThai: 'contacted',
    nguoiXuLy: 'Vũ Đình Khoa',
    xuLyLuc: '2026-07-26T10:02:00+07:00',
    ghiChu: 'Khách hẹn gọi lại sau 17h.',
    kenh: 'chat',
    soLuot: 6,
    taoLuc: '2026-07-26T09:14:00+07:00',
  },
  {
    id: 15,
    sessionId: 's-moi-nhat',
    phone: '0987112222',
    ten: 'Trần Bảo Long',
    duAn: 'NCR',
    tenDuAn: null,
    toolThieuDuLieu: 'analyze_projects',
    summary:
      'Khách: Trần Bảo Long, SĐT: 0987112222, Dự án: NCR. Lý do chuyển: hệ thống không có dữ liệu.',
    summaryLuc: null,
    messageSeq: 2,
    trangThai: 'done',
    nguoiXuLy: 'Lê Thu Hà',
    xuLyLuc: '2026-07-25T16:40:00+07:00',
    ghiChu: 'Đã gọi lại, khách chốt xem nhà thứ Bảy 14h. Đã gửi bảng giá qua Zalo.',
    kenh: null,
    soLuot: 0,
    taoLuc: '2026-07-25T15:02:00+07:00',
  },
]

/**
 * Overview đầy đủ — ô ② ghép vào ĐÂY, sau `CA_GIA`, vì tử số của nó phải là
 * chính số ca mà `/chuyen-sale` liệt kê.
 *
 * Đây là bản sao ở tầng fake của quyết định vừa làm ở backend cùng ngày:
 * `repo.dem_chuyen_sale` đổi tử số từ cờ `conversations.transferred_to_sales`
 * sang đếm hàng `tenant_data.escalations`. Fake mà giữ nếp cũ thì màn dưới MSW
 * vẫn nói dối đúng như trước khi sửa — và MSW là thứ chạy mặc định khi dev.
 *
 * `tuXuLy` = tổng phiên − số ca, kẹp sàn 0 y như `router.py` (hai bảng, hai
 * thời điểm ghi ⇒ tử số có thể vượt mẫu số).
 */
const OVERVIEW_DAY_DU: Overview = {
  ...OVERVIEW_GIA,
  chuyenSale: {
    chuyen: CA_GIA.length,
    tuXuLy: Math.max(0, OVERVIEW_GIA.hoiThoai.tong - CA_GIA.length),
  },
}

function locCa(trangThai: string | null): Ca[] {
  if (trangThai === 'new' || trangThai === 'contacted' || trangThai === 'done') {
    return CA_GIA.filter((c) => c.trangThai === trangThai)
  }
  if (trangThai === 'handled') return CA_GIA.filter((c) => c.trangThai !== 'new')
  return CA_GIA
}

const GHI_CHU_GIA: Record<number, GhiChu[]> = {
  12: [
    {
      id: 1,
      noiDung: 'Gọi lần 1 không nghe, nhắn Zalo rồi.',
      nguoi: 'Trần Hải Đăng',
      luc: '2026-07-27T15:10:00+07:00',
    },
    {
      id: 2,
      noiDung: 'Khách gọi lại, hẹn gửi mã hợp đồng chiều nay.',
      nguoi: 'Lê Biên Tập',
      luc: '2026-07-27T16:02:00+07:00',
    },
    {
      id: 3,
      noiDung: 'Đã nhận mã HĐ, nhờ pháp lý tra. Khách hơi gắt vì chờ 3 tháng.',
      nguoi: 'Phạm Thu Hà',
      luc: '2026-07-28T09:20:00+07:00',
    },
    {
      id: 4,
      noiDung: 'Pháp lý báo thiếu bản sao CCCD, đã gọi xin, khách gửi chiều nay.',
      nguoi: 'Vũ Đình Khoa',
      luc: '2026-07-28T14:05:00+07:00',
    },
    {
      id: 5,
      noiDung: 'Nhận đủ hồ sơ, chuyển pháp lý. Hẹn khách 5 ngày làm việc.',
      nguoi: 'u_da_nghi',
      luc: '2026-07-29T08:40:00+07:00',
    },
  ],
}

/**
 * Trích đoạn hội thoại của từng ca. Backend đã lọc sạch hàng `tool` và assistant
 * rỗng ở tầng SQL, nên fake này CHỈ chứa lượt người nói — khác hẳn `CHI_TIET_GIA`
 * ở trên, nơi cố ý giữ cặp tool_calls/tool để `Transcript` có cái mà ghép.
 *
 * Ca 15 cố ý KHÔNG có mặt: bên agent ghi transcript fire-and-forget nên lượt cuối
 * có thể chưa kịp xuống Postgres, và màn phải nói thật chứ không hiện khung trống.
 */
const TRICH_GIA: Record<number, Luot[]> = {
  12: [
    {
      seq: 3,
      role: 'user',
      content: 'Em ơi cho anh hỏi thủ tục làm sổ hồng thì cần giấy tờ gì?',
      taoLuc: '2026-07-27T14:30:02+07:00',
      meta: {},
    },
    {
      seq: 4,
      role: 'assistant',
      content: 'Dạ anh cho em xin mã hợp đồng để em tra giúp mình ạ.',
      taoLuc: '2026-07-27T14:30:28+07:00',
      meta: {},
    },
    {
      seq: 5,
      role: 'user',
      content: 'Anh không nhớ mã, anh mua căn 2 phòng ngủ toà S2 hồi tháng 4.',
      taoLuc: '2026-07-27T14:31:15+07:00',
      meta: {},
    },
    {
      seq: 6,
      role: 'user',
      content: 'Anh chờ ba tháng rồi mà chưa thấy ai báo gì cả.',
      taoLuc: '2026-07-27T14:32:04+07:00',
      meta: {},
    },
  ],
  13: [
    {
      seq: 2,
      role: 'user',
      content: 'Bên mình còn căn hai phòng ngủ nào tầm 3 tỷ không em?',
      taoLuc: '2026-07-27T15:02:11+07:00',
      meta: {},
    },
    {
      seq: 3,
      role: 'assistant',
      content: 'Dạ để em kiểm tra giúp anh ngay ạ.',
      taoLuc: '2026-07-27T15:02:29+07:00',
      meta: {},
    },
    {
      seq: 6,
      role: 'user',
      content: 'Với lại bao giờ thì bàn giao vậy em?',
      taoLuc: '2026-07-27T15:03:40+07:00',
      meta: {},
    },
  ],
  14: [
    {
      seq: 1,
      role: 'user',
      content: 'Chị muốn xem mặt bằng tầng 12 toà A.',
      taoLuc: '2026-07-26T09:14:02+07:00',
      meta: {},
    },
  ],
}

/** Backend trả 200 RỖNG (không 404) cho số agent chưa ghi gì. */
const CHAN_DUNG_RONG: ChanDung = { hoSo: {}, ghiNho: null, tinHieu: [], capNhatLuc: null }

/** Cố ý KHÔNG mang `full_name`/`name`: tên khách đã ở header, lặp ở panel làm mọi
 *  bài `findByText(<tên>)` của màn chi tiết khớp hai chỗ. */
const CHAN_DUNG_GIA: Record<string, ChanDung> = {
  '0912448111': {
    hoSo: {
      gender: 'F',
      project_interest: 'OCEAN_PARK_2',
      purpose: 'ở',
      budget: 'dưới 6 tỷ',
      bedroom_count: '3PN',
      audience: 'end_user',
      timeline: 'trong quý này',
      interest_level: 'cao',
      is_buyer: true,
      notes: 'làm ở Long Biên; con sắp vào lớp 1',
    },
    ghiNho: 'Chị tìm căn 3 phòng ngủ dưới 6 tỷ ở Ocean Park 2 để ở, đã chốt lịch xem nhà.',
    tinHieu: ['co_doi_tuong', 'co_du_an', 'co_ngan_sach', 'co_phong', 'muon_xem_nha'],
    capNhatLuc: '2026-07-28T09:00:00+07:00',
  },
}

export const opsHandlers = [
  http.get('/api/v1/escalations/:id/trich', ({ params }) => {
    const id = Number(params.id)
    if (!CA_GIA.some((c) => c.id === id)) {
      return HttpResponse.json(
        { error: { code: 'ESCALATION_NOT_FOUND', message: 'Không tìm thấy ca' } },
        { status: 404 },
      )
    }
    return HttpResponse.json(TRICH_GIA[id] ?? [])
  }),
  http.get('/api/v1/escalations/:id/notes', ({ params }) => {
    const id = Number(params.id)
    if (!CA_GIA.some((c) => c.id === id)) {
      return HttpResponse.json(
        { error: { code: 'ESCALATION_NOT_FOUND', message: 'Không tìm thấy ca' } },
        { status: 404 },
      )
    }
    return HttpResponse.json(GHI_CHU_GIA[id] ?? [])
  }),
  http.get('/api/v1/escalations', ({ request }) => {
    const u = new URL(request.url)
    const duAn = u.searchParams.get('du_an') ?? ''
    let tap = locCa(u.searchParams.get('trang_thai'))
    if (duAn) tap = tap.filter((c) => c.duAn === duAn)
    if (u.searchParams.get('sap_xep') === 'cu') tap = [...tap].reverse()
    const offset = Number(u.searchParams.get('offset') ?? 0)
    const limit = Number(u.searchParams.get('limit') ?? 10)
    return HttpResponse.json({
      items: tap.slice(offset, offset + limit),
      tongCa: tap.length,
      duAnCo: [...new Set(CA_GIA.map((c) => c.duAn).filter(Boolean))]
        .sort()
        .map((ma) => ({ ma, ten: CA_GIA.find((c) => c.duAn === ma)?.tenDuAn ?? null })),
    })
  }),
  http.patch('/api/v1/escalations/:id', async ({ params, request }) => {
    const than = (await request.json()) as { trangThai: string; ghiChu?: string }
    const i = CA_GIA.findIndex((c) => c.id === Number(params.id))
    if (i < 0) {
      return HttpResponse.json(
        { error: { code: 'ESCALATION_NOT_FOUND', message: 'Không tìm thấy ca' } },
        { status: 404 },
      )
    }
    CA_GIA[i] = {
      ...CA_GIA[i]!,
      trangThai: than.trangThai,
      nguoiXuLy: 'Bạn',
      xuLyLuc: new Date().toISOString(),
      ghiChu: than.ghiChu || CA_GIA[i]!.ghiChu,
    }
    if (than.ghiChu) {
      const ds = (GHI_CHU_GIA[Number(params.id)] ??= [])
      ds.push({
        id: ds.length + 1,
        noiDung: than.ghiChu,
        nguoi: 'Bạn',
        luc: new Date().toISOString(),
      })
    }
    return HttpResponse.json(CA_GIA[i])
  }),
  // Cắt theo `limit`/`offset` như backend; `tongKhach` vẫn là của CẢ tập
  // (backend `dem_tong`) — đó là thứ thanh phân trang của `/convos` dựa vào.
  http.get('/api/v1/convos/khach', ({ request }) => {
    const u = new URL(request.url)
    const offset = Number(u.searchParams.get('offset') ?? 0)
    const limit = Number(u.searchParams.get('limit') ?? 10)
    const stage = u.searchParams.get('lead_stage')
    if (!stage) {
      return HttpResponse.json({
        ...KHACH_GIA,
        items: KHACH_GIA.items.slice(offset, offset + limit),
      })
    }
    const loc = KHACH_GIA.items.filter((k) =>
      stage === 'none' ? !k.leadStage : k.leadStage === stage,
    )
    return HttpResponse.json({
      tongKhach: loc.length,
      tongPhien: loc.reduce((s, k) => s + k.soPhien, 0),
      items: loc.slice(offset, offset + limit),
    })
  }),
  http.get('/api/v1/convos/khach/:phone/phien', ({ params }) =>
    HttpResponse.json(PHIEN_GIA[String(params.phone)] ?? []),
  ),
  http.get('/api/v1/convos/khach/:phone/chan-dung', ({ params }) =>
    HttpResponse.json(CHAN_DUNG_GIA[String(params.phone)] ?? CHAN_DUNG_RONG),
  ),
  http.get('/api/v1/convos/phien/:sessionId', ({ params }) => {
    const ct = CHI_TIET_GIA[String(params.sessionId)]
    return ct
      ? HttpResponse.json(ct)
      : HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: 'Không tìm thấy phiên' } },
          { status: 404 },
        )
  }),
  http.get('/api/v1/overview', () => HttpResponse.json(OVERVIEW_DAY_DU)),
]
