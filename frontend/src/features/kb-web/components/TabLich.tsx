import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_HANG, NUT_PHU, O_LOC } from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import { DauMuc } from '@/components/ui/DauMuc'
import { LoiTai } from '@/components/ui/TrangThai'
import { LoiApi } from '@/lib/http'
import { chayNgay, docLich, KHOA, luuLich, type Lich, type LichGui, type Mode } from '../api'
import { MO_TA_MODE, NHAN_MODE, THU_TRONG_TUAN } from '../nhan'
import { luc, sapToi } from '../thoiGian'
import { HopThoai } from './HopThoai'

const SO_THANG = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] as const
const moiThang = (n: number) => (n === 1 ? 'mỗi tháng' : `mỗi ${n} tháng`)
const NHAN_NGAY = { d1: 'Ngày 1', d15: 'Ngày 15', first_sunday: 'Chủ nhật đầu tháng' } as const
const NHAN_LAT_CAT: Record<number, string> = { 1: 'mọi dự án', 2: '½ số dự án', 3: '⅓ số dự án' }
function lichGui(l: Lich): LichGui {
  return {
    mode: l.mode,
    bat: l.bat,
    gio: l.gio,
    ngayTrongTuan: l.ngayTrongTuan,
    soThang: l.soThang,
    ngayTrongChuKy: l.ngayTrongChuKy,
    latCat: l.latCat,
  }
}

function tomTat(l: Lich): string {
  if (l.mode === 'nightly') return `Mỗi ngày lúc ${l.gio}`
  if (l.mode === 'weekly') {
    const ngay = l.ngayTrongTuan.length ? l.ngayTrongTuan.map((i) => THU_TRONG_TUAN[i]).join(', ') : 'Chưa chọn ngày'
    return `${ngay} lúc ${l.gio}`
  }
  return `${NHAN_NGAY[l.ngayTrongChuKy ?? 'd1']}, ${moiThang(l.soThang ?? 3)}, lúc ${l.gio}`
}

function Dong({ nhan, children }: { nhan: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted">{nhan}</dt>
      <dd className="text-fg">{children}</dd>
    </>
  )
}

function TheLich({
  l,
  suaDuoc,
  dangGui,
  bat,
  sua,
  chay,
}: {
  l: Lich
  suaDuoc: boolean
  dangGui: boolean
  bat: (v: boolean) => void
  sua: () => void
  chay: () => void
}) {
  return (
    <div className="flex flex-col rounded-lg border border-border bg-surface">
      <div className="flex items-start gap-3 px-4 pt-4">
        <CongTac bat={l.bat} nhan={`Bật ${NHAN_MODE[l.mode]}`} dangGui={dangGui || !suaDuoc} doi={bat} />
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-fg">{NHAN_MODE[l.mode]}</p>
          <p className="mt-0.5 text-phu text-muted">{MO_TA_MODE[l.mode]}</p>
        </div>
      </div>
      <dl className="mx-4 mt-3.5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 border-t border-rule pt-3.5 text-[13px]">
        <Dong nhan="Lịch chạy">{tomTat(l)}</Dong>
        {l.mode === 'weekly' && <Dong nhan="Mỗi lần">{NHAN_LAT_CAT[l.latCat] ?? `${l.latCat} phần`}</Dong>}
        <Dong nhan="Lần gần nhất">{l.lanGanNhat ? luc(l.lanGanNhat) : 'Chưa chạy'}</Dong>
        <Dong nhan="Lần kế tiếp">{l.bat ? sapToi(l.lanKeTiep) : 'Đang tắt'}</Dong>
      </dl>
      {suaDuoc && (
        <div className="mt-auto flex justify-end gap-2 px-4 pt-4 pb-4">
          <button type="button" className={NUT_HANG} onClick={sua}>
            Sửa
          </button>
          <button type="button" className={NUT_HANG} onClick={chay} disabled={dangGui}>
            Chạy ngay
          </button>
        </div>
      )}
    </div>
  )
}

function Truong({ nhan, children }: { nhan: string; children: React.ReactNode }) {
  return (
    <label className="mt-3.5 block">
      <span className="mb-1.5 block text-phu text-muted">{nhan}</span>
      {children}
    </label>
  )
}

