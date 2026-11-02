/**
 * Cấu hình agent — state + luồng lưu, dùng chung cho MỌI màn sửa agent.
 *
 * TỪ BACKEND `0966` (2026-09-29): KHÔNG CÒN BẢN NHÁP. `GET /config` trả cấu hình của
 * MỌI role, `PUT /config` ghi tất cả trong một giao dịch và agent thấy ngay ở hội thoại
 * kế tiếp. Từ `0967` (2026-09-30) tập role là DỮ LIỆU: `customer` luôn có, workspace tự
 * thêm/đổi tên/xoá role khác (`useVaiTro.ts`) — form theo `key`, không theo hằng. Tên hook giữ `useBanNhap` để không đổi mọi chỗ gọi —
 * «bản nháp» giờ chỉ còn nghĩa là `form`: phần người dùng đang sửa, chưa bấm Lưu.
 *
 * HAI MÀN, MỘT HOOK (2026-08-07): «Cấu hình chung» (`/agent`) và «Kỹ năng» của lĩnh vực
 * (`/ky-nang-bds`) sửa CÙNG một cấu hình. Chép vòng đọc-sửa-lưu ra hai màn là mở đúng
 * một lớp lỗi: màn A giữ ảnh chụp lúc mở, người dùng sang màn B sửa và lưu, quay lại A
 * bấm Lưu — A ghi đè bản của B.
 *
 * TRƯỜNG DÙNG CHUNG (`TRUONG_CHUNG`, người dùng chốt 2026-09-29): Danh tính + Chuẩn hoá
 * cách đọc là MỘT bộ giá trị cho mọi role — CHỈ ở FE. Backend vẫn lưu mỗi role một bản;
 * hook này giữ các bản đó luôn bằng nhau, lấy role MẶC ĐỊNH làm gốc:
 *   · lúc nạp: chép phần chung của role mặc định sang mọi role (hàng lệch nhau vì ai đó
 *     sửa DB tay, hay role mới tạo mang bộ mặc định, thì màn hiện đúng thứ sẽ được lưu),
 *   · lúc sửa: `suaChung()` ghi vào MỌI role.
 * Phạm vi · Giọng điệu · Kỹ năng chung là RIÊNG từng role (`sua(role, …)`). Kỹ năng BĐS
 * (`/ky-nang-bds`) chưa chia tab nên bật/tắt ở đó áp cho mọi role.
 *
 * TẬP ROLE ĐỔI GIỮA CHỪNG (thêm/xoá ở `useVaiTro`, áp dụng ngay): form GIỮ phần đang sửa
 * của role còn lại, thêm role mới từ server (kèm phần chung đang gõ), bỏ role đã xoá.
 * Nạp lại cả form là xoá mất những gì người dùng chưa kịp Lưu.
 *
 * `form` vẫn là state cục bộ của từng lần mount: rời màn là bỏ phần chưa lưu, và
 * `ManTheoWorkspace` (routes/_app.tsx) dựa vào việc state chết theo lần mount khi đổi
 * workspace.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  docCauHinh,
  docTrangThai,
  luuCauHinh,
  KEY_ROLE_MAC_DINH,
  SCHEMA_VERSION_HIEN_TAI,
  type CauHinh,
  type CauHinhOut,
  type ConfigPayload,
  type VaiTro,
  type VaiTroMeta,
} from './api'
import { locKyNangTheoLinhVuc, type LinhVuc } from './linhVuc'
import { CAU_HINH_QUERY } from './contracts'

/** Payload nào cũng phải nạp được vào form, kể cả khi backend thiếu một trường.
 *
 * DỰNG LẠI `danh_tinh` từ năm khoá, KHÔNG spread: khoá lạ bị loại vì nó không được dựng,
 * và vì object literal này phải khớp `ConfigPayload['danh_tinh']`, thêm một ô vào kiểu
 * mà quên thêm ở đây là lỗi biên dịch. */
function chuanHoa(p: ConfigPayload): ConfigPayload {
  const tho = p.danh_tinh as unknown as Record<string, unknown>
  const chuoi = (k: string) => (typeof tho[k] === 'string' ? (tho[k] as string) : '')

  return {
    ...p,
    schema_version: SCHEMA_VERSION_HIEN_TAI,
    // Backend chưa deploy trả payload KHÔNG có trường này; `undefined` chảy vào `.map()`
    // của bảng là màn trắng, không phải một lỗi đọc được.
    tts_normalization: Array.isArray(p.tts_normalization) ? p.tts_normalization : [],
    danh_tinh: {
      ten_agent: chuoi('ten_agent'),
      ten_thuong_hieu: chuoi('ten_thuong_hieu'),
      // `|| 'em'` chứ không `?? 'em'`: chuỗi RỖNG cũng phải thành mặc định. Backend
      // đòi `min_length=1` — xem `contracts.DanhTinh`.
      tu_xung: chuoi('tu_xung') || 'em',
      goi_khach: chuoi('goi_khach') || 'anh/chị',
      loi_chao: chuoi('loi_chao'),
    },
  }
}

