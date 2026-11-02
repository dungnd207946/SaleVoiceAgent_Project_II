/**
 * Hộp thoại «Người dẫn» của tab Voice — chọn người dẫn lip sync và TẠO người dẫn riêng.
 *
 * Ba màn trong một hộp thoại (không route riêng: đây là thiết lập của sân khấu, mở
 * từ chính sân khấu):
 *  - `ds`      danh sách: người dẫn mặc định + nhân vật đã tạo (poster · trạng thái ·
 *              Dùng / Xem / Xoá) + ô «Tạo nhân vật».
 *  - `tao`     form: tên · nguồn (video tự quay | ảnh → AI tạo video) · tệp · đồng ý.
 *  - `xem`     một nhân vật: đang dựng ⇒ tiến độ (thăm dò 3s); lỗi ⇒ hướng dẫn + Thử lại;
 *              xong ⇒ 3 video nói thử + ô «thử câu khác» + «Dùng nhân vật này».
 *
 * Dựng chạy NỀN ở backend — đóng hộp thoại không huỷ gì, mở lại vẫn thấy tiến độ.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Icon, type IconName } from '@/components/icons'
import { CAO_O, HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { O_CHUNG } from '@/components/ui/Truong'
import { LoiApi } from '@/lib/http'
import { ANH_CHO_AVATAR } from '../avatarLipSync'
import {
  chonNhanVat,
  dangDung,
  KHOA_DANG_DUNG,
  KHOA_NHAN_VAT,
  khoaMotNhanVat,
  nhanBuoc,
  taiDanhSach,
  taiNhanVat,
  taoNhanVat,
  thuLai,
  xemTruocCau,
  xoaNhanVat,
  type NhanVat,
} from '../nhanVat'

/** Nút phá huỷ — cùng khuôn `XoaWorkspaceDialog` (nền đỏ, chữ trắng). */
const NUT_XOA = `${CAO_O} inline-flex items-center justify-center rounded-md bg-badge-alert-fg px-[15px] text-than font-semibold text-white disabled:opacity-50`

type Man = { loai: 'ds' } | { loai: 'tao' } | { loai: 'xem'; id: string }

const thongDiep = (e: unknown, macDinh: string) => (e instanceof LoiApi ? e.message : macDinh)

export function NguoiDanDialog({ onDong }: { onDong: () => void }) {
  const [man, setMan] = useState<Man>({ loai: 'ds' })
  const [dangGui, setDangGui] = useState(false)
  return (
    <HopThoai
      onDong={onDong}
      khoaDong={dangGui}
      aria-labelledby="nguoi-dan-tieu-de"
      className={`${KHUNG_HOP_THOAI} max-w-[760px]`}
    >
      <div className="flex items-start gap-3">
        {man.loai !== 'ds' && (
          <button
            type="button"
            aria-label="Quay lại danh sách"
            disabled={dangGui}
            onClick={() => setMan({ loai: 'ds' })}
            className="mt-0.5 cursor-pointer text-muted hover:text-fg"
          >
            ←
          </button>
        )}
        <div>
          <h2 id="nguoi-dan-tieu-de" className="text-[16.5px] font-semibold leading-tight text-fg">
            {man.loai === 'tao' ? 'Tạo người dẫn mới' : 'Người dẫn'}
          </h2>
          {man.loai === 'ds' && (
            <p className="mt-1 text-than text-muted">
              Nhân vật mấp máy môi theo giọng agent trên sân khấu tab Voice.
            </p>
          )}
        </div>
      </div>
      {man.loai === 'ds' && (
        <DanhSach
          onMo={(id) => setMan({ loai: 'xem', id })}
          onTao={() => setMan({ loai: 'tao' })}
        />
      )}
      {man.loai === 'tao' && (
        <FormTao
          onDangGui={setDangGui}
          onXong={(id) => setMan({ loai: 'xem', id })}
          onHuy={() => setMan({ loai: 'ds' })}
        />
      )}
      {man.loai === 'xem' && <ChiTiet id={man.id} onVe={() => setMan({ loai: 'ds' })} />}
    </HopThoai>
  )
}

