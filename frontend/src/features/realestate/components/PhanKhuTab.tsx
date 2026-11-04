/**
 * Tab Phân khu — bảng phân khu của một dự án và màn chi tiết một phân khu.
 *
 * `zoneCode` KHÔNG có ô nhập: backend suy nó từ `name` (`core/ma_ban_ghi.py`), và nó là khoá bất biến.
 * Tải một lần tối đa 200 phân khu (như tab Toà) để xếp theo tên; dự án thật ít khi quá vài chục phân khu.
 */
import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  danhSachMedia,
  danhSachPhanKhu,
  danhSachToa,
  suaPhanKhu,
  taoPhanKhu,
  xoaPhanKhu,
  type Media,
  type PhanKhu,
  type PhanKhuGhi,
} from '../api'
import { LOAI_HINH, SALE_PHASE, nhanCua } from '../enums'
import { cauLoi, laBienMat, loiO } from '../thongDiep'
import { CaHang, DongTrangThai, OChon, OChu, OSo, ReadField } from '@/components/ui/Truong'
import { ngayThangNam, gioPhut, so } from '@/lib/dinhDang'
import { useKhungSua } from '../khungSua'
import { useLuuTungO } from '../useLuuTungO'
import { useXacNhanXoa } from '../useXacNhanXoa'
import { OMedia } from './OMedia'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { VeLai } from './KhungDuAn'
import { SectionCard } from './SectionCard'
import { SalePhaseChip } from './SaleChip'
import { ImageCard } from './ImageCard'
import { useTrangCuon } from './useTrangCuon'
import { mediaKem } from '../mediaKem'
import { plainNumber } from '../formatValue'
import {
  HANG_NUT,
  HANG_NUT_DAN,
  Bang,
  TAB_DAY,
  DauBang,
  Hang,
  NUT_CHINH,
  NUT_PHU,
  TD,
  TD_PHU,
  TD_SO,
  TheBang,
  ThanhCong,
  type Cot,
} from '@/components/ui/Bang'

const MOI: PhanKhuGhi = {
  name: '',
  category: null,
  productScale: '',
  overview: '',
  salePhase: null,
  note: '',
  amenities: '',
  numBuildings: null,
  totalUnits: null,
}

const LINK = 'text-than font-medium text-ac hover:text-acd'
const LINK_XOA = 'text-than font-medium text-badge-alert-fg hover:underline'

const COT: readonly Cot[] = [
  { nhan: 'Phân khu' },
  { nhan: 'Loại hình' },
  { nhan: 'Toà' },
  { nhan: 'Căn đã nhập', phai: true },
  { nhan: 'Tổng số căn', phai: true },
  { nhan: 'Giai đoạn bán' },
  { nhan: '', phai: true },
]

function ngayGio(iso: string): string {
  const d = new Date(iso)
  return `${ngayThangNam(d)} ${gioPhut(d)}`
}

