/**
 * Màn `/projects` — Kiến thức của lĩnh vực Bất động sản. Một bảng dự án, cộng
 * một màn con «Nạp qua API» mở bằng `?nap=1` (`NguonDuLieuTab`).
 *
 * ── TAB «TÀI LIỆU GỬI KHÁCH» (`__ALL__`) ĐÃ BỎ (2026-08-08) ─────────────────
 * Người dùng chốt: **mọi tài liệu phải gắn với một dự án**. Kho `__ALL__` được
 * định nghĩa bằng đúng điều ngược lại — docstring cũ ở đây viết «nó KHÔNG thuộc
 * dự án nào» — nên nó là thứ đầu tiên rơi theo luật đó. Tài liệu của TỪNG dự án
 * vẫn nguyên, ở tab «Tài liệu» trong `/pform`.
 *
 * Bỏ tab thứ hai kéo theo bỏ cả HÀNG TAB: một `NhomTab` còn đúng một mục là một
 * điều khiển không chuyển được đi đâu. ⚠️ 2026-08-14 hàng tab QUAY LẠI một lần
 * cho «Nguồn dữ liệu» rồi BỊ BỎ NGAY trong ngày: hai tab là hai thứ NGANG HÀNG,
 * mà bảng dự án là bản thân kiến thức (hiện MỌI dự án, bất kể vào bằng tay hay
 * qua API) còn cổng nạp là đường ống, không chứa một mẩu kiến thức nào. Nó là
 * một TUỲ CHỌN của màn này ⇒ một nút cạnh «Thêm dự án», không phải nửa màn.
 *
 * ⚠️ ENDPOINT VÀ DỮ LIỆU `__ALL__` VẪN CÒN Ở BACKEND. Hàng nào đã tạo trước đây
 * thì agent vẫn đọc được bằng `get_document`, nhưng từ portal KHÔNG còn đường
 * xem/sửa/xoá chúng. Dọn dữ liệu đó là việc của backend; đừng dựng lại một màn
 * ẩn ở FE để với tới nó.
 *
 * BADGE THIẾU DỮ LIỆU hiện ngay trong bảng. Đây là chỗ duy nhất thấy được tình
 * trạng của CẢ danh mục mà không phải mở từng form — và nó là câu trả lời cho
 * "dự án nào chưa sẵn sàng cho agent". Tính bằng `completeness.ts`, cùng luật
 * `02a §7` mà backend cưỡng chế lúc publish.
 *
 * Diện mạo (thẻ · dải công cụ · `thead` dính · hàng bấm được · tab pill) ở
 * `Bang.tsx` — một nguồn cho cả bốn bảng của M4.
 *
 * KHÔNG CÓ `<h1>` Ở ĐÂY. `components/shell/Topbar.tsx` đã render
 * `<h1>Bất động sản</h1>` lấy từ nav label — thêm một h1 cùng chữ ở đây là hai
 * tiêu đề cấp một cho một màn, và trình đọc màn hình mất mốc để nhảy vào nội
 * dung (đúng thứ docstring của Topbar dặn).
 */