// ───────────────────────────────────────────────────────────── danh sách

function useDoiNguoiDan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: chonNhanVat,
    onSuccess: (dd) => {
      qc.setQueryData(KHOA_DANG_DUNG, dd)
      void qc.invalidateQueries({ queryKey: KHOA_NHAN_VAT })
    },
  })
}

function DanhSach({ onMo, onTao }: { onMo: (id: string) => void; onTao: () => void }) {
  const ds = useQuery({
    queryKey: KHOA_NHAN_VAT,
    queryFn: taiDanhSach,
    // Còn nhân vật đang dựng ⇒ thăm dò để thẻ tự chuyển trạng thái.
    refetchInterval: (q) => (q.state.data?.nhanVat.some(dangDung) ? 4000 : false),
  })
  const chon = useDoiNguoiDan()

  if (ds.error) {
    return (
      <p role="alert" className="mt-4 text-than text-badge-alert-fg">
        {thongDiep(ds.error, 'Không tải được danh sách người dẫn.')}
      </p>
    )
  }
  const d = ds.data
  // Chưa có dữ liệu thì KHÔNG vẽ danh sách: vẽ sớm là người dẫn mặc định chớp «không
  // đang dùng» và ô Tạo chớp «đã đủ số lượng» — hai câu sai về một tập chưa ai biết.
  if (!d) return <p className="mt-4 text-than text-muted">Đang tải…</p>
  const conCho = d.nhanVat.length < d.toiDa
  return (
    <>
      <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3" aria-label="Danh sách người dẫn">
        <TheNguoiDan
          ten="Người dẫn mặc định"
          anh={ANH_CHO_AVATAR}
          phu="Có sẵn"
          dangDungNay={d.dangDung === null}
          onDung={() => chon.mutate(null)}
          ban={chon.isPending}
        />
        {d.nhanVat.map((nv) => (
          <TheNguoiDan
            key={nv.id}
            ten={nv.ten}
            anh={nv.posterUrl}
            phu={
              nv.trangThai === 'loi'
                ? 'Lỗi — bấm để xem'
                : dangDung(nv)
                  ? `${nhanBuoc(nv)} · ${Math.round(nv.tienDo * 100)}%`
                  : nv.nguon === 'anh'
                    ? 'Tạo từ ảnh'
                    : 'Từ video'
            }
            loi={nv.trangThai === 'loi'}
            tienDo={dangDung(nv) ? nv.tienDo : null}
            dangDungNay={nv.dangDung}
            onDung={nv.trangThai === 'san_sang' ? () => chon.mutate(nv.id) : undefined}
            onMo={() => onMo(nv.id)}
            ban={chon.isPending}
          />
        ))}
        <li>
          <button
            type="button"
            onClick={onTao}
            disabled={!conCho}
            className="flex aspect-[3/4] w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border-field text-than text-muted hover:border-fg hover:text-fg disabled:opacity-50"
          >
            <Icon name="them" className="size-5" />
            Tạo người dẫn
            {!conCho && (
              <span className="px-3 text-center text-phu">
                Tối đa {d.toiDa} — xoá bớt nhân vật cũ
              </span>
            )}
          </button>
        </li>
      </ul>
      {chon.error && (
        <p role="alert" className="mt-3 text-than text-badge-alert-fg">
          {thongDiep(chon.error, 'Không đổi được người dẫn.')}
        </p>
      )}
    </>
  )
}

