/**
 * Hộp chỉnh sửa MỘT media: tên, mô tả, xoá.
 *
 * Danh sách chỉ hiện tên — sửa phải qua đây. Ô nhập nằm ngay dưới mỗi ảnh (bản
 * trước) làm lưới 4 cột chật và biến mọi lần bấm nhầm thành một lần sửa dữ liệu.
 *
 * KHÔNG có nút tạo lại mô tả: VLM chỉ chạy một lần lúc tải ảnh lên.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { HopThoai } from '@/components/ui/HopThoai'

import { nguonAnh, suaMedia, xoaMedia, type Media } from '../api'
import { cauLoi } from '../thongDiep'

const O = 'w-full rounded border border-border-field px-2 py-1.5 text-[13px]'
const NUT = 'rounded border border-border-strong px-3 py-1.5 text-[13px] hover:border-ac'
const NUT_CHINH = 'rounded bg-ac px-3 py-1.5 text-[13px] text-white disabled:opacity-50'
const NUT_XOA = 'rounded border border-badge-alert-fg px-3 py-1.5 text-[13px] text-badge-alert-fg'

export function SuaMedia({
  projectCode,
  m,
  onDong,
  lamMoi,
}: {
  projectCode: string
  m: Media
  onDong: () => void
  lamMoi: () => void
}) {
  const [ten, setTen] = useState(m.fileName ?? '')
  const [moTa, setMoTa] = useState(m.caption ?? '')
  const [hoiXoa, setHoiXoa] = useState(false)

  const mLuu = useMutation({
    mutationFn: () => suaMedia(projectCode, m.id, { fileName: ten, caption: moTa }),
    onSuccess: () => {
      lamMoi()
      onDong()
    },
  })

  const mXoa = useMutation({
    mutationFn: () => xoaMedia(projectCode, m.id),
    onSuccess: () => {
      lamMoi()
      onDong()
    },
  })

  return (
    <HopThoai
      onDong={onDong}
      aria-label="Chỉnh sửa ảnh"
      className="m-auto w-[calc(100%-2rem)] max-w-lg max-h-[calc(100dvh-2rem)] space-y-3 overflow-y-auto rounded-xl border border-border bg-surface p-4 text-fg backdrop:bg-black/50"
    >
      <h2 className="text-the font-semibold">Chỉnh sửa</h2>

      {m.contentType === 'image' ? (
        <img
          src={nguonAnh(m.thumbUrl ?? m.mediaUrl)}
          alt=""
          className="max-h-56 w-full rounded border border-border object-contain"
        />
      ) : (
        <p className="break-all rounded bg-border-soft p-2 font-mono text-[12px]">{m.mediaUrl}</p>
      )}

      <label className="block space-y-1">
        <span className="text-[13px] text-muted">Tên</span>
        <input type="text" className={O} value={ten} onChange={(e) => setTen(e.target.value)} />
      </label>

      <label className="block space-y-1">
        <span className="text-[13px] text-muted">Mô tả (agent dùng câu này khi gửi cho khách)</span>
        <textarea rows={3} className={O} value={moTa} onChange={(e) => setMoTa(e.target.value)} />
      </label>

      {/* Vùng thông báo TỒN TẠI SẴN (rỗng lúc đầu): trình đọc màn hình chỉ đọc chữ đổ vào
            một vùng đã có, không đọc vùng mới mount cùng chữ. */}
      <p role="status" className="text-[12px] text-muted">
        {mLuu.isPending ? 'Đang lưu…' : mXoa.isPending ? 'Đang xoá…' : ''}
      </p>
      {mLuu.error && (
        <p role="alert" className="text-[12px] text-badge-alert-fg">
          {cauLoi(mLuu.error, 'lưu')}
        </p>
      )}
      {mXoa.error && (
        <p role="alert" className="text-[12px] text-badge-alert-fg">
          {cauLoi(mXoa.error, 'xoá')}
        </p>
      )}

      {hoiXoa ? (
        <div className="flex items-center justify-between gap-2 rounded border border-border p-2">
          <span className="text-[13px]">Xoá hẳn khỏi danh mục?</span>
          <div className="flex gap-2">
            <button type="button" className={NUT} onClick={() => setHoiXoa(false)}>
              Huỷ
            </button>
            <button
              type="button"
              className={NUT_XOA}
              disabled={mXoa.isPending}
              onClick={() => mXoa.mutate()}
            >
              Xoá
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <button type="button" className={NUT_XOA} onClick={() => setHoiXoa(true)}>
            Xoá
          </button>
          <div className="flex gap-2">
            <button type="button" className={NUT} onClick={onDong}>
              Huỷ
            </button>
            <button
              type="button"
              className={NUT_CHINH}
              disabled={mLuu.isPending}
              onClick={() => mLuu.mutate()}
            >
              {mLuu.isPending ? 'Đang lưu…' : 'Lưu'}
            </button>
          </div>
        </div>
      )}
    </HopThoai>
  )
}
