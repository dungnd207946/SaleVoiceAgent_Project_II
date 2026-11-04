/**
 * SỔ BẢY TAB của màn `/usage` — mã component → nhãn → ĐƠN VỊ → thứ tự.
 *
 * MỘT CHỖ DUY NHẤT, và đó là điều kiện chứ không phải sở thích: rail, biểu đồ,
 * trục dọc và tooltip đều phải nói cùng một đơn vị cho cùng một tab. Bốn bản
 * chép tay sẽ lệch nhau ở lần đầu ai đó thêm một component.
 *
 * ⚠️ ĐƠN VỊ LẤY TỪ `billing.pricing_basis`, KHÔNG tự chọn. Đây là chỗ bản vẽ đã
 * sai một lần (vòng 6): nó vẽ TTS theo GIÂY và Embed theo TOKEN, trong khi
 * migration `0948` chuyển cả hai sang `text_units` — KÝ TỰ. Và công thức đối
 * chiếu của bên agent (`test_doi_chieu_cong_thuc_agent.py`) KHÔNG có vế
 * `audio_sec` nào cho `tts`, nên vẽ TTS theo giây gần như chắc chắn ra một
 * đường phẳng bằng 0 trên dữ liệu thật.
 *
 *   llm                        → input + output + cache_read   (token)
 *   call · vad · speaker_verify → audio_sec                    (giây)
 *   stt                        → wall_ms  (purpose=stream)     (giây)
 *                              + text_units (purpose=conversation), vế ĐỘC LẬP
 *   tts · embed                → text_units                    (KÝ TỰ)
 *
 * ⚠️ «KÝ TỰ» Ở TRÊN LÀ SỰ THẬT VỀ DỮ LIỆU, KHÔNG PHẢI NHÃN TRÊN MÀN. Ba chỗ đo
 * `text_units` (TTS · Embed · đường 2 của STT) đều bày nhãn **«token»** —
 * người dùng chốt 2026-08-25. Migration `0948` và `billing.metric`
 * (`('text_units','Ký tự text',…,'character')`) nói đó là KÝ TỰ; giữ dòng này
 * để người đọc code không suy ngược từ nhãn ra dữ liệu.
 *
 * ⚠️ STT ĐỔI VẾ THỜI LƯỢNG `audio_sec` → `wall_ms` NGÀY 2026-08-25 (người dùng
 * chốt). `pricing_basis` khai HAI dòng và ghi «CHỌN MỘT» cho cặp thời lượng:
 * `stt/conversation/audio_sec` (giây khách thực nói) vs `stt/stream/wall_ms`
 * (thời gian stream mở). Bản đầu chọn `audio_sec` — đó là SUY LUẬN của người
 * viết, không có tài liệu nào chỉ định; §7 của spec đã ghi nó thành rủi ro đã
 * biết và hẹn tách theo `purpose` ở vòng sau. Vòng sau chính là đây.
 *
 * ⚠️ HỆ QUẢ PHẢI BIẾT: `audio_sec` của `stt` nay KHÔNG còn hiện ở đâu trên màn,
 * mà theo bảng giá trên DB dev thì nó mới là vế THU TIỀN — `stt/conversation/
 * audio_sec` có `unit_price` 2,6/4,8/6,0 còn MỌI dòng `stt/stream/wall_ms` đều
 * `unit_price = 0`, và `billing.purpose` ghi thẳng «stream … giá 0 vì STT thu
 * theo giây». Chấp nhận được vì `/usage` là màn LƯỢNG chứ không phải màn TIỀN,
 * nhưng đừng suy từ con số dẫn của tab này ra chi phí.
 *
 * ⚠️ `speaker_verify` là mã THẬT trong `billing.usage_events.component` — không
 * phải `sv`. Bản vẽ dùng `sv` cho ngắn; đừng mang nó vào code.
 *
 * ⚠️ MỘT TAB = MỘT COMPONENT. Đừng thêm một tab «tổng audio», và đừng gộp hai
 * chặng lại «cho đỡ nhiều tab» — luật «không cộng chéo `audio_sec`» được thi
 * hành ở đây bằng kiến trúc: không tab nào chứa hai component thì cũng không
 * tab nào cộng được `audio_sec` của hai component.
 *
 * ⚠️ MỘT TAB CÓ THỂ CÓ ĐƯỜNG THỨ HAI (`duong2`) — và ĐÚNG MỘT tab dùng: `stt`.
 * Bản đầu của sổ này viết «một tab = một đường, không ngoại lệ», và câu đó vừa
 * quá chặt vừa canh sai chỗ. Cái phải cấm là CỘNG hai số đo lại, không phải bày
 * chúng cạnh nhau: migration `0948` nói rõ vế ký tự của `stt` là ĐỘC LẬP và
 * CỘNG THÊM vào vế thời lượng (vendor kiểu Soniox thu hai đồng hồ — audio vào
 * và text ra), nên giấu nó đi là bỏ mất một nửa thứ khách trả tiền.
 *
 * Ba điều kiện của một `duong2`, đủ để phép cộng sai KHÔNG viết ra được:
 *   1. Nó mang ĐƠN VỊ RIÊNG (`donVi`) — hai đơn vị khác nhau thì không có phép
 *      cộng nào hợp lệ để mà lỡ tay viết.
 *   2. Nó ở CHUỖI RIÊNG (`ChuoiTab.gia2`), không trộn vào `gia`.
 *   3. Nó có TRỤC RIÊNG bên phải. Dùng chung trục là ép hai thang về một, tức
 *      chính là cộng — chỉ là cộng bằng mắt: 431 giây và 1.887 ký tự trên cùng
 *      một trục thì đường giây nằm bẹp dưới đáy.
 *
 * ⚠️ THỨ TỰ do người dùng chốt (2026-08-24) — đừng sắp lại theo độ lớn: xếp
 * theo con số thì đổi kỳ là các tab đổi chỗ, và người dùng mất khả năng nhớ
 * «STT nằm thứ hai».
 */