function TheNguoiDan({
  ten,
  anh,
  phu,
  loi = false,
  tienDo = null,
  dangDungNay,
  onDung,
  onMo,
  ban,
}: {
  ten: string
  anh: string | null
  phu: string
  loi?: boolean
  tienDo?: number | null
  dangDungNay: boolean
  onDung?: (() => void) | undefined
  onMo?: (() => void) | undefined
  ban: boolean
}) {
  return (
    <li
      className={`flex flex-col overflow-hidden rounded-lg border ${dangDungNay ? 'border-ac ring-1 ring-ac' : 'border-border'}`}
    >
      <button
        type="button"
        onClick={onMo}
        disabled={!onMo}
        aria-label={onMo ? `Xem ${ten}` : undefined}
        className="relative aspect-[3/4] w-full cursor-pointer bg-fill disabled:cursor-default"
      >
        {anh ? (
          <img
            src={anh}
            alt=""
            className="absolute inset-0 size-full object-contain object-bottom"
          />
        ) : (
          <Icon name="agent" className="absolute inset-0 m-auto size-10 text-muted-2" />
        )}
        {dangDungNay && (
          <span className="absolute left-2 top-2 rounded-sm bg-ac px-1.5 py-0.5 text-nhan font-semibold text-white">
            Đang dùng
          </span>
        )}
        {tienDo !== null && (
          <span className="absolute inset-x-2 bottom-2 h-1.5 overflow-hidden rounded-full bg-fill-strong">
            <span
              className="block h-full bg-ac transition-[width]"
              style={{ width: `${Math.round(tienDo * 100)}%` }}
            />
          </span>
        )}
      </button>
      <div className="flex items-center gap-2 p-2.5">
        <div className="min-w-0 flex-1">
          <div className="truncate text-than font-medium text-fg">{ten}</div>
          <div className={`truncate text-phu ${loi ? 'text-badge-alert-fg' : 'text-muted'}`}>
            {phu}
          </div>
        </div>
        {onDung && !dangDungNay && (
          <button type="button" onClick={onDung} disabled={ban} className={`${NUT_PHU} h-8 px-2.5`}>
            Dùng
          </button>
        )}
      </div>
    </li>
  )
}

// ───────────────────────────────────────────────────────────── tạo

const GOI_Y_VIDEO = [
  'Một người, bán thân, nhìn thẳng máy quay; máy quay đặt cố định (không cầm tay).',
  'Mở đầu 1–2 giây đứng yên, miệng khép — đây sẽ là tư thế chờ của nhân vật.',
  'Sau đó nói tự nhiên 3–8 giây. Mặt luôn thấy rõ, tay không che miệng.',
  'Nền gì cũng được (hệ thống tự tách nền). MP4/MOV/WebM, tối đa 100 MB.',
]
const GOI_Y_ANH = [
  'Ảnh bán thân, mặt nhìn thẳng, miệng khép, đủ sáng. Dáng đứng, tay chưa chuẩn cũng được — AI sẽ chỉnh về dáng người dẫn.',
  'Chừa khoảng trống phía trên đầu — video giữ nguyên khung ảnh, ảnh cắt sát tóc thì nhân vật cũng mất đỉnh đầu.',
  'Chỉ một người trong ảnh; mặt không bị che (kính râm, khẩu trang, tóc).',
  'JPG/PNG/WebP, tối đa 10 MB. AI tạo video mất vài phút.',
]

