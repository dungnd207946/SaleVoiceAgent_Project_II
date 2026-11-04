/**
 * Tab Căn — quỹ căn của một dự án: danh sách + 3 bộ lọc, link sang `/uform`.
 *
 * KHÔNG CÓ FORM Ở ĐÂY, khác tab Phân khu. Căn có 15 ô và một quỹ căn có hàng
 * nghìn dòng — form inline sẽ đẩy bảng xuống dưới màn hình mỗi lần sửa một căn.
 * Nên căn có màn riêng (`/uform`), và tab này là chỗ tìm ra căn cần sửa.
 *
 * BỘ LỌC VÀ SẮP XẾP ĐI QUA SERVER (`zone_code`/`product_type`/`sale_status`/
 * `direction`/`unit_code`/`sort`/`desc` là tham số thật của
 * `GET /projects/{code}/units`), không xử lý trên mảng đã tải: một quỹ căn 1.240
 * dòng thì lọc client chỉ lọc trong 50 dòng của trang đầu, và người dùng kết luận
 * "không còn căn 3PN nào" từ một câu trả lời sai. Sắp xếp cũng vậy — "căn đắt
 * nhất" hoá ra là căn đắt nhất TRONG TRANG ĐANG XEM.
 *
 * HAI Ô «loại sản phẩm» VÀ «hướng» LẤY MỤC TỪ `/units/facets`, không từ enum:
 * enum có 12 loại và 8 hướng, còn một dự án chung cư thường chỉ có 2–3 loại —
 * dropdown liệt kê cả 12 bắt người dùng đọc qua chín mục rồi chọn vào một mục
 * chắc chắn ra bảng rỗng. Facet chưa về (hoặc lỗi) thì rơi về enum đầy đủ: thà
 * thừa mục còn hơn một ô lọc trống rỗng không giải thích được.
 *
 * ⚠ PHÂN KHU KHÔNG CÒN BẮT BUỘC (từ migration `0902_noi_zone_code_nullable`,
 * 2026-08-15) — `units.zone_code` đã nullable, `CanOut.zoneCode` là `str | null`.
 * Dữ liệu ingest từ đối tác thường không có khái niệm phân khu (dự án 0 hàng
 * `zones`, mọi unit `zone_code NULL`) — đây KHÔNG phải dữ liệu bẩn. Tab từng
 * chặn cứng theo `dsZone.items.length === 0` (tiền đề "phân khu bắt buộc" đã
 * chết) khiến quỹ căn hợp lệ không bao giờ hiện được dù API `/units` trả đủ.
 * Đã bỏ gate đó — bảng render bình thường, "Mọi phân khu" trong bộ lọc chỉ đơn
 * giản không có mục con nào khi dự án chưa có phân khu.
 *
 * Diện mạo bảng ở `Bang.tsx` — cùng nguồn với ba bảng còn lại của M4.
 */
import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  danhSachCan,
  danhSachPhanKhu,
  danhSachToa,
  facetCan,
  xoaCan,
  type Can,
  type PhanKhu,
  type SapXepCan,
  type TrangThai,
} from '../api'
import { HUONG, PRODUCT_TYPE, SALE_STATUS, TRANG_THAI, nhanCua } from '../enums'
import { so } from '@/lib/dinhDang'
import { useKhungSua } from '../khungSua'
import { SaleStatusChip } from './SaleChip'
import { nhanThieu, thieuTruongCan } from '../completeness'
import { ChipTrangThai } from './ChipTrangThai'
import { cauLoi } from '../thongDiep'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { useTrangCuon } from './useTrangCuon'
import { useTrangSo } from './useTrangSo'
import { useXacNhanXoa } from '../useXacNhanXoa'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import {
  HANG_NUT,
  Bang,
  CAO_MAN,
  TAB_KHUNG,
  DauBang,
  Hang,
  NUT_CHINH,
  NUT_PHU,
  O_LOC,
  TD,
  TD_PHU,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
  type SapXep,
} from '@/components/ui/Bang'

