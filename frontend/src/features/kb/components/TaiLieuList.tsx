/**
 * Màn Tài liệu (M6). Nguồn nghiệp vụ: KB_01.
 *
 * BỐN THỨ MÀN NÀY PHẢI GIỮ, và cả bốn là lời hứa với người dùng:
 *   · Trạng thái từng file hiện RÕ (§I.2) — "không để khách tưởng upload xong là
 *     agent biết ngay". Giữa upload và Sẵn sàng có một khoảng bóc chữ + nhúng.
 *   · Lỗi nói LÝ DO VÀ CÁCH SỬA, không chỉ chữ "Lỗi" (§II.3). Đó là chỗ khách tự
 *     sửa được hoặc phải gọi hỗ trợ — chênh nhau đúng một câu.
 *   · Kho rỗng hiện HƯỚNG DẪN, không hiện như lỗi (BR04).
 *   · Xoá có xác nhận nói rõ không hoàn tác được (BR07).
 *
 * ⚠️ HAI TAB CHƯA LÀM — Agent đã trích dẫn và Không tìm được tài liệu.
 * Cả hai đọc dữ liệu mà `kb_search` phải ghi lại, và `kb_search` chạy TRONG tiến
 * trình agent (quyết định #6: in-process, một chặng, để giữ TTFA của voice).
 * Portal không nằm trên đường truy vấn nên không tự biết agent đã trích dẫn gì.
 * Dựng hai tab rỗng bây giờ là hứa một tính năng không có dữ liệu — chúng làm
 * cùng lúc với Gói G. Xem spec M6 §6.
 *
 * ─── Diện mạo ───────────────────────────────────────────────────────────────
 * ĐƯA VỀ HỆ DÙNG CHUNG 2026-08-07. Bản trước là màn LẠC NHẤT của portal, lạc
 * theo bốn cách cùng lúc — cả bốn đo được trên trình duyệt:
 *   ① Bảng KHÔNG có thẻ bọc: `<table>` trần nằm thẳng trên nền trang, trong khi
 *      bốn bảng còn lại đều nằm trong `TheBang` (thẻ trắng bo 12px, có viền).
 *   ② `<th>` không có padding ngang (`className="py-2"`), nên hai cột Dung
 *      lượng và Trạng thái DÍNH SÁT nhau — đo được x=329 và x=372, mỗi cột
 *      rộng 43px, không còn khe nào giữa chúng.
 *   ③ Màu lấy thẳng bảng mặc định của Tailwind — `text-red-700`, `border-red-300`,
 *      `bg-black` — thay vì token của hệ. Đây là nơi DUY NHẤT trong `features/`
 *      còn dùng màu ngoài token, nên nó đọc ra như một ứng dụng khác.
 *   ④ Padding trang `p-6` (24px) trong khi mọi màn khác `px-7` (28px), cộng một
 *      `<h1>` thứ hai trùng chữ với `<h1>` mà Topbar đã render.
 * Docstring của `Bang.tsx` đã dặn trước đúng chuyện này: năm bảng có cùng một
 * hình dạng… cái thứ năm luôn là cái bị quên. Đây chính là cái thứ năm.
 *
 * KHÔNG CÓ `<h1>` Ở ĐÂY — `components/shell/Topbar.tsx` render nó từ nhãn nav.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  HANG_NUT,
  Bang,
  DauBang,
  Hang,
  NUT_HANG_XOA,
  NUT_PHU,
  NutIcon,
  PILL,
  TD,
  TD_GON,
  TD_PHU,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { KhoRong } from '@/components/ui/TrangThai'
import { useKhoManHinh } from '@/lib/khoManHinh'
import { danhSach, taiLen, xoa, type TaiLieu } from '../api'
import { XemNoiDung } from './XemNoiDung'

const NHAN_TRANG_THAI: Record<TaiLieu['state'], string> = {
  dang_xu_ly: 'Đang xử lý',
  san_sang: 'Sẵn sàng',
  loi: 'Lỗi',
}

const MAU_TRANG_THAI: Record<TaiLieu['state'], string> = {
  dang_xu_ly: 'bg-badge-warn-bg text-badge-warn-fg',
  san_sang: 'bg-badge-neutral-bg text-badge-neutral-fg',
  loi: 'bg-badge-alert-bg text-badge-alert-fg',
}

const COT: readonly Cot[] = [
  { nhan: 'Tên tệp' },
  { nhan: 'Dung lượng', phai: true },
  { nhan: 'Trạng thái' },
  { nhan: '', phai: true },
]

const LOAI_NHAN = '.pdf, .docx, .xlsx, .md'

function kb(byte: number): string {
  const kib = Math.max(1, Math.round(byte / 1024))
  return kib < 1024 ? `${kib} KB` : `${(kib / 1024).toFixed(1)} MB`
}

/** Pill trạng thái + câu giải thích — ô riêng ở desktop, dòng phụ ở điện thoại. */
function trangThai(t: TaiLieu) {
  return (
    <>
      <span className={`${PILL} ${MAU_TRANG_THAI[t.state]}`}>{NHAN_TRANG_THAI[t.state]}</span>
      {t.state === 'dang_xu_ly' && (
        <p className="mt-1 text-phu text-muted">Agent chưa dùng tài liệu này.</p>
      )}
      {t.state === 'loi' && <p className="mt-1 text-phu text-badge-alert-fg">{t.loiMessage}</p>}
      {t.state === 'san_sang' && <p className="mt-1 text-phu text-muted">{t.chunkCount} đoạn</p>}
    </>
  )
}

