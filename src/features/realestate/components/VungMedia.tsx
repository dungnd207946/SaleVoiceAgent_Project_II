/**
 * MỘT vùng media theo `category` — dùng ở tab Media (folder) và ở ba tab chuyên
 * đề (Vị trí · Mặt bằng · Tiến độ, mỗi tab một vùng).
 *
 * TÁCH RA KHỎI `MediaTab.tsx` (2026-08-10) vì bốn tab dùng chung. Cả bốn phải
 * giữ CÙNG query key `['re', code, 'media']` để số đếm không lệch nhau sau mỗi
 * lần upload cho tới khi cả bốn invalidate.
 *
 * BA BỐ CỤC (2026-08-11, thêm `moc` 2026-08-25):
 *   · `gallery` — một ảnh lớn `object-contain` + dải thumbnail. Cho Vị trí và
 *     Mặt bằng: mặt bằng là bản vẽ, `object-cover` cắt mất rìa mà rìa là chỗ ghi
 *     ký hiệu và tỉ lệ.
 *   · `luoi` — lưới thẻ lớn `object-cover`. Cho tab Media: nhiều ảnh, xem lướt,
 *     và ảnh phối cảnh cắt được.
 *   · `moc` — TIMELINE cho Tiến độ: cùng ô ảnh của `luoi` nhưng nhóm theo mốc
 *     («Tiến độ dd/mm/yyyy — …» trong caption — hợp đồng với adapter AINA, xem
 *     `moc.ts`), mốc mới nhất trước, ảnh không tiền tố nhóm theo ngày tạo. Lưới
 *     phẳng làm 30 ảnh của 3 tháng đọc thành một đống không phân biệt đợt nào
 *     mới (người dùng chốt theo giao diện bảng hàng AINA). Nhãn dưới ảnh chỉ
 *     còn phần RIÊNG của ảnh — caption mốc đã đứng ở heading nhóm.
 *
 * Nút ✎/✕ trên ảnh hiện THƯỜNG TRỰC (2026-08-21). Bản trước ẩn sau hover cho
 * ảnh làm nhân vật chính, nhưng thao tác xoá vì thế thành vô hình.
 */
import { useState } from 'react'
import { Icon } from '@/components/icons'
import { useMutation } from '@tanstack/react-query'
import { nguonAnh, taoMedia, xoaMedia, type Media, type MediaKem } from '../api'
import { nhanTrongMoc, nhomTheoMoc } from '../moc'
import { useEnrichStatus } from '../useEnrichStatus'
import { SuaMedia } from './SuaMedia'
import { CONTENT_TYPE, nhanCua } from '../enums'
import { cauLoi } from '../thongDiep'
import { AnhLon, type AnhXem } from './AnhLon'
import { OMedia } from './OMedia'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { tenMedia } from '../tenMedia'
import { useKhungSua } from '../khungSua'
import { SectionCard } from './SectionCard'

const NUT = 'rounded border border-border-field px-2 py-1 text-[13px]'
/**
 * Nút trên ảnh hiện THƯỜNG TRỰC. Bản trước dùng `opacity-0 group-hover:opacity-100`
 * để ảnh làm nhân vật chính, nhưng cái giá là xoá một ảnh trở thành thao tác vô
 * hình — và trên cảm ứng thì không có hover để mà hiện.
 */
// `max-md:` 40px: vùng chạm của cặp nút góc ảnh bản cũ chỉ ~20px — trên điện thoại
// là chạm trượt vào ảnh (mở lightbox) thay vì vào nút.
const NUT_ANH_CHUNG =
  'inline-flex items-center justify-center rounded px-1.5 py-0.5 text-nhan leading-normal text-white transition-colors max-md:min-h-10 max-md:min-w-10 max-md:text-[13px]'
const NUT_ANH = `${NUT_ANH_CHUNG} bg-black/60 hover:bg-black/80`
const NUT_ANH_XOA = `${NUT_ANH_CHUNG} bg-badge-alert-fg/85 hover:bg-badge-alert-fg`