import { SO, giay, token } from './dinh-dang'
import type { PhanUsageNgay } from './kieu'

/** Đơn vị của một tab. `so` dành cho phép đếm trần (chưa tab nào dùng — giữ vì
 *  `so_event` là số đo có thật của mọi component, ngày nào cần thì đã có chỗ). */
export type DonVi = 'token' | 'giay' | 'so'

/**
 * Đường thứ hai của một tab — số đo ĐỘC LẬP, đơn vị RIÊNG, trục RIÊNG.
 * Xem ba điều kiện ở đầu tệp. Chỉ `stt` có.
 */
export interface DuongPhu {
  /** Nhãn của ĐƯỜNG 2 trong chú giải + tooltip. */
  readonly nhan: string
  /**
   * Nhãn ĐÈ cho ĐƯỜNG CHÍNH, chỉ ở biểu đồ/tooltip — rail vẫn dùng `tab.nhan`.
   *
   * Có mặt vì `tab.nhan` là tên của cả TAB («STT»), và khi tab có hai đường thì
   * một trong hai không thể mang tên của cả tab: đọc ra thành «STT» đứng cạnh
   * một thứ khác, tức đường kia không thuộc STT. Hai đường thì cần hai tên
   * ngang hàng nhau.
   */
  readonly nhanChinh: string
  readonly donVi: DonVi
  readonly doTu: (p: PhanUsageNgay) => number
}

export interface TabUsage {
  /** Mã `component` trong `billing.usage_events` — cũng là khoá màu ở `theme.css`. */
  readonly ma: string
  readonly nhan: string
  readonly donVi: DonVi
  /** Rút SỐ ĐO của tab này từ một hàng `phan[]` của đúng component đó. */
  readonly doTu: (p: PhanUsageNgay) => number
  readonly duong2?: DuongPhu
}

export const NHAN_DON_VI: Record<DonVi, string> = {
  token: 'token',
  giay: 'giây',
  so: 'lượt',
}

/** Bộ định dạng theo ĐƠN VỊ — không có hàm "chung" nào cho cả ba.
 *
 *  ⚠️ Biến `kytu` ĐÃ BỎ (2026-08-25): ba tab đo `text_units` nay đều mang nhãn
 *  «token» nên nó thành một nhãn không ai dùng — và một biến tên `kytu` gắn
 *  chữ «ký tự» nằm cạnh ba tab gọi cùng thứ đó là «token» chính là chỗ người
 *  sau khôi phục lại sự lệch. Khác `so` (giữ dù chưa tab nào dùng): `so` để
 *  dành cho `so_event`, một số đo CÓ THẬT chưa có tab; `kytu` thì không dành
 *  cho gì cả. Định dạng không đổi — `token` vốn đã là hàm cũ của `kytu`. */
export const DINH_DANG: Record<DonVi, (n: number) => string> = {
  token,
  giay,
  so: SO,
}

/**
 * Định dạng MỐC TRỤC thời gian — MỘT đơn vị cho CẢ TRỤC, chọn theo BƯỚC CHIA.
 *
 * ⚠️ Đơn vị suy từ `buoc`, KHÔNG từ từng giá trị. Suy theo từng giá trị thì một
 * trục bước 30s in ra `0s · 30s · 1m · 90s` — ba đơn vị trong bốn mốc xếp dọc,
 * và mắt phải quy đổi giữa hai mốc liền nhau để biết cái nào lớn hơn. Đo được
 * trên tab «Xác thực giọng» (2026-08-25). Theo bước thì cả trục cùng thang:
 * `0 · 30s · 60s · 90s`.
 *
 * ⚠️ Mốc GỐC in `0` TRẦN, không `0s`/`0m`/`0h`: số 0 không có đơn vị nào đúng
 * hơn đơn vị nào, và gắn hậu tố vào nó là chỗ DUY NHẤT còn lại trên trục nói
 * một thang khác phần còn lại. Trục token/lượt vốn đã in `0` trần — nay ba loại
 * trục cùng một quy ước.
 *
 * Giá trị trong tooltip và trên rail VẪN dùng `giay()` đầy đủ (`4m 07s`): ở đó
 * là số ĐO thật, không phải một mốc tròn.
 */
