/**
 * Dialog xác nhận trước khi Lưu và áp dụng — bước Xem trước của AG_01 §II.1 nuốt vào đây.
 *
 * TỪ BACKEND `0966`: không còn `POST /config/preview`. Danh sách «Sẽ đổi» tính ở CLIENT
 * (`thayDoi` — so `form` với bản đang lưu), chia ba nhóm theo đúng cách màn chia ô:
 * phần DÙNG CHUNG một lần, rồi phần riêng của từng role. Hợp lệ hay không do `PUT /config`
 * trả lời (422/409) — lỗi thì dialog ở lại, không có gì được ghi (một giao dịch).
 *
 * Lưu là ÁP DỤNG NGAY cho mọi role, nên dialog nói thẳng điều đó.
 */
import { useEffect, useRef } from 'react'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import type { CauHinh, VaiTroMeta } from '../api'
import { thayDoi } from '../useBanNhap'
import { NUT_CHINH, NUT_PHU } from './lop'

function DanhSach({ tieuDe, ds }: { tieuDe: string; ds: string[] }) {
  if (ds.length === 0) return null
  return (
    <div>
      <p className="mb-2 text-phu text-muted">{tieuDe}</p>
      <ul aria-label={`Sẽ đổi — ${tieuDe}`} className="flex flex-wrap gap-1.5">
        {ds.map((t) => (
          <li
            key={t}
            className="rounded-md bg-badge-warn-bg px-2 py-[3px] font-mono text-[12px] font-medium text-badge-warn-fg"
          >
            {t}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function LuuApDungDialog(props: {
  /** Bản đang lưu trên server (đã chuẩn hoá) — mốc để tính «Sẽ đổi». */
  goc: CauHinh
  form: CauHinh
  /** Thứ tự + tên hiển thị của các nhóm «Sẽ đổi» theo role. */
  vaiTro: VaiTroMeta[]
  dangGui: boolean
  /** Lỗi của lần `PUT /config` trước — dialog KHÔNG tự đóng khi lỗi. */
  loiApDung: boolean
  onDong: () => void
  onXacNhan: () => void
}) {
  // Cùng khuôn `TaoKhoaDialog.tsx`: Esc đóng được (chặn khi đang gửi), focus vào Huỷ.
  const huyRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    huyRef.current?.focus()
  }, [])

  const doi = thayDoi(props.goc, props.form)
  const coDoi =
    doi.chung.length + Object.values(doi.theoRole).reduce((n, ds) => n + ds.length, 0) > 0

  return (
    <HopThoai
      onDong={props.onDong}
      khoaDong={props.dangGui}
      aria-label="Xem lại trước khi áp dụng"
      className={`${KHUNG_HOP_THOAI} max-w-[520px]`}
    >
      <h2 className="text-[16.5px] font-semibold leading-tight">Xem lại trước khi áp dụng</h2>

      <div className="mt-3.5 flex flex-col gap-3">
        {coDoi ? (
          <>
            <DanhSach tieuDe="Dùng chung" ds={doi.chung} />
            {props.vaiTro.map((r) => (
              <DanhSach key={r.key} tieuDe={r.ten} ds={doi.theoRole[r.key] ?? []} />
            ))}
          </>
        ) : (
          <p className="text-than text-muted">Không có thay đổi so với bản đang chạy.</p>
        )}
      </div>

      {/* BR10 — thiếu câu này, người sửa một rào chắn đang nói sai sẽ tưởng chặn được ngay. */}
      <p className="mt-3.5 text-phu leading-[1.5] text-muted-2">
        Áp dụng ngay cho mọi role. Cuộc hội thoại đang diễn ra vẫn dùng bản cũ tới khi kết thúc.
      </p>

      {props.loiApDung && (
        <p className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] font-medium text-badge-alert-fg">
          Chưa áp dụng được — chưa có gì thay đổi, thử lại lần nữa.
        </p>
      )}

      <div className="mt-5 flex items-center justify-end gap-2">
        <button
          ref={huyRef}
          type="button"
          onClick={props.onDong}
          disabled={props.dangGui}
          className={NUT_PHU}
        >
          Huỷ
        </button>
        <button
          type="button"
          onClick={props.onXacNhan}
          disabled={props.dangGui}
          className={NUT_CHINH}
        >
          {props.dangGui ? 'Đang áp dụng…' : 'Xác nhận áp dụng'}
        </button>
      </div>
    </HopThoai>
  )
}
