/**
 * Ô media dùng chung — tải lên MinIO HOẶC dán URL ngoài.
 *
 * HAI TAB, KHÔNG PHẢI MỘT. `media.media_url` chứa hai loại giá trị theo đúng
 * `02a §4` (URL file (MinIO/YouTube/kuula/Drive)): tệp của ta thì upload được,
 * còn video YouTube và tour 360 kuula thì KHÔNG — chúng không phải tệp ta giữ.
 * Chỉ làm ô upload nghĩa là không nhập được video; chỉ làm ô URL nghĩa là người
 * biên tập phải tự đi upload ảnh ở đâu đó trước. Nên cả hai.
 *
 * GIÁ TRỊ RA NGOÀI luôn là `mediaUrl` dạng chuỗi: khoá MinIO (`tenants/…`) hoặc
 * URL `http…`. Chỗ gọi không cần biết nó tới từ tab nào — `api.nguonAnh()` lo
 * việc render.
 *
 * `caption` CÓ MÁY VIẾT NHÁP ĐÚNG MỘT LẦN, ngay lúc tải ảnh lên và TRƯỚC khi lưu:
 * mô tả hiện trong form để người dùng đọc/sửa, nên cú bấm Thêm chính là cú duyệt.
 * Sau đó không đường nào gọi model cho ảnh này nữa — không nút "Tạo lại mô tả",
 * không tự tả lại khi đổi ảnh.
 */
import { useRef, useState } from 'react'
import { LoiApi } from '@/lib/http'
import { laNguonNgoai, nguonAnh, taiTepLen, type MediaKem } from '../api'
import { useDraftCaption } from '../useDraftCaption'

interface Props {
  nhan: string
  giaTri: MediaKem | null
  doi: (v: MediaKem | null) => void
  goiY?: string | undefined
  choVideo?: boolean | undefined
  noDraftCaption?: boolean | undefined
  /** Chỉ-đọc: giữ ảnh đang có, bỏ mọi đường tải lên / dán URL / xoá. */
  khoa?: boolean | undefined
  /** Bỏ khung và nhãn — khi ô nằm trong một thẻ đã có tiêu đề. */
  bare?: boolean | undefined
}

const NUT = 'rounded border border-border-field px-2 py-1 text-[13px]'
const NUT_CHON = 'rounded border border-ac bg-acs px-2 py-1 text-[13px] text-acd'

