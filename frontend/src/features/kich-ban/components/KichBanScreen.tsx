import { useEffect, useMemo, useRef, useState } from 'react'
import { useBlocker, useNavigate, useSearch } from '@tanstack/react-router'
import { ChonMot, NUT_CHINH, NUT_PHU, O_LOC } from '@/components/ui/Bang'
import { HopThoai } from '@/components/ui/HopThoai'
import { ACTIONS } from '@/lib/actions'
import { useKhoManHinh } from '@/lib/khoManHinh'
import { useSession } from '@/lib/session'
import { LoiApi } from '@/lib/http'
import { useKichBan, useTemplate, type Ngay } from '../api'
import { laSale, soMau } from '../khuon'
import { tenNut } from '../logic'
import { DaiTrangThai } from './DaiTrangThai'
import { DanhSachNut } from './DanhSachNut'
import { DoThi } from './DoThi'
import { KhungChiTiet } from './KhungChiTiet'
import { SoVoiMau } from './SoVoiMau'
import { XacNhan } from '@/components/ui/XacNhan'

const NGAY: Ngay[] = [7, 30, 90]

const CHU_GIAI: { lop: string; nhan: string }[] = [
  { lop: 'bg-ac', nhan: 'Đạt từ 80%' },
  { lop: 'bg-badge-warn-fg', nhan: '60–80%' },
  { lop: 'bg-badge-alert-fg', nhan: 'Dưới 60%' },
  { lop: 'bg-n6', nhan: 'Chưa đủ 5 lượt chấm' },
]