export function PhanKhuTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const { dangSua: editing } = useKhungSua()
  // `v` khác null = đang ở form TẠO MỚI. `dangSua` = đang mở một phân khu có sẵn.
  const [v, setV] = useState<PhanKhuGhi | null>(null)
  const [dangSua, setDangSua] = useState<PhanKhu | null>(null)
  const {
    sap: sapXoa,
    hoi: hoiXoa,
    boQua,
    daXoa,
    huyRef,
    dich,
    idTieuDe,
    idMoTa,
  } = useXacNhanXoa<PhanKhu>()

  function suaV(next: PhanKhuGhi) {
    setV(next)
  }

  const ds = useQuery({
    queryKey: ['re', projectCode, 'zones', 'tat-ca'],
    queryFn: () => danhSachPhanKhu(projectCode, { limit: 200 }),
  })
  const dsToa = useQuery({
    queryKey: ['re', projectCode, 'buildings'],
    queryFn: () => danhSachToa(projectCode),
  })
  // Dự án chưa có toà nào thì bỏ cột Toà; tải toà lỗi thì giữ cột.
  const coToa = !dsToa.isSuccess || dsToa.data.items.length > 0
  const cot = coToa ? COT : COT.filter((c) => c.nhan !== 'Toà')
  const toaCua = (zoneCode: string) =>
    (dsToa.data?.items ?? [])
      .filter((t) => t.zoneCode === zoneCode)
      .map((t) => t.name || t.buildingCode)
      .sort((a, b) => a.localeCompare(b, 'vi'))
      .join(', ')

  function lamMoi() {
    void qc.invalidateQueries({ queryKey: ['re', projectCode] })
  }

  const mGhi = useMutation({
    mutationFn: (b: PhanKhuGhi) => taoPhanKhu(projectCode, { ...b, status: 'published' }),
    onSuccess: () => {
      dong()
      lamMoi()
    },
    onError: (e) => {
      if (laBienMat(e)) {
        dong()
        lamMoi()
      }
    },
  })

  const mXoa = useMutation({
    mutationFn: (ma: string) => xoaPhanKhu(projectCode, ma),
    onSuccess: () => {
      daXoa()
      lamMoi()
    },
  })

  function dong() {
    setV(null)
    setDangSua(null)
  }

  function mo(z: PhanKhu) {
    mGhi.reset()
    setV(null)
    setDangSua(z)
  }

  if (dangSua)
    return (
      <ChiTietPhanKhu
        key={dangSua.zoneCode}
        projectCode={projectCode}
        zone={ds.data?.items.find((z) => z.zoneCode === dangSua.zoneCode) ?? dangSua}
        ve={dong}
        lamMoi={lamMoi}
      />
    )

  const items = [...(ds.data?.items ?? [])].sort((a, b) => a.name.localeCompare(b.name, 'vi'))

  return (
    <div className={`${TAB_DAY} flex flex-col gap-3 pb-2`}>
      {v && (
        <form
          className="flex min-h-0 flex-1 flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            mGhi.mutate(v)
          }}
        >
          <VeLai
            nhan="Danh sách phân khu"
            ve={() => {
              mGhi.reset()
              dong()
            }}
          />
          <SectionCard title="Phân khu mới">
            <OChu
              ten="zoneName"
              nhan="Tên phân khu"
              batBuoc
              chanTrong
              giaTri={v.name ?? ''}
              doi={(x) => suaV({ ...v, name: x })}
              loi={loiO(mGhi.error, 'name')}
              goiYTrongO="Tên khách nghe khi tư vấn, VD: Sao Biển"
            />
            <OChon
              ten="zoneCategory"
              nhan="Loại hình (chọn một)"
              giaTri={v.category ?? ''}
              doi={(x) => suaV({ ...v, category: x === '' ? null : x })}
              muc={LOAI_HINH}
              nhanRong="— chưa xác định —"
              loi={loiO(mGhi.error, 'category')}
            />
            <OChu
              ten="zoneProductScale"
              nhan="Quy mô phân khu"
              giaTri={v.productScale ?? ''}
              doi={(x) => suaV({ ...v, productScale: x })}
              loi={loiO(mGhi.error, 'productScale')}
              goiYTrongO="126 căn liền kề · 18 biệt thự đơn lập"
            />
            <OChon
              ten="zoneSalePhase"
              nhan="Giai đoạn bán"
              giaTri={v.salePhase ?? ''}
              doi={(x) => suaV({ ...v, salePhase: x === '' ? null : x })}
              muc={SALE_PHASE}
              nhanRong="— chưa xác định —"
              loi={loiO(mGhi.error, 'salePhase')}
            />
            <OSo
              ten="zoneTotalUnits"
              nhan="Tổng số căn"
              giaTri={v.totalUnits ?? null}
              doi={(x) => suaV({ ...v, totalUnits: x })}
              min={0}
              buoc={1}
              loi={loiO(mGhi.error, 'totalUnits')}
              goiYTrongO="620"
            />
            <OSo
              ten="zoneNumBuildings"
              nhan="Số toà"
              giaTri={v.numBuildings ?? null}
              doi={(x) => suaV({ ...v, numBuildings: x })}
              min={0}
              buoc={1}
              loi={loiO(mGhi.error, 'numBuildings')}
              goiYTrongO="0 với khu thấp tầng"
            />
            <CaHang>
              <OChu
                ten="zoneNote"
                nhan="Vị trí trong dự án"
                giaTri={v.note ?? ''}
                doi={(x) => suaV({ ...v, note: x })}
                loi={loiO(mGhi.error, 'note')}
                goiYTrongO="Sát cổng chính, cạnh trường liên cấp, nhìn ra hồ trung tâm"
              />
            </CaHang>
            <CaHang>
              <OChu
                ten="zoneAmenities"
                nhan="Tiện ích riêng của phân khu"
                hangChu={2}
                giaTri={v.amenities ?? ''}
                doi={(x) => suaV({ ...v, amenities: x })}
                loi={loiO(mGhi.error, 'amenities')}
                goiYTrongO="Clubhouse, bể bơi riêng, vườn Nhật"
              />
            </CaHang>
            <CaHang>
              <OChu
                ten="zoneOverview"
                nhan="Tổng quan phân khu"
                hangChu={5}
                giaTri={v.overview ?? ''}
                doi={(x) => suaV({ ...v, overview: x })}
                loi={loiO(mGhi.error, 'overview')}
                goiYTrongO="Phân khu này khác gì các phân khu còn lại: dòng sản phẩm, tầm nhìn, tiện ích riêng, khoảng giá, phù hợp với nhóm khách nào."
              />
            </CaHang>
            <CaHang>
              <div className="grid gap-4 md:grid-cols-2">
                <OMedia
                  nhan="Ảnh cover"
                  giaTri={v.coverMedia ?? null}
                  doi={(x) => suaV({ ...v, coverMedia: x })}
                />
                <OMedia
                  nhan="Mặt bằng phân khu"
                  giaTri={v.mapMedia ?? null}
                  doi={(x) => suaV({ ...v, mapMedia: x })}
                  noDraftCaption
                />
              </div>
            </CaHang>
          </SectionCard>

          {mGhi.error && (
            <DongTrangThai mau="alert">{cauLoi(mGhi.error, 'lưu phân khu')}</DongTrangThai>
          )}
          <div data-testid="pform-day" className={HANG_NUT_DAN}>
            <button
              type="button"
              className={NUT_PHU}
              onClick={() => {
                mGhi.reset()
                setV(null)
              }}
            >
              Huỷ
            </button>
            <button type="submit" className={NUT_CHINH} disabled={mGhi.isPending}>
              {mGhi.isPending ? 'Đang lưu…' : 'Lưu phân khu'}
            </button>
          </div>
        </form>
      )}

      {!v && (
        <TheBang>
          {editing && (
            <ThanhCong>
              <span className="flex-1" />
              <button
                ref={dich}
                type="button"
                className={`${NUT_CHINH} flex-none`}
                onClick={() => {
                  mGhi.reset()
                  setV({ ...MOI })
                }}
              >
                Thêm phân khu
              </button>
            </ThanhCong>
          )}
          {ds.isPending || dsToa.isPending ? (
            <p className="p-4 text-than text-muted">Đang tải…</p>
          ) : ds.error ? (
            <div className="p-4">
              <LoiTai viec="danh sách phân khu" thuLai={() => void ds.refetch()} />
            </div>
          ) : items.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Dự án này chưa có phân khu nào."
                huongDan="Mỗi căn phải thuộc một phân khu, nên tạo phân khu trước khi nhập quỹ căn."
              />
            </div>
          ) : (
            <Bang>
              <DauBang cot={cot} />
              <tbody>
                {items.map((z) => (
                  <Hang key={z.id} mo={() => mo(z)}>
                    <td className={TD}>
                      <button
                        type="button"
                        className="text-left font-semibold text-fg hover:text-ac"
                        onClick={() => mo(z)}
                      >
                        {z.name || '(chưa có tên)'}
                      </button>
                    </td>
                    <td className={TD_PHU}>{nhanCua(LOAI_HINH, z.category) || '—'}</td>
                    {coToa && <td className={TD_PHU}>{toaCua(z.zoneCode) || '—'}</td>}
                    <td className={TD_SO}>{z.unitCount == null ? '—' : so(z.unitCount)}</td>
                    <td className={TD_SO}>{z.totalUnits == null ? '—' : so(z.totalUnits)}</td>
                    <td className={TD}>
                      <SalePhaseChip value={z.salePhase} />
                    </td>
                    <td className={`${TD} whitespace-nowrap text-right`}>
                      {editing ? (
                        <span className="inline-flex gap-3">
                          <button type="button" className={LINK} onClick={() => mo(z)}>
                            Sửa
                          </button>
                          <button type="button" className={LINK_XOA} onClick={() => hoiXoa(z)}>
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
            Xoá phân khu {sapXoa.name || sapXoa.zoneCode}?
          </p>
          {/* FK `units_tenant_zone_fk ... ON DELETE CASCADE` (migration 0400). */}
          <div id={idMoTa}>
            <p>Mọi căn thuộc phân khu này bị xoá cùng.</p>
            <p className="text-[13px] text-muted">Không hoàn tác được.</p>
          </div>
          {mXoa.error && (
            <p role="alert" className="mt-1 text-[13px] text-badge-alert-fg">
              {cauLoi(mXoa.error, 'xoá phân khu')}
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
              onClick={() => mXoa.mutate(sapXoa.zoneCode)}
            >
              Xoá
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Một phân khu đã có — chế độ xem dạng chữ, bấm Sửa ở đầu trang thì tự lưu từng ô. */
function ChiTietPhanKhu({
  projectCode,
  zone,
  ve,
  lamMoi,
}: {
  projectCode: string
  zone: PhanKhu
  ve: () => void
  lamMoi: () => void
}) {
  const { dangSua } = useKhungSua()
  const khoa = !dangSua

  const luu = useCallback(
    async (patch: PhanKhuGhi) => {
      const r = await suaPhanKhu(projectCode, zone.zoneCode, patch)
      lamMoi()
      return r
    },
    [projectCode, zone.zoneCode, lamMoi],
  )

  const o = useLuuTungO<PhanKhuGhi>(
    {
      name: zone.name,
      category: zone.category,
      productScale: zone.productScale,
      overview: zone.overview,
      salePhase: zone.salePhase ?? null,
      note: zone.note ?? '',
      amenities: zone.amenities ?? '',
      numBuildings: zone.numBuildings ?? null,
      totalUnits: zone.totalUnits ?? null,
    },
    luu,
  )

  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )
  // Ô ảnh vắng = chưa đổi ở màn này ⇒ hiện ảnh đang lưu; `null` = vừa bỏ ảnh.
  const cover =
    o.v.coverMedia === undefined
      ? mediaKem(media.items.find((m) => m.id === zone.coverMediaId))
      : o.v.coverMedia
  const map =
    o.v.mapMedia === undefined
      ? mediaKem(media.items.find((m) => m.id === zone.mapMediaId))
      : o.v.mapMedia

  return (
    <div className={`${TAB_DAY} flex flex-col gap-4 pb-2`}>
      <div>
        <VeLai nhan="Danh sách phân khu" ve={ve} />
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
          <h3 className="text-[20px] font-semibold text-fg">{zone.name || zone.zoneCode}</h3>
          <SalePhaseChip value={o.v.salePhase} />
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-than text-muted-2">
          <span className="font-mono text-[12px]">{zone.zoneCode}</span>
          <span aria-hidden>·</span>
          <span>Sửa lần cuối {ngayGio(zone.updatedAt)}</span>
        </div>
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_312px]">
        <div className="flex min-w-0 flex-col gap-4">
          <SectionCard title="Thông tin phân khu">
            <OChu
              ten="zoneName"
              khoa={khoa}
              nhan="Tên phân khu"
              batBuoc
              giaTri={o.v.name ?? ''}
              doi={(x) => o.doi('name', x)}
              xong={() => o.xong('name')}
              loi={loiO(o.loi, 'name')}
              goiYTrongO="Tên khách nghe khi tư vấn, VD: Sao Biển"
            />
            <OChon
              ten="zoneCategory"
              khoa={khoa}
              nhan="Loại hình"
              giaTri={o.v.category ?? ''}
              doi={(x) => o.doiVaLuu('category', x === '' ? null : x)}
              muc={LOAI_HINH}
              nhanRong="— chưa xác định —"
              loi={loiO(o.loi, 'category')}
            />
            <OChon
              ten="zoneSalePhase"
              khoa={khoa}
              nhan="Giai đoạn bán"
              giaTri={o.v.salePhase ?? ''}
              doi={(x) => o.doiVaLuu('salePhase', x === '' ? null : x)}
              muc={SALE_PHASE}
              nhanRong="— chưa xác định —"
              loi={loiO(o.loi, 'salePhase')}
              renderValue={(x) => <SalePhaseChip value={x} />}
            />
            <OSo
              ten="zoneTotalUnits"
              khoa={khoa}
              nhan="Tổng số căn"
              unit="căn"
              giaTri={o.v.totalUnits ?? null}
              doi={(x) => o.doi('totalUnits', x)}
              xong={() => o.xong('totalUnits')}
              min={0}
              buoc={1}
              loi={loiO(o.loi, 'totalUnits')}
              goiYTrongO="620"
            />
            <OSo
              ten="zoneNumBuildings"
              khoa={khoa}
              nhan="Số toà"
              unit="toà"
              giaTri={o.v.numBuildings ?? null}
              doi={(x) => o.doi('numBuildings', x)}
              xong={() => o.xong('numBuildings')}
              min={0}
              buoc={1}
              loi={loiO(o.loi, 'numBuildings')}
              goiYTrongO="0 với khu thấp tầng"
            />
            <ReadField label="Căn đã nhập">
              {zone.unitCount == null ? '—' : <>{plainNumber(zone.unitCount)} căn</>}
              {dangSua && <span className="block text-phu text-muted-2">Đếm từ quỹ căn.</span>}
            </ReadField>
            <CaHang>
              <OChu
                ten="zoneProductScale"
                khoa={khoa}
                nhan="Quy mô phân khu"
                giaTri={o.v.productScale ?? ''}
                doi={(x) => o.doi('productScale', x)}
                xong={() => o.xong('productScale')}
                loi={loiO(o.loi, 'productScale')}
                goiYTrongO="126 căn liền kề · 18 biệt thự đơn lập"
              />
            </CaHang>
          </SectionCard>

          <SectionCard title="Vị trí và tiện ích" cols={1}>
            <OChu
              ten="zoneNote"
              khoa={khoa}
              nhan="Vị trí trong dự án"
              giaTri={o.v.note ?? ''}
              doi={(x) => o.doi('note', x)}
              xong={() => o.xong('note')}
              loi={loiO(o.loi, 'note')}
              goiYTrongO="Sát cổng chính, cạnh trường liên cấp, nhìn ra hồ trung tâm"
            />
            <OChu
              ten="zoneAmenities"
              khoa={khoa}
              nhan="Tiện ích riêng của phân khu"
              hangChu={2}
              giaTri={o.v.amenities ?? ''}
              doi={(x) => o.doi('amenities', x)}
              xong={() => o.xong('amenities')}
              loi={loiO(o.loi, 'amenities')}
              goiYTrongO="Clubhouse, bể bơi riêng, vườn Nhật"
            />
          </SectionCard>

          <SectionCard title="Tổng quan phân khu" cols={1}>
            <OChu
              ten="zoneOverview"
              khoa={khoa}
              nhan="Tổng quan phân khu"
              hideLabelInView
              hangChu={5}
              giaTri={o.v.overview ?? ''}
              doi={(x) => o.doi('overview', x)}
              xong={() => o.xong('overview')}
              loi={loiO(o.loi, 'overview')}
              goiYTrongO="Phân khu này khác gì các phân khu còn lại: dòng sản phẩm, tầm nhìn, tiện ích riêng, khoảng giá, phù hợp với nhóm khách nào."
            />
          </SectionCard>

          {o.loi != null && (
            <DongTrangThai mau="alert">{cauLoi(o.loi, 'lưu phân khu')}</DongTrangThai>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          <ImageCard
            title="Ảnh cover"
            media={cover}
            editing={dangSua}
            editor={
              <OMedia
                bare
                nhan="Ảnh cover"
                giaTri={cover}
                doi={(x) => o.doiVaLuu('coverMedia', x)}
              />
            }
          />
          <ImageCard
            title="Mặt bằng phân khu"
            media={map}
            editing={dangSua}
            editor={
              <OMedia
                bare
                nhan="Mặt bằng phân khu"
                giaTri={map}
                doi={(x) => o.doiVaLuu('mapMedia', x)}
                noDraftCaption
              />
            }
          />
        </aside>
      </div>
    </div>
  )
}
