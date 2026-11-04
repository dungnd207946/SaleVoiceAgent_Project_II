/**
 * Tài liệu của MỘT dự án — tab «Tài liệu» trong `/pform` và `/uform`.
 *
 * NHÁNH `__ALL__` ĐÃ BỎ (2026-08-08). Component này từng phục vụ cả tab «Tài
 * liệu chung» ở `/projects` (`project_code = '__ALL__'`, tức không thuộc dự án
 * nào). Người dùng chốt mọi tài liệu phải gắn với một dự án, nên tab đó rời màn
 * và mọi rẽ nhánh `chung` ở đây thành code chết — xoá luôn thay vì để lại một
 * nhánh không đường tới.
 *
 * `SENTINEL` vẫn tồn tại ở `api.ts` (backend còn dùng), chỉ file này không còn
 * so với nó nữa.
 *
 * `body` NAY CÓ MÁY BÓC NHÁP: job `kb_enrich` đọc tệp đính kèm (Docling, và VLM
 * cho PDF không có lớp chữ) rồi ghi vào cột này. Cột đang bóc thì hiện "◐ Đang bóc
 * nội dung tệp…" thay vì "chưa có nội dung" — câu sau đọc thành một lỗi và người
 * dùng sẽ đi dán tay trong khi máy đang làm. Tài liệu nhập tay (không tệp) vẫn
 * phải tự viết, và người dùng sửa được mọi lúc.
 *
 * Diện mạo bảng ở `Bang.tsx` — cùng nguồn với ba bảng còn lại của M4.
 */
