/**
 * NGUỒN DUY NHẤT của số liệu đánh giá trong mọi fake MSW.
 *
 * Vì sao ở `lib/msw/` chứ không ở một `features/*`: **hai module** đọc nó —
 * `ops` (ô ③ màn Tổng quan, qua `GET /overview`) và `quality` (dải thống kê
 * màn `/quality`, qua `GET /agent/feedback`). Luật ranh giới của repo cấm
 * `features/ops` import ruột `features/quality`, mà `lib/*` thì mọi module đều
 * được import — nên đây là chỗ HỢP LỆ duy nhất cho một hằng dùng chung giữa
 * hai fake, cùng vai trò `lib/msw/handlers.ts` đang gom fake của cả hai
 * (dòng thứ ba của `ALLOWLIST` trong `tests/module-boundaries.test.ts`).
 *
 * ⚠️ **Trước 2026-08-14 đây là HAI bảng số viết tay rời nhau** — `ops/msw.ts`
 * khai `tong: 190 · trungBinh: 4,33`, còn `quality/msw.ts` suy `total`/
 * `theo_sao` từ đúng 5 hàng mẫu của chính nó (`total: 5 · 3,00`). Chạy dev
 * dưới MSW (mặc định của repo) thì hai màn cạnh nhau in hai con số hoàn toàn
 * khác nhau dưới cùng một nhãn «điểm trung bình», và người xem không có cách
 * nào biết cái nào đúng. Đây là ĐÚNG lớp lỗi CLAUDE.md đã ghi ở gotcha
 * «fake MSW không phải nguồn sự thật»: fake không có cổng parity nào canh, nên
 * cách duy nhất chống lệch là **không có bản sao thứ hai để mà lệch**.
 *
 * Fake của `/quality` giữ ĐÚNG 5 hàng mẫu cho `items` — đó KHÔNG phải mâu
 * thuẫn với `TONG` dưới đây, mà chính là hành vi của backend thật:
 * `liet_ke_feedback_cua_tenant` phân trang `items` nhưng tính `total`/
 * `theo_sao`/`diem_trung_binh` trên TOÀN BỘ feedback của tenant, bất kể bộ
 * lọc đang áp. Bản cũ suy tổng từ trang đầu — đó mới là chỗ nói sai.
 */

/** Phân bố phiếu theo mức sao. MỌI con số khác trong file này suy ra từ đây,
 *  nên sửa một mức là cả bộ tự khớp lại. */
export const PHAN_BO_SAO_GIA: Readonly<Record<'1' | '2' | '3' | '4' | '5', number>> = {
  '1': 4,
  '2': 8,
  '3': 20,
  '4': 48,
  '5': 110,
}

/** Tổng lượt chấm — CỘNG từ phân bố, không gõ tay. Hai con số nói về cùng một
 *  tập mà khai rời nhau là hai chỗ có thể lệch (đúng lời demo đã ghi ở
 *  `docs/design/demo-tong-quan.html` khối ③). */
export const TONG_DANH_GIA_GIA = Object.values(PHAN_BO_SAO_GIA).reduce((a, b) => a + b, 0)

/** Điểm trung bình — TÍNH TỪ phân bố, làm tròn 2 chữ số như backend
 *  (`round(..., 2)` ở `ops/router.py` và `enrollment/service.py`). */
export const DIEM_TRUNG_BINH_GIA =
  Math.round(
    (Object.entries(PHAN_BO_SAO_GIA).reduce((s, [sao, n]) => s + Number(sao) * n, 0) /
      TONG_DANH_GIA_GIA) *
      100,
  ) / 100
