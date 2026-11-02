/** Nội dung khung chi tiết (desktop: khung trượt; điện thoại: bottom sheet) — MỘT chỗ dựng cho cả hai. */
import { useEffect, useRef } from 'react'
import type { DuLieuKichBan, Ngay, NutKichBan, NutVao, TemplateKichBan } from '../api'
import { nutTrong, veKhuon, type LoaiMau, type SoMau } from '../khuon'
import { tenNut } from '../logic'
import { useGhi } from '../useGhi'
import { BangChiTiet } from './BangChiTiet'
import { FormNut } from './FormNut'
import { HanhDongNut } from './HanhDongNut'
import { CHIP } from './lop'

const NHAN_MAU: Record<LoaiMau, string> = {
  giong: 'Giống mẫu',
  khac: 'Khác mẫu',
  rieng: 'Riêng của workspace',
}

function ChipLop({ n, loai }: { n: NutKichBan; loai: LoaiMau | undefined }) {
  if (n.lop === 'he_thong') return <span className={CHIP}>Hệ thống NobleX — chỉ xem</span>
  return loai ? <span className={CHIP}>{NHAN_MAU[loai]}</span> : null
}

export interface KhungChiTietProps {
  data: DuLieuKichBan
  mau: TemplateKichBan | undefined
  so: SoMau | null
  nut: string
  che: 'xem' | 'sua' | 'them'
  ngay: Ngay
  nguon: string | undefined
  ghiDuoc: boolean
  lyDoKhoa: string | null
  onChon: (id: string) => void
  onDong: () => void
  onSua: () => void
  onXong: (id: string) => void
  onHuy: () => void
  onDoi: (dirty: boolean) => void
  /** Lần mở khung (KichBanScreen) — form thêm dựng lại khi số này đổi. */
  lan?: number | undefined
  khung?: string | undefined
}

/** Topbar dính của portal (`h-[72px]`) — đầu khung nằm dưới nó là khuất. */
const TOPBAR = 72

export function KhungChiTiet({
  data,
  mau,
  so,
  nut,
  che,
  ngay,
  nguon,
  ghiDuoc,
  lyDoKhoa,
  onChon,
  onDong,
  onSua,
  onXong,
  onHuy,
  onDoi,
  lan = 0,
  khung,
}: KhungChiTietProps) {
  const ghi = useGhi(data, mau?.gioiHan)
  // Lưu (hoặc Huỷ) một form dài xong, vùng cuộn vẫn ở chỗ nút Lưu — đầu khung, giờ là bản xem, nằm khuất trên
  // (dưới topbar, hoặc trên mép bottom sheet). Kéo về đầu khung, chỉ khi nó thật sự khuất.
  const goc = useRef<HTMLDivElement>(null)
  const cheTruoc = useRef(che)
  useEffect(() => {
    const vuaXong = cheTruoc.current !== 'xem' && che === 'xem'
    cheTruoc.current = che
    const el = goc.current
    if (!vuaXong || !el) return
    const tran = el.closest('dialog')?.getBoundingClientRect().top ?? TOPBAR
    if (el.getBoundingClientRect().top < tran) el.scrollIntoView?.({ block: 'start' })
  }, [che])
  const n = data.nodes.find((x) => x.id === nut)
  const loai = so?.loai[nut]
  const g = mau?.gioiHan
  const khungSua = (moi: boolean, dau: NutVao, gh: NonNullable<typeof g>) => (
    <section
      data-testid="khung-sua"
      className={`space-y-3 ${khung ?? 'rounded-lg border border-border bg-surface p-4'}`}
    >
      <h2 className="text-muc font-semibold">
        {moi ? 'Thêm tình huống' : `Sửa «${n ? tenNut(n) : nut}»`}
      </h2>
      <FormNut
        key={moi ? `moi-${lan}` : nut}
        dau={dau}
        moi={moi}
        data={data}
        gioiHan={gh}
        ghi={ghi}
        onXong={onXong}
        onHuy={onHuy}
        onDoi={onDoi}
        onChon={onChon}
      />
    </section>
  )
  // Nút Sửa/Thêm khoá khi thiếu `gioiHan`, nên `g` luôn có ở hai nhánh này.
  const noiDung =
    g && che === 'them' ? (
      khungSua(true, nutTrong(), g)
    ) : g && che === 'sua' && n ? (
      khungSua(false, veKhuon(n), g)
    ) : (
      <BangChiTiet
        id={nut}
        nut={n}
        nodes={data.nodes}
        soDo={data.soDo[nut]}
        ngay={ngay}
        nguon={nguon}
        onChon={onChon}
        onDong={onDong}
        khung={khung}
        chip={n ? <ChipLop n={n} loai={loai} /> : null}
        hanhDong={
          n?.lop === 'sale' ? (
            <HanhDongNut
              // Cùng cấp với `LuotGanDay key={id}` trong `<aside>` — key phải khác chuỗi, không thì React trùng key.
              key={`hanh-dong:${n.id}`}
              n={n}
              data={data}
              nutMau={mau?.nodes.find((x) => x.id === nut)}
              loai={loai}
              gioiHan={g}
              ghiDuoc={ghiDuoc}
              lyDoKhoa={lyDoKhoa}
              onChon={onChon}
              onDaXoa={onDong}
              onSua={onSua}
            />
          ) : null
        }
      />
    )
  // `scroll-mt` bằng topbar dính + khe — cuộn tới đầu khung không để nó nằm dưới topbar (sheet điện thoại không có).
  return (
    <div ref={goc} className="md:scroll-mt-[88px]">
      {noiDung}
    </div>
  )
}