import { useCallback, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  danhSachTaiLieu,
  duyetTaiLieu,
  nguonAnh,
  suaTaiLieu,
  taoTaiLieu,
  xoaTaiLieu,
  type TaiLieu,
  type TaiLieuGhi,
  type LoaiTaiLieu,
} from '../api'
import { useEnrichStatus } from '../useEnrichStatus'
import { LOAI_TAI_LIEU, mauLoaiTaiLieu, nhanCua } from '../enums'
import { cauLoi, laBienMat, loiO } from '../thongDiep'
import { CaHang, DongTrangThai, OChon, OChu } from '@/components/ui/Truong'
import { ngayThangNam, so } from '@/lib/dinhDang'
import { SectionCard } from './SectionCard'
import { OTep } from './OMedia'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { useKhungSua } from '../khungSua'
import { useLuuTungO } from '../useLuuTungO'
import { useTrangSo } from './useTrangSo'
import { useXacNhanXoa } from '../useXacNhanXoa'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { VeLai } from './KhungDuAn'
import {
  HANG_NUT,
  HANG_NUT_DAN,
  Bang,
  DauBang,
  Hang,
  NUT_CHINH,
  NUT_PHU,
  NHOM_LOC,
  TAB_DAY,
  TAB_KHUNG,
  LOC,
  LOC_CHON,
  PILL,
  TD,
  TD_PHU,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'

interface Props {
  projectCode: string
  cao?: string | undefined
}

const MOI: TaiLieuGhi = { title: '', loai: 'khac', body: '', fileUrl: null }

const DUOI_ANH = ['.jpg', '.jpeg', '.png', '.webp', '.gif']

function laAnh(url: string): boolean {
  const ten = url.split('?')[0]?.split('#')[0]?.toLowerCase() ?? ''
  return DUOI_ANH.some((d) => ten.endsWith(d))
}

const COT: readonly Cot[] = [
  { nhan: 'Tiêu đề' },
  { nhan: 'Loại' },
  { nhan: 'Nội dung' },
  { nhan: 'Tệp' },
  { nhan: 'Cập nhật' },
  { nhan: '', phai: true },
]

const LINK = 'text-than font-medium text-ac hover:text-acd'
const LINK_XOA = 'text-than font-medium text-badge-alert-fg hover:underline'

/** Loại tệp từ đuôi khoá/URL: «PDF», «DOCX»… */
function loaiTep(url: string): string {
  const duoi = url.split('?')[0]!.split('.').pop() ?? ''
  return duoi.length > 0 && duoi.length <= 5 ? duoi.toUpperCase() : 'Có'
}

export function TaiLieuTab({ projectCode, cao }: Props) {
  const qc = useQueryClient()
  const { dangSua: editing } = useKhungSua()
  const enrich = useEnrichStatus(projectCode)
  const [nhap, setNhap] = useState<TaiLieuGhi | null>(null)
  const [dangSua, setDangSua] = useState<TaiLieu | null>(null)
  const {
    sap: sapXoa,
    hoi: hoiXoa,
    boQua,
    daXoa,
    huyRef,
    dich,
    idTieuDe,
    idMoTa,
  } = useXacNhanXoa<TaiLieu>()
  const [locLoai, setLocLoai] = useState<LoaiTaiLieu | null>(null)

  function doiNhap<K extends keyof TaiLieuGhi>(k: K, x: TaiLieuGhi[K]) {
    setNhap((t) => (t ? { ...t, [k]: x } : t))
  }

  function doiNhapNhieu(patch: Partial<TaiLieuGhi>) {
    setNhap((t) => (t ? { ...t, ...patch } : t))
  }

  const ds = useTrangSo<TaiLieu>(['re', projectCode, 'documents'], ({ limit, offset }) =>
    danhSachTaiLieu(projectCode, { limit, offset }),
  )
  const hienThi = locLoai ? ds.items.filter((t) => t.loai === locLoai) : ds.items
  const coDuLieu = !ds.isPending && !ds.error

  function dong() {
    setNhap(null)
    setDangSua(null)
  }

  function xong() {
    dong()
    void qc.invalidateQueries({ queryKey: ['re', projectCode, 'documents'] })
  }

  const mGhi = useMutation({
    mutationFn: (b: TaiLieuGhi) => taoTaiLieu(projectCode, { ...b, status: 'published' }),
    onSuccess: xong,
    onError: (e) => {
      if (laBienMat(e)) xong()
    },
  })

  const mXoa = useMutation({
    mutationFn: (id: number) => xoaTaiLieu(projectCode, id),
    onSuccess: () => {
      daXoa()
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'documents'] })
    },
  })

  function mo(t: TaiLieu) {
    mGhi.reset()
    setNhap(null)
    setDangSua(t)
  }

  if (dangSua)
    return (
      <SuaTaiLieu
        key={dangSua.id}
        projectCode={projectCode}
        tl={dangSua}
        ve={dong}
        lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'documents'] })}
      />
    )

  return (
    <div className={`${nhap ? TAB_DAY : TAB_KHUNG} flex flex-col gap-3`}>
      {nhap && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            mGhi.mutate(nhap)
          }}
        >
          <FormTaiLieu
            gia_tri={nhap}
            doi={doiNhap}
            xong={() => {}}
            doiNhieu={doiNhapNhieu}
            loi={mGhi.error}
            veDanhSach={() => {
              mGhi.reset()
              dong()
            }}
            day={
              <div data-testid="pform-day" className={HANG_NUT_DAN}>
                <button
                  type="button"
                  className={NUT_PHU}
                  onClick={() => {
                    mGhi.reset()
                    setNhap(null)
                  }}
                >
                  Huỷ
                </button>
                <button type="submit" className={NUT_CHINH} disabled={mGhi.isPending}>
                  {mGhi.isPending ? 'Đang lưu…' : 'Lưu tài liệu'}
                </button>
              </div>
            }
          />
        </form>
      )}

      {!nhap && (
        <TheBang cao={cao}>
          {/* MỘT hàng: chip lọc bên trái, nút Thêm bên phải (người dùng chốt
              2026-08-21). Trước đó nút đứng riêng một hàng phía trên, và hàng đó
              trống hoác — hai dải công cụ cho một bảng. */}
          <ThanhCong>
            {!coDuLieu && <span className="min-w-0 flex-1" />}
            {coDuLieu && (
              <div role="group" aria-label="Lọc theo loại" className={`${NHOM_LOC} min-w-0 flex-1`}>
                <button
                  type="button"
                  aria-pressed={locLoai === null}
                  className={`${locLoai === null ? LOC_CHON : LOC} bg-surface text-fg`}
                  onClick={() => setLocLoai(null)}
                >
                  Tất cả {ds.items.length}
                </button>
                {LOAI_TAI_LIEU.map((l) => (
                  <button
                    key={l.value}
                    type="button"
                    aria-pressed={locLoai === l.value}
                    className={`${locLoai === l.value ? LOC_CHON : LOC} ${mauLoaiTaiLieu(l.value)}`}
                    onClick={() => setLocLoai(l.value as LoaiTaiLieu)}
                  >
                    {l.nhan} {ds.items.filter((t) => t.loai === l.value).length}
                  </button>
                ))}
              </div>
            )}
            {editing && (
              <button
                ref={dich}
                type="button"
                className={`${NUT_CHINH} flex-none`}
                onClick={() => {
                  mGhi.reset()
                  setNhap({ ...MOI })
                }}
              >
                Thêm tài liệu
              </button>
            )}
          </ThanhCong>

          <VungCuon>
            {ds.isPending ? (
              <p className="p-4 text-than text-muted">Đang tải…</p>
            ) : ds.error ? (
              <div className="p-4">
                <LoiTai viec="danh sách tài liệu" thuLai={() => void ds.refetch()} />
              </div>
            ) : ds.items.length === 0 ? (
              <div className="p-4">
                <KhoRong
                  tieuDe={
                    ds.total > 0 ? 'Trang này không có tài liệu nào.' : 'Chưa có tài liệu nào.'
                  }
                  huongDan={
                    ds.total > 0
                      ? 'Dữ liệu vẫn còn — quay lại một trang trước đó.'
                      : 'Nạp tài liệu riêng của dự án này — pháp lý, chính sách, tiến độ.'
                  }
                />
              </div>
            ) : hienThi.length === 0 ? (
              <p className="p-4 text-[14px] text-muted">
                {ds.soTrang > 1
                  ? `Chưa thấy tài liệu ${nhanCua(LOAI_TAI_LIEU, locLoai)} nào trong trang đang xem — thử trang khác hoặc bỏ bộ lọc.`
                  : 'Không có tài liệu nào thuộc loại này. Bỏ bộ lọc để xem tất cả.'}
              </p>
            ) : (
              <Bang>
                <DauBang cot={COT} />
                <tbody>
                  {hienThi.map((t) => (
                    <Hang key={t.id} mo={() => mo(t)}>
                      <td className={TD}>
                        <button
                          type="button"
                          className="text-left font-semibold text-fg hover:text-ac"
                          onClick={() => mo(t)}
                        >
                          {t.title}
                        </button>
                      </td>
                      <td className={TD_PHU}>
                        <span className={`${PILL} ${mauLoaiTaiLieu(t.loai)}`}>
                          {nhanCua(LOAI_TAI_LIEU, t.loai)}
                        </span>
                      </td>
                      <td className={TD_PHU}>
                        {enrich.running.has(t.id) ? (
                          <span className="text-[12px] text-ac">◐ Đang bóc nội dung tệp…</span>
                        ) : t.body ? (
                          <span className="text-[12px] text-muted-2">
                            <span className="font-mono">{so(t.body.length)}</span> ký tự
                          </span>
                        ) : (
                          <span className="text-[12px] text-badge-alert-fg">
                            chưa có nội dung — agent không đọc được
                          </span>
                        )}
                      </td>
                      <td className={TD_PHU}>{t.fileUrl ? loaiTep(t.fileUrl) : '—'}</td>
                      <td className={`${TD_PHU} font-mono`}>
                        {ngayThangNam(new Date(t.updatedAt))}
                      </td>
                      <td className={`${TD} whitespace-nowrap text-right`}>
                        {editing ? (
                          <span className="inline-flex gap-3">
                            <button type="button" className={LINK} onClick={() => mo(t)}>
                              Sửa
                            </button>
                            <button type="button" className={LINK_XOA} onClick={() => hoiXoa(t)}>
                              Xoá
                            </button>
                          </span>
                        ) : (
                          <span aria-hidden className="text-muted-3">
                            ›
                          </span>
                        )}
                      </td>
                    </Hang>
                  ))}
                </tbody>
              </Bang>
            )}
          </VungCuon>

          <ThanhTrang
            trang={ds.trang}
            soTrang={ds.soTrang}
            total={ds.total}
            soHang={ds.soHang}
            doiTrang={ds.doiTrang}
            doiSoHang={ds.doiSoHang}
            dangTai={ds.isPending}
          />
        </TheBang>
      )}

      {sapXoa && (
        <div
          className="rounded-xl border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]"
          role="alertdialog"
          aria-labelledby={idTieuDe}
          aria-describedby={idMoTa}
        >
          <p id={idTieuDe} className="font-semibold">
            Xoá {sapXoa.title}?
          </p>
          <div id={idMoTa}>
            <p>Agent sẽ thôi dùng tài liệu này từ lần trả lời kế tiếp.</p>
            <p className="text-[13px] text-muted">
              Không có thùng rác — thao tác này không hoàn tác được.
            </p>
          </div>
          {mXoa.error && (
            <p role="alert" className="mt-1 text-[13px] text-badge-alert-fg">
              {cauLoi(mXoa.error, 'xoá')}
            </p>
          )}
          <div className={`mt-3 ${HANG_NUT}`}>
            <button ref={huyRef} type="button" className={NUT_PHU} onClick={boQua}>
              Huỷ
            </button>
            <button
              type="button"
              className={NUT_CHINH}
              disabled={mXoa.isPending}
              onClick={() => mXoa.mutate(sapXoa.id)}
            >
              Xoá
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

interface FormProps {
  gia_tri: TaiLieuGhi
  /** Gõ. `xong` gửi (chế độ SỬA); ở chế độ TẠO thì `xong` là no-op. */
  doi: <K extends keyof TaiLieuGhi>(k: K, x: TaiLieuGhi[K]) => void
  xong: (k: keyof TaiLieuGhi) => void
  /** Một thao tác đổi nhiều ô (chọn tệp đặt luôn tiêu đề). */
  doiNhieu: (patch: Partial<TaiLieuGhi>) => void
  loi: unknown
  veDanhSach: () => void
  /** Chế độ TẠO: hàng nút Huỷ / Lưu. Chế độ SỬA: không có — giờ lưu ở đầu trang. */
  day?: ReactNode
  /** Xem trước tệp ảnh + băng «Duyệt nội dung đọc từ ảnh» — chỉ chế độ SỬA. */
  truocNoiDung?: ReactNode
  /** Chỉ-đọc: chế độ SỬA truyền `!dangSua`, chế độ TẠO không truyền. */
  khoa?: boolean | undefined
}

/**
 * Một bộ ô, hai người điều khiển: chế độ TẠO đẩy vào state rồi Lưu một lần
 * (chưa có hàng thì không có gì để PATCH), chế độ SỬA nối vào `useLuuTungO`.
 * Chép đôi phần markup là chép đôi mọi lần thêm một ô.
 */
function FormTaiLieu({
  gia_tri,
  doi,
  xong,
  doiNhieu,
  loi,
  veDanhSach,
  day,
  truocNoiDung,
  khoa,
}: FormProps) {
  return (
    <div className={`${TAB_DAY} flex flex-col gap-3 pb-2`}>
      <VeLai nhan="Danh sách tài liệu" ve={veDanhSach} />
      <SectionCard title="Nội dung tài liệu">
        <OChu
          ten="title"
          khoa={khoa}
          nhan="Tiêu đề"
          batBuoc
          giaTri={gia_tri.title ?? ''}
          doi={(v) => doi('title', v)}
          xong={() => xong('title')}
          loi={loiO(loi, 'title')}
          goiY="Agent trích dẫn tiêu đề này khi trả lời"
          goiYTrongO="VD: Chính sách bán hàng đợt 3 · Quy trình vay mua nhà"
        />
        <OChon
          ten="loai"
          khoa={khoa}
          nhan="Loại"
          giaTri={gia_tri.loai ?? 'khac'}
          doi={(v) => doiNhieu({ loai: v as LoaiTaiLieu })}
          muc={LOAI_TAI_LIEU}
          loi={loiO(loi, 'loai')}
        />
        <OTep
          khoa={khoa}
          nhan="Tệp tài liệu"
          giaTri={gia_tri.fileUrl ?? null}
          doi={(key, tenGoc) =>
            doiNhieu({
              fileUrl: key,
              title: gia_tri.title ? gia_tri.title : tenGoc.replace(/\.[^.]+$/, ''),
            })
          }
          loi={loiO(loi, 'fileUrl')}
          goiY="Tệp gốc để agent gửi kèm câu trả lời. Chữ trong tệp được bóc ra tự động; ảnh và PDF scan thì cần bấm Duyệt trước khi agent dùng."
        />
        {truocNoiDung && <CaHang>{truocNoiDung}</CaHang>}
        <CaHang>
          <OChu
            ten="body"
            khoa={khoa}
            nhan={khoa ? 'Nội dung' : 'Nội dung (markdown)'}
            hangChu={10}
            giaTri={gia_tri.body ?? ''}
            doi={(v) => doi('body', v)}
            xong={() => xong('body')}
            loi={loiO(loi, 'body')}
            goiY="Đây là thứ agent thật sự tìm kiếm. Tệp đính kèm ở trên tự bóc chữ vào đây; bạn sửa lại được."
            goiYTrongO="Dán nguyên văn nội dung tài liệu: điều khoản chính sách, tiến độ thanh toán, điều kiện vay và lãi suất, phí và thuế… Càng đủ chữ, agent trả lời càng đúng."
          />
        </CaHang>
      </SectionCard>

      {!!loi && <DongTrangThai mau="alert">{cauLoi(loi, 'lưu tài liệu')}</DongTrangThai>}
      {day}
    </div>
  )
}

/** Sửa một tài liệu ĐÃ CÓ — tự lưu từng ô. `key={id}` để đổi hàng là dựng lại. */
function SuaTaiLieu({
  projectCode,
  tl,
  ve,
  lamMoi,
}: {
  projectCode: string
  tl: TaiLieu
  ve: () => void
  lamMoi: () => void
}) {
  const luu = useCallback(
    async (patch: TaiLieuGhi) => {
      const r = await suaTaiLieu(projectCode, tl.id, patch)
      lamMoi()
      return r
    },
    [projectCode, tl.id, lamMoi],
  )

  const { dangSua } = useKhungSua()
  const o = useLuuTungO<TaiLieuGhi>(
    { title: tl.title, loai: tl.loai, body: tl.body, fileUrl: tl.fileUrl },
    luu,
  )

  const [daDuyet, setDaDuyet] = useState(!tl.bodyChoDuyet)
  const mDuyet = useMutation({
    mutationFn: () => duyetTaiLieu(projectCode, tl.id),
    onSuccess: () => {
      setDaDuyet(true)
      lamMoi()
    },
  })

  return (
    <FormTaiLieu
      gia_tri={o.v}
      doi={o.doi}
      xong={o.xong}
      doiNhieu={o.doiNhieuVaLuu}
      loi={o.loi}
      veDanhSach={ve}
      khoa={!dangSua}
      truocNoiDung={
        <div className="space-y-2">
          {o.v.fileUrl && laAnh(o.v.fileUrl) && (
            <a href={nguonAnh(o.v.fileUrl)} target="_blank" rel="noreferrer" className="block">
              <img
                src={nguonAnh(o.v.fileUrl)}
                alt={o.v.title ?? ''}
                className="max-h-[50vh] w-auto max-w-full rounded border border-border-field object-contain"
              />
            </a>
          )}
          {!daDuyet && (
            <div className="flex flex-wrap items-center gap-2 rounded border border-badge-warn-fg/40 bg-badge-warn-bg/40 px-2 py-1.5">
              <span className="text-[13px] text-badge-warn-fg">
                Nội dung đọc từ ảnh — bấm Duyệt để agent dùng
              </span>
              <button
                type="button"
                className="rounded border border-badge-warn-fg/50 px-2 py-0.5 text-[12px] hover:bg-badge-warn-fg hover:text-white disabled:opacity-50"
                disabled={mDuyet.isPending}
                onClick={() => mDuyet.mutate()}
              >
                {mDuyet.isPending ? 'Đang duyệt…' : 'Duyệt'}
              </button>
              {mDuyet.error && (
                <p className="w-full text-[13px] text-badge-alert-fg">
                  {cauLoi(mDuyet.error, 'duyệt')}
                </p>
              )}
            </div>
          )}
        </div>
      }
    />
  )
}
