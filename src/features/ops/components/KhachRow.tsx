/**
 * Một hàng khách — dải ngang trọn chiều rộng, KHÔNG phải hàng bảng.
 *
 * Bốn thứ tách nó khỏi hình dạng "table list" (spec §5.1), đừng bỏ khi dọn CSS:
 * hàng cao để summary giữ 2 dòng · chip nằm DƯỚI summary · vạch accent trái khi
 * hover · mũi › sáng lên. Một hàng bấm được phải nói ra rằng nó bấm được.
 *
 * Hàng KHÔNG có nền và viền riêng — nó sống bên trong tấm nền trắng của
 * `KhachList`. Đừng trả lại `rounded-xl border bg-surface`: thẻ trắng đặt lên
 * nền xám của trang là đúng cái làm màn đọc ra "thiếu nền", và đó là lý do bố
 * cục này đổi (07/08).
 */
import { Link } from '@tanstack/react-router'
import { type Khach, duongDanKhach } from '../api'
import { mauCua, noiDungAvatar } from '../avatar'
import { gioNgan } from '../thoiGian'
import { TomTatLead } from './ChipStage'

export function KhachRow({ khach, bayGio }: { khach: Khach; bayGio?: Date | undefined }) {
  const an = khach.phone === ''
  // Không có tên thì DÙNG SỐ làm tên. Hiện chuỗi 'null' hay ô trống đều tệ hơn.
  const ten = an ? 'Chưa có số' : (khach.ten ?? khach.phone)
  // Số đã lên làm TÊN rồi thì đừng lặp lại y nguyên ở dòng phụ đề — không thêm
  // thông tin gì, và làm text tra theo số khớp hai chỗ một lúc.
  const soLapLaiOTen = !an && !khach.ten

  return (
    <Link
      to="/convos/$phone"
      params={{ phone: duongDanKhach(khach.phone) }}
      // Hàng nằm TRONG tấm nền trắng của `KhachList`, nên nó không mang nền và
      // viền riêng nữa — chỉ một đường kẻ ngăn với hàng dưới. Trước đây mỗi hàng
      // là một thẻ trắng đặt thẳng lên nền xám của trang, và cả màn đọc ra như
      // mấy mảnh giấy rời trên bàn thay vì một danh sách trong hộp.
      //
      // Nền hover tràn hết chiều ngang tấm (`px-5` nằm ở chính hàng, không ở
      // khung cha) — một dải sáng chạy trọn bề mặt đọc rõ hơn nhiều so với một
      // khối bo góc thụt vào trong.
      className={`group relative flex items-start gap-4 overflow-hidden border-b border-border-soft
                  px-5 py-4 transition last:border-b-0
                  max-md:flex-wrap max-md:gap-x-3 max-md:gap-y-2 max-md:px-4
                  ${an ? 'bg-bg hover:bg-border-soft' : 'hover:bg-bg'}`}
    >
      <span className="absolute inset-y-0 left-0 w-[3px] bg-ac opacity-0 transition-opacity group-hover:opacity-100" />
      <span
        className={`flex size-[42px] shrink-0 items-center justify-center rounded-full text-[15.5px] font-semibold
                    ${an ? 'bg-border-soft text-muted-3' : mauCua(khach.phone)}`}
      >
        {noiDungAvatar(khach.ten)}
      </span>

      <span className="w-[186px] shrink-0 max-md:w-auto max-md:min-w-0 max-md:flex-1">
        <span className={`block text-the font-semibold ${an ? 'text-muted' : ''}`}>{ten}</span>
        {!soLapLaiOTen && (
          <span className={`mt-[3px] block text-phu text-muted-2 ${an ? '' : 'font-mono'}`}>
            {an ? '— ẩn danh' : khach.phone}
          </span>
        )}
      </span>

      {/* KẺ DỌC giữa ba vùng: tên · tóm tắt · thời gian.
          `self-stretch` là bắt buộc — hàng là `items-start`, nên không có nó thì
          kẻ chỉ cao bằng NỘI DUNG của chính cột đó, mà ba cột cao khác nhau
          (tóm tắt 2 dòng + chip so với một dòng giờ), và mỗi hàng lại một kiểu
          cụt. `self-stretch` cho kẻ chạy hết vùng nội dung của hàng, dừng đúng
          trong phần đệm dọc.

          `border-border-soft` — CÙNG sắc với kẻ ngang ngăn hai hàng. Đậm hơn thì
          lưới dọc hút mắt hơn chính nội dung, mà đây là danh sách để đọc lướt
          chứ không phải bảng để dò ô. */}
      <span className="min-w-0 flex-1 self-stretch border-l border-border-soft pl-4 pr-1.5 max-md:order-last max-md:basis-full max-md:border-l-0 max-md:pl-0">
        {khach.summaryCuoi && (
          <span className="line-clamp-2 block text-than leading-[1.55] text-muted">
            {khach.summaryCuoi}
          </span>
        )}
        <span className="mt-2 flex flex-wrap gap-1.5">
          <span className="rounded-full bg-border-soft px-2 py-[3px] text-[11.5px] font-medium text-muted">
            {khach.tenDuAn || khach.duAn || 'Chưa rõ dự án'}
          </span>
          {khach.daChuyen && (
            <span className="rounded-full bg-acs px-2 py-[3px] text-[11.5px] font-medium text-acd">
              Đã chuyển sales
            </span>
          )}
        </span>
      </span>

      {/* CỘT LEAD RIÊNG (spec §4.2): việc chính của màn là DÒ MẮT DỌC «ai đang nóng»,
          chen chip vào hàng chip dự án thì mỗi hàng nằm một chỗ. Cùng kẻ dọc
          `border-border-soft` với hai cột kia. Mobile: rơi xuống dưới tóm tắt. */}
      <span
        data-testid="cot-lead"
        className="w-[158px] shrink-0 self-stretch border-l border-border-soft pl-4 pt-px max-md:order-last max-md:w-auto max-md:basis-full max-md:border-l-0 max-md:pl-0"
      >
        {/* «Chưa có số» là NHIỀU người ẩn danh — không có lead cấp khách (backend cũng
            không trả), và «Chưa phân loại» ở đây sẽ nói như thể đó là một khách chờ phân loại. */}
        {an ? (
          <span className="block text-[12px] text-muted-3">—</span>
        ) : (
          <TomTatLead stage={khach.leadStage} diem={khach.leadScore} doiTuong={khach.audience} />
        )}
      </span>

      <span className="w-[132px] shrink-0 self-stretch border-l border-border-soft pl-4 pt-0.5 text-right max-md:w-auto max-md:border-l-0 max-md:pl-0">
        <span className="block font-mono text-than">{gioNgan(khach.ganNhat, bayGio)}</span>
        <span className="mt-1 block font-mono text-[12px] text-muted-2">{khach.soPhien} phiên</span>
      </span>

      <span className="self-center text-muc text-muted-3 group-hover:text-ac max-md:hidden">›</span>
    </Link>
  )
}
