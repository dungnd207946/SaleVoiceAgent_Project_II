/**
 * Form sửa / thêm MỘT tình huống lớp sale (spec đợt 3 §4c). Thứ tự và nhãn ô = bản xem (`NHAN_TRUONG`). Lưu qua
 * `useGhi` của khung (một đường ghi); lỗi client (`kiemNut`) và 422 (`phanLoi422`) hiện dưới đúng ô; 409 giữ
 * nguyên chữ đang gõ — Lưu lần nữa dựng bộ từ bản vừa tải lại.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { OChon, OChonNhieu, OChu } from '@/components/ui/Truong'
import { LoiApi } from '@/lib/http'
import { type DuLieuKichBan, type GioiHan, type NutVao } from '../api'
import {
  NHAN_KENH,
  NHAN_TRUONG,
  chuanHoa,
  doDai,
  idBuocMoi,
  idRieng,
  kiemNut,
  phanLoi422,
  thayNut,
  themNut,
  type LoiNut,
  type LyDoChan,
} from '../khuon'
import { TEN_NHOM, THU_TU_NHOM, nhanKyNang, tenNut } from '../logic'
import { cauLoi, type useGhi } from '../useGhi'
import { ODanhSachDong } from './ODanhSachDong'

interface Props {
  dau: NutVao
  moi: boolean
  data: DuLieuKichBan
  gioiHan: GioiHan
  ghi: ReturnType<typeof useGhi>
  onXong: (id: string) => void
  onHuy: () => void
  onDoi: (dirty: boolean) => void
  onChon: (id: string) => void
}

const KENH = [
  { value: 'ca_hai', nhan: 'Cả chat và cuộc gọi' },
  ...Object.entries(NHAN_KENH).map(([value, nhan]) => ({ value, nhan })),
]
type DsTruong = 'dau_hieu' | 'lam' | 'cam'

export function FormNut({ dau, moi, data, gioiHan: g, ghi, onXong, onHuy, onDoi, onChon }: Props) {
  // Tool agent đã gỡ (không còn trong `gioiHan.tool`) bỏ ngay lúc mở — như BE `tuong_thich` bỏ trước khi băm: để
  // lại thì ô chọn không hiện nó mà `kiemNut` vẫn báo, người dùng không có cách gỡ (Review Focus 4).
  const [goc] = useState(() => ({ ...dau, tool: dau.tool.filter((t) => g.tool.includes(t)) }))
  const [f, setF] = useState(goc)
  const [loi, setLoi] = useState<LoiNut>({})
  const [chung, setChung] = useState<string[]>([])
  const [nutKhac, setNutKhac] = useState<LyDoChan[]>([])
  const [gap409, setGap409] = useState(false)
  const [hashLucMo] = useState(() => data.nodes.find((n) => n.id === dau.id)?.hash)
  const formRef = useRef<HTMLFormElement>(null)

  const dirty = JSON.stringify(f) !== JSON.stringify(goc)
  useEffect(() => onDoi(dirty), [dirty, onDoi])
  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, [loi])

  const dat = <K extends keyof NutVao>(k: K, v: NutVao[K]) => setF((x) => ({ ...x, [k]: v }))
  const ds = (k: DsTruong) => ({
    giaTri: f[k],
    doiY: (i: number, s: string) =>
      setF((x) => ({ ...x, [k]: x[k].map((y, j) => (j === i ? s : y)) })),
    them: () => setF((x) => ({ ...x, [k]: [...x[k], ''] })),
    bo: (i: number) => setF((x) => ({ ...x, [k]: x[k].filter((_, j) => j !== i) })),
  })

  const coNguon = !moi && data.nodes.some((n) => n.id !== f.id && n.lan_2 === f.id)
  const doiNoiKhac = gap409 && !moi && data.nodes.find((n) => n.id === dau.id)?.hash !== hashLucMo
  const nhom = [...g.nhom].sort(
    (a, b) =>
      (THU_TU_NHOM as readonly string[]).indexOf(a) - (THU_TU_NHOM as readonly string[]).indexOf(b),
  )
  const tongDauHieu = doDai(
    f.dau_hieu
      .map((s) => s.trim())
      .filter(Boolean)
      .join(' | '),
  )
  const tongCam = f.cam.reduce((s, x) => s + doDai(x.trim()), 0)

  async function luu(e: FormEvent) {
    e.preventDefault()
    setChung([])
    setNutKhac([])
    const sach = chuanHoa(f)
    const id = moi ? idRieng(sach.ten, new Set(data.nodes.map((n) => n.id))) : sach.id
    const nut = { ...sach, id }
    // Không đổi gì so với bản đọc từ GET ⇒ không ghi: ở trạng thái mẫu, một lần ghi là tạo bản riêng (không quay lại
    // mẫu được), và lần nào cũng tăng version + dựng lại agent. So với `dau` (chưa lọc tool) — tool agent đã gỡ bị bỏ
    // lúc mở form vẫn tính là một thay đổi cần ghi.
    if (!moi && JSON.stringify(nut) === JSON.stringify(dau)) {
      onDoi(false)
      return onHuy()
    }
    const l = kiemNut(nut, g)
    setLoi(l)
    if (Object.keys(l).length) return
    const kq = await ghi.ghi((bo) => (moi ? themNut(bo, nut) : thayNut(bo, nut)))
    if (kq.ok) return onXong(id)
    if (kq.loiBo.length) return setChung(kq.loiBo)
    if (kq.loi instanceof LoiApi && kq.loi.code === 'VALIDATION_ERROR') {
      const p = phanLoi422(kq.loi, kq.moi, id, ghi.ten)
      setLoi(p.cuaNut)
      setNutKhac(p.nutKhac)
      setChung(p.chung)
      return
    }
    if (kq.loi instanceof LoiApi && kq.loi.code === 'PLAYBOOK_DA_DOI') setGap409(true)
    setChung([cauLoi(kq.loi)])
  }

  return (
    <form
      ref={formRef}
      onSubmit={(e) => void luu(e)}
      noValidate
      data-testid="form-nut"
      className="space-y-4"
    >
      <OChu
        ten="nut-ten"
        nhan={NHAN_TRUONG.ten}
        batBuoc
        giaTri={f.ten}
        doi={(v) => dat('ten', v)}
        goiY={`${doDai(f.ten)}/${g.maxTen} ký tự`}
        loi={loi.ten}
      />
      <OChon
        ten="nut-nhom"
        nhan={NHAN_TRUONG.nhom}
        batBuoc
        giaTri={f.nhom || null}
        doi={(v) => dat('nhom', v)}
        muc={nhom.map((x) => ({ value: x, nhan: TEN_NHOM[x] ?? x }))}
        nhanRong="Chọn nhóm"
        loi={loi.nhom}
      />
      <OChon
        ten="nut-kenh"
        nhan={NHAN_TRUONG.kenh}
        giaTri={f.kenh.length === 1 ? f.kenh[0]! : 'ca_hai'}
        doi={(v) => dat('kenh', v === 'ca_hai' ? [] : [v])}
        muc={KENH.filter((k) => k.value === 'ca_hai' || g.kenh.includes(k.value))}
        loi={loi.kenh}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.dau_hieu}
        batBuoc
        {...ds('dau_hieu')}
        toiDa={g.maxDong.dau_hieu}
        kyTuMoiY={g.maxKyTu}
        tong={{ gia: tongDauHieu, toiDa: g.maxDauHieuTong }}
        goiY="Tả lời khách nói để agent nhận ra tình huống. Nhắc tình huống khác bằng tên, không bằng mã."
        loi={loi.dau_hieu}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.lam}
        batBuoc
        {...ds('lam')}
        toiDa={g.maxDong.lam}
        kyTuMoiY={g.maxKyTu}
        loi={loi.lam}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.buoc}
        giaTri={f.buoc.map((b) => b.lam)}
        doiY={(i, s) =>
          setF((x) => ({ ...x, buoc: x.buoc.map((b, j) => (j === i ? { ...b, lam: s } : b)) }))
        }
        them={() => setF((x) => ({ ...x, buoc: [...x.buoc, { id: idBuocMoi(x.buoc), lam: '' }] }))}
        bo={(i) => setF((x) => ({ ...x, buoc: x.buoc.filter((_, j) => j !== i) }))}
        toiDa={g.maxBuoc}
        kyTuMoiY={g.maxKyTu}
        goiY="Để trống nếu xử lý trong một lượt"
        loi={loi.buoc}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.cam}
        {...ds('cam')}
        toiDa={g.maxDong.cam}
        tong={{ gia: tongCam, toiDa: g.maxCamTong }}
        loi={loi.cam}
      />
      <OChonNhieu
        ten="nut-tool"
        nhan={NHAN_TRUONG.tool}
        giaTri={f.tool}
        doi={(v) => dat('tool', v)}
        muc={g.tool.map((t) => ({ value: t, nhan: nhanKyNang(t) }))}
        goiY={`Tối đa ${g.maxTool}`}
        loi={loi.tool}
      />
      <OChu
        ten="nut-khi-thieu"
        nhan={NHAN_TRUONG.khi_thieu}
        hangChu={2}
        giaTri={f.khi_thieu}
        doi={(v) => dat('khi_thieu', v)}
        goiY={`${doDai(f.khi_thieu)}/${g.maxCau} ký tự`}
        loi={loi.khi_thieu}
      />
      <OChu
        ten="nut-cau-ket"
        nhan={NHAN_TRUONG.cau_ket}
        hangChu={2}
        giaTri={f.cau_ket}
        doi={(v) => dat('cau_ket', v)}
        goiY="Agent tự bỏ khi đang hỏi trước"
        loi={loi.cau_ket}
      />
      <OChon
        ten="nut-lan-2"
        nhan={NHAN_TRUONG.lan_2}
        giaTri={f.lan_2 || null}
        doi={(v) => dat('lan_2', v)}
        nhanRong="Không chuyển"
        muc={data.nodes.filter((n) => n.id !== f.id).map((n) => ({ value: n.id, nhan: tenNut(n) }))}
        loi={loi.lan_2}
      />
      <label className="flex items-start gap-2 text-than">
        <input
          type="checkbox"
          aria-invalid={!!loi.chi_lan_2}
          aria-describedby={loi.chi_lan_2 ? 'nut-chi-lan-2-loi' : undefined}
          checked={f.chi_lan_2}
          disabled={!coNguon && !f.chi_lan_2}
          onChange={(e) => dat('chi_lan_2', e.target.checked)}
          className="mt-1"
        />
        <span>
          {NHAN_TRUONG.chi_lan_2}
          {!coNguon && !f.chi_lan_2 ? (
            <span className="block text-phu text-muted-2">
              Chưa tình huống nào chuyển sang đây khi khách lặp lại.
            </span>
          ) : null}
        </span>
      </label>
      {loi.chi_lan_2 ? (
        <p id="nut-chi-lan-2-loi" className="text-phu font-medium text-badge-alert-fg">
          {loi.chi_lan_2}
        </p>
      ) : null}
      {doiNoiKhac ? (
        <p
          role="alert"
          className="rounded-md bg-badge-warn-bg px-3 py-2 text-phu text-badge-warn-fg"
        >
          Tình huống này cũng vừa được sửa ở nơi khác — xem lại trước khi lưu.
        </p>
      ) : null}
      {chung.length || nutKhac.length ? (
        <ul role="alert" className="space-y-1 text-phu text-badge-alert-fg">
          {chung.map((c) => (
            <li key={c}>{c}</li>
          ))}
          {nutKhac.map((c) => (
            <li key={c.cau}>
              <button
                type="button"
                onClick={() => onChon(c.id)}
                className="cursor-pointer text-left underline"
              >
                {c.cau}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {data.kichBan.trangThai === 'mau' ? (
        <p className="text-phu text-muted">
          Lần lưu này tạo bản riêng cho workspace: từ đó agent dùng bản của bạn; mẫu NobleX mới chỉ
          được báo ở đầu màn, không tự cập nhật.
        </p>
      ) : null}
      <div className={HANG_NUT}>
        <span className="mr-auto text-phu text-muted">
          Lưu xong, số đo tình huống này đếm lại từ đầu.
        </span>
        <button type="button" onClick={onHuy} className={`${NUT_PHU} cursor-pointer`}>
          Huỷ
        </button>
        <button type="submit" disabled={ghi.dangGhi} className={`${NUT_CHINH} cursor-pointer`}>
          Lưu
        </button>
      </div>
    </form>
  )
}