const COT: readonly Cot[] = [
  { nhan: 'Mã căn' },
  { nhan: 'Toà' },
  { nhan: 'Loại' },
  { nhan: 'PN', phai: true, sap: 'bedrooms' },
  { nhan: 'DT thông thuỷ', phai: true, sap: 'area_built_m2' },
  { nhan: 'Hướng' },
  { nhan: 'Giá', phai: true, sap: 'price_vnd' },
  { nhan: 'Trạng thái bán' },
  { nhan: 'Phát hành' },
  { nhan: '', phai: true },
]

const LINK_XOA = 'text-than font-medium text-badge-alert-fg hover:underline'

function tien(v: number | null): string {
  if (v === null) return '—'
  if (v >= 1_000_000_000)
    return `${(v / 1_000_000_000).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} tỷ`
  if (v >= 1_000_000)
    return `${(v / 1_000_000).toLocaleString('vi-VN', { maximumFractionDigits: 0 })} tr`
  return v.toLocaleString('vi-VN')
}

export function CanTab({ projectCode }: { projectCode: string }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { dangSua: editing } = useKhungSua()
  const [zone, setZone] = useState('')
  const [loai, setLoai] = useState('')
  const [banHang, setBanHang] = useState('')
  const [huong, setHuong] = useState('')
  const [ma, setMa] = useState('')
  const [trangThai, setTrangThai] = useState('')
  const [sap, setSap] = useState<SapXep | null>(null)
  const {
    sap: sapXoa,
    hoi: hoiXoa,
    boQua,
    daXoa,
    huyRef,
    dich,
    idTieuDe,
    idMoTa,
  } = useXacNhanXoa<Can>()
  const coLoc = Boolean(zone || loai || banHang || huong || ma || trangThai)

  const dsZone = useTrangCuon<PhanKhu>(['re', projectCode, 'zones'], (c) =>
    danhSachPhanKhu(projectCode, { cursor: c }),
  )
  const dsToa = useQuery({
    queryKey: ['re', projectCode, 'buildings'],
    queryFn: () => danhSachToa(projectCode),
  })
  // Dự án chưa có toà nào (thường là thấp tầng) thì bỏ cột Toà; tải toà lỗi thì giữ cột.
  const coToa = !dsToa.isSuccess || dsToa.data.items.length > 0
  const cot = coToa ? COT : COT.filter((c) => c.nhan !== 'Toà')
  const facet = useQuery({
    queryKey: ['re', projectCode, 'unit-facets'],
    queryFn: () => facetCan(projectCode),
  })
  // Dòng tóm tắt: `total` của danh sách lọc theo trạng thái bán, mỗi lượt một hàng.
  const dem = useQuery({
    queryKey: ['re', projectCode, 'units', 'dem'],
    queryFn: async () => {
      const [tong, con, ban, coc] = await Promise.all(
        ['', 'available', 'sold', 'booked'].map((x) =>
          danhSachCan(projectCode, { sale_status: x || undefined, limit: 1 }),
        ),
      )
      return { tong: tong!.total, con: con!.total, ban: ban!.total, coc: coc!.total }
    },
  })
  const ds = useTrangSo<Can>(
    ['re', projectCode, 'units', { zone, loai, banHang, huong, ma, trangThai, sap }],
    ({ limit, offset }) =>
      danhSachCan(projectCode, {
        zone_code: zone,
        product_type: loai,
        sale_status: banHang,
        direction: huong,
        unit_code: ma,
        status: trangThai as TrangThai | '',
        sort: (sap?.cot as SapXepCan | undefined) ?? undefined,
        desc: sap?.giam ? 'true' : undefined,
        limit,
        offset,
      }),
  )

  const mucLoai = facet.data
    ? PRODUCT_TYPE.filter((m) => facet.data.productType.includes(m.value))
    : PRODUCT_TYPE
  const mucHuong = facet.data ? HUONG.filter((m) => facet.data.direction.includes(m.value)) : HUONG

  function doiLoc(setter: (v: string) => void, v: string) {
    setter(v)
    ds.doiTrang(1)
  }

  function doiSap(khoa: string) {
    setSap((s) =>
      s?.cot !== khoa ? { cot: khoa, giam: false } : s.giam ? null : { ...s, giam: true },
    )
    ds.doiTrang(1)
  }

  const mXoa = useMutation({
    mutationFn: (id: number) => xoaCan(projectCode, id),
    onSuccess: () => {
      daXoa()
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'units'] })
    },
  })

  return (
    <div className={`${TAB_KHUNG} flex flex-col gap-3`}>
      <TheBang cao={CAO_MAN}>
        <ThanhCong>
          {dem.data && (
            <p className="flex flex-none flex-wrap gap-x-4 text-than text-nav max-md:basis-full">
              <span>
                <b className="font-mono font-medium text-fg">{so(dem.data.tong)}</b> căn
              </span>
              <span>
                <b className="font-mono font-medium text-fg">{so(dem.data.con)}</b> còn hàng
              </span>
              <span>
                <b className="font-mono font-medium text-fg">{so(dem.data.ban)}</b> đã bán
              </span>
              {dem.data.coc > 0 && (
                <span>
                  <b className="font-mono font-medium text-fg">{so(dem.data.coc)}</b> đã cọc
                </span>
              )}
            </p>
          )}
          {/* Điện thoại: ô tìm trọn dòng, năm ô lọc xếp HAI cột — bản cũ mỗi ô một dòng nên
              thanh lọc cao ~500px, bảng bị đẩy xuống dưới màn. */}
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5 max-md:grid max-md:basis-full max-md:grid-cols-2 max-md:gap-2 max-md:[&>*]:min-w-0 max-md:[&>*]:max-w-none">
            <input
              type="search"
              aria-label="Tìm theo mã căn"
              placeholder="Tìm mã căn…"
              value={ma}
              onChange={(e) => doiLoc(setMa, e.target.value)}
              className={`${O_LOC} min-w-[150px] max-w-[220px] flex-1 max-md:col-span-2`}
            />
            <select
              aria-label="Lọc theo phân khu"
              value={zone}
              onChange={(e) => doiLoc(setZone, e.target.value)}
              className={`${O_LOC} o-chon text-muted`}
            >
              <option value="">Mọi phân khu</option>
              {dsZone.items.map((z) => (
                <option key={z.id} value={z.zoneCode}>
                  {z.name || z.zoneCode}
                </option>
              ))}
            </select>
            <select
              aria-label="Lọc theo loại sản phẩm"
              value={loai}
              onChange={(e) => doiLoc(setLoai, e.target.value)}
              className={`${O_LOC} o-chon text-muted`}
            >
              <option value="">Mọi loại sản phẩm</option>
              {mucLoai.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.nhan}
                </option>
              ))}
            </select>
            {mucHuong.length > 0 && (
              <select
                aria-label="Lọc theo hướng"
                value={huong}
                onChange={(e) => doiLoc(setHuong, e.target.value)}
                className={`${O_LOC} o-chon text-muted`}
              >
                <option value="">Mọi hướng</option>
                {mucHuong.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.nhan}
                  </option>
                ))}
              </select>
            )}
            <select
              aria-label="Lọc theo trạng thái phát hành"
              value={trangThai}
              onChange={(e) => doiLoc(setTrangThai, e.target.value)}
              className={`${O_LOC} o-chon text-muted`}
            >
              <option value="">Mọi trạng thái</option>
              {TRANG_THAI.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.nhan}
                </option>
              ))}
            </select>
            <select
              aria-label="Lọc theo trạng thái bán"
              value={banHang}
              onChange={(e) => doiLoc(setBanHang, e.target.value)}
              className={`${O_LOC} o-chon text-muted`}
            >
              <option value="">Mọi trạng thái bán</option>
              {SALE_STATUS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.nhan}
                </option>
              ))}
            </select>
          </div>
          {editing && (
            <Link
              ref={dich}
              to="/uform"
              search={{ code: projectCode }}
              className={`${NUT_CHINH} flex-none`}
            >
              Thêm căn
            </Link>
          )}
        </ThanhCong>

        <VungCuon>
          {ds.isPending || dsToa.isPending ? (
            <p className="p-4 text-than text-muted">Đang tải…</p>
          ) : ds.error ? (
            <div className="p-4">
              <LoiTai viec="quỹ căn" thuLai={() => void ds.refetch()} />
            </div>
          ) : ds.items.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe={
                  ds.total > 0
                    ? 'Trang này không có căn nào.'
                    : coLoc
                      ? 'Không có căn nào khớp bộ lọc.'
                      : 'Chưa có căn nào.'
                }
                huongDan={
                  ds.total > 0
                    ? 'Dữ liệu vẫn còn — quay lại một trang trước đó.'
                    : coLoc
                      ? 'Bỏ một bộ lọc để xem rộng hơn.'
                      : 'Nhập quỹ căn để agent trả lời được câu hỏi về giá và diện tích.'
                }
              />
            </div>
          ) : (
            <Bang>
              <DauBang cot={cot} sapXep={sap} doiSap={doiSap} />
              <tbody>
                {ds.items.map((c) => {
                  const thieu = thieuTruongCan(c)
                  return (
                    <Hang
                      key={c.id}
                      mo={() =>
                        void nav({ to: '/uform', search: { code: projectCode, unit: c.id } })
                      }
                    >
                      <td className={TD}>
                        <Link
                          to="/uform"
                          search={{ code: projectCode, unit: c.id }}
                          className="font-mono font-semibold whitespace-nowrap text-fg hover:text-ac"
                        >
                          {c.unitCode}
                        </Link>
                        {thieu.length > 0 && (
                          <p className="mt-0.5 text-[12px] text-badge-warn-fg">
                            ⚠ Thiếu: {nhanThieu(thieu)}
                          </p>
                        )}
                      </td>
                      {coToa && <td className={TD_PHU}>{c.block || '—'}</td>}
                      <td className={TD_PHU}>{nhanCua(PRODUCT_TYPE, c.productType)}</td>
                      <td className={`${TD_PHU} text-right font-mono`}>{c.bedrooms ?? '—'}</td>
                      <td className={`${TD_PHU} text-right`}>
                        {c.areaBuiltM2 == null ? (
                          '—'
                        ) : (
                          <>
                            <span className="font-mono">{so(c.areaBuiltM2)}</span> m²
                          </>
                        )}
                      </td>
                      <td className={TD_PHU}>{nhanCua(HUONG, c.direction) || '—'}</td>
                      <td className={`${TD_PHU} text-right font-mono`}>{tien(c.priceVnd)}</td>
                      <td className={TD}>
                        <SaleStatusChip value={c.saleStatus} />
                      </td>
                      <td className={TD}>
                        {c.status !== 'published' && <ChipTrangThai status={c.status} />}
                      </td>
                      <td className={`${TD} whitespace-nowrap text-right`}>
                        {editing ? (
                          <button type="button" className={LINK_XOA} onClick={() => hoiXoa(c)}>
                            Xoá
                          </button>
                        ) : (
                          <span aria-hidden className="text-muted-3">
                            ›
                          </span>
                        )}
                      </td>
                    </Hang>
                  )
                })}
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

      {sapXoa && (
        <div
          className="rounded-xl border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]"
          role="alertdialog"
          aria-labelledby={idTieuDe}
          aria-describedby={idMoTa}
        >
          <p id={idTieuDe} className="font-semibold">
            Xoá căn {sapXoa.unitCode} (phân khu {sapXoa.zoneName || sapXoa.zoneCode || '—'})?
          </p>
          <p id={idMoTa} className="text-[13px] text-muted">
            Không hoàn tác được.
          </p>
          {mXoa.error && (
            <p role="alert" className="mt-1 text-[13px] text-badge-alert-fg">
              {cauLoi(mXoa.error, 'xoá căn')}
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