export function OMedia({ nhan, giaTri, doi, goiY, choVideo, noDraftCaption, khoa, bare }: Props) {
  const [tab, setTab] = useState<'len' | 'url'>('len')
  const [dangTai, setDangTai] = useState(false)
  const [loi, setLoi] = useState('')
  const [urlNhap, setUrlNhap] = useState('')
  const oTep = useRef<HTMLInputElement>(null)
  const giaTriRef = useRef(giaTri)
  giaTriRef.current = giaTri
  const { sinh, running: dangTaoMoTa } = useDraftCaption((caption) => {
    const hienTai = giaTriRef.current
    if (hienTai && !hienTai.caption) doi({ ...hienTai, caption })
  })

  async function chonTep(tep: File) {
    setLoi('')
    setDangTai(true)
    try {
      const len = await taiTepLen(tep)
      const loai = len.contentType.startsWith('video/') ? 'video' : 'image'
      doi({
        mediaUrl: len.key,
        caption: giaTri?.caption ?? '',
        fileName: tep.name,
        contentType: loai,
        contentHash: len.contentHash,
      })
      if (!noDraftCaption) void sinh(len.key, loai)
    } catch (e) {
      setLoi(e instanceof LoiApi ? e.message : 'Không tải được tệp lên')
    } finally {
      setDangTai(false)
      if (oTep.current) oTep.current.value = ''
    }
  }

  function datUrl() {
    const v = urlNhap.trim()
    if (!v) return
    if (!/^https?:\/\//i.test(v)) {
      setLoi('URL phải bắt đầu bằng http:// hoặc https://')
      return
    }
    setLoi('')
    const loai = choVideo ? 'video' : 'image'
    doi({
      mediaUrl: v,
      caption: giaTri?.caption ?? '',
      fileName: decodeURIComponent(v.split('?')[0]?.split('/').pop() ?? ''),
      contentType: loai,
    })
    setUrlNhap('')
    if (!noDraftCaption) void sinh(v, loai)
  }

  const daCo = !!giaTri?.mediaUrl

  return (
    <div className={bare ? '' : 'rounded-xl border border-border bg-surface p-3'}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className={bare ? 'sr-only' : 'text-[13px] text-muted'}>{nhan}</span>
        <div className="flex gap-1" hidden={khoa}>
          <button
            type="button"
            aria-label={`Tải lên — ${nhan}`}
            className={tab === 'len' ? NUT_CHON : NUT}
            onClick={() => setTab('len')}
          >
            Tải lên
          </button>
          <button
            type="button"
            aria-label={`Dán URL — ${nhan}`}
            className={tab === 'url' ? NUT_CHON : NUT}
            onClick={() => setTab('url')}
          >
            Dán URL
          </button>
        </div>
      </div>

      {daCo && giaTri ? (
        <div className="space-y-2">
          {giaTri.contentType === 'video' ? (
            <p className="break-all rounded bg-border-soft p-2 font-mono text-[12px]">
              {laNguonNgoai(giaTri.mediaUrl) ? 'Video ngoài: ' : 'Video trong kho: '}
              {giaTri.mediaUrl}
            </p>
          ) : (
            <img
              src={nguonAnh(giaTri.mediaUrl)}
              alt={giaTri.caption || nhan}
              className="max-h-40 rounded border border-border object-contain"
            />
          )}
          {khoa ? (
            giaTri.caption && <p className="text-[13px] text-muted">{giaTri.caption}</p>
          ) : (
            <input
              type="text"
              aria-label={`Chú thích — ${nhan}`}
              placeholder={
                dangTaoMoTa
                  ? 'Đang tạo mô tả…'
                  : 'Chú thích (agent dùng câu này khi gửi ảnh cho khách)'
              }
              value={giaTri.caption ?? ''}
              onChange={(e) => doi({ ...giaTri, caption: e.target.value })}
              className="w-full rounded border border-border-field px-2 py-1 text-[13px]"
            />
          )}
          {dangTaoMoTa && (
            <p className="text-[12px] text-muted">◐ Đang tạo mô tả tự động — sửa được sau</p>
          )}
          {!khoa && (
            <button type="button" className={NUT} onClick={() => doi(null)}>
              Bỏ {nhan.toLowerCase()}
            </button>
          )}
        </div>
      ) : khoa ? (
        <p className="text-[13px] text-muted-2">Chưa có {nhan.toLowerCase()}.</p>
      ) : tab === 'len' ? (
        <label
          // `max-md:relative`: ô nhập ẩn (`sr-only`, `position:absolute`)
          // bên trong không tự neo được vào label này ở mọi bề rộng —
          // thiếu containing block, nó bám ra tới `<main>` (chỗ duy nhất có
          // `relative` phía trên) và kéo theo static position của nó, một
          // con số tính như thể cả tab KHÔNG bị cuộn/cắt. Trên các màn dùng
          // `KHUNG_MAN`+`VUNG_TAB` (`/pform`, `/uform` ở chế độ Sửa) điều đó
          // cho `<main>` một khoảng cuộn dư thừa hàng trăm px mà lẽ ra phải
          // bằng 0 — cuộn chuột quá đáy `VUNG_TAB` thì scroll-chain sang
          // `<main>`, kéo luôn thanh Lưu dán đáy lên gần đỉnh màn. Xem
          // task-11-report.md §"Fix round 1" để có phép đo trước/sau.
          className={`block cursor-pointer rounded-md border border-dashed p-4 text-center text-[13px] transition-colors max-md:relative ${
            dangTai
              ? 'border-ac bg-acs font-medium text-acd'
              : 'border-border-strong text-muted hover:border-ac hover:bg-acs/50 hover:text-acd'
          }`}
        >
          {dangTai ? 'Đang tải lên…' : 'Kéo thả hoặc chọn tệp .jpg .png .webp (≤ 10 MB)'}
          <input
            ref={oTep}
            type="file"
            aria-label={`Kéo thả hoặc chọn tệp — ${nhan}`}
            className="sr-only"
            accept=".jpg,.jpeg,.png,.webp"
            disabled={dangTai}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void chonTep(f)
            }}
          />
        </label>
      ) : (
        <div className="flex gap-2">
          <input
            type="url"
            aria-label={`URL — ${nhan}`}
            placeholder={
              choVideo ? 'https://youtube.com/… hoặc https://kuula.co/…' : 'https://…/anh.webp'
            }
            value={urlNhap}
            onChange={(e) => setUrlNhap(e.target.value)}
            className="flex-1 rounded border border-border-field px-2 py-1 text-[13px]"
          />
          <button type="button" className={NUT} aria-label={`Dùng URL — ${nhan}`} onClick={datUrl}>
            Dùng
          </button>
        </div>
      )}

      {goiY && !loi && <p className="mt-1 text-[12px] text-muted-2">{goiY}</p>}
      {loi && <p className="mt-1 text-[12px] text-badge-alert-fg">{loi}</p>}
    </div>
  )
}

