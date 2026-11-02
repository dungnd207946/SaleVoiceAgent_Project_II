/**
 * Màn `/uform` — form một căn. 15 ô chung, 5 ô đặc điểm, nhóm ô riêng của cao tầng hoặc
 * thấp tầng (theo loại sản phẩm), + ảnh căn.
 *
 * ĐỊNH DANH BẰNG `id`, KHÔNG BẰNG `unitCode`: `units.unit_code` KHÔNG unique
 * (`02a §4.3` — dữ liệu nhập tay trùng mã giữa các đợt), nên "sửa căn mã A-12" là
 * một câu hỏi mơ hồ. `?unit=41` là `id` thật, và đó cũng là thứ `PATCH`/`DELETE`
 * của backend nhận.
 *
 * ẢNH CĂN ĐI BA BƯỚC, VÀ BƯỚC HAI KHÔNG NGUYÊN TỬ. `UnitIn` không có DTO media
 * lồng (khác `ProjectIn.coverMedia`) — đây là khoảng hở đã ghi deferred ở Task 4
 * của backend. FE phải: ① upload từng tệp lấy khoá ② `POST /media` từng ảnh với
 * `unitCode` ③ `PATCH` căn đặt `imageUrl` = khoá ảnh đầu. Nếu ② vỡ giữa chừng thì
 * một phần ảnh đã lên: màn PHẢI nói ảnh nào đã lên và ảnh nào chưa, vì người dùng
 * bấm lại là nhân đôi số ảnh trong kho cho cùng một tệp.
 */