export type BoCucMedia = 'luoi' | 'gallery' | 'moc'

/** 20 = mặc định của `ThanhTrang`; lưới 4 cột nên 20 ra 5 hàng đầy. */
const SO_HANG_MEDIA = 20

interface VungProps {
  projectCode: string
  category: string
  nhan: string
  anh: readonly Media[]
  lamMoi: () => void
  boCuc?: BoCucMedia
  /** Tiêu đề thẻ của bố cục `gallery`; vắng thì thẻ không có tiêu đề. */
  title?: string | undefined
}

const LINK = 'font-medium text-ac hover:text-acd'
const LINK_XOA = 'font-medium text-badge-alert-fg hover:underline'

/** Bản đồ và bản vẽ: model tả ra chữ không có giá trị tra cứu. */
const KHONG_TA: Record<string, boolean> = { vi_tri: true, mat_bang: true }

export function VungMedia({
  projectCode,
  category,
  nhan,
  anh,
  lamMoi,
  boCuc = 'luoi',
  title,
}: VungProps) {
  const { dangSua: editing } = useKhungSua()
  const [them, setThem] = useState<MediaKem | null>(null)
  const enrich = useEnrichStatus(projectCode)
  const [dangXem, setDangXem] = useState<number | null>(null)
  const [dangSua, setDangSua] = useState<Media | null>(null)
  const [hoiXoa, setHoiXoa] = useState<number | null>(null)
  const [chinh, setChinh] = useState(0)
  const [trang, setTrang] = useState(1)
  const [soHang, setSoHang] = useState(SO_HANG_MEDIA)

  const mThem = useMutation({
    mutationFn: (b: MediaKem) =>
      taoMedia(projectCode, {
        category,
        contentType: b.contentType ?? 'image',
        mediaUrl: b.mediaUrl,
        caption: b.caption ?? '',
        fileName: b.fileName ?? '',
        contentHash: b.contentHash ?? '',
        status: 'published',
      }),
    onSuccess: () => {
      setThem(null)
      lamMoi()
    },
  })

  const mXoa = useMutation({
    mutationFn: (id: number) => xoaMedia(projectCode, id),
    onSuccess: () => {
      setHoiXoa(null)
      lamMoi()
    },
  })

  // Lightbox chỉ đi trong ẢNH: một video xen giữa làm `‹ ›` nhảy qua một ô trống.
  const chiAnh = anh.filter((m) => m.contentType === 'image')
  const boXem: AnhXem[] = chiAnh.map((m) => ({
    src: nguonAnh(m.mediaUrl),
    caption: m.caption || '',
  }))
  const moXem = (m: Media) => setDangXem(chiAnh.findIndex((x) => x.id === m.id))

  /** Ô video: bấm mở nguồn ở tab mới. Không nhúng player — nguồn lẫn YouTube embed và .mp4. */
  const oVideo = (m: Media, lop: string) => (
    <a
      href={nguonAnh(m.mediaUrl)}
      target="_blank"
      rel="noreferrer"
      className={`${lop} flex items-center justify-center rounded border border-border bg-border-soft text-[13px] text-muted hover:border-border-field`}
    >
      ▶ {nhanCua(CONTENT_TYPE, m.contentType)}
    </a>
  )

  /**
   * Cặp nút góc ảnh. Xoá xác nhận NGAY TẠI ĐÂY chứ không mở `SuaMedia`: mở form
   * sửa để xoá là bắt người ta đi qua một màn không liên quan tới việc họ muốn làm.
   */
  const nutAnh = (m: Media) => (
    <span className="absolute right-1.5 top-1.5 flex gap-1">
      {hoiXoa === m.id ? (
        <>
          <button
            type="button"
            className={NUT_ANH}
            onClick={() => setHoiXoa(null)}
            disabled={mXoa.isPending}
          >
            Thôi
          </button>
          <button
            type="button"
            className={NUT_ANH_XOA}
            onClick={() => mXoa.mutate(m.id)}
            disabled={mXoa.isPending}
          >
            Xoá hẳn
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            className={NUT_ANH}
            aria-label={`Sửa ảnh — ${moTaCua(m)}`}
            onClick={() => setDangSua(m)}
          >
            <Icon name="edit" className="size-3.5 max-md:size-4" />
          </button>
          <button
            type="button"
            className={NUT_ANH_XOA}
            aria-label={`Xoá ảnh — ${moTaCua(m)}`}
            onClick={() => setHoiXoa(m.id)}
          >
            <Icon name="trash" className="size-3.5 max-md:size-4" />
          </button>
        </>
      )}
    </span>
  )

  /**
   * `alt`/`aria-label` — CÂU MÔ TẢ, không phải tên tệp: trình đọc màn hình cần
   * biết ảnh CHỤP GÌ, và `01533f6a-….jpg` không nói được điều đó.
   */
  const tenCua = (m: Media) => tenMedia(m)
  const moTaCua = (m: Media, thu?: string) => m.caption || tenCua(m) || thu || nhan

  /**
   * HAI DÒNG: tên tệp trên, mô tả dưới (người dùng chốt 2026-08-25 — «luôn ưu tiên
   * show tên tệp trước»).
   *
   * ⚠️ Vì sao không THAY mô tả bằng tên: đo trên `aina_prod` — 723/723 ảnh của cổng
   * nạp mang `fileName` là UUID, còn 93 video và 19 tour 360 có `fileName` RỖNG
   * hoàn toàn. Bỏ mô tả đi thì được một lưới UUID và 112 thẻ không nhãn. Nên tên
   * lên trước, mô tả ở lại làm dòng phụ, và link ngoài suy tên từ URL.
   *
   * `ta` ĐÈ dòng mô tả (timeline `moc` chỉ hiện phần RIÊNG của ảnh — caption mốc
   * đã đứng ở heading nhóm, lặp lại dưới từng ảnh là nhiễu); `''` là GIẤU hẳn
   * dòng đó, không phải rơi về caption.
   */
  const dongTen = (m: Media, ta?: string) => {
    const ten = tenCua(m)
    const taHien = ta ?? (m.caption || '')
    return (
      <div className="mt-1 min-w-0">
        <p className="truncate text-[12px] font-medium text-fg" title={ten}>
          {ten}
        </p>
        {enrich.running.has(m.id) ? (
          <p className="truncate text-nhan text-ac">◐ Đang tạo mô tả…</p>
        ) : (
          taHien && (
            <p className="truncate text-nhan text-muted-2" title={taHien}>
              {taHien}
            </p>
          )
        )}
        <a
          href={m.mediaUrl}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="text-nhan text-ac hover:underline"
        >
          Mở bản gốc ↗
        </a>
      </div>
    )
  }

  /** Một Ô media của lưới — dùng chung cho `luoi`/`gallery` và từng nhóm của
      `moc`. `ta` đè dòng mô tả (xem `dongTen`); aria/alt vẫn mang caption đầy
      đủ — máy đọc không thấy heading nhóm đứng ngay trên như mắt thấy. */
  const oMuc = (m: Media, ta?: string) => (
    <li key={m.id} className="group relative">
      {m.contentType === 'image' ? (
        <button
          type="button"
          onClick={() => moXem(m)}
          aria-label={moTaCua(m)}
          className="block w-full"
        >
          <img
            src={nguonAnh(m.thumbUrl ?? m.mediaUrl)}
            alt={moTaCua(m)}
            className="h-40 w-full rounded-lg border border-border object-cover"
          />
        </button>
      ) : (
        oVideo(m, 'h-40 w-full')
      )}
      {dongTen(m, ta)}
      {nutAnh(m)}
    </li>
  )

  const chinhAnToan = Math.min(chinh, Math.max(chiAnh.length - 1, 0))
  const anhChinh = chiAnh[chinhAnToan]

  /**
   * PHÂN TRANG CLIENT-SIDE, cố ý: cả bốn folder của tab Media dùng CHUNG một query
   * `['re', code, 'media']` (xem docstring đầu file) nên chia trang ở server sẽ làm
   * số đếm bốn folder lệch nhau. Ở đây mảng đã nằm trong tay, cắt là đủ.
   *
   * `gallery` không phân trang: dải thumbnail của nó là bộ điều hướng của chính ảnh
   * lớn, cắt nó thành trang là cắt đường đi tới ảnh thứ 21. `moc` cũng không —
   * timeline là một dòng thời gian liền, cắt trang là cắt giữa hai mốc.
   */
  const trongLuoi = boCuc === 'luoi' ? anh : anh.filter((m) => m.contentType !== 'image')
  const soTrang = boCuc === 'luoi' ? Math.max(1, Math.ceil(trongLuoi.length / soHang)) : 1
  const trangAnToan = Math.min(trang, soTrang)
  const cuaTrang =
    boCuc === 'luoi' ? trongLuoi.slice((trangAnToan - 1) * soHang, trangAnToan * soHang) : trongLuoi

  const formThem = them && (
    <div className="space-y-2">
      <OMedia
        nhan={`Ảnh mới — ${nhan}`}
        giaTri={them}
        doi={setThem}
        choVideo
        noDraftCaption={KHONG_TA[category]}
      />
      <button
        type="button"
        className="rounded bg-ac px-3 py-1.5 text-[13px] text-white disabled:opacity-50"
        disabled={mThem.isPending || !them.mediaUrl}
        onClick={() => mThem.mutate(them)}
      >
        {mThem.isPending ? 'Đang lưu…' : 'Thêm vào danh mục'}
      </button>
      <button type="button" className={NUT} onClick={() => setThem(null)}>
        Huỷ
      </button>
    </div>
  )

  const loiThaoTac = (
    <>
      {mThem.error && (
        <p className="mt-1 text-[12px] text-badge-alert-fg" role="alert">
          {cauLoi(mThem.error, 'thêm ảnh')}
        </p>
      )}
      {mXoa.error && (
        <p className="mt-1 text-[12px] text-badge-alert-fg" role="alert">
          {cauLoi(mXoa.error, 'xoá ảnh')}
        </p>
      )}
    </>
  )

  const lightboxVaSua = (
    <>
      {dangXem !== null && dangXem >= 0 && (
        <AnhLon anh={boXem} batDau={dangXem} onDong={() => setDangXem(null)} />
      )}
      {dangSua && (
        <SuaMedia
          projectCode={projectCode}
          m={dangSua}
          onDong={() => setDangSua(null)}
          lamMoi={lamMoi}
        />
      )}
    </>
  )

  // Vị trí, Mặt bằng: ảnh to hết chiều ngang, mô tả ngay dưới; nút thêm, sửa, xoá chỉ hiện khi đang sửa.
  if (boCuc === 'gallery') {
    return (
      <SectionCard
        title={title}
        cols={1}
        actions={
          editing && !them ? (
            <button
              type="button"
              className={NUT}
              onClick={() => setThem({ mediaUrl: '', caption: '' })}
            >
              Thêm ảnh
            </button>
          ) : undefined
        }
      >
        {anhChinh ? (
          <div>
            <button
              type="button"
              onClick={() => moXem(anhChinh)}
              aria-label={`Phóng to: ${moTaCua(anhChinh)}`}
              className="block w-full cursor-zoom-in overflow-hidden rounded-lg bg-fill-strong"
            >
              <img
                data-testid="anh-lon"
                src={nguonAnh(anhChinh.mediaUrl)}
                alt={moTaCua(anhChinh)}
                className="mx-auto block max-h-[78vh] w-full object-contain"
              />
            </button>
            {anhChinh.caption && (
              <p className="mt-2.5 max-w-[110ch] text-than leading-[1.55] text-nav">
                {anhChinh.caption}
              </p>
            )}
            <div className="mt-1.5 flex flex-wrap items-center gap-4 text-than">
              <a href={anhChinh.mediaUrl} target="_blank" rel="noreferrer" className={LINK}>
                Mở ảnh gốc
              </a>
              {editing &&
                (hoiXoa === anhChinh.id ? (
                  <>
                    <span className="text-nav">Xoá ảnh này?</span>
                    <button type="button" className={LINK} onClick={() => setHoiXoa(null)}>
                      Thôi
                    </button>
                    <button
                      type="button"
                      className={LINK_XOA}
                      disabled={mXoa.isPending}
                      onClick={() => mXoa.mutate(anhChinh.id)}
                    >
                      Xoá hẳn
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      className={LINK}
                      aria-label={`Sửa mô tả — ${moTaCua(anhChinh)}`}
                      onClick={() => setDangSua(anhChinh)}
                    >
                      Sửa mô tả
                    </button>
                    <button
                      type="button"
                      className={LINK_XOA}
                      aria-label={`Xoá ảnh — ${moTaCua(anhChinh)}`}
                      onClick={() => setHoiXoa(anhChinh.id)}
                    >
                      Xoá
                    </button>
                  </>
                ))}
            </div>
            {chiAnh.length > 1 && (
              <ul className="mt-3.5 flex flex-wrap gap-2.5">
                {chiAnh.map((m, idx) => (
                  <li key={m.id}>
                    <button
                      type="button"
                      onClick={() => setChinh(idx)}
                      aria-label={`Chọn: ${moTaCua(m, `ảnh ${idx + 1}`)}`}
                      aria-current={idx === chinhAnToan}
                      className={`overflow-hidden rounded-lg border-2 ${
                        idx === chinhAnToan ? 'border-ac' : 'border-transparent'
                      }`}
                    >
                      <img
                        data-testid="anh-thumb"
                        src={nguonAnh(m.thumbUrl ?? m.mediaUrl)}
                        alt=""
                        className="block h-[76px] w-[132px] object-cover"
                      />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          !them && <p className="text-than text-muted-2">Chưa có ảnh.</p>
        )}
        {trongLuoi.length > 0 && (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {cuaTrang.map((m) => oMuc(m))}
          </ul>
        )}
        {formThem}
        {loiThaoTac}
        {lightboxVaSua}
      </SectionCard>
    )
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-3">
      <header className="mb-3 flex items-baseline justify-between">
        <h3 className="text-[14px] font-medium">{nhan}</h3>
        <span className="text-[12px] text-muted">{anh.length} mục</span>
      </header>

      {boCuc === 'luoi' && trongLuoi.length > 0 && (
        <ul className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {cuaTrang.map((m) => oMuc(m))}
        </ul>
      )}

      {boCuc === 'moc' && anh.length > 0 && (
        <ol className="mb-3 ml-1 space-y-6 border-l border-border pl-5">
          {nhomTheoMoc(anh).map((g) => (
            <li key={g.khoa} className="relative">
              {/* Chấm neo vào vạch dọc: -25px = pl-5 (20) + nửa chấm (5). */}
              <span
                aria-hidden
                className="absolute top-[3px] -left-[25px] size-2.5 rounded-full bg-ac"
              />
              <p data-testid="moc-ngay" className="text-[12px] leading-none text-muted">
                {g.ngay}
              </p>
              {g.tieuDe && <p className="mt-1 text-[14px] font-medium">{g.tieuDe}</p>}
              <ul className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {g.anh.map((m) => oMuc(m, nhanTrongMoc(m)))}
              </ul>
            </li>
          ))}
        </ol>
      )}

      {soTrang > 1 && (
        <ThanhTrang
          trang={trangAnToan}
          soTrang={soTrang}
          total={trongLuoi.length}
          soHang={soHang}
          doiTrang={setTrang}
          doiSoHang={(n) => {
            setSoHang(n)
            setTrang(1)
          }}
        />
      )}

      {them ? (
        formThem
      ) : (
        <button
          type="button"
          className={NUT}
          onClick={() => setThem({ mediaUrl: '', caption: '' })}
        >
          ＋ Thêm ảnh / video
        </button>
      )}

      {loiThaoTac}
      {lightboxVaSua}
    </section>
  )
}
