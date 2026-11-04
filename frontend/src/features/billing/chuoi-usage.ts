/**
 * Dẫn xuất của màn `/usage`: từ MỘT response `usage-by-day` ra chuỗi N ngày của
 * từng tab, cộng ba con số tóm tắt (tổng kỳ · đỉnh · số ngày hoạt động).
 *
 * VÌ SAO CỘNG Ở ĐÂY CHỨ KHÔNG XIN BE MỘT ENDPOINT TỔNG:
 * `GET /billing/breakdown` đã trả `theo_component[]` với đúng bộ số đo tổng kỳ.
 * Lấy tổng từ đó là HAI NGUỒN cho MỘT con số — tổng cả kỳ và tổng của chuỗi
 * ngày phải bằng nhau, mà chúng đến từ hai câu SQL khác nhau (một gộp theo
 * component, một gộp theo ngày+component), nên ngày nào lệch sẽ lệch ÂM THẦM:
 * rail nói một số, biểu đồ vẽ một số khác, và không cổng nào đỏ. Cộng chuỗi
 * ngày ở đây thì hai con số KHÔNG THỂ lệch nhau — chúng là cùng một mảng.
 *
 * Hàm THUẦN, không hook, không `fetch` — test dựng được không cần provider.
 */
import { timTab } from './so-tab-usage'
import type { UsageNgay } from './kieu'

export interface ChuoiTab {
  /** Mã component (= mã tab). */
  ma: string
  /** Nhãn ngày `YYYY-MM-DD`, ĐỦ mọi ngày của kỳ, tăng dần. */
  ngay: string[]
  /** Số đo từng ngày, cùng chỉ số với `ngay`. Ngày không có usage = 0. */
  gia: number[]
  /** Số phiên từng ngày — thuộc tính của NGÀY, dùng chung cho cả bảy tab. */
  soPhien: number[]
  tong: number
  dinh: number
  /**
   * Trung bình mỗi ngày của kỳ — dòng phụ của mục rail.
   *
   * ⚠️ MẪU SỐ LÀ SỐ NGÀY CỦA KỲ (`ngay.length`), KHÔNG phải `soNgayHoatDong`.
   * Hai cách chia trả lời hai câu khác nhau và lệch nhau thật (19/21 ngày là
   * ~10%, kỳ nhiều ngày nghỉ thì hơn nhiều):
   *   · chia cho ngày của KỲ  → «mỗi ngày trôi qua tốn bao nhiêu» — khớp đúng
   *     nhãn `/ngày` mà mắt đọc, và là con số dùng để ước lượng cả tháng.
   *   · chia cho ngày HOẠT ĐỘNG → «những hôm có chạy thì cường độ ra sao» —
   *     đúng hơn về cường độ, nhưng nhãn phải mang thêm chữ «ngày hoạt động»
   *     mới không nói dối, và dòng phụ của rail không có chỗ cho vế đó.
   * Bảng «Cường độ theo service» (ĐÃ BỎ) từng chọn vế thứ hai — hợp lý Ở ĐÓ vì
   * nó có hẳn một tiêu đề cột nói rõ và một cột «Ngày hoạt động» ngay cạnh làm
   * ngữ cảnh. Ở rail thì không còn cả hai. Đổi mẫu số thì ĐỔI CẢ NHÃN.
   */
  tbMoiNgay: number
  /** Số ngày có số đo > 0. KHÁC số ngày của kỳ. */
  soNgayHoatDong: number
  /**
   * Chuỗi của ĐƯỜNG THỨ HAI, chỉ có khi tab khai `duong2` (hiện chỉ `stt`).
   * Cùng chỉ số với `ngay`, ĐƠN VỊ KHÁC `gia`.
   *
   * ⚠️ Để RIÊNG chứ không nối vào `gia`, và đó là điều kiện chứ không phải cách
   * xếp tệp: `gia` là giây, cái này là ký tự. Trộn hai mảng là mở đường cho
   * `tong`/`dinh`/`tbMoiNgay` cộng qua hai đơn vị — một con số không tồn tại.
   */
  gia2?: number[]
  tong2?: number
  dinh2?: number
}

/**
 * ⚠️ KHÔNG lọc bỏ ngày `gia = 0`. Ngày đã ĐO và bằng 0 là một ngày THẬT (chủ
 * nhật agent không chạy); bỏ nó khỏi mảng thì biểu đồ nối thẳng hai điểm hai bên
 * và vẽ ra một mức dương cho ngày không phát sinh — đúng cái nó sinh ra để nói,
 * nói sai. BE đã cố ý trả đủ mọi ngày (`generate_series`); đừng vứt đi ở đây.
 *
 * `phan` của một ngày KHÔNG chứa component nào của tab ⇒ 0, không phải `NaN` và
 * cũng không phải bỏ qua: hai chuỗi khác nhau về ĐỘ DÀI thì mọi phép vẽ theo
 * chỉ số sau đó lệch một ngày.
 */
