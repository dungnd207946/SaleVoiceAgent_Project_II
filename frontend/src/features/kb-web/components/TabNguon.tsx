import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bang,
  DauBang,
  HANG_NUT,
  Hang,
  NUT_CHINH,
  NUT_HANG,
  NUT_HANG_XOA,
  NUT_PHU,
  O_LOC,
  PILL,
  TD,
  TD_PHU,
  TD_SO,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import { DauMuc } from '@/components/ui/DauMuc'
import { LoiTai } from '@/components/ui/TrangThai'
import { LoiApi } from '@/lib/http'
import {
  docNguon,
  docWorker,
  ghiKetQuaThu,
  KHOA,
  ketQuaThu,
  suaNguon,
  themNguon,
  thuLaiNguon,
  thuNguon,
  xoaNguon,
  type KetQuaThu,
  type Nguon,
} from '../api'
import { MAU_TINH_TRANG, NHAN_TINH_TRANG } from '../nhan'
import { luc } from '../thoiGian'

const COT: readonly Cot[] = [
  { nhan: 'Bật' },
  { nhan: 'Trang', rong: 'w-full' },
  { nhan: 'Bài 7 ngày qua', phai: true },
  { nhan: 'Tình trạng' },
  { nhan: 'Kiểm tra lúc' },
  { nhan: '' },
]

const NHIP_POLL_MS = 1_500
const TRAN_POLL_MS = 60_000

/** Poll kết quả thử nguồn tới khi xong / lỗi / quá 60 s. */
function useKetQuaThu(token: string | null, luuKhiXong?: (kq: KetQuaThu) => void) {
  const [trangThai, setTrangThai] = useState<'dang_chay' | 'xong' | 'loi' | 'qua_han' | null>(null)
  const [ketQua, setKetQua] = useState<KetQuaThu | null>(null)
  const luuRef = useRef(luuKhiXong)
  luuRef.current = luuKhiXong
  useEffect(() => {
    if (!token) {
      setTrangThai(null)
      setKetQua(null)
      return
    }
    let dung = false
    const batDau = Date.now()
    setTrangThai('dang_chay')
    setKetQua(null)
    const vong = async () => {
      while (!dung) {
        try {
          const r = await ketQuaThu(token)
          if (dung) return
          if (r.trangThai !== 'dang_chay') {
            setTrangThai(r.trangThai)
            setKetQua(r.ketQua)
            if (r.trangThai === 'xong' && r.ketQua) luuRef.current?.(r.ketQua)
            return
          }
        } catch {
          setTrangThai('loi')
          return
        }
        if (Date.now() - batDau > TRAN_POLL_MS) {
          setTrangThai('qua_han')
          return
        }
        await new Promise((r) => setTimeout(r, NHIP_POLL_MS))
      }
    }
    void vong()
    return () => {
      dung = true
    }
  }, [token])
  return { trangThai, ketQua }
}