import { useCallback, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LoiApi } from '@/lib/http'
import {
  danhSachMedia,
  docDuAn,
  danhSachPhanKhu,
  danhSachToa,
  docCan,
  nguonAnh,
  suaCan,
  taoCan,
  taoMedia,
  xoaMedia,
  type Can,
  type CanGhi,
  type Media,
  type MediaKem,
  type PhanKhu,
} from '../api'
import {
  BAN_GIAO_CAN,
  CO_KHONG,
  HUONG,
  MEDIA_CATEGORY,
  PRODUCT_TYPE,
  SALE_STATUS,
  VIEW,
  laCaoTang,
  nhanCua,
} from '../enums'
import { trangThaiCan } from '../trangThai'
import { cauLoi, loiO } from '../thongDiep'
import { DongTrangThai, OChon, OChonNhieu, OChu, OSo } from '@/components/ui/Truong'
import { OMedia } from './OMedia'
import { HANG_NUT_DAN, KHUNG_MAN, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { useLuuTungO } from '../useLuuTungO'
import { LoiTai } from '@/components/ui/TrangThai'
import { DaiDangSua, DauDuAn, LinkVe } from './KhungDuAn'
import { KhungSuaProvider, useKhungSua, useSaveStatus } from '../khungSua'
import { setEditing, useEditing } from '../editMode'
import { SectionCard } from './SectionCard'
import { SaleStatusChip } from './SaleChip'
import { AnhLon } from './AnhLon'
import { priceBillion, pricePerM2, plainNumber } from '../formatValue'
import { ngayThangNam, gioPhut } from '@/lib/dinhDang'
import { useTrangCuon } from './useTrangCuon'
import { panelTab } from '@/components/ui/panelTab'
import { ID_TAB_DU_AN } from '../tabDuAn'

const NUT = NUT_PHU
const DANH_MUC_ANH_CAN = 'noi_that'

const MOI: CanGhi = {
  zoneCode: '',
  unitCode: '',
  productType: 'chung_cu',
  bedrooms: null,
  block: null,
  floor: null,
  numFloors: null,
  direction: null,
  areaBuiltM2: null,
  areaWallM2: null,
  areaLandM2: null,
  priceVnd: null,
  pricePerM2Vnd: null,
  saleStatus: 'available',
  views: [],
  isCorner: null,
  openSides: null,
  bathrooms: null,
  handoverCondition: null,
  hrBalconyM2: null,
  hrLoggiaM2: null,
  lrFrontageM: null,
  lrDepthM: null,
  lrRoadWidthM: null,
}

function tuCan(c: Can): CanGhi {
  return {
    bedrooms: c.bedrooms,
    block: c.block,
    floor: c.floor,
    numFloors: c.numFloors,
    direction: c.direction,
    areaBuiltM2: c.areaBuiltM2,
    areaWallM2: c.areaWallM2,
    areaLandM2: c.areaLandM2,
    priceVnd: c.priceVnd,
    pricePerM2Vnd: c.pricePerM2Vnd,
    saleStatus: c.saleStatus,
    imageUrl: c.imageUrl,
    views: [...(c.views ?? [])],
    isCorner: c.isCorner ?? null,
    openSides: c.openSides ?? null,
    bathrooms: c.bathrooms ?? null,
    handoverCondition: c.handoverCondition ?? null,
    hrBalconyM2: c.hrBalconyM2 ?? null,
    hrLoggiaM2: c.hrLoggiaM2 ?? null,
    lrFrontageM: c.lrFrontageM ?? null,
    lrDepthM: c.lrDepthM ?? null,
    lrRoadWidthM: c.lrRoadWidthM ?? null,
  }
}

interface Props {
  projectCode: string
  unitId?: number | undefined
}

export function CanForm({ projectCode, unitId }: Props) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const moi = unitId === undefined

  const qCan = useQuery({
    queryKey: ['re', projectCode, 'unit', unitId],
    queryFn: () => docCan(projectCode, unitId!),
    enabled: !moi,
  })
  const qDuAn = useQuery({
    queryKey: ['re', projectCode],
    queryFn: () => docDuAn(projectCode),
  })
  const dsZone = useTrangCuon<PhanKhu>(['re', projectCode, 'zones'], (c) =>
    danhSachPhanKhu(projectCode, { cursor: c }),
  )
  const dsToa = useQuery({
    queryKey: ['re', projectCode, 'buildings'],
    queryFn: () => danhSachToa(projectCode),
  })

  const can = qCan.data ?? null

  // Sửa một căn ĐÃ CÓ: mỗi ô tự lưu. TẠO căn mới: gom vào state rồi một POST —
  // chưa có hàng thì không có gì để PATCH.
  const luuMotO = useCallback(
    async (patch: CanGhi) => {
      if (!can) return
      // `status` của CĂN được SUY ra, không ai chọn (`trangThaiCan`) — nên nó
      // phải đi cùng mọi lượt lưu: điền nốt Giá bán mà không gửi status thì căn
      // đủ dữ liệu vẫn nằm ở `draft` và agent không đọc. Khác dự án, chỗ đó có
      // chip và chip là người sở hữu duy nhất.
      const than = { ...patch, status: trangThaiCan({ ...tuCan(can), ...patch }, can.status) }
      const c = await suaCan(projectCode, can.id, than)
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'units'] })
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'unit', c.id] })
      return c
    },
    [can, projectCode, qc],
  )

  // Cùng cờ đang sửa với `/pform` của dự án; tạo căn mới thì luôn mở.
  const dangSuaDuAn = useEditing(projectCode)
  const dangSua = moi || dangSuaDuAn
  const khoaO = !dangSua
  const saveStatus = useSaveStatus()

  const o = useLuuTungO<CanGhi>(
    can ? tuCan(can) : { ...MOI },
    luuMotO,
    can?.id ?? 'moi',
    saveStatus.reportSave,
  )
  const gia_tri = o.v
  const dat = <K extends keyof CanGhi>(k: K, x: CanGhi[K]) => o.doi(k, x)
  const xongO = (k: keyof CanGhi) => {
    if (!moi) o.xong(k)
  }
  const chon = <K extends keyof CanGhi>(k: K, x: CanGhi[K]) => {
    if (moi) o.doi(k, x)
    else o.doiVaLuu(k, x)
  }

  const mTao = useMutation({
    mutationFn: (body: CanGhi) => taoCan(projectCode, body),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'units'] })
      void nav({ to: '/uform', search: { code: projectCode, unit: c.id } })
    },
  })

  if ((!moi && qCan.isPending) || dsToa.isPending)
    return <p className="px-7 py-6 text-[14px] text-muted max-md:px-4 max-md:py-4">Đang tải…</p>
  if (!moi && qCan.error) {
    const mat = qCan.error instanceof LoiApi && qCan.error.code === 'UNIT_NOT_FOUND'
    return mat ? (
      <div className="space-y-3 px-7 py-6 text-[14px] max-md:px-4 max-md:py-4">
        <p>Căn này không còn tồn tại — có thể vừa bị xoá.</p>
        <Link to="/pform" search={{ code: projectCode, tab: 'quy-can' }} className={NUT}>
          Về quỹ căn của dự án
        </Link>
      </div>
    ) : (
      <div className="px-7 py-6 max-md:px-4 max-md:py-4">
        <LoiTai viec="căn" thuLai={() => void qCan.refetch()} />
      </div>
    )
  }
  if (!gia_tri) return null

  // Chỉ chặn khi TẠO MỚI — sửa/xem một căn ĐÃ CÓ (kể cả loại ingest, zone_code
  // NULL) không được phép rơi vào nhánh này, xem docstring `CanTab.tsx`.
  const chuaCoPhanKhu = moi && !dsZone.isPending && dsZone.items.length === 0

  const loai = moi ? gia_tri.productType : can?.productType
  const caoTang = laCaoTang(loai)
  const coNha = loai !== 'dat_nen'
  // Ô không áp dụng cho loại căn thì ẩn, trừ khi bản ghi đã lưu có giá trị — không giấu dữ liệu.
  const daLuu = can ? tuCan(can) : null
  const hien = (apDung: boolean, k: keyof CanGhi) => apDung || (daLuu?.[k] ?? null) !== null
  // Căn chọn toà trong danh sách toà của dự án (khoá ngoại phía backend), lọc theo phân khu của căn.
  const khuCuaCan = moi ? gia_tri.zoneCode : can?.zoneCode
  const coToa = !dsToa.isSuccess || dsToa.data.items.length > 0
  const toaChon = (dsToa.data?.items ?? [])
    .filter((t) => !khuCuaCan || !t.zoneCode || t.zoneCode === khuCuaCan)
    .map((t) => ({ value: t.buildingCode, nhan: t.name || t.buildingCode }))
  if (gia_tri.block && !toaChon.some((t) => t.value === gia_tri.block))
    toaChon.push({ value: gia_tri.block, nhan: gia_tri.block })

  const ngayGio = (iso: string) => `${ngayThangNam(new Date(iso))} ${gioPhut(new Date(iso))}`

  return (
    <KhungSuaProvider
      value={{
        duAn: qDuAn.data ?? null,
        dangSua,
        doiSua: (v) => setEditing(v ? projectCode : null),
        ...saveStatus,
      }}
    >
      <div className={KHUNG_MAN}>
        <div
          data-testid="uform-dinh"
          className="sticky top-0 z-20 -mx-7 flex-none border-b border-border bg-bg px-7 pt-6 pb-3 max-md:-mx-4 max-md:px-4"
        >
          <DauDuAn
            code={projectCode}
            duAn={qDuAn.data}
            tab="quy-can"
            doiTab={(id) => void nav({ to: '/pform', search: { code: projectCode, tab: id } })}
            editToggle={!moi}
          />
        </div>
        <DaiDangSua />

        {/* Chỉ vùng này cuộn — form và khối ảnh cùng nằm trong nó. Hàng nút thì
          KHÔNG: nó là của cả màn, và ở `/uform` còn có khối ảnh NẰM SAU form, nên
          một hàng nút dán đáy bên trong form sẽ trôi lên đè khối ảnh đó. */}
        <div
          className="min-h-0 flex-1 space-y-4 overflow-y-auto pt-5 pb-2"
          {...panelTab(ID_TAB_DU_AN, 'quy-can')}
        >
          <div>
            <LinkVe code={projectCode} tab="quy-can" nhan="‹ Quỹ căn" />
            <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
              <h3 className="text-[20px] font-semibold text-fg">
                {can ? (
                  <>
                    Căn <span className="font-mono">{can.unitCode}</span>
                  </>
                ) : (
                  'Căn mới'
                )}
              </h3>
              {can && <SaleStatusChip value={gia_tri.saleStatus ?? can.saleStatus} />}
            </div>
            {can && (
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-than text-muted-2">
                <span>Phân khu {can.zoneName || can.zoneCode || '—'}</span>
                {can.block && (
                  <>
                    <span aria-hidden>·</span>
                    <span>Toà {can.block}</span>
                  </>
                )}
                {can.floor != null && (
                  <>
                    <span aria-hidden>·</span>
                    <span>Tầng {can.floor}</span>
                  </>
                )}
                <span aria-hidden>·</span>
                <span>Sửa lần cuối {ngayGio(can.updatedAt)}</span>
              </div>
            )}
          </div>
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_312px]">
            {chuaCoPhanKhu ? (
              <div className="rounded-xl border border-border bg-surface p-6 text-[14px]">
                <p className="font-medium">Chưa thêm căn được — dự án chưa có phân khu nào.</p>
                <p className="mt-1 text-muted">
                  Mỗi căn buộc phải thuộc một phân khu (ràng buộc ở cơ sở dữ liệu, không phải quy
                  ước).
                </p>
                <Link
                  to="/pform"
                  search={{ code: projectCode, tab: 'phan-khu' }}
                  className={`${NUT} mt-3 inline-block`}
                >
                  Sang tab Phân khu
                </Link>
              </div>
            ) : (
              <form
                id="uform-can"
                className="flex min-w-0 flex-col gap-4"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!moi) return
                  const thanGui: CanGhi = { ...gia_tri, status: trangThaiCan(gia_tri, can?.status) }
                  mTao.mutate(thanGui)
                }}
              >
                <SectionCard title="Thông tin căn">
                  {moi ? (
                    <OChon
                      ten="zoneCode"
                      khoa={khoaO}
                      nhan="Phân khu"
                      batBuoc
                      giaTri={gia_tri.zoneCode ?? ''}
                      doi={(x) => chon('zoneCode', x)}
                      muc={dsZone.items.map((z) => ({
                        value: z.zoneCode,
                        nhan: z.name || z.zoneCode,
                      }))}
                      nhanRong="— chọn phân khu —"
                      loi={loiO(o.loi, 'zoneCode')}
                    />
                  ) : (
                    <OChu
                      ten="zoneCode"
                      nhan="Phân khu"
                      khoa
                      giaTri={can?.zoneName || can?.zoneCode || ''}
                      doi={() => {}}
                    />
                  )}
                  <OChu
                    ten="unitCode"
                    nhan="Mã căn"
                    batBuoc
                    khoa={!moi}
                    giaTri={moi ? (gia_tri.unitCode ?? '') : (can?.unitCode ?? '')}
                    doi={(x) => dat('unitCode', x)}
                    xong={() => xongO('unitCode')}
                    loi={loiO(o.loi, 'unitCode')}
                    goiY={
                      moi
                        ? 'Mã căn không cần duy nhất — hai đợt nhập trùng mã là hợp lệ'
                        : undefined
                    }
                    goiYTrongO="VD: S2.03-1508"
                  />
                  {moi ? (
                    <OChon
                      ten="productType"
                      khoa={khoaO}
                      nhan="Loại sản phẩm"
                      giaTri={gia_tri.productType ?? 'chung_cu'}
                      doi={(x) => chon('productType', x)}
                      muc={PRODUCT_TYPE}
                      loi={loiO(o.loi, 'productType')}
                    />
                  ) : (
                    <OChu
                      ten="productType"
                      nhan="Loại sản phẩm"
                      khoa
                      giaTri={nhanCua(PRODUCT_TYPE, can?.productType)}
                      doi={() => {}}
                    />
                  )}
                  <OSo
                    ten="bedrooms"
                    khoa={khoaO}
                    nhan="Số phòng ngủ"
                    format={plainNumber}
                    giaTri={gia_tri.bedrooms ?? null}
                    doi={(x) => dat('bedrooms', x)}
                    xong={() => xongO('bedrooms')}
                    min={0}
                    max={50}
                    buoc={1}
                    loi={loiO(o.loi, 'bedrooms')}
                    goiYTrongO="2"
                  />
                  <OChon
                    ten="saleStatus"
                    khoa={khoaO}
                    nhan="Trạng thái bán"
                    batBuoc
                    giaTri={gia_tri.saleStatus ?? 'available'}
                    doi={(x) => chon('saleStatus', x)}
                    muc={SALE_STATUS}
                    loi={loiO(o.loi, 'saleStatus')}
                    renderValue={(x) => <SaleStatusChip value={x} />}
                  />
                  <OChon
                    ten="direction"
                    khoa={khoaO}
                    nhan="Hướng"
                    giaTri={gia_tri.direction ?? ''}
                    doi={(x) => chon('direction', x === '' ? null : x)}
                    muc={HUONG}
                    nhanRong="— chưa xác định —"
                    loi={loiO(o.loi, 'direction')}
                  />
                  {hien(caoTang && coToa, 'block') && (
                    <OChon
                      ten="block"
                      khoa={khoaO}
                      nhan="Toà / block"
                      giaTri={gia_tri.block ?? ''}
                      doi={(x) => chon('block', x === '' ? null : x)}
                      muc={toaChon}
                      nhanRong="— chưa chọn toà —"
                      goiY={
                        dsToa.isSuccess && toaChon.length === 0
                          ? 'Phân khu này chưa có toà — thêm ở tab Toà'
                          : undefined
                      }
                      loi={loiO(o.loi, 'block')}
                    />
                  )}
                  {hien(caoTang, 'floor') && (
                    <OSo
                      ten="floor"
                      khoa={khoaO}
                      nhan="Căn nằm ở tầng"
                      giaTri={gia_tri.floor ?? null}
                      doi={(x) => dat('floor', x)}
                      xong={() => xongO('floor')}
                      min={-50}
                      max={300}
                      buoc={1}
                      loi={loiO(o.loi, 'floor')}
                      goiYTrongO="15"
                    />
                  )}
                  <OSo
                    ten="numFloors"
                    khoa={khoaO}
                    nhan="Số tầng của căn"
                    giaTri={gia_tri.numFloors ?? null}
                    doi={(x) => dat('numFloors', x)}
                    xong={() => xongO('numFloors')}
                    min={0}
                    max={300}
                    buoc={1}
                    loi={loiO(o.loi, 'numFloors')}
                    goiYTrongO="1"
                  />
                </SectionCard>

                <SectionCard title="Diện tích và giá">
                  {hien(coNha, 'areaBuiltM2') && (
                    <OSo
                      ten="areaBuiltM2"
                      khoa={khoaO}
                      nhan="DT thông thuỷ"
                      unit="m²"
                      giaTri={gia_tri.areaBuiltM2 ?? null}
                      doi={(x) => dat('areaBuiltM2', x)}
                      xong={() => xongO('areaBuiltM2')}
                      min={0}
                      loi={loiO(o.loi, 'areaBuiltM2')}
                      goiYTrongO="68.5"
                    />
                  )}
                  {hien(coNha, 'areaWallM2') && (
                    <OSo
                      ten="areaWallM2"
                      khoa={khoaO}
                      nhan="DT tim tường"
                      unit="m²"
                      giaTri={gia_tri.areaWallM2 ?? null}
                      doi={(x) => dat('areaWallM2', x)}
                      xong={() => xongO('areaWallM2')}
                      min={0}
                      loi={loiO(o.loi, 'areaWallM2')}
                      goiYTrongO="72.0"
                    />
                  )}
                  {hien(!caoTang, 'areaLandM2') && (
                    <OSo
                      ten="areaLandM2"
                      khoa={khoaO}
                      nhan="DT đất"
                      unit="m²"
                      giaTri={gia_tri.areaLandM2 ?? null}
                      doi={(x) => dat('areaLandM2', x)}
                      xong={() => xongO('areaLandM2')}
                      min={0}
                      loi={loiO(o.loi, 'areaLandM2')}
                      goiYTrongO="96"
                    />
                  )}
                  {caoTang && (
                    <>
                      <OSo
                        ten="hrBalconyM2"
                        khoa={khoaO}
                        nhan="DT ban công"
                        unit="m²"
                        giaTri={gia_tri.hrBalconyM2 ?? null}
                        doi={(x) => dat('hrBalconyM2', x)}
                        xong={() => xongO('hrBalconyM2')}
                        min={0}
                        loi={loiO(o.loi, 'hrBalconyM2')}
                        goiYTrongO="4.5"
                      />
                      <OSo
                        ten="hrLoggiaM2"
                        khoa={khoaO}
                        nhan="DT logia"
                        unit="m²"
                        giaTri={gia_tri.hrLoggiaM2 ?? null}
                        doi={(x) => dat('hrLoggiaM2', x)}
                        xong={() => xongO('hrLoggiaM2')}
                        min={0}
                        loi={loiO(o.loi, 'hrLoggiaM2')}
                        goiYTrongO="2.5"
                      />
                    </>
                  )}
                  <OSo
                    ten="priceVnd"
                    khoa={khoaO}
                    nhan="Giá bán"
                    unit="đồng"
                    format={priceBillion}
                    batBuoc
                    giaTri={gia_tri.priceVnd ?? null}
                    doi={(x) => dat('priceVnd', x)}
                    xong={() => xongO('priceVnd')}
                    min={0}
                    loi={loiO(o.loi, 'priceVnd')}
                    goiYTrongO="5600000000"
                  />
                  <OSo
                    ten="pricePerM2Vnd"
                    khoa={khoaO}
                    nhan="Đơn giá"
                    unit="đ/m²"
                    format={pricePerM2}
                    giaTri={gia_tri.pricePerM2Vnd ?? null}
                    doi={(x) => dat('pricePerM2Vnd', x)}
                    xong={() => xongO('pricePerM2Vnd')}
                    min={0}
                    loi={loiO(o.loi, 'pricePerM2Vnd')}
                    goiYTrongO="81750000"
                  />
                </SectionCard>

                <SectionCard title="Đặc điểm căn">
                  <OChonNhieu
                    ten="views"
                    khoa={khoaO}
                    nhan="View"
                    giaTri={gia_tri.views ?? []}
                    doi={(x) => chon('views', x)}
                    muc={VIEW}
                    loi={loiO(o.loi, 'views')}
                  />
                  <OChon
                    ten="isCorner"
                    khoa={khoaO}
                    nhan="Căn góc"
                    giaTri={gia_tri.isCorner == null ? '' : gia_tri.isCorner ? 'co' : 'khong'}
                    doi={(x) => chon('isCorner', x === '' ? null : x === 'co')}
                    muc={CO_KHONG}
                    nhanRong="— chưa xác định —"
                    loi={loiO(o.loi, 'isCorner')}
                  />
                  <OSo
                    ten="openSides"
                    khoa={khoaO}
                    nhan="Số mặt thoáng"
                    giaTri={gia_tri.openSides ?? null}
                    doi={(x) => dat('openSides', x)}
                    xong={() => xongO('openSides')}
                    min={1}
                    max={4}
                    buoc={1}
                    loi={loiO(o.loi, 'openSides')}
                    goiYTrongO="1 – 4"
                  />
                  <OSo
                    ten="bathrooms"
                    khoa={khoaO}
                    nhan="Số WC"
                    giaTri={gia_tri.bathrooms ?? null}
                    doi={(x) => dat('bathrooms', x)}
                    xong={() => xongO('bathrooms')}
                    min={0}
                    max={50}
                    buoc={1}
                    loi={loiO(o.loi, 'bathrooms')}
                    goiYTrongO="2"
                  />
                  {hien(coNha, 'handoverCondition') && (
                    <OChon
                      ten="handoverCondition"
                      khoa={khoaO}
                      nhan="Tình trạng bàn giao"
                      giaTri={gia_tri.handoverCondition ?? ''}
                      doi={(x) => chon('handoverCondition', x === '' ? null : x)}
                      muc={BAN_GIAO_CAN}
                      nhanRong="— chưa xác định —"
                      loi={loiO(o.loi, 'handoverCondition')}
                    />
                  )}
                </SectionCard>

                {!caoTang && (
                  <SectionCard title="Kích thước lô">
                    <OSo
                      ten="lrFrontageM"
                      khoa={khoaO}
                      nhan="Mặt tiền"
                      unit="m"
                      giaTri={gia_tri.lrFrontageM ?? null}
                      doi={(x) => dat('lrFrontageM', x)}
                      xong={() => xongO('lrFrontageM')}
                      min={0}
                      loi={loiO(o.loi, 'lrFrontageM')}
                      goiYTrongO="6"
                    />
                    <OSo
                      ten="lrDepthM"
                      khoa={khoaO}
                      nhan="Chiều sâu lô"
                      unit="m"
                      giaTri={gia_tri.lrDepthM ?? null}
                      doi={(x) => dat('lrDepthM', x)}
                      xong={() => xongO('lrDepthM')}
                      min={0}
                      loi={loiO(o.loi, 'lrDepthM')}
                      goiYTrongO="18"
                    />
                    <OSo
                      ten="lrRoadWidthM"
                      khoa={khoaO}
                      nhan="Đường trước nhà"
                      unit="m"
                      giaTri={gia_tri.lrRoadWidthM ?? null}
                      doi={(x) => dat('lrRoadWidthM', x)}
                      xong={() => xongO('lrRoadWidthM')}
                      min={0}
                      loi={loiO(o.loi, 'lrRoadWidthM')}
                      goiYTrongO="13.5"
                    />
                  </SectionCard>
                )}

                {/* Hai câu «Agent đã / chưa đọc dữ liệu này» đã BỎ (người dùng chốt
              2026-08-21, cùng lượt với dòng của dự án): dấu `*` ở từng ô đã nói
              ô nào còn thiếu. Ca lưu trữ ở lại — không chỗ nào khác nói ra. */}
                {can?.status === 'archived' && (
                  <DongTrangThai mau="warn">
                    Căn này đã lưu trữ nên agent không đọc. Portal không còn đường bỏ lưu trữ.
                  </DongTrangThai>
                )}
                {o.loi != null && (
                  <DongTrangThai mau="alert">{cauLoi(o.loi, 'lưu căn')}</DongTrangThai>
                )}
              </form>
            )}

            {can && (
              <aside>
                <AnhCan projectCode={projectCode} can={can} />
              </aside>
            )}
          </div>
        </div>

        {/* Căn mới: nút Tạo căn ngoài vùng cuộn, submit form bằng thuộc tính `form=`. */}
        {!chuaCoPhanKhu && moi && (
          <div data-testid="uform-day" className={HANG_NUT_DAN}>
            <span className="mr-auto" />
            <button type="submit" form="uform-can" className={NUT_CHINH} disabled={mTao.isPending}>
              {mTao.isPending ? 'Đang tạo…' : 'Tạo căn'}
            </button>
          </div>
        )}
      </div>
    </KhungSuaProvider>
  )
}