/** Lối vào cho test — phép sinh mặc định của `chuanHoa` giữ màn không trắng. */
export const chuanHoaChoTest = chuanHoa

/** Khoá gốc của `ConfigPayload` là DÙNG CHUNG cho mọi role — xem đầu file. */
export const TRUONG_CHUNG = ['danh_tinh', 'tts_normalization'] as const
type PhanChung = Pick<ConfigPayload, (typeof TRUONG_CHUNG)[number]>

function layChung(p: ConfigPayload): PhanChung {
  return { danh_tinh: p.danh_tinh, tts_normalization: p.tts_normalization }
}

/** Role làm GỐC cho phần chung: role mặc định, không có (không nên xảy ra) thì role đầu. */
function khoaGoc(c: CauHinh): VaiTro {
  return KEY_ROLE_MAC_DINH in c ? KEY_ROLE_MAC_DINH : (Object.keys(c)[0] ?? KEY_ROLE_MAC_DINH)
}

/** Chuẩn hoá mọi role + ép phần chung của mọi role bằng role gốc. */
function tuServer(d: CauHinhOut): CauHinh {
  const tho: CauHinh = Object.fromEntries(d.vaiTro.map((v) => [v.key, chuanHoa(v.cauHinh)]))
  const goc = tho[khoaGoc(tho)]
  if (!goc) return tho
  const chung = layChung(goc)
  return Object.fromEntries(Object.entries(tho).map(([k, p]) => [k, { ...p, ...chung }]))
}

/** Tập role trên server đổi (thêm/xoá) ⇒ ghép vào form mà KHÔNG mất phần đang sửa. Trả
 *  đúng `c` khi tập role không đổi — `setForm` với cùng tham chiếu thì không render lại. */
function ghepTapRole(c: CauHinh, d: CauHinhOut): CauHinh {
  const keys = d.vaiTro.map((v) => v.key)
  const giong = keys.length === Object.keys(c).length && keys.every((k) => k in c)
  if (giong) return c
  const server = tuServer(d)
  const gocForm = c[khoaGoc(c)]
  const chung = gocForm ? layChung(gocForm) : null
  return Object.fromEntries(
    keys.map((k) => {
      const cu = c[k]
      if (cu) return [k, cu]
      const moi = server[k] as ConfigPayload
      return [k, chung ? { ...moi, ...chung } : moi]
    }),
  )
}

/** Đường dẫn các trường khác nhau giữa hai payload, vd `pham_vi.lam_gi`. So từng lá. */
function khac(a: unknown, b: unknown, tienTo = ''): string[] {
  const laObj = (x: unknown): x is Record<string, unknown> =>
    typeof x === 'object' && x !== null && !Array.isArray(x)
  if (laObj(a) && laObj(b)) {
    return [...new Set([...Object.keys(a), ...Object.keys(b)])]
      .sort()
      .flatMap((k) => khac(a[k], b[k], `${tienTo}${k}.`))
  }
  return JSON.stringify(a) === JSON.stringify(b) ? [] : [tienTo.slice(0, -1)]
}

/** Thay đổi CHƯA LƯU, chia theo nhóm hiển thị: phần chung một lần, phần riêng theo role.
 *
 * Tính ở client vì `POST /config/preview` đã bỏ (backend `0966`). Phần chung đọc từ role
 * gốc — mọi role luôn bằng nhau ở phần đó (`tuServer`/`suaChung`). Chỉ so role có ở CẢ
 * HAI phía: role vừa thêm/xoá đã được áp dụng ngay, không phải «thay đổi chưa lưu». */
export function thayDoi(
  goc: CauHinh,
  form: CauHinh,
): { chung: string[]; theoRole: Record<VaiTro, string[]> } {
  const laChung = (d: string) => TRUONG_CHUNG.some((t) => d === t || d.startsWith(`${t}.`))
  const keys = Object.keys(form).filter((k) => k in goc)
  const cua = (r: VaiTro) => khac(goc[r], form[r])
  const k0 = khoaGoc(form)
  return {
    chung: k0 in goc ? cua(k0).filter(laChung) : [],
    theoRole: Object.fromEntries(keys.map((r) => [r, cua(r).filter((d) => !laChung(d))])),
  }
}

/** `onApDungXong` chạy sau khi `PUT /config` thành công. `/agent` dùng nó để đóng form
 * về chế độ xem. Màn chỉ-sửa bỏ trống tham số này. */