function KetQuaThuNguon({
  trangThai,
  ketQua,
  url,
  onHuy,
  onThem,
  dangThem,
}: {
  trangThai: 'dang_chay' | 'xong' | 'loi' | 'qua_han'
  ketQua: KetQuaThu | null
  url: string
  onHuy: () => void
  onThem: (kq: KetQuaThu, ten: string) => void
  dangThem: boolean
}) {
  const worker = useQuery({ queryKey: ['kb-web', 'worker'], queryFn: docWorker, enabled: trangThai === 'qua_han' })
  const [ten, setTen] = useState('')
  useEffect(() => setTen(ketQua?.deXuat?.ten ?? ''), [ketQua])
  if (trangThai === 'dang_chay')
    return (
      <div className="mt-3 rounded-md border border-dashed border-border-strong bg-fill px-3.5 py-3 text-[13px]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2 animate-pulse rounded-full bg-ac" />
          Đang thử tải <b>{url}</b> — tìm RSS/sitemap, tải vài bài bằng http rồi trình duyệt…
        </span>
      </div>
    )
  if (trangThai === 'qua_han' || trangThai === 'loi')
    return (
      <div className="mt-3 rounded-md border border-dashed border-border-strong bg-fill px-3.5 py-3 text-[13px]" role="alert">
        {trangThai === 'loi'
          ? 'Lượt thử bị lỗi. Thử lại sau ít phút.'
          : worker.data?.dangChay === false
            ? 'Chưa có tiến trình thu thập nào đang chạy nên không thử được — liên hệ vận hành.'
            : 'Chưa có kết quả sau một phút. Trang có thể rất chậm — thử lại sau.'}
      </div>
    )
  if (!ketQua) return null
  const themDuoc = (ketQua.trangThai === 'ok' || ketQua.trangThai === 'no_feed') && ketQua.deXuat && !ketQua.daCo
  return (
    <div className="mt-3 rounded-md border border-dashed border-border-strong bg-fill px-3.5 py-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className={`${PILL} ${MAU_TINH_TRANG[ketQua.trangThai]}`}>
          {NHAN_TINH_TRANG[ketQua.trangThai]}
        </span>
        <b>{ketQua.deXuat?.domain ?? url}</b>
        {ketQua.daCo && <span className="text-muted">— đã có trong danh sách nguồn</span>}
      </div>
      <ul className="mt-1.5 ml-4.5 list-disc text-muted">
        {ketQua.deXuat && ketQua.trangThai === 'ok' && (
          <li>
            {ketQua.deXuat.rss.length > 0 || ketQua.deXuat.sitemapIndex || ketQua.deXuat.newsSitemaps.length > 0
              ? `Tìm bài qua ${ketQua.deXuat.rss.length > 0 ? 'RSS' : 'sitemap'}, 2 ngày gần nhất có ${ketQua.soBai} bài bất động sản`
              : 'Tìm bài qua trang chuyên mục'}
          </li>
        )}
        {ketQua.soTrangThu > 0 && (
          <li>
            Tải thử {ketQua.soTrangThu} bài{ketQua.deXuat?.cheDo === 'browser' ? ' bằng trình duyệt' : ' bằng http'}:{' '}
            {ketQua.soTrangDoc === ketQua.soTrangThu ? 'đủ nội dung' : `${ketQua.soTrangDoc}/${ketQua.soTrangThu} đọc được`}
          </li>
        )}
        {ketQua.ghiChu && <li>{ketQua.ghiChu}</li>}
      </ul>
      {themDuoc && ketQua.deXuat && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block flex-1">
            <span className="mb-1.5 block text-phu text-muted">Tên hiển thị</span>
            <input className={`${O_LOC} w-full`} value={ten} onChange={(e) => setTen(e.target.value)} />
          </label>
          <div className={HANG_NUT}>
            <button type="button" className={NUT_PHU} onClick={onHuy}>
              Huỷ
            </button>
            <button type="button" className={NUT_CHINH} disabled={dangThem || !ten.trim()} onClick={() => onThem(ketQua, ten.trim())}>
              Thêm vào nguồn
            </button>
          </div>
        </div>
      )}
      {!themDuoc && (
        <div className={`${HANG_NUT} mt-3`}>
          <button type="button" className={NUT_PHU} onClick={onHuy}>
            Đóng
          </button>
        </div>
      )}
    </div>
  )
}