function AnhCan({ projectCode, can }: { projectCode: string; can: Can }) {
  const qc = useQueryClient()
  const { dangSua } = useKhungSua()
  const [them, setThem] = useState<MediaKem | null>(null)
  const [danhMuc, setDanhMuc] = useState(DANH_MUC_ANH_CAN)
  const [xem, setXem] = useState<number | null>(null)

  const ds = useTrangCuon<Media>(['re', projectCode, 'media', 'unit', can.unitCode], (c) =>
    danhSachMedia(projectCode, { unit_code: can.unitCode, limit: 200, cursor: c }),
  )

  function lamMoi() {
    void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })
    void qc.invalidateQueries({ queryKey: ['re', projectCode, 'unit', can.id] })
  }

  const mThem = useMutation({
    mutationFn: async (b: MediaKem) => {
      const m = await taoMedia(projectCode, {
        unitCode: can.unitCode,
        category: danhMuc,
        contentType: b.contentType ?? 'image',
        mediaUrl: b.mediaUrl,
        caption: b.caption ?? '',
        fileName: b.fileName ?? '',
        contentHash: b.contentHash ?? '',
        status: 'published',
      })
      if (!can.imageUrl && m.contentType === 'image') {
        await suaCan(projectCode, can.id, { imageUrl: m.mediaUrl })
      }
      return m
    },
    onSuccess: () => {
      setThem(null)
      lamMoi()
    },
  })

  const mXoa = useMutation({
    mutationFn: (id: number) => xoaMedia(projectCode, id),
    onSuccess: lamMoi,
  })

  const anh = ds.items.filter((m) => m.contentType === 'image')
  const chonDanhMuc = (
    <label className="text-[13px] text-muted">
      Danh mục
      <select
        value={danhMuc}
        onChange={(e) => setDanhMuc(e.target.value)}
        className="o-chon ml-2 rounded border border-border-field px-2 py-1 text-[14px]"
      >
        {MEDIA_CATEGORY.map((m) => (
          <option key={m.value} value={m.value}>
            {m.nhan}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <SectionCard title="Ảnh căn" cols={1}>
      {ds.isError ? (
        <LoiTai viec="ảnh của căn" thuLai={() => void ds.refetch()} />
      ) : (
        <>
          {ds.items.length === 0 ? (
            !them && (
              <div className="grid aspect-[16/10] place-items-center rounded-lg bg-fill-strong text-than text-muted-2">
                Chưa có ảnh
              </div>
            )
          ) : (
            <ul className="grid grid-cols-2 gap-2.5">
              {ds.items.map((m) => (
                <li key={m.id} className="min-w-0">
                  <button
                    type="button"
                    className="block w-full cursor-zoom-in overflow-hidden rounded-lg bg-fill-strong"
                    aria-label={`Xem ảnh lớn — ${m.caption || can.unitCode}`}
                    onClick={() => setXem(anh.findIndex((x) => x.id === m.id))}
                  >
                    <img
                      src={nguonAnh(m.thumbUrl ?? m.mediaUrl)}
                      alt={m.caption || can.unitCode}
                      className="block aspect-[4/3] w-full object-cover"
                    />
                  </button>
                  <p className="mt-1 truncate text-[12px] text-muted">
                    {m.mediaUrl === can.imageUrl ? 'Ảnh đại diện' : m.caption || '—'}
                  </p>
                  {dangSua && (
                    <button
                      type="button"
                      className="text-[12px] font-medium text-badge-alert-fg hover:underline"
                      disabled={mXoa.isPending}
                      onClick={() => mXoa.mutate(m.id)}
                    >
                      Xoá
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {dangSua &&
            (them ? (
              <div className="space-y-2">
                {chonDanhMuc}
                <OMedia nhan="Ảnh mới" giaTri={them} doi={setThem} />
                <button
                  type="button"
                  className={NUT_CHINH}
                  disabled={mThem.isPending || !them.mediaUrl}
                  onClick={() => mThem.mutate(them)}
                >
                  {mThem.isPending ? 'Đang lưu…' : 'Thêm ảnh'}
                </button>
                <button type="button" className={`${NUT} ml-2`} onClick={() => setThem(null)}>
                  Huỷ
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                {chonDanhMuc}
                <button
                  type="button"
                  className={NUT}
                  onClick={() => setThem({ mediaUrl: '', caption: '' })}
                >
                  Thêm ảnh
                </button>
              </div>
            ))}

          {mThem.error && (
            <p className="text-[13px] text-badge-alert-fg" role="alert">
              {cauLoi(mThem.error, 'thêm ảnh')} Tệp đã nằm trong kho — kiểm danh sách ảnh ở trên
              trước khi thử lại để không thêm trùng.
            </p>
          )}
          {mXoa.error && (
            <p className="text-[13px] text-badge-alert-fg" role="alert">
              {cauLoi(mXoa.error, 'xoá ảnh')}
            </p>
          )}
        </>
      )}
      {xem !== null && xem >= 0 && (
        <AnhLon
          anh={anh.map((m) => ({ src: nguonAnh(m.mediaUrl), caption: m.caption || '' }))}
          batDau={xem}
          onDong={() => setXem(null)}
        />
      )}
    </SectionCard>
  )
}
