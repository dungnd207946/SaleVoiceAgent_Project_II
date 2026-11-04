/**
 * Khách nói sao → ra dự án nào. Tự chạy qua bốn mẫu rồi lặp.
 *
 * Hiện TÊN dự án chứ không hiện mã (`NCR`/`SLC`) và không hiện điểm khớp thành
 * số: cả hai là thứ nội bộ, người mua chỉ cần thấy máy ra đúng dự án. Độ chắc
 * chắn nói bằng chiều dài thanh — một con số `0.94` tự nó không nói gì.
 */
import { useEffect, useState } from 'react'
import { MAU_KHOP } from './duLieuMau'

const NHIP = 3200
const MO_DAN = 320

export function KhopTenDuAn() {
  const [i, datI] = useState(0)
  const [mo, datMo] = useState(false)

  useEffect(() => {
    if (
      typeof matchMedia === 'function' &&
      matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      return
    }
    let doi: ReturnType<typeof setTimeout>
    const nhip = setInterval(() => {
      datMo(true)
      doi = setTimeout(() => {
        datI((cu) => (cu + 1) % MAU_KHOP.length)
        datMo(false)
      }, MO_DAN)
    }, NHIP)
    return () => {
      clearInterval(nhip)
      clearTimeout(doi)
    }
  }, [])

  const mau = MAU_KHOP[i] ?? MAU_KHOP[0]
  if (!mau) return null

  return (
    <div className="rounded-lg border border-border bg-surface px-6 py-[26px]">
      <span className="font-mono text-nhan uppercase tracking-[0.1em] text-muted-2">Khách nói</span>

      {/* `min-h` giữ chỗ cho câu dài nhất — không có nó thì cả khối co giãn
          theo từng mẫu và trang giật mỗi 3,2 giây. */}
      <p
        className={`mt-2.5 min-h-[62px] text-[clamp(18px,2vw,22px)] font-medium leading-[1.35] tracking-[-0.015em] transition-opacity duration-300 ${
          mo ? 'opacity-0' : 'opacity-100'
        }`}
      >
        {mau.noi}
      </p>

      <svg
        aria-hidden
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="my-3.5 text-border-strong"
      >
        <path d="M12 5v14M19 12l-7 7-7-7" />
      </svg>

      <div
        className={`flex items-center gap-2.5 transition-opacity duration-300 ${
          mo ? 'opacity-0' : 'opacity-100'
        }`}
      >
        <span
          className={`rounded-sm px-3 py-[5px] text-muc font-semibold tracking-[-0.01em] ${
            mau.hoiLai ? 'bg-badge-alert-bg text-badge-alert-fg' : 'bg-acs text-ac'
          }`}
        >
          {mau.ra}
        </span>
      </div>

      <div className="mt-3.5 h-[3px] overflow-hidden rounded-sm bg-fill-strong">
        <i
          className={`block h-full rounded-sm transition-[width] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
            mau.hoiLai ? 'bg-badge-alert-fg' : 'bg-ac'
          }`}
          style={{ width: mo ? '0%' : `${mau.chac * 100}%` }}
        />
      </div>
    </div>
  )
}
