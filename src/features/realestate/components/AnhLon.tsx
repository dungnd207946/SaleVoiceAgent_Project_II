/**
 * Lightbox — xem một ảnh ở cỡ lớn nhất màn hình cho phép.
 *
 * NHẬN CẢ BỘ ẢNH + CHỈ SỐ, KHÔNG NHẬN MỘT ẢNH: `‹ ›` đi trong bộ là lý do chính
 * người ta mở nó. Truyền một ảnh thì mỗi lần xem ảnh kế phải đóng rồi mở lại.
 *
 * KHÔNG BIẾT GÌ VỀ MEDIA CỦA BĐS (`{ src, caption }` trần) nên form phân khu và
 * form căn dùng lại được mà không phải kéo theo kiểu `Media`.
 */
import { useEffect, useState } from 'react'
import { HopThoai } from '@/components/ui/HopThoai'

export interface AnhXem {
  readonly src: string
  readonly caption: string
}

const NUT_DIEU_HUONG =
  'rounded-full bg-black/50 px-3 py-2 text-[18px] text-white hover:bg-black/70 disabled:opacity-30'

export function AnhLon({
  anh,
  batDau,
  onDong,
}: {
  anh: readonly AnhXem[]
  batDau: number
  onDong: () => void
}) {
  const [i, setI] = useState(batDau)

  useEffect(() => {
    function phim(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') setI((x) => Math.min(x + 1, anh.length - 1))
      if (e.key === 'ArrowLeft') setI((x) => Math.max(x - 1, 0))
    }
    document.addEventListener('keydown', phim)
    return () => document.removeEventListener('keydown', phim)
  }, [anh.length])

  const hienTai = anh[i]
  if (!hienTai) return null

  return (
    <HopThoai
      onDong={onDong}
      aria-label="Xem ảnh"
      className="m-auto flex max-h-[calc(100dvh-1.5rem)] max-w-[calc(100vw-1.5rem)] flex-col items-center gap-3 overflow-visible bg-transparent p-0 text-white backdrop:bg-black/80"
    >
      <img
        src={hienTai.src}
        alt={hienTai.caption}
        className="max-h-[75vh] max-w-full max-md:max-h-[calc(100dvh-8rem)] max-md:max-w-full rounded object-contain"
      />
      <p className="text-center text-[14px] text-white">
        {hienTai.caption || '(chưa có chú thích)'}
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          className={NUT_DIEU_HUONG}
          onClick={() => setI(i - 1)}
          disabled={i === 0}
          aria-label="Ảnh trước"
        >
          ‹
        </button>
        <span className="text-[13px] text-white/70">
          {i + 1}/{anh.length}
        </span>
        <button
          type="button"
          className={NUT_DIEU_HUONG}
          onClick={() => setI(i + 1)}
          disabled={i === anh.length - 1}
          aria-label="Ảnh kế"
        >
          ›
        </button>
        <button
          type="button"
          className="ml-3 rounded-full bg-black/50 px-3 py-1.5 text-[14px] text-white hover:bg-black/70"
          onClick={onDong}
        >
          Đóng
        </button>
      </div>
    </HopThoai>
  )
}
