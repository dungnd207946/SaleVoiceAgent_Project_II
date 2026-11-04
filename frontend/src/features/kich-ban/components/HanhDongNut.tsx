/**
 * Hàng thao tác của MỘT tình huống lớp sale (spec §4b, §4e): công tắc «Đang dùng», Xoá (không có với tình huống
 * khoá xoá — agent chỉ bắt buộc chúng CÓ MẶT, tắt được), Xem / Dùng bản mẫu khi khác mẫu. Mọi lần ghi qua `useGhi`.
 */
import { useState } from 'react'
import { NUT_PHU } from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import type { DuLieuKichBan, GioiHan, NutKichBan, NutVao } from '../api'
import { boSale, chanXoa, heThong, thayNut, veKhuon, xoaNut, type LoaiMau } from '../khuon'
import { cauLoi, useGhi } from '../useGhi'
import { SoHaiBan } from './SoHaiBan'
import { XacNhan } from '@/components/ui/XacNhan'

interface Props {
  n: NutKichBan
  data: DuLieuKichBan
  nutMau: NutKichBan | undefined
  loai: LoaiMau | undefined
  gioiHan: GioiHan | undefined
  ghiDuoc: boolean
  /** Có quyền ghi nhưng thiếu `gioiHan` ⇒ nút hiện ở dạng khoá kèm lý do này. */
  lyDoKhoa: string | null
  onChon: (id: string) => void
  onDaXoa: () => void
  onSua: () => void
}

export function HanhDongNut({
  n,
  data,
  nutMau,
  loai,
  gioiHan,
  ghiDuoc,
  lyDoKhoa,
  onChon,
  onDaXoa,
  onSua,
}: Props) {
  const { ghi, dangGhi, ten } = useGhi(data, gioiHan)
  const [hoi, setHoi] = useState<'xoa' | 'mau' | null>(null)
  const [xemMau, setXemMau] = useState(false)
  const [loi, setLoi] = useState<string[]>([])
  const coGhi = ghiDuoc || lyDoKhoa !== null
  const khoa = !ghiDuoc || dangGhi
  const tenNay = ten[n.id] ?? n.id

  async function chay(bienDoi: (bo: NutVao[]) => NutVao[], sau?: () => void) {
    setLoi([])
    const kq = await ghi(bienDoi)
    setHoi(null)
    if (kq.ok) return sau?.()
    setLoi(kq.loiBo.length ? kq.loiBo : [cauLoi(kq.loi)])
  }

  const chan = hoi === 'xoa' ? chanXoa(n.id, boSale(data.nodes), heThong(data.nodes), ten) : []
  // Hộp xác nhận đứng NGOÀI khối `space-y-2` (cùng lý do `DaiTrangThai`): không làm hàng nút nhảy khi hộp mở.
  return (
    <>
      <div className="space-y-2">
        {coGhi ? (
          <div className="flex flex-wrap items-center gap-2" title={lyDoKhoa ?? undefined}>
            <button
              type="button"
              disabled={khoa}
              onClick={onSua}
              className={`${NUT_PHU} cursor-pointer disabled:opacity-50`}
            >
              Sửa
            </button>
            <span className="flex items-center gap-2 text-than">
              Đang dùng
              <CongTac
                bat={n.bat}
                nhan="Đang dùng"
                dangGui={khoa}
                doi={(b) => void chay((bo) => thayNut(bo, { ...veKhuon(n), bat: b }))}
              />
            </span>
            {n.khoaXoa ? null : (
              <button
                type="button"
                disabled={khoa}
                onClick={() => setHoi('xoa')}
                className={`${NUT_PHU} ml-auto cursor-pointer disabled:opacity-50`}
              >
                Xoá
              </button>
            )}
          </div>
        ) : null}
        {loai === 'khac' && nutMau ? (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              aria-expanded={xemMau}
              onClick={() => setXemMau((v) => !v)}
              className={`${NUT_PHU} cursor-pointer`}
            >
              Xem bản mẫu
            </button>
            {ghiDuoc ? (
              <button
                type="button"
                disabled={dangGhi}
                onClick={() => setHoi('mau')}
                className={`${NUT_PHU} cursor-pointer disabled:opacity-50`}
              >
                Dùng bản mẫu
              </button>
            ) : null}
          </div>
        ) : null}
        {xemMau && nutMau ? <SoHaiBan cua={n} mau={nutMau} ten={ten} /> : null}
        {loi.length ? (
          <ul role="alert" className="space-y-1 text-phu text-badge-alert-fg">
            {loi.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {hoi === 'xoa' && chan.length ? (
        <XacNhan tieuDe={`Chưa xoá được «${tenNay}»`} nutPhu="Đóng" onHuy={() => setHoi(null)}>
          <ul className="space-y-1">
            {chan.map((c) => (
              <li key={c.cau}>
                <button
                  type="button"
                  onClick={() => {
                    setHoi(null)
                    onChon(c.id)
                  }}
                  className="cursor-pointer text-left text-ac"
                >
                  {c.cau}
                </button>
              </li>
            ))}
          </ul>
        </XacNhan>
      ) : null}
      {hoi === 'xoa' && !chan.length ? (
        <XacNhan
          tieuDe={`Xoá «${tenNay}»?`}
          nutChinh="Xoá"
          phaHuy
          dangGui={dangGhi}
          onHuy={() => setHoi(null)}
          onDongY={() => void chay((bo) => xoaNut(bo, n.id), onDaXoa)}
        >
          <p>Lượt cũ của nó chuyển vào mục «tình huống đã bỏ».</p>
        </XacNhan>
      ) : null}
      {hoi === 'mau' && nutMau ? (
        <XacNhan
          tieuDe={`Thay «${tenNay}» bằng bản mẫu?`}
          nutChinh="Dùng bản mẫu"
          phaHuy
          dangGui={dangGhi}
          onHuy={() => setHoi(null)}
          onDongY={() =>
            void chay(
              (bo) => thayNut(bo, veKhuon(nutMau)),
              () => setXemMau(false),
            )
          }
        >
          <p>Chữ hiện tại sẽ mất.</p>
        </XacNhan>
      ) : null}
    </>
  )
}