export function TabNguon({ suaDuoc }: { suaDuoc: boolean }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: KHOA.nguon, queryFn: docNguon })
  const [url, setUrl] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [thuLaiCua, setThuLaiCua] = useState<number | null>(null)
  const [loi, setLoi] = useState('')
  const lamTuoi = () => void qc.invalidateQueries({ queryKey: ['kb-web'] })

  const thu = useMutation({
    mutationFn: thuNguon,
    onMutate: () => setLoi(''),
    onSuccess: (r) => {
      setThuLaiCua(null)
      setToken(r.token)
    },
    onError: (e: Error) => setLoi(e.message),
  })
  const thuLai = useMutation({
    mutationFn: thuLaiNguon,
    onSuccess: (r, id) => {
      setThuLaiCua(id)
      setToken(r.token)
    },
    onError: (e: Error) => setLoi(e.message),
  })
  const { trangThai, ketQua } = useKetQuaThu(token, (kq) => {
    if (thuLaiCua !== null) void ghiKetQuaThu(thuLaiCua, kq).then(lamTuoi)
  })
  const them = useMutation({
    mutationFn: themNguon,
    onSuccess: () => {
      setToken(null)
      setUrl('')
      lamTuoi()
    },
    onError: (e: Error) => setLoi(e instanceof LoiApi ? e.message : 'Không thêm được nguồn.'),
  })
  const sua = useMutation({ mutationFn: (v: { id: number; bat: boolean }) => suaNguon(v.id, { bat: v.bat }), onSuccess: lamTuoi })
  const xoa = useMutation({
    mutationFn: xoaNguon,
    onSuccess: lamTuoi,
    onError: (e: Error) => setLoi(e.message),
  })

  if (q.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (q.isError) return <LoiTai viec="danh sách nguồn" thuLai={() => void q.refetch()} />
  const ds = q.data
  const soBat = ds.filter((n) => n.bat).length

  return (
    <div className="flex flex-col gap-6">
      {suaDuoc && (
        <div className="rounded-lg border border-border bg-surface px-5 py-4">
          <h3 className="text-[14px] font-semibold">Thêm nguồn</h3>
          <p className="mt-0.5 mb-3.5 text-[13px] text-muted">
            Dán địa chỉ trang báo, chuyên mục bất động sản hoặc trang chủ đầu tư.
          </p>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (url.trim()) thu.mutate(url.trim())
            }}
          >
            <label className="block flex-1">
              <span className="mb-1.5 block text-phu text-muted">Địa chỉ</span>
              <input
                className={`${O_LOC} w-full`}
                placeholder="https://cafeland.vn/tin-tuc/"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </label>
            <button type="submit" className={NUT_CHINH} disabled={thu.isPending || trangThai === 'dang_chay' || !url.trim()}>
              Thử nguồn
            </button>
          </form>
          {loi && (
            <p role="alert" className="mt-2 text-[13px] text-badge-alert-fg">
              {loi}
            </p>
          )}
          {trangThai && thuLaiCua === null && (
            <KetQuaThuNguon
              trangThai={trangThai}
              ketQua={ketQua}
              url={url}
              onHuy={() => setToken(null)}
              dangThem={them.isPending}
              onThem={(kq, ten) =>
                kq.deXuat &&
                them.mutate({
                  ...kq.deXuat,
                  ten,
                  tinhTrang: kq.trangThai === 'no_feed' ? 'no_feed' : 'ok',
                  ghiChu: kq.ghiChu,
                })
              }
            />
          )}
        </div>
      )}
      <div>
        <DauMuc
          tieuDe="Nguồn đang dùng"
          dem={`${soBat} / ${ds.length} đang bật`}
        />
        {trangThai && thuLaiCua !== null && (
          <div className="mb-3">
            <KetQuaThuNguon
              trangThai={trangThai}
              ketQua={ketQua}
              url={ds.find((n) => n.id === thuLaiCua)?.domain ?? ''}
              onHuy={() => setToken(null)}
              dangThem={false}
              onThem={() => setToken(null)}
            />
          </div>
        )}
        <TheBang>
          <VungCuon>
            <Bang nhan="Nguồn">
              <DauBang cot={COT} />
              <tbody>
                {ds.map((n) => (
                  <HangNguon
                    key={n.id}
                    n={n}
                    suaDuoc={suaDuoc}
                    dangGui={sua.isPending}
                    doi={(bat) => sua.mutate({ id: n.id, bat })}
                    thuLai={() => thuLai.mutate(n.id)}
                    xoa={() => {
                      if (window.confirm(`Xoá nguồn ${n.domain}? Bài đã thu vẫn giữ; từ nay không thu thêm.`)) xoa.mutate(n.id)
                    }}
                  />
                ))}
              </tbody>
            </Bang>
          </VungCuon>
        </TheBang>
      </div>
    </div>
  )
}

function HangNguon({
  n,
  suaDuoc,
  dangGui,
  doi,
  thuLai,
  xoa,
}: {
  n: Nguon
  suaDuoc: boolean
  dangGui: boolean
  doi: (bat: boolean) => void
  thuLai: () => void
  xoa: () => void
}) {
  return (
    <Hang>
      <td className={`${TD} w-12`}>
        <CongTac bat={n.bat} nhan={n.ten} dangGui={dangGui || !suaDuoc} doi={doi} />
      </td>
      <td className={TD}>
        <span className="font-medium text-fg">{n.ten}</span>
        <span className="ml-2 text-phu text-muted">{n.domain}</span>
      </td>
      <td className={TD_SO}>{n.theoDoi === 'living' ? '—' : n.baiBayNgay}</td>
      <td className={TD}>
        {n.tinhTrang ? (
          <span className={`${PILL} whitespace-nowrap ${MAU_TINH_TRANG[n.tinhTrang]}`}>{NHAN_TINH_TRANG[n.tinhTrang]}</span>
        ) : (
          <span className="text-phu whitespace-nowrap text-muted">Chưa kiểm tra</span>
        )}
      </td>
      <td className={TD_PHU}>{luc(n.thuLuc)}</td>
      <td className={`${TD} text-right whitespace-nowrap`}>
        {suaDuoc && (
          <span className="inline-flex gap-1.5">
            <button type="button" className={NUT_HANG} onClick={thuLai}>
              Kiểm tra lại
            </button>
            <button type="button" className={NUT_HANG_XOA} onClick={xoa}>
              Xoá
            </button>
          </span>
        )}
      </td>
    </Hang>
  )
}