function SuaLich({ ban, luu, dong, dangLuu }: { ban: Lich; luu: (l: Lich) => void; dong: () => void; dangLuu: boolean }) {
  const [l, setL] = useState(ban)
  return (
    <HopThoai tieuDe={`Sửa lịch «${NHAN_MODE[l.mode]}»`} dong={dong}>
      {l.mode === 'weekly' && (
        <div className="mt-3.5">
          <span className="mb-1.5 block text-phu text-muted">Ngày chạy</span>
          <div className="flex gap-1.5">
            {THU_TRONG_TUAN.map((t, i) => {
              const chon = l.ngayTrongTuan.includes(i)
              return (
                <button
                  key={t}
                  type="button"
                  aria-pressed={chon}
                  className={`h-8 w-10 rounded-md border text-[13px] ${chon ? 'border-ac bg-acs font-semibold text-acd' : 'border-border-strong text-muted'}`}
                  onClick={() =>
                    setL({ ...l, ngayTrongTuan: chon ? l.ngayTrongTuan.filter((d) => d !== i) : [...l.ngayTrongTuan, i].sort() })
                  }
                >
                  {t}
                </button>
              )
            })}
          </div>
        </div>
      )}
      {l.mode === 'rebuild' && (
        <div className="grid grid-cols-2 gap-3">
          <Truong nhan="Chu kỳ">
            <select
              className={`o-chon ${O_LOC} w-full`}
              value={String(l.soThang ?? 3)}
              onChange={(e) => setL({ ...l, soThang: Number(e.target.value) })}
            >
              {SO_THANG.map((n) => (
                <option key={n} value={n}>
                  {n === 1 ? 'Mỗi tháng' : `Mỗi ${n} tháng`}
                </option>
              ))}
            </select>
          </Truong>
          <Truong nhan="Vào ngày">
            <select
              className={`o-chon ${O_LOC} w-full`}
              value={l.ngayTrongChuKy ?? 'd1'}
              onChange={(e) => setL({ ...l, ngayTrongChuKy: e.target.value as Lich['ngayTrongChuKy'] })}
            >
              <option value="d1">Ngày 1</option>
              <option value="d15">Ngày 15</option>
              <option value="first_sunday">Chủ nhật đầu tháng</option>
            </select>
          </Truong>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Truong nhan="Giờ chạy (giờ Việt Nam)">
          <input type="time" className={`${O_LOC} w-full`} value={l.gio} onChange={(e) => setL({ ...l, gio: e.target.value })} />
        </Truong>
        {l.mode === 'weekly' && (
          <Truong nhan="Mỗi lần chạy">
            <select
              className={`o-chon ${O_LOC} w-full`}
              value={String(l.latCat)}
              onChange={(e) => setL({ ...l, latCat: Number(e.target.value) })}
            >
              <option value="3">⅓ số dự án</option>
              <option value="2">½ số dự án</option>
              <option value="1">Mọi dự án</option>
            </select>
          </Truong>
        )}
      </div>
      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" className={NUT_PHU} onClick={dong}>
          Huỷ
        </button>
        <button
          type="button"
          className={NUT_CHINH}
          disabled={dangLuu || !l.gio || (l.mode === 'weekly' && l.ngayTrongTuan.length === 0)}
          onClick={() => luu(l)}
        >
          Lưu
        </button>
      </div>
    </HopThoai>
  )
}

export function TabLich({ suaDuoc }: { suaDuoc: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: KHOA.lich, queryFn: docLich })
  const [dangSua, setDangSua] = useState<Lich | null>(null)
  const [thongBao, setThongBao] = useState('')
  const luu = useMutation({
    mutationFn: (lich: readonly Lich[]) => luuLich({ lich: lich.map(lichGui) }),
    onSuccess: () => {
      setDangSua(null)
      setThongBao('')
      void qc.invalidateQueries({ queryKey: ['kb-web'] })
    },
    onError: (e: Error) => setThongBao(e instanceof LoiApi ? e.message : 'Không lưu được lịch.'),
  })
  const chay = useMutation({
    mutationFn: (mode: Mode) => chayNgay(mode),
    onSuccess: (v) => {
      setThongBao(`Đã xếp lượt «${NHAN_MODE[v.mode as Mode] ?? v.mode}», xem tiến độ ở tab Tổng quan.`)
      void qc.invalidateQueries({ queryKey: ['kb-web'] })
    },
    onError: (e: Error) => setThongBao(e.message),
  })

  if (q.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (q.isError) return <LoiTai viec="lịch tự động" thuLai={() => void q.refetch()} />
  const { lich } = q.data
  const doiMot = (moi: Lich) => lich.map((x) => (x.mode === moi.mode ? moi : x))

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <DauMuc tieuDe="Lịch tự động" ghiChu="Giờ Việt Nam. Lịch đã tắt thì không tự chạy, vẫn bấm «Chạy ngay» được." />
        {thongBao && (
          <p role="status" className="text-[13px] text-muted">
            {thongBao}
          </p>
        )}
        <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-1">
          {lich.map((l) => (
            <TheLich
              key={l.mode}
              l={l}
              suaDuoc={suaDuoc}
              dangGui={luu.isPending || chay.isPending}
              bat={(v) => luu.mutate(doiMot({ ...l, bat: v }))}
              sua={() => setDangSua(l)}
              chay={() => chay.mutate(l.mode)}
            />
          ))}
        </div>
      </div>
      {dangSua && (
        <SuaLich ban={dangSua} dangLuu={luu.isPending} dong={() => setDangSua(null)} luu={(l) => luu.mutate(doiMot(l))} />
      )}
    </div>
  )
}
