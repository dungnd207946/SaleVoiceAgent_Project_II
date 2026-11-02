/**
 * Tab Toà — bảng toà / block của một dự án và màn chi tiết một toà.
 *
 * `buildingCode` phải trùng `units.block` của các căn thuộc toà (số căn đếm theo đó). Toà cũng tự
 * sinh khi một căn mang block mới, nên danh sách thường đã có sẵn tên — việc chính ở đây là điền
 * thông số toà.
 */
import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { danhSachPhanKhu, danhSachToa, suaToa, taoToa, xoaToa, type Toa, type ToaGhi } from '../api'
import { HUONG, SALE_PHASE } from '../enums'
import { cauLoi, laBienMat, loiO } from '../thongDiep'
import { CaHang, DongTrangThai, OChon, OChu, OSo, ReadField } from '@/components/ui/Truong'
import { ngayThangNam, gioPhut, so } from '@/lib/dinhDang'
import { useKhungSua } from '../khungSua'
import { useLuuTungO } from '../useLuuTungO'
import { useXacNhanXoa } from '../useXacNhanXoa'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { VeLai } from './KhungDuAn'
import { SectionCard } from './SectionCard'
import { SalePhaseChip } from './SaleChip'
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

const MOI: ToaGhi = {
  buildingCode: '',
  name: '',
  zoneCode: null,
  numFloors: null,
  numBasements: null,
  unitsPerFloor: null,
  elevatorsPassenger: null,
  elevatorsService: null,
  carSlots: null,
  motoSlots: null,
  ceilingHeightM: null,
  facing: null,
  salePhase: null,
  amenities: '',
  overview: '',
}

const COT: readonly Cot[] = [
  { nhan: 'Toà' },
  { nhan: 'Phân khu' },
  { nhan: 'Số tầng', phai: true },
  { nhan: 'Thang máy' },
  { nhan: 'Căn đã nhập', phai: true },
  { nhan: 'Giai đoạn bán' },
  { nhan: '', phai: true },
]

const LINK = 'text-than font-medium text-ac hover:text-acd'
const LINK_XOA = 'text-than font-medium text-badge-alert-fg hover:underline'

type Ghi = (k: keyof ToaGhi, x: ToaGhi[keyof ToaGhi]) => void

interface OProps {
  v: ToaGhi
  khoa?: boolean | undefined
  doi: Ghi
  xong?: ((k: keyof ToaGhi) => void) | undefined
  chon: Ghi
  loi: unknown
  phanKhu: readonly { value: string; nhan: string }[]
}

function ngayGio(iso: string): string {
  const d = new Date(iso)
  return `${ngayThangNam(d)} ${gioPhut(d)}`
}

/** Phân khu, giai đoạn bán, hướng — chung cho form tạo và màn chi tiết. */
function OThongTin({ v, khoa, chon, loi, phanKhu }: OProps) {
  return (
    <>
      <OChon
        ten="toa-zoneCode"
        khoa={khoa}
        nhan="Phân khu"
        giaTri={v.zoneCode ?? ''}
        doi={(x) => chon('zoneCode', x === '' ? null : x)}
        muc={phanKhu}
        nhanRong="— chưa gắn phân khu —"
        loi={loiO(loi, 'zoneCode')}
      />
      <OChon
        ten="toa-salePhase"
        khoa={khoa}
        nhan="Giai đoạn bán"
        giaTri={v.salePhase ?? ''}
        doi={(x) => chon('salePhase', x === '' ? null : x)}
        muc={SALE_PHASE}
        nhanRong="— chưa xác định —"
        loi={loiO(loi, 'salePhase')}
        renderValue={(x) => <SalePhaseChip value={x} />}
      />
      <OChon
        ten="toa-facing"
        khoa={khoa}
        nhan="Hướng toà"
        giaTri={v.facing ?? ''}
        doi={(x) => chon('facing', x === '' ? null : x)}
        muc={HUONG}
        nhanRong="— chưa xác định —"
        loi={loiO(loi, 'facing')}
      />
    </>
  )
}