export function chuoiCuaTab(theoNgay: readonly UsageNgay[], ma: string): ChuoiTab {
  const tab = timTab(ma)
  const ngay: string[] = []
  const gia: number[] = []
  const soPhien: number[] = []
  const d2 = tab.duong2
  const gia2: number[] | undefined = d2 ? [] : undefined

  for (const n of theoNgay) {
    const p = n.phan.find((x) => x.component === ma)
    ngay.push(n.ngay)
    gia.push(p ? tab.doTu(p) : 0)
    soPhien.push(n.so_phien)
    if (d2 && gia2) gia2.push(p ? d2.doTu(p) : 0)
  }

  const tong = gia.reduce((a, b) => a + b, 0)
  const dinh = gia.length ? Math.max(...gia) : 0
  return {
    ...(gia2
      ? {
          gia2,
          tong2: gia2.reduce((a, b) => a + b, 0),
          dinh2: gia2.length ? Math.max(...gia2) : 0,
        }
      : {}),
    ma,
    ngay,
    gia,
    soPhien,
    tong,
    dinh,
    // Kỳ rỗng ⇒ mẫu số 0 ⇒ `NaN`, và `NaN` đi thẳng ra DOM thành chữ «NaN».
    tbMoiNgay: gia.length ? tong / gia.length : 0,
    soNgayHoatDong: gia.filter((v) => v > 0).length,
  }
}

/**
 * Ba con số phụ của tab Token: `in`/`out`/`cache read` cộng qua các ngày.
 *
 * Tách riêng vì chỉ tab đó có, và có LÝ DO khác hẳn năm tab kia: ba con số này
 * là TÁCH LOẠI của chính con số dẫn (cộng lại đúng bằng nó), không phải một chỉ
 * số thứ hai. Năm tab còn lại chở `tbMoiNgay`; `stt` chở `sttHaiVe()`.
 */
export function tokenTachLoai(theoNgay: readonly UsageNgay[]): {
  input: number
  output: number
  cache: number
} {
  let input = 0
  let output = 0
  let cache = 0
  for (const n of theoNgay) {
    const p = n.phan.find((x) => x.component === 'llm')
    if (!p) continue
    input += p.input_tokens
    output += p.output_tokens
    cache += p.cache_read_tokens
  }
  return { input, output, cache }
}

/** Phần của dữ liệu ngoài trong tab Token (in+out+cache) và Embed (ký tự), cộng qua các ngày. */
export function duLieuNgoai(theoNgay: readonly UsageNgay[]): { token: number; kyTu: number } {
  let tk = 0
  let kyTu = 0
  for (const n of theoNgay) {
    for (const p of n.phan) {
      if (p.component === 'llm') tk += p.token_du_lieu_ngoai ?? 0
      if (p.component === 'embed') kyTu += p.text_units_du_lieu_ngoai ?? 0
    }
  }
  return { token: tk, kyTu }
}

/**
 * Hai vế của tab STT, cộng qua các ngày — dòng phụ của mục rail.
 *
 * KHÁC `tokenTachLoai` ở chỗ căn bản: ba con số của Token là TÁCH LOẠI của
 * chính con số dẫn (in + out + cache = tổng token). Hai con số ở đây KHÔNG
 * cộng vào `audio_sec` và cũng không cộng vào nhau — chúng là hai ĐỒNG HỒ
 * riêng mà vendor STT thu song song (`billing.pricing_basis` khai hẳn hai
 * dòng: `stt/stream/wall_ms` và `stt/conversation/text_units`).
 *
 * ⚠️ `streamGiay` ĐÃ ĐỔI ms → GIÂY ở đây, một lần, ngay cạnh chỗ đọc trường.
 * BE trả `wall_ms_stream` bằng MILI giây; đưa thẳng vào `giay()` thì rail in
 * ra một quãng gấp 1000 lần — và nó vẫn là một chuỗi hợp lệ trông rất thật
 * (`49h 22m`), nên không cổng nào ngoài mắt người bắt được.
 */
export function sttHaiVe(theoNgay: readonly UsageNgay[]): {
  streamGiay: number
  hoiThoaiKyTu: number
} {
  let ms = 0
  let hoiThoaiKyTu = 0
  for (const n of theoNgay) {
    const p = n.phan.find((x) => x.component === 'stt')
    if (!p) continue
    ms += p.wall_ms_stream
    hoiThoaiKyTu += p.text_units_hoi_thoai
  }
  return { streamGiay: ms / 1000, hoiThoaiKyTu }
}
