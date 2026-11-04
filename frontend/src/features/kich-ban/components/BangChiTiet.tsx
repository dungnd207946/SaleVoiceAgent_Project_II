import { useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { NUT_PHU } from '@/components/ui/Bang'
import { PHONE_TRONG } from '@/features/ops/contracts'
import { useLuotNut, type Ngay, type NutKichBan, type SoDoNut } from '../api'
import { NHAN_KENH, NHAN_TRUONG } from '../khuon'
import { TEN_LOAI, TEN_NHOM, banDoc, canh, docDe, gio, nhanKyNang, tenNut } from '../logic'
import { CHIP } from './lop'

const pct = (x: number | null) => (x === null ? '—' : `${Math.round(x * 100)}%`)
const DAU_DAT = { true: '✓ Đạt', false: '✗ Chưa đạt' } as const

interface Props {
  nut: NutKichBan | undefined
  id: string
  nodes: NutKichBan[]
  soDo?: SoDoNut | undefined
  ngay: Ngay
  nguon?: string | undefined
  onChon: (id: string) => void
  onDong: () => void
  /** Lớp khung ngoài. Trong bottom sheet (điện thoại) sheet đã là mặt nền — khung riêng
   *  là thẻ lồng trong thẻ. */
  khung?: string | undefined
  /** Chip lớp / so mẫu (KhungChiTiet). */
  chip?: ReactNode
  /** Hàng thao tác ghi (KhungChiTiet) — vắng với người chỉ xem / tình huống hệ thống. */
  hanhDong?: ReactNode
}

const KHUNG_MAC_DINH = 'rounded-lg border border-border bg-surface p-4'

function Muc({ ten, ds, so }: { ten: string; ds: string[]; so?: boolean }) {
  if (!ds.length) return null
  const The = so ? 'ol' : 'ul'
  return (
    <section>
      <h3 className="mb-1 text-phu font-medium text-muted">{ten}</h3>
      <The className={`${so ? 'list-decimal' : 'list-disc'} space-y-0.5 pl-4 text-[13px]`}>
        {ds.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </The>
    </section>
  )
}

function SoDo({ s, dich }: { s: SoDoNut; dich: (s: string) => string }) {
  const dem = (nhan: string, ds: SoDoNut['hayThieu']) =>
    ds.length ? (
      <p className="text-phu text-muted">
        {nhan}: {ds.map((m) => `${dich(m.ten)} (${m.so} lần)`).join('; ')}
      </p>
    ) : null
  return (
    <section className="space-y-1 rounded-md bg-fill p-2 text-[13px]">
      <p>
        {s.soLuot} lượt · đạt <b>{pct(s.tiLeDat)}</b> · thiếu tài liệu{' '}
        {Math.round(s.thieuDuLieu * 100)}%
      </p>
      {s.jevSo > 0 ? (
        <p className="text-phu text-muted">
          Nhận ra đúng tình huống ngay trong lượt: {pct(s.jevKhop)} ({s.jevSo} lượt)
        </p>
      ) : null}
      {dem('Hay thiếu', s.hayThieu)}
      {dem('Hay phạm điều cấm', s.hayPham)}
    </section>
  )
}

function LuotGanDay({
  id,
  ngay,
  nguon,
  dich,
}: {
  id: string
  ngay: Ngay
  nguon?: string | undefined
  dich: (s: string) => string
}) {
  const [chiKhongDat, setChiKhongDat] = useState(false)
  const kq = useLuotNut(id, { ngay, nguon, chiKhongDat })
  return (
    <section className="space-y-2">
      <h3 className="text-phu font-medium text-muted">Lượt gần đây</h3>
      <label className="flex items-center gap-2 text-[13px]">
        <input
          type="checkbox"
          checked={chiKhongDat}
          onChange={(e) => setChiKhongDat(e.target.checked)}
        />
        Chỉ lượt không đạt
      </label>
      {kq.isError ? <p className="text-[13px]">Không tải được danh sách lượt.</p> : null}
      {kq.data?.length === 0 ? (
        <p className="text-[13px] text-muted">Chưa có lượt nào trong khoảng này</p>
      ) : null}
      {kq.data?.map((l) => (
        <div
          key={`${l.sessionId}-${l.seq}`}
          data-testid="luot-nut"
          className="space-y-0.5 rounded-md border border-border p-2 text-phu"
        >
          <p className="text-muted">
            {l.dat === null ? '—' : DAU_DAT[`${l.dat}`]} · {gio(l.taoLuc)}
          </p>
          {l.khach ? <p>Khách: {l.khach}</p> : null}
          <p>Agent: {l.agent.length > 300 ? `${l.agent.slice(0, 300)}…` : l.agent}</p>
          {l.thieu.length ? <p>Còn thiếu: {l.thieu.map(dich).join('; ')}</p> : null}
          <Link
            to="/convos/$phone"
            params={{ phone: l.phone ?? PHONE_TRONG }}
            search={{ session: l.sessionId, seq: l.seq }}
            className="text-ac"
          >
            Mở phiên
          </Link>
        </div>
      ))}
    </section>
  )
}

export function BangChiTiet({
  nut,
  id,
  nodes,
  soDo,
  ngay,
  nguon,
  onChon,
  onDong,
  khung = KHUNG_MAC_DINH,
  chip,
  hanhDong,
}: Props) {
  const ten = Object.fromEntries(nodes.map((n) => [n.id, tenNut(n)]))
  const doc = nut ? banDoc(nut, ten) : null
  const dich = doc?.dich ?? ((s: string) => docDe(s, ten))
  const den = canh(nodes).filter((e) => e.target === id)
  const lan = nut && typeof nut.dieu_kien.lan === 'number' ? nut.dieu_kien.lan : null
  // Tên tình huống đích là dòng chính, điều kiện là dòng phụ — không ghép bằng mũi tên trong một nút cao cố định
  // (nhãn dài xuống dòng là tràn khỏi nút).
  const ChuyenNut = ({ toi, khi }: { toi: string; khi: string }) => (
    <button
      type="button"
      onClick={() => onChon(toi)}
      className="block w-full cursor-pointer rounded-md border border-border-field px-3 py-1.5 text-left hover:bg-fill-strong"
    >
      <span className="block text-than">{ten[toi] ?? toi}</span>{' '}
      <span className="block text-[12px] text-muted">Khi {khi}</span>
    </button>
  )
  return (
    <aside data-testid="bang-chi-tiet" className={`space-y-3 ${khung}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-1.5">
          <p className="text-muc font-semibold">{ten[id] ?? id}</p>
          {nut ? (
            <div className="flex flex-wrap gap-1.5">
              <span className={CHIP}>{TEN_NHOM[nut.nhom] ?? nut.nhom}</span>
              <span className={CHIP}>{TEN_LOAI[nut.loai] ?? nut.loai}</span>
              {/* Cùng chữ với form (luật «xem trước, sửa sau» điều 1). `lan` chỉ còn cho JSON cũ. */}
              {nut.chi_lan_2 ? (
                <span className={CHIP}>{NHAN_TRUONG.chi_lan_2}</span>
              ) : lan ? (
                <span className={CHIP}>Lần {lan} trong phiên</span>
              ) : null}
              {nut.kenh.length === 1 ? (
                <span className={CHIP}>{NHAN_KENH[nut.kenh[0]!] ?? nut.kenh[0]}</span>
              ) : null}
              {nut.trang_thai === 'nhap' ? (
                <span className="rounded-full bg-badge-warn-bg px-2 py-0.5 text-[12px] text-badge-warn-fg">
                  Đang tắt — agent không chọn
                </span>
              ) : null}
              {chip}
            </div>
          ) : (
            <p className="text-phu text-muted">Tình huống này không còn trong kịch bản</p>
          )}
        </div>
        <button type="button" onClick={onDong} className={NUT_PHU}>
          Đóng
        </button>
      </div>
      {hanhDong}
      {soDo ? <SoDo s={soDo} dich={dich} /> : null}
      {nut && doc ? (
        <>
          <Muc ten={NHAN_TRUONG.dau_hieu} ds={doc.dauHieu} />
          <Muc ten={NHAN_TRUONG.lam} ds={doc.lam} />
          <Muc ten={NHAN_TRUONG.buoc} ds={doc.buoc} so />
          <Muc ten={NHAN_TRUONG.cam} ds={doc.cam} />
          {nut.tool.length ? (
            <section>
              <h3 className="mb-1 text-phu font-medium text-muted">{NHAN_TRUONG.tool}</h3>
              <div className="flex flex-wrap gap-1.5">
                {nut.tool.map((t) => (
                  <span key={t} className={CHIP}>
                    {nhanKyNang(t)}
                  </span>
                ))}
              </div>
            </section>
          ) : null}
          {doc.khiThieu ? (
            <section>
              <h3 className="mb-1 text-phu font-medium text-muted">{NHAN_TRUONG.khi_thieu}</h3>
              <p className="text-[13px]">{doc.khiThieu}</p>
            </section>
          ) : null}
          {nut.cau_ket ? (
            <section>
              <h3 className="mb-1 text-phu font-medium text-muted">{NHAN_TRUONG.cau_ket}</h3>
              <p className="text-[13px]">{docDe(nut.cau_ket, ten)}</p>
            </section>
          ) : null}
          {Object.keys(nut.tiep).length ? (
            <section className="space-y-1">
              <h3 className="text-phu font-medium text-muted">{NHAN_TRUONG.lan_2}</h3>
              {canh(nodes)
                .filter((e) => e.source === id)
                .map((e) => (
                  <ChuyenNut key={e.id} toi={e.target} khi={e.label} />
                ))}
            </section>
          ) : null}
          {den.length ? (
            <section className="space-y-1">
              <h3 className="text-phu font-medium text-muted">Đến từ</h3>
              {den.map((e) => (
                <ChuyenNut key={e.id} toi={e.source} khi={e.label} />
              ))}
            </section>
          ) : null}
        </>
      ) : null}
      <LuotGanDay key={id} id={id} ngay={ngay} nguon={nguon} dich={dich} />
    </aside>
  )
}