function ChuGiai({ rieng }: { rieng: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-phu text-muted">
      {CHU_GIAI.map((c) => (
        <span key={c.nhan} className="flex items-center gap-1.5">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${c.lop}`} />
          {c.nhan}
        </span>
      ))}
      <span>▸ nhiều bước</span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2.5 w-2.5 rounded-full border border-dashed border-n6" />
        đang tắt
      </span>
      {rieng ? (
        <>
          <span>· khác mẫu: khác bản mẫu NobleX hiện tại</span>
          <span>· riêng: workspace tự thêm</span>
        </>
      ) : null}
    </div>
  )
}

export function KichBanScreen() {
  const { nut, ngay, nguon, q, them: themUrl, so: soMo } = useSearch({ from: '/_app/kich-ban' })
  const navigate = useNavigate({ from: '/kich-ban' })
  const kq = useKichBan(ngay ?? 7, nguon)
  const data = kq.data
  const sua = (moi: Record<string, unknown>, replace = false) =>
    void navigate({ search: (s) => ({ ...s, ...moi }), replace })
  const soNutCu = data ? Object.values(data.nutCu).reduce((a, b) => a + b, 0) : 0
  const { can } = useSession()
  const suaDuoc = can([ACTIONS.AGENT_CONFIG_WRITE])
  const tpl = useTemplate()
  const gioiHan = tpl.data?.gioiHan
  const ghiDuoc = suaDuoc && gioiHan !== undefined
  // `?them=1` gõ tay KHÔNG mở form cho người chỉ xem (Lưu sẽ 403) hay khi thiếu `gioiHan` (form không dựng được).
  const them = themUrl === true && ghiDuoc
  // Thiếu `gioiHan` (template lỗi, hoặc BE chưa có MR trả khối này) ⇒ khoá thao tác trên tình huống, phần xem vẫn chạy.
  const lyDoKhoa =
    suaDuoc && !gioiHan && !tpl.isPending
      ? 'Không tải được giới hạn kịch bản — tải lại trang'
      : null
  // So với mẫu chỉ có nghĩa ở bản riêng — ở trạng thái mẫu mọi tình huống sale CHÍNH LÀ mẫu.
  const so = useMemo(
    () =>
      data && tpl.data && data.kichBan.trangThai === 'rieng'
        ? soMau(data.nodes.filter(laSale), tpl.data.nodes)
        : null,
    [data, tpl.data],
  )
  const soSale = data ? data.nodes.filter(laSale).length : 0
  const day = gioiHan !== undefined && soSale >= gioiHan.maxNut
  // Sửa / thêm (spec §4c–4d). `suaNut` = id đang mở form; `?nut=` đổi (kể cả Back) là tự về bản xem.
  const [suaNut, setSuaNut] = useState<string | null>(null)
  const dangSua = !them && !!nut && suaNut === nut
  const dirty = useRef(false)
  const [cho, setCho] = useState<(() => void) | null>(null)
  // Back của trình duyệt / cử chỉ Back của điện thoại không đi qua `diKhi` — chặn ở router. Chỉ khi đổi tình huống
  // đang mở (`nut`/`them`) hoặc rời màn; đổi bộ lọc giữ nguyên form (bản cũ giữ tới lúc bản mới về).
  const chan = useBlocker({
    shouldBlockFn: ({ current, next }) => {
      if (!((dangSua || them) && dirty.current)) return false
      const a = current.search as { nut?: unknown; them?: unknown }
      const b = next.search as { nut?: unknown; them?: unknown }
      return current.pathname !== next.pathname || a.nut !== b.nut || a.them !== b.them
    },
    enableBeforeUnload: false,
    withResolver: true,
  })
  /** Mọi đường đổi nội dung khung đi qua đây: đang sửa dở thì hỏi «Bỏ phần đang sửa?» trước. */
  const diKhi = (lam: () => void) => {
    if ((dangSua || them) && dirty.current) setCho(() => lam)
    else lam()
  }
  // Mỗi lần rời/mở lại khung là một form MỚI — «Thêm tình huống» khi đang thêm dở rồi «Bỏ» phải ra form trống.
  const [lanMo, setLanMo] = useState(0)
  const roi = (moi: Record<string, unknown>) =>
    diKhi(() => {
      dirty.current = false
      setSuaNut(null)
      setLanMo((x) => x + 1)
      sua(moi)
    })
  const chon = (id: string) => roi({ nut: id, so: undefined, them: undefined })
  const dong = () => roi({ nut: undefined, so: undefined, them: undefined })
  // Toàn màn hình bọc cả sơ đồ LẪN khung chi tiết — chỉ sơ đồ thì bấm tình huống mở bảng vô hình.
  const toanRef = useRef<HTMLDivElement>(null)
  const [toan, setToan] = useState(false)
  useEffect(() => {
    const doi = () => setToan(document.fullscreenElement === toanRef.current)
    document.addEventListener('fullscreenchange', doi)
    return () => document.removeEventListener('fullscreenchange', doi)
  }, [])
  const batTatToan = () => {
    const p = document.fullscreenElement
      ? document.exitFullscreen()
      : toanRef.current?.requestFullscreen()
    p?.catch(() => {})
  }
  // Safari iPhone KHÔNG có `requestFullscreen()` cho phần tử thường — nút bấm vào hư không.
  const coToan = typeof document !== 'undefined' && document.fullscreenEnabled !== false
  const kho = useKhoManHinh()
  // Điện thoại: danh sách + bottom sheet thay cho sơ đồ + khung trượt (xem `DanhSachNut`).
  const dienThoai = kho === 'mobile'
  const xemSo = soMo === 'mau' && !!so && !!tpl.data && !them
  const mo = !!data && (them === true || xemSo || !!nut)
  const rong = them === true || dangSua
  // Dưới `lg` khung chi tiết xếp DƯỚI một sơ đồ cao gần bằng màn: chọn nút xong phải kéo
  // khung tới, không thì chạm trông như không có gì xảy ra (audit 05/10).
  const chiTietRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (mo && kho === 'tablet')
      chiTietRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [mo, nut, them, kho])

  const khungChiTiet = (khung?: string) =>
    data && xemSo && so && tpl.data ? (
      <SoVoiMau
        data={data}
        mau={tpl.data}
        so={so}
        ghiDuoc={ghiDuoc}
        onChon={chon}
        onDong={dong}
        khung={khung}
      />
    ) : data && (nut || them) ? (
      <KhungChiTiet
        data={data}
        mau={tpl.data}
        so={so}
        nut={nut ?? ''}
        che={them ? 'them' : dangSua ? 'sua' : 'xem'}
        ngay={ngay ?? 7}
        nguon={nguon}
        ghiDuoc={ghiDuoc}
        lyDoKhoa={lyDoKhoa}
        onChon={chon}
        onDong={dong}
        onSua={() => setSuaNut(nut ?? null)}
        lan={lanMo}
        onXong={(id) => {
          dirty.current = false
          setSuaNut(null)
          // THAY mục lịch sử của form: Back sau khi lưu về chỗ trước form, không mở lại form thêm rỗng.
          sua({ nut: id, them: undefined }, true)
        }}
        onHuy={() =>
          diKhi(() => {
            dirty.current = false
            setSuaNut(null)
            if (them) sua({ them: undefined })
          })
        }
        onDoi={(d) => {
          dirty.current = d
        }}
        khung={khung}
      />
    ) : null

  return (
    <div className="flex flex-col gap-4 px-7 pt-[22px] pb-15 max-md:px-4">
      {data ? (
        <DaiTrangThai
          kichBan={data.kichBan}
          so={so}
          suaDuoc={suaDuoc}
          onSoMau={() => roi({ so: 'mau', nut: undefined, them: undefined })}
        />
      ) : null}
      <div className="flex flex-wrap items-center gap-2 max-md:grid max-md:grid-cols-3">
        <ChonMot
          nhan="Khoảng thời gian"
          muc={NGAY.map((n) => ({ ma: n, nhan: `${n} ngày` }))}
          chon={ngay ?? 7}
          doi={(n) => sua({ ngay: n })}
          className="max-md:col-span-3"
        />
        <select
          aria-label="Nguồn"
          value={nguon ?? ''}
          onChange={(e) => sua({ nguon: e.target.value || undefined })}
          className={`${O_LOC} o-chon bg-surface max-md:col-span-3 max-md:h-10`}
        >
          <option value="">Tất cả nguồn</option>
          {data?.nguon.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <input
          type="search"
          aria-label="Tìm tình huống"
          placeholder="Tìm tình huống"
          value={q ?? ''}
          onChange={(e) => sua({ q: e.target.value || undefined })}
          className={`${O_LOC} w-[220px] bg-surface max-md:col-span-3 max-md:h-10 max-md:w-full`}
        />
        {suaDuoc ? (
          <button
            type="button"
            disabled={!ghiDuoc || day}
            title={lyDoKhoa ?? (day && gioiHan ? `Đã đủ ${gioiHan.maxNut} tình huống` : undefined)}
            onClick={() => roi({ them: true, nut: undefined, so: undefined })}
            className={`${NUT_CHINH} ml-auto cursor-pointer max-md:col-span-3 max-md:ml-0`}
          >
            Thêm tình huống
          </button>
        ) : null}
      </div>

      {kq.isError ? (
        <div
          className="rounded-lg border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]"
          role="alert"
        >
          <p>{kq.error instanceof LoiApi ? kq.error.message : 'Không tải được kịch bản.'}</p>
          <button type="button" className={`${NUT_PHU} mt-2`} onClick={() => void kq.refetch()}>
            Thử lại
          </button>
        </div>
      ) : null}
      {kq.isPending ? <p className="text-[14px] text-muted">Đang tải…</p> : null}

      {data ? (
        <>
          <ChuGiai rieng={data.kichBan.trangThai === 'rieng'} />
          {!data.coDuLieu ? (
            <p className="text-[13px] text-muted">
              Chưa có dữ liệu chấm — cần bật đo kịch bản cho workspace này
            </p>
          ) : null}
          {soNutCu > 0 || data.phienBanCu > 0 ? (
            <p className="text-[12px] text-muted-3">
              {soNutCu} lượt thuộc tình huống đã bỏ · {data.phienBanCu} lượt chấm bằng phiên bản cũ
              (không tính)
            </p>
          ) : null}
          {dienThoai ? (
            <>
              <DanhSachNut
                nodes={data.nodes}
                soDo={data.soDo}
                chon={nut}
                q={q ?? ''}
                onChon={chon}
                loaiMau={so?.loai}
              />
              {mo ? (
                // Bottom sheet: chi tiết nổi lên TẠI CHỖ ngón tay vừa chạm, danh sách vẫn nằm
                // nguyên phía sau — vuốt xuống dưới danh sách để tìm bảng là cách cũ, không ai
                // đoán ra. `starting:` trượt sheet lên từ đáy khi mở (bỏ khi giảm chuyển động).
                <HopThoai
                  onDong={dong}
                  aria-label={
                    xemSo
                      ? 'So với mẫu NobleX'
                      : them
                        ? 'Thêm tình huống'
                        : `${dangSua ? 'Sửa' : 'Chi tiết'} tình huống ${tenNut(data.nodes.find((n) => n.id === nut) ?? { id: nut ?? '' })}`
                  }
                  className="mx-0 mt-auto mb-0 max-h-[85dvh] w-full max-w-none overflow-y-auto rounded-t-lg bg-surface text-fg shadow-hop-thoai backdrop:bg-panel/45 motion-safe:transition-transform motion-safe:duration-300 motion-safe:ease-out motion-safe:starting:translate-y-full"
                >
                  {khungChiTiet('px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]')}
                </HopThoai>
              ) : null}
            </>
          ) : null}
          {/* Chưa chọn gì: bản đồ chiếm cả bề ngang. Chọn một nút: khung chi tiết trượt vào từ phải
              (bề rộng chạy 0 → 376px) và bản đồ co lại theo. Ruột khung rộng CỐ ĐỊNH để chữ không
              xuống dòng lại từng nhịp trong lúc trượt; dưới `lg` khung xếp xuống dưới, không trượt. */}
          {dienThoai ? null : (
            <div
              ref={toanRef}
              className={`flex max-lg:flex-col ${toan ? 'items-stretch overflow-y-auto bg-bg p-4' : 'items-start'}`}
            >
              <div className="min-w-0 flex-1 max-lg:w-full">
                <DoThi
                  nodes={data.nodes}
                  soDo={data.soDo}
                  chon={nut}
                  q={q ?? ''}
                  onChon={chon}
                  toanManHinh={toan}
                  onToanManHinh={coToan ? batTatToan : undefined}
                  loaiMau={so?.loai}
                />
              </div>
              <div
                ref={chiTietRef}
                data-testid="khung-chi-tiet"
                data-mo={mo ? 'true' : 'false'}
                className={`shrink-0 overflow-hidden transition-[width,opacity] duration-300 ease-out motion-reduce:transition-none max-lg:w-full ${
                  mo ? `${rong ? 'w-[560px]' : 'w-[376px]'} opacity-100` : 'w-0 opacity-0'
                }`}
              >
                {mo ? (
                  <div
                    className={`${rong ? 'w-[560px]' : 'w-[376px]'} pl-4 max-lg:w-full max-lg:pt-4 max-lg:pl-0 ${toan ? 'h-full overflow-y-auto' : ''}`}
                  >
                    {khungChiTiet()}
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </>
      ) : null}
      {cho || chan.status === 'blocked' ? (
        <XacNhan
          tieuDe="Bỏ phần đang sửa?"
          nutPhu="Ở lại"
          nutChinh="Bỏ"
          phaHuy
          onHuy={() => (cho ? setCho(null) : chan.reset?.())}
          onDongY={() => {
            if (cho) {
              setCho(null)
              cho()
              return
            }
            dirty.current = false
            setSuaNut(null)
            chan.proceed?.()
          }}
        >
          <p>Những gì vừa gõ chưa được lưu.</p>
        </XacNhan>
      ) : null}
    </div>
  )
}