export function useBanNhap(opts: { onApDungXong?: () => void } = {}) {
  const qc = useQueryClient()
  const nhap = useQuery({ queryKey: CAU_HINH_QUERY, queryFn: docCauHinh })
  const trangThai = useQuery({ queryKey: ['config', 'status'], queryFn: docTrangThai })

  const [form, setForm] = useState<CauHinh | null>(null)
  const [moDialog, setMoDialog] = useState(false)
  // Số vừa ghi, để xác nhận bằng một con số thay vì bằng im lặng.
  const [vuaApDung, setVuaApDung] = useState<number | null>(null)

  const goc = nhap.data ? tuServer(nhap.data) : null

  useEffect(() => {
    const d = nhap.data
    if (!d) return
    setForm((c) => (c === null ? tuServer(d) : ghepTapRole(c, d)))
  }, [nhap.data])

  // Sửa bất cứ gì ⇒ xác nhận «Đã áp dụng» phải tắt ngay: để nó lại là nói bản đang gõ
  // đã ra khách, đúng cái nói dối mà HT01 §II.2.1 cấm.
  function doi(f: (c: CauHinh) => CauHinh) {
    setForm((c) => (c ? f(c) : c))
    setVuaApDung(null)
  }

  /** Sửa trường RIÊNG của một role. */
  const sua = (role: VaiTro, f: (p: ConfigPayload) => ConfigPayload) =>
    doi((c) => {
      const p = c[role]
      // Role vừa bị xoá ở nơi khác giữa lúc gõ — không hồi sinh nó bằng một cú gõ phím.
      return p ? { ...c, [role]: f(p) } : c
    })

  /** Sửa trường DÙNG CHUNG — ghi vào MỌI role. Dựng từ role gốc rồi chép sang các role
   * còn lại, để các bản không thể lệch nhau dù `f` có đọc giá trị cũ. */
  const suaChung = (f: (p: ConfigPayload) => ConfigPayload) =>
    doi((c) => {
      const goc = c[khoaGoc(c)]
      if (!goc) return c
      const chung = layChung(f(goc))
      return Object.fromEntries(Object.entries(c).map(([k, p]) => [k, { ...p, ...chung }]))
    })

  /** Bỏ mọi thay đổi chưa lưu, quay về đúng thứ đang lưu trên server.
   *
   * KHÔNG `setForm(null)` rồi để effect nạp lại: giữa hai lần render `form` là `null`,
   * và mọi màn coi đó là «đang tải» — nút Huỷ sẽ nháy «Đang tải…». */
  function huy() {
    if (nhap.data) setForm(tuServer(nhap.data))
  }

  /** `role` vắng mặt ⇒ áp cho MỌI role (màn `/ky-nang-bds` chưa chia tab). */
  const doiKyNang = (ten: string, bat: boolean, role?: VaiTro) =>
    doi((c) => {
      const ra = { ...c }
      for (const r of role ? [role] : Object.keys(c)) {
        const p = c[r]
        if (!p) continue
        const ds = p.tools.enabled.filter((t) => t !== ten)
        ra[r] = { ...p, tools: { enabled: bat ? [...ds, ten] : ds } }
      }
      return ra
    })

  const mApDung = useMutation({
    mutationFn: async () => {
      // Lọc kỹ năng của lĩnh vực đang TẮT ngay trước khi ghi — chỗ duy nhất payload rời
      // client. Lọc lúc LƯU chứ không lúc gõ: tắt một lĩnh vực rồi bật lại mà mất sạch
      // lựa chọn kỹ năng là một cú xoá dữ liệu không ai xin phép.
      const c = form as CauHinh
      const dsLinhVuc = qc.getQueryData<LinhVuc[]>(['linh-vuc']) ?? []
      const loc = (p: ConfigPayload): ConfigPayload => ({
        ...p,
        tools: { enabled: locKyNangTheoLinhVuc(p.tools.enabled, dsLinhVuc) },
      })
      return luuCauHinh(Object.fromEntries(Object.entries(c).map(([k, p]) => [k, loc(p)])))
    },
    onSuccess: (kq) => {
      setMoDialog(false)
      setVuaApDung(kq.version)
      // Nạp lại TRƯỚC khi báo xong: `huy()` sau đó phải về đúng bản vừa lưu, không về
      // ảnh chụp cũ.
      void qc.invalidateQueries({ queryKey: ['config'] })
      opts.onApDungXong?.()
    },
    onError: () => setVuaApDung(null),
  })

  /** Chưa ai cấu hình (ít nhất một role vẫn là bộ platform sinh). `/agent` dùng nó để
   * mở thẳng vào form thay vì bản tóm tắt. */
  const laMacDinh = nhap.data?.vaiTro.some((v) => v.laMacDinh) ?? false

  /** Role theo thứ tự tab — CHỈ những role đã có trong `form` (giữa lúc server vừa báo
   *  role mới và effect ghép xong, tab chưa được hiện: form chưa có gì để hiện cho nó). */
  const vaiTro: VaiTroMeta[] = (nhap.data?.vaiTro ?? [])
    .filter((v) => form !== null && v.key in form)
    .map(({ key, ten, icon, macDinh }) => ({ key, ten, icon, macDinh }))

  return {
    nhap,
    trangThai,
    goc,
    form,
    sua,
    suaChung,
    huy,
    doiKyNang,
    mApDung,
    moDialog,
    setMoDialog,
    vuaApDung,
    laMacDinh,
    vaiTro,
    soRoleToiDa: nhap.data?.soRoleToiDa ?? 0,
  }
}