/** Tám ô số của toà. */
function OSoLieu({ v, khoa, doi, xong, loi }: OProps) {
  const oSo = (k: keyof ToaGhi, nhan: string, unit: string, goiY: string, max?: number) => (
    <OSo
      ten={`toa-${k}`}
      khoa={khoa}
      nhan={nhan}
      unit={unit}
      giaTri={(v[k] as number | null | undefined) ?? null}
      doi={(x) => doi(k, x)}
      xong={xong ? () => xong(k) : undefined}
      min={0}
      max={max}
      buoc={k === 'ceilingHeightM' ? 'any' : 1}
      loi={loiO(loi, k)}
      goiYTrongO={goiY}
    />
  )
  return (
    <>
      {oSo('numFloors', 'Số tầng nổi', 'tầng', '25', 300)}
      {oSo('numBasements', 'Số tầng hầm', 'tầng', '2', 20)}
      {oSo('unitsPerFloor', 'Số căn mỗi sàn', 'căn', '12', 200)}
      {oSo('ceilingHeightM', 'Chiều cao trần', 'm', '3.1', 20)}
      {oSo('elevatorsPassenger', 'Thang máy khách', 'thang', '4', 100)}
      {oSo('elevatorsService', 'Thang máy hàng', 'thang', '1', 100)}
      {oSo('carSlots', 'Chỗ đỗ ô tô', 'chỗ', '250')}
      {oSo('motoSlots', 'Chỗ đỗ xe máy', 'chỗ', '900')}
    </>
  )
}

/** Mô tả và tiện ích riêng của toà. */
function OMoTa({ v, khoa, doi, xong, loi }: OProps) {
  return (
    <>
      <OChu
        ten="toa-overview"
        khoa={khoa}
        nhan="Mô tả toà"
        hangChu={4}
        giaTri={v.overview ?? ''}
        doi={(x) => doi('overview', x)}
        xong={xong ? () => xong('overview') : undefined}
        loi={loiO(loi, 'overview')}
        goiYTrongO="Toà này khác gì các toà còn lại: vị trí, tầm nhìn, dòng căn, nhóm khách phù hợp."
      />
      <OChu
        ten="toa-amenities"
        khoa={khoa}
        nhan="Tiện ích riêng của toà"
        hangChu={2}
        giaTri={v.amenities ?? ''}
        doi={(x) => doi('amenities', x)}
        xong={xong ? () => xong('amenities') : undefined}
        loi={loiO(loi, 'amenities')}
        goiYTrongO="Sảnh khách sạn, bể bơi tầng mái, phòng gym, khu sinh hoạt cộng đồng"
      />
    </>
  )
}