import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useConflictCounts, WorkspaceConflictButton } from '@/features/conflicts/contracts'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { SENTINEL, danhSachDuAn, xoaDuAn, type DuAn } from '../api'
import { KHU_VUC, LOAI_HINH, SALE_PHASE, nhanCua } from '../enums'
import { nhanThieu, thieuTruongDuAn } from '../completeness'
import { cauLoi } from '../thongDiep'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { XacNhan } from '@/components/ui/XacNhan'
import { useTrangSo } from './useTrangSo'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { NguonDuLieuTab } from './NguonDuLieuTab'
import { useKhoManHinh } from '@/lib/khoManHinh'
import {
  DUONG_VE,
  Bang,
  CAO_MAN,
  DauBang,
  Hang,
  NUT_CHINH,
  NUT_PHU,
  NutIcon,
  O_LOC,
  TD,
  TD_GON,
  TD_PHU,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'

const COT: readonly Cot[] = [
  { nhan: 'Dự án' },
  { nhan: 'Loại hình' },
  { nhan: 'Vị trí' },
  { nhan: 'Kinh doanh' },
  { nhan: '', phai: true },
]

export function DuAnList({ nap }: { readonly nap: boolean }) {
  return (
    <div className="flex h-[calc(100vh-72px)] flex-col px-7 py-6 max-lg:h-[calc(100dvh-72px)] max-md:h-[calc(100dvh-56px)] max-md:px-4 max-md:py-4">
      {nap ? <ManNapApi /> : <BangDuAn />}
    </div>
  )
}

function ManNapApi() {
  return (
    <>
      <Link to="/projects" search={{}} className={`${DUONG_VE} mb-3 flex-none`}>
        ‹ Kiến thức
      </Link>
      <NguonDuLieuTab />
    </>
  )
}

function BangDuAn() {
  const dienThoai = useKhoManHinh() === 'mobile'
  const nav = useNavigate()
  const qc = useQueryClient()
  const [tim, setTim] = useState('')
  const [khuVuc, setKhuVuc] = useState('')
  const [sapXoa, setSapXoa] = useState<DuAn | null>(null)
  const conflicts = useConflictCounts()

  const ds = useTrangSo<DuAn>(['re', 'projects', { tim, khuVuc }], ({ limit, offset }) =>
    danhSachDuAn({ search: tim, region: khuVuc, limit, offset }),
  )

  function doiTim(v: string) {
    setTim(v)
    ds.doiTrang(1)
  }
  function doiKhuVuc(v: string) {
    setKhuVuc(v)
    ds.doiTrang(1)
  }

  const mXoa = useMutation({
    mutationFn: xoaDuAn,
    onSuccess: () => {
      setSapXoa(null)
      void qc.invalidateQueries({ queryKey: ['re', 'projects'] })
    },
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TheBang cao={CAO_MAN}>
        <ThanhCong>
          {/* Mobile: ô tìm một hàng · ô khu vực một hàng · hai nút chia đôi hàng
              cuối (ThanhCong xuống dòng ở `max-md`). */}
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5 max-md:basis-full">
            <input
              type="search"
              aria-label="Tìm theo mã hoặc tên dự án"
              placeholder="Tìm theo tên hoặc mã…"
              value={tim}
              onChange={(e) => doiTim(e.target.value)}
              className={`${O_LOC} min-w-[190px] max-w-[300px] flex-1 max-md:min-w-0 max-md:max-w-none max-md:basis-full`}
            />
            <input
              type="text"
              aria-label="Lọc theo khu vực"
              placeholder="Lọc khu vực…"
              value={khuVuc}
              onChange={(e) => doiKhuVuc(e.target.value)}
              className={`${O_LOC} w-[130px] text-muted max-md:w-auto max-md:flex-1`}
            />
          </div>
          <WorkspaceConflictButton />
          <Link
            to="/projects"
            search={{ nap: true }}
            className={`${NUT_PHU} flex-none max-md:flex-1`}
          >
            Nạp qua API
          </Link>
          <Link to="/pform" className={`${NUT_CHINH} flex-none max-md:flex-1`}>
            Thêm dự án
          </Link>
        </ThanhCong>

        <VungCuon>
          {ds.isPending ? (
            <p className="p-4 text-than text-muted">Đang tải…</p>
          ) : ds.error ? (
            <div className="p-4">
              <LoiTai viec="danh sách dự án" thuLai={() => void ds.refetch()} />
            </div>
          ) : ds.items.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe={ds.total > 0 ? 'Trang này không có dự án nào.' : 'Chưa có dự án nào.'}
                huongDan={
                  ds.total > 0
                    ? 'Dữ liệu vẫn còn — quay lại một trang trước đó.'
                    : 'Tạo dự án đầu tiên để agent có gì trả lời khi khách hỏi về sản phẩm.'
                }
              />
            </div>
          ) : (
            <Bang gon={dienThoai}>
              <DauBang cot={dienThoai ? [COT[0]!, COT[4]!] : COT} />
              <tbody>
                {ds.items.map((d) => {
                  const thieu = thieuTruongDuAn(d)
                  return (
                    <Hang
                      key={d.id}
                      mo={() => void nav({ to: '/pform', search: { code: d.projectCode } })}
                    >
                      <td className={`${TD} ${TD_GON}`}>
                        <Link
                          to="/pform"
                          search={{ code: d.projectCode }}
                          className="font-semibold uppercase text-fg hover:text-ac max-md:block max-md:truncate"
                        >
                          {d.name || '(chưa có tên)'}
                        </Link>
                        <div className="mt-0.5 flex items-center gap-2 text-[12px]">
                          <span className="font-mono text-muted-2">{d.projectCode}</span>
                          {thieu.length > 0 && (
                            <span className="whitespace-nowrap text-badge-warn-fg">
                              ⚠ Thiếu: {nhanThieu(thieu)}
                            </span>
                          )}
                          {conflicts.has(d.projectCode) && (
                            <span className="whitespace-nowrap text-badge-warn-fg">
                              {conflicts.get(d.projectCode)} mâu thuẫn
                            </span>
                          )}
                        </div>
                        {/* Điện thoại: ba cột giữa thành MỘT dòng phụ — bảng gọn, không cuộn ngang. */}
                        {dienThoai && (
                          <p className="mt-1 truncate text-phu text-nav">
                            {[
                              d.category.map((c) => nhanCua(LOAI_HINH, c)).join(', '),
                              nhanCua(KHU_VUC, d.region),
                              nhanCua(SALE_PHASE, d.salePhase),
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </p>
                        )}
                      </td>
                      {dienThoai ? null : (
                        <>
                          <td className={TD_PHU}>
                            {d.category.map((c) => nhanCua(LOAI_HINH, c)).join(', ')}
                          </td>
                          <td className={TD_PHU}>{nhanCua(KHU_VUC, d.region)}</td>
                          <td className={TD_PHU}>{nhanCua(SALE_PHASE, d.salePhase)}</td>
                        </>
                      )}
                      <td className={`${TD} whitespace-nowrap text-right`}>
                        {d.projectCode !== SENTINEL && (
                          <NutIcon icon="trash" nhan="Xoá" phaHuy onClick={() => setSapXoa(d)} />
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

      {/* Popup, không phải khối dưới danh sách: khối cũ nằm ngoài tầm mắt khi bảng dài. */}
      {sapXoa && (
        <XacNhan
          tieuDe={`Xoá dự án ${sapXoa.projectCode}?`}
          nutChinh={mXoa.isPending ? 'Đang xoá…' : 'Xoá'}
          phaHuy
          role="alertdialog"
          dangGui={mXoa.isPending}
          loi={mXoa.error ? cauLoi(mXoa.error, 'xoá dự án') : null}
          onHuy={() => setSapXoa(null)}
          onDongY={() => mXoa.mutate(sapXoa.projectCode)}
        >
          <p>
            Mọi phân khu, căn, tài liệu và media của dự án này bị xoá cùng. Không có thùng rác —
            thao tác này không hoàn tác được.
          </p>
        </XacNhan>
      )}
    </div>
  )
}
