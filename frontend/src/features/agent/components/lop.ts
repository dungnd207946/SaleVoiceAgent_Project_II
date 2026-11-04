import { O_CHUNG } from '@/components/ui/Truong'

/** Hằng class dùng chung của màn Agent — tách khỏi form.tsx vì eslint
 * `react-refresh/only-export-components` không cho file component export hằng. */

export const NUT_PHU =
  'rounded-lg border border-border-strong bg-surface px-3.5 py-2 text-than font-medium whitespace-nowrap transition-colors hover:border-fg disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-border-strong'

export const NUT_CHINH =
  'rounded-lg bg-ac px-[15px] py-2 text-than font-semibold text-white whitespace-nowrap transition-colors hover:bg-acd disabled:cursor-not-allowed disabled:bg-border-strong disabled:text-muted'

/** Ô nhập của màn Agent = khuôn ô nhập chung (`O_CHUNG`, viền `border-field`). Bản
 *  chép tay trước đây viền n5 (1,39:1) và placeholder một sắc riêng. */
export const O_LOP = O_CHUNG

/**
 * Lưới của MỌI khu trong màn Cấu hình chung — hai cột đều nhau, ô dài chiếm trọn
 * hàng (`rong`). Một hằng cho cả chế độ xem lẫn chế độ sửa.
 *
 * VÌ SAO MỘT HẰNG. Trước 2026-08-08 mỗi khu tự khai lưới riêng: khu Danh tính có
 * một hàng 2 cột rồi một hàng `1fr 1fr 2fr`, khu Phạm vi có 2 cột rồi một ô trần
 * full-width, và khoảng cách chạy giữa `gap-3.5` với `mt-3.5`. Kết quả là mép
 * phải của các ô không thẳng hàng nhau qua các khu, và không có chỗ nào để sửa
 * một lần — «đều» là thứ phải cưỡng chế bằng cấu trúc, không phải canh bằng mắt.
 *
 * Hệ quả có chủ đích: bản tóm tắt và form dùng CÙNG lưới này, nên bấm «Sửa cấu
 * hình» là các ô nằm đúng chỗ mắt vừa đọc, không phải tìm lại.
 */
export const LUOI_O = 'grid grid-cols-1 gap-4 sm:grid-cols-2'

/**
 * Cùng lưới, nhịp dọc chặt hơn — dành cho bản tóm tắt chỉ-đọc.
 *
 * Thứ phải khớp giữa hai chế độ là VỊ TRÍ NGANG (mắt tìm lại đúng ô sau khi bấm
 * Sửa), không phải khoảng cách dọc. `gap-y-4` là số đo cho một hàng ô nhập cao
 * 43px; một dòng nhãn-trên-giá-trị chỉ cao ~34px, và giữ nguyên 16px ở đó làm
 * bản tóm tắt cao gần bằng form trong khi nó chứa ít hơn hẳn.
 */
export const LUOI_XEM = 'grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2'

/** Hai thẻ nhỏ đứng CẠNH NHAU thay vì xếp chồng: «Giọng điệu» có đúng 2 giá trị
 * và «Kỹ năng chung» có 3 — mỗi cái một thẻ nguyên bề rộng là hai dải trắng dài
 * cho sáu dòng chữ. Chỉ ghép từ `lg` trở lên; hẹp hơn thì hai cột thành hai cột
 * chật và chip giọng điệu xuống dòng.
 *
 * Cặp này nằm TRONG `KhoiVaiTro` nên hai thẻ là `The phang` (không vỏ), và
 * `gap-x-4` CỐ Ý bằng khe cột của `LUOI_O`/`LUOI_XEM`: «Kỹ năng chung» thẳng mép
 * với cột phải của «Phạm vi» ngay trên. Kẻ dọc giữa hai khu thì lệch đúng nửa khe. */
export const CAP_THE = 'grid gap-x-4 gap-y-6 lg:grid-cols-2'