export function TaiLieuList() {
  const qc = useQueryClient()
  const ds = useQuery({ queryKey: ['kb', 'files'], queryFn: danhSach })
  const [sapXoa, setSapXoa] = useState<TaiLieu | null>(null)
  const [dangXem, setDangXem] = useState<TaiLieu | null>(null)
  const dienThoai = useKhoManHinh() === 'mobile'

  const [loiTaiLen, setLoiTaiLen] = useState<readonly string[]>([])
  const [dangTai, setDangTai] = useState(0)

  const mTaiLen = useMutation({
    mutationFn: taiLen,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kb'] }),
    onError: (e: Error, file: File) => setLoiTaiLen((c) => [...c, `${file.name}: ${e.message}`]),
    onSettled: () => setDangTai((n) => Math.max(0, n - 1)),
  })

  const mXoa = useMutation({
    mutationFn: xoa,
    onSuccess: () => {
      setSapXoa(null)
      void qc.invalidateQueries({ queryKey: ['kb'] })
    },
  })

  if (ds.isPending)
    return <p className="px-7 py-6 text-[14px] text-muted max-md:px-4 max-md:py-4">Đang tải…</p>
  if (ds.error)
    return (
      <p className="px-7 py-6 text-[14px] max-md:px-4 max-md:py-4">
        Không tải được danh sách tài liệu.
      </p>
    )

  return (
    <div className="space-y-4 px-7 py-6 max-md:px-4 max-md:py-4">
      <label className="block cursor-pointer rounded-xl border border-dashed border-border-strong bg-surface p-6 text-center text-[14px] text-muted hover:border-fg focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ac">
        Kéo thả hoặc chọn tệp {LOAI_NHAN}
        <input
          type="file"
          className="sr-only"
          accept=".pdf,.docx,.xlsx,.md"
          multiple
          onChange={(e) => {
            const tep = Array.from(e.target.files ?? [])
            e.target.value = ''
            if (tep.length === 0) return
            setLoiTaiLen([])
            setDangTai((n) => n + tep.length)
            for (const f of tep) mTaiLen.mutate(f)
          }}
        />
      </label>

      {/* Vùng tồn tại sẵn — chữ đổ vào mới được đọc (xem `KhungSuaAgent`). */}
      <p role="status" className={dangTai > 0 ? 'text-[13px] text-muted' : 'sr-only'}>
        {dangTai > 0 && (
          <>
            Đang tải lên <span className="font-mono">{dangTai}</span> tệp…
          </>
        )}
      </p>

      {loiTaiLen.length > 0 && (
        <div role="alert" className="space-y-1">
          {loiTaiLen.map((l) => (
            <p key={l} className="text-[13px] leading-[1.5] text-badge-alert-fg">
              {l}
            </p>
          ))}
        </div>
      )}

      {sapXoa && <XacNhanXoa t={sapXoa} onDong={() => setSapXoa(null)} mXoa={mXoa} />}
      {dangXem && <XemNoiDung t={dangXem} onDong={() => setDangXem(null)} />}

      <TheBang>
        {ds.data.length === 0 ? (
          <div className="p-4">
            <KhoRong
              tieuDe="Chưa có tài liệu nào."
              huongDan="Nạp chính sách bán hàng, quy trình hoặc biểu phí để agent trả lời khách bằng chính tài liệu của bạn."
            />
          </div>
        ) : (
          <VungCuon>
            <Bang gon={dienThoai}>
              <DauBang cot={dienThoai ? [COT[0]!, COT[3]!] : COT} />
              <tbody>
                {ds.data.map((t) => (
                  <Hang key={t.id}>
                    {dienThoai ? (
                      // Điện thoại: tên (cắt bằng «…») · dung lượng, rồi trạng thái + câu giải
                      // thích xuống dòng phụ — bản cũ bóp cột trạng thái tới mức câu lỗi tải lên
                      // vỡ thành một chữ một dòng (audit 05/10).
                      <td className={`${TD} ${TD_GON}`}>
                        <p className="truncate font-semibold text-fg">{t.tenFile}</p>
                        <p className="font-mono text-[12px] text-muted-2">{kb(t.kichThuoc)}</p>
                        <div className="mt-1.5">{trangThai(t)}</div>
                      </td>
                    ) : (
                      <>
                        <td className={`${TD} font-semibold whitespace-nowrap text-fg`}>
                          {t.tenFile}
                        </td>
                        <td className={`${TD_PHU} text-right font-mono`}>{kb(t.kichThuoc)}</td>
                      </>
                    )}
                    {dienThoai ? null : <td className={TD}>{trangThai(t)}</td>}
                    <td className={`${TD} text-right`}>
                      <div className="flex items-center justify-end gap-1.5">
                        {t.state === 'san_sang' && (
                          <NutIcon
                            icon="xemNoiDung"
                            nhan={`Xem nội dung đã nạp ${t.tenFile}`}
                            onClick={() => setDangXem(t)}
                          />
                        )}
                        <NutIcon
                          icon="trash"
                          nhan={`Xoá tài liệu ${t.tenFile}`}
                          phaHuy
                          onClick={() => setSapXoa(t)}
                        />
                      </div>
                    </td>
                  </Hang>
                ))}
              </tbody>
            </Bang>
          </VungCuon>
        )}
      </TheBang>
    </div>
  )
}

function XacNhanXoa({
  t,
  onDong,
  mXoa,
}: {
  t: TaiLieu
  onDong: () => void
  mXoa: { mutate: (id: TaiLieu['id']) => void; isPending: boolean }
}) {
  return (
    <div
      role="group"
      aria-label={`Xác nhận xoá ${t.tenFile}`}
      className="rounded-xl border border-badge-alert-fg/30 bg-badge-alert-bg/60 p-4"
    >
      <p className="text-than leading-[1.55] text-fg">
        Xoá <strong>{t.tenFile}</strong>? Agent sẽ thôi dùng tài liệu này từ lần trả lời kế tiếp.
        Không có thùng rác — <strong>việc này không hoàn tác được</strong>.
      </p>
      <div className={`mt-2.5 ${HANG_NUT}`}>
        <button type="button" className={NUT_PHU} onClick={onDong}>
          Huỷ
        </button>
        <button
          type="button"
          className={`${NUT_HANG_XOA} disabled:opacity-60`}
          disabled={mXoa.isPending}
          onClick={() => mXoa.mutate(t.id)}
        >
          {mXoa.isPending ? 'Đang xoá…' : 'Xác nhận xoá'}
        </button>
      </div>
    </div>
  )
}