function FormTao({
  onDangGui,
  onXong,
  onHuy,
}: {
  onDangGui: (dang: boolean) => void
  onXong: (id: string) => void
  onHuy: () => void
}) {
  const qc = useQueryClient()
  const ds = useQuery({ queryKey: KHOA_NHAN_VAT, queryFn: taiDanhSach })
  const [ten, setTen] = useState('')
  // Mặc định «Tạo từ ảnh» (một ảnh dễ có hơn một video quay đúng chuẩn); chưa cấu hình
  // dịch vụ AI tạo video thì rơi về video. `null` = người dùng chưa tự chọn.
  const [nguonChon, setNguon] = useState<'video' | 'anh' | null>(null)
  const [tep, setTep] = useState<File | null>(null)
  const [tepTay, setTepTay] = useState<File | null>(null)
  const [dongY, setDongY] = useState(false)
  const [tienDo, setTienDo] = useState(0)
  const taoTuAnh = ds.data?.taoTuAnh ?? false
  const nguon = nguonChon ?? (taoTuAnh ? 'anh' : 'video')
  const xemAnh = useXemTep(nguon === 'anh' ? tep : null)

  const tao = useMutation({
    mutationFn: () =>
      taoNhanVat(
        { ten: ten.trim(), nguon, tep: tep!, tepTay: nguon === 'video' ? tepTay : null },
        setTienDo,
      ),
    onMutate: () => onDangGui(true),
    onSettled: () => onDangGui(false),
    onSuccess: (nv) => {
      void qc.invalidateQueries({ queryKey: KHOA_NHAN_VAT })
      qc.setQueryData(khoaMotNhanVat(nv.id), nv)
      onXong(nv.id)
    },
  })
  const duDe = ten.trim().length > 0 && tep !== null && dongY && !tao.isPending

  return (
    <form
      className="mt-4 flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (duDe) tao.mutate()
      }}
    >
      <label className="flex flex-col gap-1.5 text-than font-medium text-fg">
        Tên người dẫn
        <input
          className={O_CHUNG}
          value={ten}
          maxLength={60}
          onChange={(e) => setTen(e.target.value)}
          placeholder="Minh Anh"
        />
      </label>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1.5 text-than font-medium text-fg">Nguồn</legend>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <ONguon
            chon={nguon === 'anh'}
            khoa={!taoTuAnh}
            onChon={() => {
              setNguon('anh')
              setTep(null)
              setTepTay(null)
            }}
            icon="anh"
            tieuDe="Tạo từ ảnh bằng AI"
            moTa={
              taoTuAnh
                ? 'Một ảnh chân dung, AI dựng thành video.'
                : 'Chưa cấu hình dịch vụ AI tạo video.'
            }
          />
          <ONguon
            chon={nguon === 'video'}
            onChon={() => {
              setNguon('video')
              setTep(null)
            }}
            icon="video"
            tieuDe="Tải video lên"
            moTa="Video tự quay — giống người thật nhất."
          />
        </div>
      </fieldset>

      {/* Lưới hai cột CHỈ khi có ảnh xem trước — chừa sẵn cột 200px là bắt danh sách
          lưu ý xuống dòng giữa chừng trong khi bên phải bỏ trống. */}
      <div className={xemAnh ? 'grid gap-4 sm:grid-cols-[1fr_160px]' : 'flex flex-col'}>
        <div className="flex flex-col gap-3">
          <ChonTep
            nhan={nguon === 'video' ? 'Video chính' : 'Ảnh chân dung'}
            batBuoc
            nutChon={nguon === 'video' ? 'Chọn video' : 'Chọn ảnh'}
            accept={
              nguon === 'video'
                ? 'video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm'
                : 'image/jpeg,image/png,image/webp'
            }
            tep={tep}
            onChon={setTep}
          />
          {nguon === 'video' && (
            <ChonTep
              nhan="Video đưa tay (tuỳ chọn)"
              phu="Giơ tay giới thiệu rồi hạ tay về đúng tư thế đầu video chính."
              nutChon="Chọn video"
              accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm"
              tep={tepTay}
              onChon={setTepTay}
            />
          )}
        </div>
        {xemAnh && (
          <img
            src={xemAnh}
            alt="Ảnh đã chọn"
            className="max-h-[200px] w-full self-end rounded-lg border border-border bg-fill object-contain"
          />
        )}
      </div>

      <div className="rounded-lg bg-fill px-4 py-3">
        <div className="mb-2 text-phu font-medium text-fg">
          {nguon === 'video' ? 'Lưu ý khi quay' : 'Lưu ý khi chọn ảnh'}
        </div>
        <ul className="flex flex-col gap-1.5 text-phu text-muted">
          {(nguon === 'video' ? GOI_Y_VIDEO : GOI_Y_ANH).map((g) => (
            <li key={g} className="flex gap-2">
              <Icon name="check" className="mt-0.5 size-3.5 shrink-0 text-ac" />
              <span>{g}</span>
            </li>
          ))}
        </ul>
      </div>

      <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border px-4 py-3 text-than text-fg has-[:checked]:border-ac has-[:checked]:bg-acs">
        <input
          type="checkbox"
          checked={dongY}
          onChange={(e) => setDongY(e.target.checked)}
          className="mt-0.5 size-4 shrink-0 accent-ac"
        />
        <span>
          Tôi xác nhận có quyền sử dụng hình ảnh của người trong{' '}
          {nguon === 'video' ? 'video' : 'ảnh'} này để tạo
          người dẫn ảo.
        </span>
      </label>

      {tao.isPending && (
        <div className="flex items-center gap-2 text-than text-muted" role="status">
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-fill-strong">
            <span
              className="block h-full bg-ac"
              style={{ width: `${Math.round(tienDo * 100)}%` }}
            />
          </span>
          Đang tải lên {Math.round(tienDo * 100)}%
        </div>
      )}
      {tao.error && (
        <p role="alert" className="text-than text-badge-alert-fg">
          {thongDiep(tao.error, 'Không tạo được nhân vật.')}
        </p>
      )}
      <div className={HANG_NUT}>
        <button type="button" onClick={onHuy} disabled={tao.isPending} className={NUT_PHU}>
          Huỷ
        </button>
        <button type="submit" disabled={!duDe} className={NUT_CHINH}>
          {tao.isPending ? 'Đang tải lên…' : 'Tạo người dẫn'}
        </button>
      </div>
    </form>
  )
}