export function ToaTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const { dangSua: editing } = useKhungSua()
  const [v, setV] = useState<ToaGhi | null>(null)
  const [dangSua, setDangSua] = useState<Toa | null>(null)
  const {
    sap: sapXoa,
    hoi: hoiXoa,
    boQua,
    daXoa,
    huyRef,
    dich,
    idTieuDe,
    idMoTa,
  } = useXacNhanXoa<Toa>()

  const ds = useQuery({
    queryKey: ['re', projectCode, 'buildings'],
    queryFn: () => danhSachToa(projectCode),
  })
  const dsZone = useQuery({
    queryKey: ['re', projectCode, 'zones', 'tat-ca'],
    queryFn: () => danhSachPhanKhu(projectCode, { limit: 200 }),
  })
  const phanKhu = (dsZone.data?.items ?? []).map((z) => ({
    value: z.zoneCode,
    nhan: z.name || z.zoneCode,
  }))
  const tenPhanKhu = (ma: string | null) => phanKhu.find((z) => z.value === ma)?.nhan ?? ma ?? '—'

  function lamMoi() {
    void qc.invalidateQueries({ queryKey: ['re', projectCode] })
  }

  const mGhi = useMutation({
    mutationFn: (b: ToaGhi) => taoToa(projectCode, b),
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
    mutationFn: (ma: string) => xoaToa(projectCode, ma),
    onSuccess: () => {
      daXoa()
      lamMoi()
    },
  })

  function dong() {
    setV(null)
    setDangSua(null)
  }

  function mo(t: Toa) {
    mGhi.reset()
    setV(null)
    setDangSua(t)
  }

  if (dangSua)
    return (
      <ChiTietToa
        key={dangSua.buildingCode}
        projectCode={projectCode}
        toa={ds.data?.items.find((t) => t.buildingCode === dangSua.buildingCode) ?? dangSua}
        phanKhu={phanKhu}
        tenPhanKhu={tenPhanKhu}
        ve={dong}
        lamMoi={lamMoi}
      />
    )

  const items = [...(ds.data?.items ?? [])].sort((a, b) =>
    a.buildingCode.localeCompare(b.buildingCode, 'vi', { numeric: true }),
  )

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
            nhan="Danh sách toà"
            ve={() => {
              mGhi.reset()
              dong()
            }}
          />
          <SectionCard title="Toà mới">
            <OChu
              ten="toa-buildingCode"
              nhan="Mã toà"
              batBuoc
              chanTrong
              giaTri={v.buildingCode ?? ''}
              doi={(x) => setV({ ...v, buildingCode: x })}
              loi={loiO(mGhi.error, 'buildingCode')}
              goiY="Căn chọn toà theo mã này ở ô «Toà / block»"
              goiYTrongO="VD: S2.03"
            />
            <OChu
              ten="toa-name"
              nhan="Tên toà"
              giaTri={v.name ?? ''}
              doi={(x) => setV({ ...v, name: x })}
              loi={loiO(mGhi.error, 'name')}
              goiYTrongO="Để trống thì dùng mã toà"
            />
            <OThongTin
              v={v}
              doi={(k, x) => setV({ ...v, [k]: x })}
              chon={(k, x) => setV({ ...v, [k]: x })}
              loi={mGhi.error}
              phanKhu={phanKhu}
            />
            <OSoLieu
              v={v}
              doi={(k, x) => setV({ ...v, [k]: x })}
              chon={(k, x) => setV({ ...v, [k]: x })}
              loi={mGhi.error}
              phanKhu={phanKhu}
            />
            <CaHang>
              <OMoTa
                v={v}
                doi={(k, x) => setV({ ...v, [k]: x })}
                chon={(k, x) => setV({ ...v, [k]: x })}
                loi={mGhi.error}
                phanKhu={phanKhu}
              />
            </CaHang>
          </SectionCard>

          {mGhi.error && <DongTrangThai mau="alert">{cauLoi(mGhi.error, 'lưu toà')}</DongTrangThai>}
          <div className={HANG_NUT_DAN}>
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
              {mGhi.isPending ? 'Đang lưu…' : 'Lưu toà'}
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
                Thêm toà
              </button>
            </ThanhCong>
          )}
          {ds.isPending ? (
            <p className="p-4 text-than text-muted">Đang tải…</p>
          ) : ds.error ? (
            <div className="p-4">
              <LoiTai viec="danh sách toà" thuLai={() => void ds.refetch()} />
            </div>
          ) : items.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Dự án này chưa có toà nào."
                huongDan="Thêm toà ở đây rồi chọn toà cho căn ở ô «Toà / block»; dự án thấp tầng thường không có toà."
              />
            </div>
          ) : (
            <Bang>
              <DauBang cot={COT} />
              <tbody>
                {items.map((t) => (
                  <Hang key={t.id} mo={() => mo(t)}>
                    <td className={TD}>
                      <button
                        type="button"
                        className="text-left font-semibold text-fg hover:text-ac"
                        onClick={() => mo(t)}
                      >
                        {t.name || t.buildingCode}
                      </button>
                      {t.name && t.name !== t.buildingCode && (
                        <div className="font-mono text-phu text-muted-2">{t.buildingCode}</div>
                      )}
                    </td>
                    <td className={TD_PHU}>{tenPhanKhu(t.zoneCode)}</td>
                    <td className={TD_SO}>{t.numFloors ?? '—'}</td>
                    <td className={TD_PHU}>
                      {t.elevatorsPassenger == null
                        ? '—'
                        : `${t.elevatorsPassenger} khách · ${t.elevatorsService ?? 0} hàng`}
                    </td>
                    <td className={TD_SO}>{so(t.unitCount)}</td>
                    <td className={TD}>
                      <SalePhaseChip value={t.salePhase} />
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
        </TheBang>
      )}

      {sapXoa && (
        <div
          className="rounded-lg border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-than"
          role="alertdialog"
          aria-labelledby={idTieuDe}
          aria-describedby={idMoTa}
        >
          <p id={idTieuDe} className="font-semibold">
            Xoá toà {sapXoa.name || sapXoa.buildingCode}?
          </p>
          <div id={idMoTa}>
            {sapXoa.unitCount > 0 ? (
              <p>Toà còn {sapXoa.unitCount} căn — chuyển các căn sang toà khác trước khi xoá.</p>
            ) : (
              <p className="text-phu text-muted">Không hoàn tác được.</p>
            )}
          </div>
          {mXoa.error && (
            <p role="alert" className="mt-1 text-phu text-badge-alert-fg">
              {cauLoi(mXoa.error, 'xoá toà')}
            </p>
          )}
          <div className={`mt-3 ${HANG_NUT}`}>
            <button ref={huyRef} type="button" className={NUT_PHU} onClick={boQua}>
              Huỷ
            </button>
            <button
              type="button"
              className={NUT_CHINH}
              disabled={mXoa.isPending || sapXoa.unitCount > 0}
              onClick={() => mXoa.mutate(sapXoa.buildingCode)}
            >
              Xoá
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Một toà đã có — chế độ xem dạng chữ, bấm Sửa ở đầu trang thì tự lưu từng ô. */
function ChiTietToa({
  projectCode,
  toa,
  phanKhu,
  tenPhanKhu,
  ve,
  lamMoi,
}: {
  projectCode: string
  toa: Toa
  phanKhu: readonly { value: string; nhan: string }[]
  tenPhanKhu: (ma: string | null) => string
  ve: () => void
  lamMoi: () => void
}) {
  const { dangSua } = useKhungSua()
  const khoa = !dangSua

  const luu = useCallback(
    async (patch: ToaGhi) => {
      const r = await suaToa(projectCode, toa.buildingCode, patch)
      lamMoi()
      return r
    },
    [projectCode, toa.buildingCode, lamMoi],
  )

  const o = useLuuTungO<ToaGhi>(
    {
      name: toa.name,
      zoneCode: toa.zoneCode,
      numFloors: toa.numFloors,
      numBasements: toa.numBasements,
      unitsPerFloor: toa.unitsPerFloor,
      elevatorsPassenger: toa.elevatorsPassenger,
      elevatorsService: toa.elevatorsService,
      carSlots: toa.carSlots,
      motoSlots: toa.motoSlots,
      ceilingHeightM: toa.ceilingHeightM,
      facing: toa.facing,
      salePhase: toa.salePhase,
      amenities: toa.amenities,
      overview: toa.overview,
    },
    luu,
  )
  const props: OProps = {
    v: o.v,
    khoa,
    doi: (k, x) => o.doi(k, x),
    xong: (k) => o.xong(k),
    chon: (k, x) => o.doiVaLuu(k, x),
    loi: o.loi,
    phanKhu,
  }

  return (
    <div className={`${TAB_DAY} flex flex-col gap-4 pb-2`}>
      <div>
        <VeLai nhan="Danh sách toà" ve={ve} />
        <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
          <h3 className="text-[20px] font-semibold text-fg">Toà {toa.name || toa.buildingCode}</h3>
          <SalePhaseChip value={o.v.salePhase} />
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-than text-muted-2">
          <span>Phân khu {tenPhanKhu(o.v.zoneCode ?? null)}</span>
          <span aria-hidden>·</span>
          <span>Sửa lần cuối {ngayGio(toa.updatedAt)}</span>
        </div>
      </div>

      <SectionCard title="Thông tin toà">
        <ReadField label="Mã toà">
          <span className="font-mono text-than">{toa.buildingCode}</span>
          {dangSua && (
            <span className="block text-phu text-muted-2">Không đổi được sau khi tạo.</span>
          )}
        </ReadField>
        <OChu
          ten="toa-name"
          khoa={khoa}
          nhan="Tên toà"
          giaTri={o.v.name ?? ''}
          doi={(x) => o.doi('name', x)}
          xong={() => o.xong('name')}
          loi={loiO(o.loi, 'name')}
        />
        <OThongTin {...props} />
        <ReadField label="Căn đã nhập">
          {plainNumber(toa.unitCount)} căn
          {dangSua && <span className="block text-phu text-muted-2">Đếm từ quỹ căn.</span>}
        </ReadField>
      </SectionCard>

      <SectionCard title="Thông số kỹ thuật" cols={4}>
        <OSoLieu {...props} />
      </SectionCard>

      <SectionCard title="Mô tả và tiện ích" cols={1}>
        <OMoTa {...props} />
      </SectionCard>

      {o.loi != null && <DongTrangThai mau="alert">{cauLoi(o.loi, 'lưu toà')}</DongTrangThai>}
    </div>
  )
}