export function nhanMocTruc(donVi: DonVi, v: number, buoc = v): string {
  if (donVi !== 'giay') return DINH_DANG[donVi](v)
  if (v === 0) return '0'
  if (buoc % 3600 === 0) return `${v / 3600}h`
  if (buoc % 60 === 0) return `${v / 60}m`
  return `${v}s`
}

export const TAB_USAGE: readonly TabUsage[] = [
  {
    ma: 'llm',
    nhan: 'Token',
    donVi: 'token',
    /* Ba loại token CỘNG LẠI — đây là phép cộng HỢP LỆ duy nhất của sổ này:
       ba con số đếm ba thứ rời nhau trong cùng một event, không phải ba cách đo
       cùng một quãng. `cache_write` cố ý ngoài vòng: nó có giá riêng nhưng
       không phải lượng khách "dùng", và BE cũng không trả nó ở endpoint này. */
    doTu: (p) => p.input_tokens + p.output_tokens + p.cache_read_tokens,
  },
  {
    ma: 'stt',
    nhan: 'STT',
    donVi: 'giay',
    doTu: (p) => p.wall_ms_stream / 1000,
    /* Vế thứ hai — `text_units_hoi_thoai`, KHÔNG `text_units`. Cột không lọc
       là số đo của `tts`/`embed`; dùng nhầm ở đây thì trên dữ liệu hôm nay ra
       cùng con số (dòng `stt/stream` có `text_units = 0`) và sai âm thầm vào
       ngày vendor bắt đầu ghi text cho vế stream. Xem hợp đồng điều 5. */
    /* Hai đường của STT = hai `purpose`, nhãn lấy thẳng giá trị `purpose`:
         Stream       ← `wall_ms`    của `purpose='stream'`       (giây)
         Conversation ← `text_units` của `purpose='conversation'` (xem `donVi`)
       Nhờ khớp `purpose` mà dòng phụ của rail và biểu đồ nay nói CÙNG hai thứ
       bằng CÙNG hai chữ — trước đó dòng phụ nói `stream` (wall_ms) trong khi
       biểu đồ vẽ `audio_sec`, tức một chữ trỏ vào hai đại lượng.

       ⚠️ CHIA 1000 Ở ĐÂY: BE trả `wall_ms_stream` bằng MILI giây, còn `donVi`
       của tab là `giay`. Quên chia thì rail in `42h 13m 20s` — một chuỗi hợp lệ
       trông rất thật, không cổng nào ngoài mắt người bắt được. `sttHaiVe()`
       cũng chia đúng một lần vì cùng lý do đó. */
    duong2: {
      nhan: 'Conversation',
      nhanChinh: 'Stream',
      /* ⚠️ `token` LÀ CHỮ NGƯỜI DÙNG CHỐT (2026-08-25), KHÔNG phải mô tả đúng
         dữ liệu: số đo là `text_units`, mà `text_units` là KÝ TỰ — migration
         `0948` viết vậy và `billing.metric` khai `('text_units','Ký tự text',
         …,'character')`. Đã báo, người dùng giữ nguyên yêu cầu.
         TTS và Embed cũng đã đổi sang `token` cùng ngày, nên cả ba chỗ đo
         `text_units` nay nói CÙNG một nhãn — đó là điều kiện: hai tab cạnh
         nhau gọi cùng một cột bằng hai tên là chỗ người đọc kết luận chúng đo
         hai thứ khác nhau. Không con số nào đổi (`token` vốn là chính hàm định
         dạng mà `kytu` dùng). */
      donVi: 'token',
      doTu: (p) => p.text_units_hoi_thoai,
    },
  },
  { ma: 'tts', nhan: 'TTS', donVi: 'token', doTu: (p) => p.text_units },
  { ma: 'vad', nhan: 'VAD', donVi: 'giay', doTu: (p) => p.audio_sec },
  { ma: 'call', nhan: 'Thời gian gọi', donVi: 'giay', doTu: (p) => p.audio_sec },
  { ma: 'embed', nhan: 'Embed', donVi: 'token', doTu: (p) => p.text_units },
  {
    ma: 'speaker_verify',
    nhan: 'Xác thực giọng',
    donVi: 'giay',
    doTu: (p) => p.audio_sec,
  },
  { ma: 'search', nhan: 'Tra Google', donVi: 'so', doTu: (p) => p.units },
]

export const MA_TAB = TAB_USAGE.map((t) => t.ma)

export function timTab(ma: string): TabUsage {
  return TAB_USAGE.find((t) => t.ma === ma) ?? TAB_USAGE[0]!
}