function ONguon(p: {
  chon: boolean
  khoa?: boolean
  onChon: () => void
  icon: IconName
  tieuDe: string
  moTa: string
}) {
  return (
    <label
      className={`flex items-start gap-3 rounded-lg border p-3.5 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ac ${p.chon ? 'border-ac bg-acs ring-1 ring-ac' : 'border-border-field'} ${p.khoa ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:border-ac'}`}
    >
      <input
        type="radio"
        name="nguon-nhan-vat"
        checked={p.chon}
        disabled={p.khoa}
        onChange={p.onChon}
        className="sr-only"
      />
      <span
        className={`flex size-9 shrink-0 items-center justify-center rounded-md ${p.chon ? 'bg-ac text-white' : 'bg-fill text-muted'}`}
      >
        <Icon name={p.icon} className="size-[18px]" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-than font-medium text-fg">{p.tieuDe}</span>
        <span className="mt-0.5 block text-phu text-muted">{p.moTa}</span>
      </span>
      <span
        aria-hidden
        className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border ${p.chon ? 'border-ac bg-ac' : 'border-border-field'}`}
      >
        {p.chon && <span className="size-1.5 rounded-full bg-white" />}
      </span>
    </label>
  )
}

/** Tệp có khớp `accept` của ô không — chỉ để bỏ qua tệp KÉO THẢ sai loại (hộp chọn
 *  tệp của trình duyệt đã tự lọc). Backend vẫn là chốt chặn. */
function khopAccept(f: File, accept: string): boolean {
  const ten = f.name.toLowerCase()
  return accept.split(',').some((a) => (a.startsWith('.') ? ten.endsWith(a) : f.type === a))
}

/** Ô chọn tệp tự vẽ: `<input type="file">` mặc định in «Choose File / No file chosen»
 *  theo ngôn ngữ trình duyệt và không đổi chữ được. Input ẩn (`sr-only`, vẫn Tab tới
 *  được) nằm TRONG một `<label>` nên bấm cả vùng là mở hộp chọn; kéo thả cũng nhận. */
function ChonTep(p: {
  nhan: string
  batBuoc?: boolean
  phu?: string
  nutChon: string
  accept: string
  tep: File | null
  onChon: (f: File | null) => void
}) {
  const id = useId()
  const [keo, setKeo] = useState(false)
  return (
    <div className="flex flex-col gap-1.5">
      {/* Dấu `*` NGOÀI span làm tên ô (khuôn `Truong.tsx`): nghĩa «bắt buộc» đi qua
          `aria-required`, không để tên ô đọc thành «Video chính sao». */}
      <span className="text-than font-medium text-fg">
        <span id={`${id}-nhan`}>{p.nhan}</span>
        {p.batBuoc && (
          <span className="ml-0.5 text-badge-alert-fg" title="Bắt buộc" aria-hidden="true">
            *
          </span>
        )}
      </span>
      {p.phu && (
        <span id={`${id}-phu`} className="-mt-1 text-phu text-muted">
          {p.phu}
        </span>
      )}
      <label
        onDragOver={(e) => {
          e.preventDefault()
          setKeo(true)
        }}
        onDragLeave={() => setKeo(false)}
        onDrop={(e) => {
          e.preventDefault()
          setKeo(false)
          const f = e.dataTransfer.files[0]
          if (f && khopAccept(f, p.accept)) p.onChon(f)
        }}
        className={`flex cursor-pointer items-center gap-3 rounded-lg border border-dashed px-3.5 py-3 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ac ${keo ? 'border-ac bg-acs' : p.tep ? 'border-border-field bg-surface' : 'border-border-field bg-fill/50 hover:border-ac'}`}
      >
        <input
          type="file"
          accept={p.accept}
          aria-labelledby={`${id}-nhan`}
          aria-required={p.batBuoc || undefined}
          aria-describedby={p.phu ? `${id}-phu` : undefined}
          onChange={(e) => p.onChon(e.target.files?.[0] ?? null)}
          className="sr-only"
        />
        <span
          className={`flex size-9 shrink-0 items-center justify-center rounded-md ${p.tep ? 'bg-acs text-ac' : 'bg-surface text-muted'}`}
        >
          <Icon name={p.tep ? 'check' : 'taiLen'} className="size-[18px]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-than text-fg">
            {p.tep ? p.tep.name : 'Chưa chọn tệp'}
          </span>
          <span className="block text-phu text-muted">
            {p.tep
              ? `${(p.tep.size / 1024 / 1024).toFixed(1)} MB`
              : 'Bấm để chọn hoặc kéo thả vào đây'}
          </span>
        </span>
        <span className={`${NUT_PHU} pointer-events-none shrink-0 bg-surface`}>
          {p.tep ? 'Đổi tệp' : p.nutChon}
        </span>
      </label>
    </div>
  )
}

/** Blob URL xem trước tệp ảnh đã chọn (thu hồi khi đổi/đóng). */
function useXemTep(tep: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!tep || typeof URL.createObjectURL !== 'function') {
      setUrl(null)
      return
    }
    const u = URL.createObjectURL(tep)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [tep])
  return url
}

// ───────────────────────────────────────────────────────────── chi tiết

function ChiTiet({ id, onVe }: { id: string; onVe: () => void }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: khoaMotNhanVat(id),
    queryFn: () => taiNhanVat(id),
    refetchInterval: (s) => (s.state.data && dangDung(s.state.data) ? 3000 : false),
  })
  const chon = useDoiNguoiDan()
  const lamMoi = (nv: NhanVat) => {
    qc.setQueryData(khoaMotNhanVat(id), nv)
    void qc.invalidateQueries({ queryKey: KHOA_NHAN_VAT })
  }
  const thu = useMutation({ mutationFn: () => thuLai(id), onSuccess: lamMoi })
  const xoa = useMutation({
    mutationFn: () => xoaNhanVat(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KHOA_NHAN_VAT })
      void qc.invalidateQueries({ queryKey: KHOA_DANG_DUNG })
      onVe()
    },
  })
  const [hoiXoa, setHoiXoa] = useState(false)
  // Trạng thái vừa chuyển sang xong ⇒ danh sách (thẻ) cũng cập nhật.
  const truoc = useRef(q.data?.trangThai)
  useEffect(() => {
    if (q.data && truoc.current && truoc.current !== q.data.trangThai) {
      void qc.invalidateQueries({ queryKey: KHOA_NHAN_VAT })
    }
    truoc.current = q.data?.trangThai
  }, [q.data, qc])

  if (q.error) {
    return (
      <p role="alert" className="mt-4 text-than text-badge-alert-fg">
        {thongDiep(q.error, 'Không tải được nhân vật.')}
      </p>
    )
  }
  const nv = q.data
  if (!nv) return <p className="mt-4 text-than text-muted">Đang tải…</p>

  return (
    <div className="mt-4 flex flex-col gap-4">
      <div className="text-the font-semibold text-fg">{nv.ten}</div>

      {dangDung(nv) && (
        <div className="rounded-md border border-border p-4" role="status" aria-live="polite">
          <div className="flex items-center justify-between text-than">
            <span className="text-fg">{nhanBuoc(nv)}…</span>
            <span className="tabular-nums text-muted">{Math.round(nv.tienDo * 100)}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-fill-strong">
            <div
              className="h-full bg-ac transition-[width] duration-700"
              style={{ width: `${Math.max(3, nv.tienDo * 100)}%` }}
            />
          </div>
          <p className="mt-3 text-phu text-muted">
            {nv.nguon === 'anh' && nv.trangThai === 'tao_video'
              ? 'AI đang tạo video từ ảnh — thường mất 2–6 phút. '
              : 'Thường mất 1–3 phút. '}
            Bạn có thể đóng hộp thoại; việc dựng vẫn chạy và nhân vật hiện trong danh sách khi xong.
          </p>
        </div>
      )}

      {nv.trangThai === 'loi' && nv.loi && (
        <div className="rounded-md border border-badge-alert-fg/40 p-4" role="alert">
          <div className="text-than font-medium text-badge-alert-fg">Chưa dựng được nhân vật</div>
          <p className="mt-1 text-than text-fg">{nv.loi.huongDan}</p>
          {nv.loi.chiTiet && <p className="mt-1 text-phu text-muted">Chi tiết: {nv.loi.chiTiet}</p>}
        </div>
      )}

      {nv.trangThai === 'san_sang' && <XemTruoc nv={nv} />}

      {nv.videoUrl && <VideoNguon nv={nv} />}

      {(thu.error || xoa.error || chon.error) && (
        <p role="alert" className="text-than text-badge-alert-fg">
          {thongDiep(thu.error ?? xoa.error ?? chon.error, 'Thao tác không thành công.')}
        </p>
      )}

      <div className={HANG_NUT}>
        {hoiXoa ? (
          <>
            <span className="mr-auto text-than text-fg">Xoá hẳn nhân vật này?</span>
            <button type="button" onClick={() => setHoiXoa(false)} className={NUT_PHU}>
              Không
            </button>
            <button
              type="button"
              onClick={() => xoa.mutate()}
              disabled={xoa.isPending}
              className={NUT_XOA}
            >
              Xoá
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => setHoiXoa(true)}
              className="mr-auto inline-flex cursor-pointer items-center gap-1.5 text-than text-muted hover:text-badge-alert-fg"
            >
              <Icon name="trash" className="size-4" /> Xoá
            </button>
            {nv.trangThai === 'loi' && (
              <button
                type="button"
                onClick={() => thu.mutate()}
                disabled={thu.isPending}
                className={NUT_PHU}
              >
                Thử lại
              </button>
            )}
            {nv.trangThai === 'san_sang' &&
              (nv.dangDung ? (
                <span className="inline-flex items-center gap-1.5 text-than text-ac">
                  <Icon name="check" className="size-4" /> Đang dùng
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    chon.mutate(nv.id, {
                      onSuccess: () => qc.invalidateQueries({ queryKey: khoaMotNhanVat(id) }),
                    })
                  }
                  disabled={chon.isPending}
                  className={NUT_CHINH}
                >
                  Dùng nhân vật này
                </button>
              ))}
          </>
        )}
      </div>
    </div>
  )
}

function XemTruoc({ nv }: { nv: NhanVat }) {
  const [cau, setCau] = useState('')
  const [video, setVideo] = useState<string | null>(null)
  useEffect(
    () => () => {
      if (video) URL.revokeObjectURL(video)
    },
    [video],
  )
  const thu = useMutation({
    mutationFn: () => xemTruocCau(nv.id, cau.trim()),
    onSuccess: (u) => setVideo(u),
  })
  return (
    <div className="flex flex-col gap-3">
      {nv.xemTruoc.length > 0 ? (
        <>
          <div className="text-than font-medium text-fg">Nghe nhân vật nói thử</div>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {nv.xemTruoc.map((x) => (
              <li key={x.url} className="flex flex-col gap-1.5">
                <video
                  src={x.url}
                  controls
                  preload="metadata"
                  playsInline
                  className="aspect-[3/4] w-full rounded-md bg-fill object-contain"
                />
                <span className="text-phu text-muted">«{x.cau}»</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="text-than text-muted">
          Nhân vật đã sẵn sàng nhưng chưa có video nói thử (dịch vụ giọng nói đang bận) — bạn vẫn
          dùng được, hoặc thử một câu bên dưới.
        </p>
      )}
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault()
          if (cau.trim()) thu.mutate()
        }}
      >
        <input
          className={`${O_CHUNG} flex-1`}
          value={cau}
          maxLength={300}
          onChange={(e) => setCau(e.target.value)}
          placeholder="Gõ một câu để nhân vật nói thử…"
          aria-label="Câu nói thử"
        />
        <button type="submit" disabled={!cau.trim() || thu.isPending} className={NUT_PHU}>
          {thu.isPending ? 'Đang tạo…' : 'Nói thử'}
        </button>
      </form>
      {thu.error && (
        <p role="alert" className="text-than text-badge-alert-fg">
          {thongDiep(thu.error, 'Không tạo được video nói thử.')}
        </p>
      )}
      {video && (
        <video
          src={video}
          controls
          autoPlay
          playsInline
          className="mx-auto max-h-[360px] rounded-md bg-fill"
        />
      )}
    </div>
  )
}

/** Video gốc mà nhân vật dựng từ đó — để xem AI đã tạo ra gì (hoặc kiểm video đã tải lên). */
function VideoNguon({ nv }: { nv: NhanVat }) {
  const ds = [
    { nhan: nv.nguon === 'anh' ? 'Video AI tạo' : 'Video đã tải lên', url: nv.videoUrl },
    { nhan: 'Video đưa tay', url: nv.videoTayUrl },
  ].filter((x): x is { nhan: string; url: string } => !!x.url)
  return (
    <details className="rounded-md border border-border">
      <summary className="cursor-pointer px-4 py-2.5 text-than font-medium text-fg">
        Video gốc {nv.nguon === 'anh' ? '(AI tạo từ ảnh)' : ''}
      </summary>
      <div className="grid gap-3 px-4 pb-4 sm:grid-cols-2">
        {ds.map((x) => (
          <div key={x.url} className="flex flex-col gap-1.5">
            <video
              src={x.url}
              controls
              preload="metadata"
              playsInline
              className="max-h-[320px] rounded-md bg-fill"
            />
            <div className="flex items-center justify-between text-phu text-muted">
              <span>{x.nhan}</span>
              <a href={x.url} download className="text-ac hover:underline">
                Tải về
              </a>
            </div>
          </div>
        ))}
      </div>
    </details>
  )
}