interface OTepProps {
  nhan: string
  /** Khoá MinIO của tệp, hoặc null. */
  giaTri: string | null
  doi: (key: string | null, tenGoc: string) => void
  goiY?: string | undefined
  loi?: string | undefined
  /** Chỉ-đọc: giữ link tới tệp, bỏ nút Bỏ tệp và ô chọn tệp. */
  khoa?: boolean | undefined
}

export function OTep({ nhan, giaTri, doi, goiY, loi, khoa }: OTepProps) {
  const [dangTai, setDangTai] = useState(false)
  const [loiTai, setLoiTai] = useState('')
  const oTep = useRef<HTMLInputElement>(null)

  async function chon(tep: File) {
    setLoiTai('')
    setDangTai(true)
    try {
      const len = await taiTepLen(tep)
      doi(len.key, tep.name)
    } catch (e) {
      setLoiTai(e instanceof LoiApi ? e.message : 'Không tải được tệp lên')
    } finally {
      setDangTai(false)
      if (oTep.current) oTep.current.value = ''
    }
  }

  return (
    <div>
      <span className="mb-1 block text-[13px] text-muted">{nhan}</span>
      {giaTri ? (
        <div className="flex items-center gap-2">
          <a
            href={nguonAnh(giaTri)}
            target="_blank"
            rel="noreferrer"
            className="flex-1 truncate rounded bg-border-soft px-2 py-1 font-mono text-[12px]"
          >
            {giaTri.split('/').pop()}
          </a>
          {!khoa && (
            <button type="button" className={NUT} onClick={() => doi(null, '')}>
              Bỏ tệp
            </button>
          )}
        </div>
      ) : khoa ? (
        <p className="text-[13px] text-muted-2">Chưa có tệp.</p>
      ) : (
        <label
          // Cùng lý do `max-md:relative` ở `OMedia` phía trên — `<input
          // sr-only>` ngay dưới cần một containing block bên trong VUNG_TAB,
          // không phải trôi ra tới `<main>`.
          className={`block cursor-pointer rounded-md border border-dashed p-3 text-center text-[13px] transition-colors max-md:relative ${
            dangTai
              ? 'border-ac bg-acs font-medium text-acd'
              : 'border-border-strong text-muted hover:border-ac hover:bg-acs/50 hover:text-acd'
          }`}
        >
          {dangTai ? 'Đang tải lên…' : 'Chọn tệp .pdf .docx .xlsx hoặc ảnh (≤ 25 MB)'}
          <input
            ref={oTep}
            type="file"
            aria-label={`Chọn tệp — ${nhan}`}
            className="sr-only"
            accept=".pdf,.docx,.xlsx,.jpg,.jpeg,.png,.webp"
            disabled={dangTai}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void chon(f)
            }}
          />
        </label>
      )}
      {goiY && !loi && !loiTai && <p className="mt-0.5 text-[12px] text-muted-2">{goiY}</p>}
      {(loi || loiTai) && <p className="mt-0.5 text-[12px] text-badge-alert-fg">{loi || loiTai}</p>}
    </div>
  )
}
