/**
 * Một ca chuyển sale trong danh sách trái — dải ngang bấm được, không phải hàng bảng.
 *
 * Hàng KHÔNG mang nền/viền riêng: nó sống trong tấm nền của `HopThuSale`. Cùng
 * lý lẽ `KhachRow` — thẻ trắng trên nền xám đọc ra như giấy rời trên bàn.
 */
import type { Ca } from '../api'
import { mauCua, noiDungAvatar } from '../avatar'
import { gioNgan } from '../thoiGian'
import { NhanKyNang, TrangThaiCa } from './caChip'

export function CaRow({
  ca,
  dangChon,
  chon,
  bayGio,
}: {
  ca: Ca
  dangChon: boolean
  chon: () => void
  bayGio?: Date | undefined
}) {
  const khuyetSo = !ca.phone

  return (
    <button
      type="button"
      onClick={chon}
      data-ca={ca.id}
      aria-current={dangChon ? 'true' : undefined}
      className={`group relative flex w-full items-start gap-3.5 overflow-hidden border-b border-border-soft
                  px-5 py-4 text-left transition last:border-b-0
                  ${dangChon ? 'bg-acs' : 'hover:bg-bg'}`}
    >
      <span
        className={`absolute inset-y-0 left-0 w-[3px] bg-ac transition-opacity
                    ${dangChon ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
      />
      {/* `aria-hidden`: hàng là MỘT nút, mà chữ cái avatar («NA») đứng đầu tên đọc
          được của nó — trình đọc màn hình nói «NA Nguyễn Minh Anh…». */}
      <span
        aria-hidden
        className={`flex size-[38px] shrink-0 items-center justify-center rounded-full text-[14px] font-semibold
                    ${khuyetSo ? 'bg-border-soft text-muted-3' : mauCua(ca.phone ?? '')}`}
      >
        {noiDungAvatar(ca.ten)}
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className={`truncate text-noi font-semibold ${ca.ten ? '' : 'text-muted'}`}>
            {ca.ten ?? 'Khách chưa cho tên'}
          </span>
          <span className="shrink-0 font-mono text-[11.5px] text-muted-2">
            {gioNgan(ca.taoLuc, bayGio)}
          </span>
        </span>

        <span
          className={`mt-[3px] block text-phu
                      ${khuyetSo ? 'text-badge-alert-fg' : 'font-mono text-muted-2'}`}
        >
          {ca.phone ?? 'Chưa có số điện thoại'}
        </span>

        <span className="mt-2 flex flex-wrap gap-1.5">
          <span className="rounded-full bg-border-soft px-2 py-[3px] text-[11.5px] font-medium text-muted">
            {ca.tenDuAn || ca.duAn || 'Chưa rõ dự án'}
          </span>
          <NhanKyNang ten={ca.toolThieuDuLieu} />
          <TrangThaiCa ca={ca} />
        </span>
      </span>
    </button>
  )
}
