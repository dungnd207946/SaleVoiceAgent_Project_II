/**
 * Màn `/users` — THÀNH VIÊN CỦA WORKSPACE ĐANG MỞ.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 *  TRỤC LÀ WORKSPACE, KHÔNG PHẢI TỔ CHỨC (đổi 2026-08-09)
 * ═══════════════════════════════════════════════════════════════════════════
 * Trước đó bảng liệt kê người dùng TOÀN TỔ CHỨC với một cột động «Vai trò tại
 * <workspace>». Một người mang vai trò khác nhau ở nhiều workspace, nên cột đó
 * hoặc phải là hàng lồng, hoặc phải kèm một dòng giải thích. Theo trục workspace
 * thì MỖI HÀNG ĐÚNG MỘT VAI TRÒ — bảng phẳng, không giải thích. Muốn xem
 * workspace khác thì đổi switcher (lối Linear, Slack).
 *
 * KHÔNG CÒN HAI NHÁNH owner / non-owner. Mọi người thấy CÙNG một bảng; ai được
 * làm gì thì backend nói bằng 403, và các mục ghi trong menu ⋯ ẩn theo `session.
 * vai trò. ⚠ Ẩn nút là cho ĐỠ RỐI MẮT (PQ_01 §BR-Q03), KHÔNG phải bảo vệ.
 *
 * KHÔNG CÒN TAB «Vai trò». 13 action ở lại backend làm ĐỊNH NGHĨA của 4 vai trò
 * dựng sẵn; đường TỰ TẠO vai trò rời giao diện. Endpoint `POST/PATCH/DELETE
 * /roles` và `GET /actions` vẫn sống ở backend — đây là cắt bề mặt, không xoá
 * năng lực. Spec 2026-08-09 §2.1.
 *
 * KHÔNG CÓ `<h1>` Ở ĐÂY — `components/shell/Topbar.tsx` đã render nó từ nav label.
 */
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSession } from '@/lib/session'
import { useKhoManHinh } from '@/lib/khoManHinh'
import {
  Bang,
  ChanBang,
  DauBang,
  TD_GON,
  Hang,
  HANG_NUT,
  NUT_CHINH,
  NUT_PHU,
  O_LOC,
  PILL,
  PILL_SAT_TRAI,
  TD,
  TD_PHU,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { KhoRong } from '@/components/ui/TrangThai'
import { LoiApi } from '@/lib/http'
import { chuCai } from '@/lib/chuCai'
import { MAU_CHO_XAC_NHAN, MAU_LIFECYCLE, NHAN_CHO_XAC_NHAN, NHAN_LIFECYCLE } from '../nhan'
import {
  goThanhVien,
  guiLaiLoiMoi,
  khoaHang,
  KHOA_TV,
  moiLaiThanhVien,
  taiThanhVien,
  thuHoiLoiMoi,
  urlMoi,
  type MemberOut,
} from '../thanhVien'
import { DoiVaiTroDialog } from './DoiVaiTroDialog'
import { MenuHang, type MucMenu } from './MenuHang'
import { MoiThanhVienDialog } from './MoiThanhVienDialog'

const CAO_BANG = 'max-h-[560px]'

const COT: readonly Cot[] = [
  // HAI CỘT ĐẦU CÙNG `w-2/5` ⇒ ba cột chữ cách đều nhau, còn Trạng thái và cột
  // thao tác co về bề rộng nội dung nên bị đẩy sát lề phải.
  //
  // ⚠ ĐỪNG dùng hai `w-full` liền nhau để «chia đôi phần dư» — đã thử, KHÔNG
  // chia: `table-auto` cho cột `w-full` đầu tiên nuốt gần hết (đo được 769px)
  // và cột thứ hai còn 108px, khoảng cách ra 769/109. Bề rộng bằng nhau phải
  // khai tường minh bằng nhau.
  //
  // Cả ba đều căn TRÁI. Bản trước dùng `phai: true` cho Trạng thái — mép PHẢI
  // trùng nhau nhưng mép TRÁI lệch theo độ dài chuỗi («Đang hoạt động» vs «Chờ
  // nhận lời mời»), mà mắt đọc chỗ bắt đầu. Vị trí cột là việc của BỀ RỘNG,
  // không phải của `text-align` — hai thứ đó bị gộp làm một suốt ba lượt sửa.
  { nhan: 'Thành viên', rong: 'w-2/5' },
  { nhan: 'Vai trò', rong: 'w-2/5' },
  { nhan: 'Trạng thái' },
  { nhan: '', phai: true },
]

const LOC_TRANG_THAI: readonly { readonly value: string; readonly nhan: string }[] = [
  { value: 'cho-xac-nhan', nhan: NHAN_CHO_XAC_NHAN },
  { value: 'active', nhan: NHAN_LIFECYCLE.active },
  { value: 'pending', nhan: NHAN_LIFECYCLE.pending },
  { value: 'suspended', nhan: NHAN_LIFECYCLE.suspended },
]

export function UserAdmin() {
  const { session } = useSession()
  const { data, error, isPending } = useQuery({ queryKey: KHOA_TV, queryFn: taiThanhVien })
  const [tim, setTim] = useState('')
  const [locTrangThai, setLocTrangThai] = useState('')
  const [moMoi, setMoMoi] = useState(false)

  const dienThoai = useKhoManHinh() === 'mobile'
  const tenWorkspace =
    session.workspaces.find((w) => w.id === session.currentWorkspaceId)?.name ?? 'workspace này'

  if (isPending)
    return (
      <div className="px-7 py-6 max-md:px-4 max-md:py-4">
        <p className="mb-3.5 text-[14px] text-muted">Đang tải…</p>
        <KhungCho dong={5} />
      </div>
    )

  if (error) {
    // Hai nguyên nhân, hai câu: backend chết mà UI báo "không có quyền" thì
    // người dùng đi xin quyền và không ai báo sự cố.
    const khongCoQuyen = error instanceof LoiApi && error.code === 'FORBIDDEN'
    return (
      <div className="px-7 py-6 max-md:px-4 max-md:py-4">
        <p role="alert" className="text-[14px] text-muted">
          {khongCoQuyen
            ? 'Bạn không có quyền xem danh sách thành viên của workspace này.'
            : `Không tải được danh sách thành viên: ${error.message}`}
        </p>
      </div>
    )
  }

  const chuoi = tim.trim().toLowerCase()
  const hien = data.filter(
    (m) =>
      (chuoi === '' ||
        (m.name ?? '').toLowerCase().includes(chuoi) ||
        m.email.toLowerCase().includes(chuoi)) &&
      // `cho-xac-nhan` KHÔNG phải một `Lifecycle` — nó là một `kind`. Bộ lọc trạng
      // thái của bảng gộp hai trục vì người dùng chỉ thấy MỘT cột «Trạng thái».
      (locTrangThai === '' ||
        (locTrangThai === 'cho-xac-nhan'
          ? m.kind === 'invite'
          : m.kind === 'member' && m.lifecycle === locTrangThai)),
  )
  const daLoc = chuoi !== '' || locTrangThai !== ''

  return (
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      {/* KHÔNG CÓ `DauMuc` Ở ĐÂY (bỏ 2026-08-10, đo trên trình duyệt).
          Chữ «Thành viên» từng hiện BA lần trên cùng một trục dọc: `<h1>` của
          Topbar ở y=19 · `<h2>` của `DauMuc` ở y=96 · tiêu đề cột đầu ở y=200,
          cả ba cùng x=336. Đúng lỗi CLAUDE.md đã ghi cho `/convos` («cùng một
          chữ ở y=19 và y=113»).

          Docstring của `DauMuc` biện minh cho `<h2>` bằng lý lẽ «một bảng có
          nhãn xếp cạnh một bảng không nhãn thì trình đọc màn hình đọc ra một
          bảng vô danh» — lý lẽ ấy viết khi màn này có HAI bảng. Còn một thì nó
          hết đứng, và cái tên chuyển sang `aria-label` của `<table>`: trình đọc
          màn hình vẫn có tên, mắt không phải đọc lại chữ vừa đọc.

          «Workspace <tên>» cũng đi theo: switcher ở đỉnh panel cách đó 200px
          luôn hiện đúng cái tên ấy. Nó cần thiết ở bản CŨ vì bảng khi đó liệt kê
          người của CẢ TỔ CHỨC và chỉ một cột thuộc về workspace; bảng này thì
          workspace là trục của chính nó. */}
      <TheBang cao={CAO_BANG}>
        <ThanhCong>
          {/* Mobile: ô tìm một hàng · ô lọc + nút Mời chung hàng dưới
              (ThanhCong xuống dòng ở `max-md`). `max-md:contents` gỡ vỏ nhóm để
              ô lọc và nút cùng tham gia MỘT hàng flex của ThanhCong. */}
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2.5 max-md:contents">
            <input
              type="search"
              aria-label="Tìm theo họ tên hoặc địa chỉ đăng nhập"
              placeholder="Tìm theo tên hoặc email…"
              value={tim}
              onChange={(e) => setTim(e.target.value)}
              className={`${O_LOC} min-w-[190px] max-w-[300px] flex-1 max-md:min-w-0 max-md:max-w-none max-md:basis-full`}
            />
            <select
              aria-label="Lọc theo trạng thái"
              value={locTrangThai}
              onChange={(e) => setLocTrangThai(e.target.value)}
              className={`${O_LOC} o-chon text-muted max-md:min-w-0 max-md:flex-1`}
            >
              <option value="">Tất cả</option>
              {LOC_TRANG_THAI.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.nhan}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className={`${NUT_CHINH} flex-none`} onClick={() => setMoMoi(true)}>
            Mời thành viên
          </button>
        </ThanhCong>

        {/* ⚠ BA NHÁNH BỌC ĐÚNG VÙNG BẢNG, KHÔNG `return` sớm cả component — nếu
            không, gõ vào ô tìm sẽ unmount cả dải lọc và ô mất focus giữa lúc
            đang gõ. Cùng cái bẫy `DuAnList` đã ghi lại. */}
        <VungCuon>
          {data.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Workspace này chưa có thành viên nào."
                huongDan="Mời người đầu tiên để họ vào được workspace."
              />
            </div>
          ) : hien.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Không có thành viên nào khớp bộ lọc."
                huongDan="Xoá bộ lọc để xem lại toàn bộ workspace."
                viec={
                  <button
                    type="button"
                    className={NUT_PHU}
                    onClick={() => {
                      setTim('')
                      setLocTrangThai('')
                    }}
                  >
                    Xoá bộ lọc
                  </button>
                }
              />
            </div>
          ) : (
            <Bang nhan={`Thành viên của workspace ${tenWorkspace}`} gon={dienThoai}>
              {/* Điện thoại: hai cột — thành viên (vai trò + trạng thái xuống dòng phụ) và ⋯. */}
              <DauBang cot={dienThoai ? [COT[0]!, COT[3]!] : COT} />
              <tbody>
                {hien.map((m) => (
                  <HangThanhVien key={khoaHang(m)} m={m} />
                ))}
              </tbody>
            </Bang>
          )}
        </VungCuon>

        {daLoc && hien.length > 0 && (
          <ChanBang>
            <p className="text-phu text-muted-2">
              Hiện {hien.length} / {data.length} dòng
            </p>
          </ChanBang>
        )}
      </TheBang>

      {moMoi && <MoiThanhVienDialog onDong={() => setMoMoi(false)} />}
    </div>
  )
}

function HangThanhVien({ m }: { m: MemberOut }) {
  const dienThoai = useKhoManHinh() === 'mobile'
  const { session } = useSession()
  const queryClient = useQueryClient()
  const laLoiMoi = m.kind === 'invite'
  const laChinhMinh = !laLoiMoi && m.userId === session.user.id
  const [hop, setHop] = useState<'doi-vai-tro' | 'go' | null>(null)
  const [linkMoi, setLinkMoi] = useState<string | null>(null)

  const lamMoi = () => void queryClient.invalidateQueries({ queryKey: KHOA_TV })

  const go = useMutation({
    // `m.userId!` an toàn: mục «Gỡ» chỉ vào `muc` ở nhánh `!laLoiMoi`, và mọi hàng
    // `kind='member'` đều có `userId`.
    mutationFn: () => goThanhVien(m.userId!),
    onSuccess: () => {
      lamMoi()
      setHop(null)
    },
  })
  const moiLai = useMutation({
    // HAI ĐƯỜNG KHÁC NHAU, không phải một đường có tham số: hàng lời mời định danh
    // bằng email (có thể chưa có `userId` nào), hàng thành viên `pending` di sản
    // định danh bằng `userId` và đường đó ĐẶT LẠI MẬT KHẨU.
    mutationFn: () => (laLoiMoi ? guiLaiLoiMoi(m.email) : moiLaiThanhVien(m.userId!)),
    onSuccess: (ra) => setLinkMoi(urlMoi(ra.invitePath)),
  })
  const thuHoi = useMutation({
    mutationFn: () => thuHoiLoiMoi(m.email),
    onSuccess: lamMoi,
  })

  // Ẩn mục là cho ĐỠ RỐI MẮT (PQ_01 §BR-Q03), KHÔNG phải bảo vệ — backend chặn
  // ca này bằng 409 `SELF_LOCKOUT` (`thanh_vien.go`).
  //
  // Vế `!m.isOrgOwner` ĐÃ GỠ 2026-08-17 cùng trường `isOrgOwner`: nó phái sinh từ
  // `users.org_role`, cột bị xoá ở migration `0106`. Backend chưa bao giờ trả
  // trường đó, nên `!undefined === true` và vị từ này THỰC TẾ đã là `!laChinhMinh`
  // suốt thời gian qua — gỡ vế đó không đổi hành vi nào.
  // ⚠ `muc` RỖNG ĐƯỢC kể từ khi «Sửa hồ sơ…» rời menu: một hàng vừa là CHÍNH MÌNH
  // vừa không mang `roleId` rớt cả ba điều kiện. `MenuHang` trả `null` khi rỗng
  // nên hàng đó không có nút `⋯` — chủ ý, không phải nút gãy: một menu mở ra
  // trống rỗng còn tệ hơn không có menu. Trước 2026-08-09 màn đã ở đúng trạng
  // thái này, `MenuHang` vẫn giữ nhánh đó nguyên vẹn.
  const muc: MucMenu[] = laLoiMoi
    ? [
        // KHÔNG có «Đổi vai trò…»: sửa vai trò của một lời mời chưa ai nhận là bề
        // mặt không ai xin. KHÔNG có «Gỡ khỏi workspace»: chưa vào thì không gỡ.
        { key: 'gui-lai', nhan: 'Gửi lại lời mời', onChon: () => moiLai.mutate() },
        { key: 'thu-hoi', nhan: 'Thu hồi lời mời', onChon: () => thuHoi.mutate(), phaHuy: true },
      ]
    : [
        // Rẽ theo `roleId`: vị từ phải nói về thứ đang quyết định (có vai trò hay
        // không), không nói về lý do vì sao không có.
        ...(m.roleId !== null
          ? [{ key: 'vai-tro', nhan: 'Đổi vai trò…', onChon: () => setHop('doi-vai-tro') }]
          : []),
        // «Sửa hồ sơ…» ĐÃ GỠ 2026-08-17 (người dùng chốt). Nó là mục DUY NHẤT của
        // màn còn chạm `/users*` — khối quản trị user TOÀN HỆ THỐNG mà backend
        // đóng bằng `USERS_ADMIN_ENABLED=false` từ migration `0106` (cửa quyền cũ
        // `users.org_role = 'owner'` biến mất cùng tầng tổ chức, và KHÔNG có gì
        // thay thế). Nên mục đó chỉ dẫn tới một hộp thoại 403 `FEATURE_DISABLED`
        // xuống cấp — một mục menu không bao giờ làm được việc nó hứa.
        //
        // Bật lại KHÔNG phải đổi một biến env: `sua_ho_so()` phía backend sửa
        // được BẤT KỲ ai trong hệ thống, nên mở cờ là cho Quản trị của một
        // workspace sửa user của MỌI workspace khác. Cần mô hình admin thật trước.
        //
        // Muốn người tự sửa hồ sơ của CHÍNH MÌNH thì hướng đúng là một màn hồ sơ
        // cá nhân (`/auth/me`), không phải mở lại khối này.
        ...(m.lifecycle === 'pending'
          ? [{ key: 'moi-lai', nhan: 'Gửi lại lời mời', onChon: () => moiLai.mutate() }]
          : []),
        ...(!laChinhMinh
          ? [{ key: 'go', nhan: 'Gỡ khỏi workspace', onChon: () => setHop('go'), phaHuy: true }]
          : []),
      ]

  // Hai pill dựng MỘT lần: desktop đặt vào cột riêng, điện thoại đặt thành dòng phụ
  // dưới email (bảng gọn hai cột — xem `Bang gon`). Kéo pill sát mép cột
  // (`PILL_SAT_TRAI`) chỉ đúng khi pill đứng trong cột của nó.
  const satTrai = dienThoai ? '' : PILL_SAT_TRAI
  const vaiTro = (
    <>
      {/* PILL «CHỦ TỔ CHỨC» ĐÃ GỠ 2026-08-17 cùng trường `isOrgOwner`.
              Nó phái sinh từ `users.org_role`, cột bị xoá ở migration `0106` —
              backend không còn cách nào tính, và chưa bao giờ trả trường đó, nên
              nhánh này THỰC TẾ chưa từng chạy: `undefined` luôn rơi xuống nhánh
              `m.role === null` dưới đây. Gỡ không đổi hành vi nào.

              Khái niệm «chủ tổ chức» chết cùng tầng organization. Ai muốn dựng lại
              một pill kiểu này phải trả lời trước: lấy giá trị từ đâu. */}
      {m.role === null ? (
        // Không có vai trò mà vẫn là thành viên ⇒ dữ liệu lệch (backend khai
        // `role: str` không nullable). «—» chứ không để trống: một `<td>` rỗng
        // trông y hệt một `<td>` chưa nạp xong — cùng lý lẽ chữ «Chưa đặt» của
        // `GiaTri`.
        <span className="text-muted-3">—</span>
      ) : (
        <span className={`${PILL} ${satTrai} bg-badge-neutral-bg text-badge-neutral-fg`}>
          {m.role}
        </span>
      )}
    </>
  )
  const trangThai = (
    <>
      {laLoiMoi ? (
        <span className={`${PILL} ${satTrai} ${MAU_CHO_XAC_NHAN}`}>{NHAN_CHO_XAC_NHAN}</span>
      ) : m.lifecycle === null ? (
        <span className="text-muted-3">—</span>
      ) : (
        <span className={`${PILL} ${satTrai} ${MAU_LIFECYCLE[m.lifecycle]}`}>
          {NHAN_LIFECYCLE[m.lifecycle]}
        </span>
      )}
    </>
  )

  return (
    <>
      <Hang>
        <td className={`${TD} ${TD_GON}`}>
          <div className="flex items-start gap-2.5">
            <span
              aria-hidden="true"
              className={`mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full text-[12px] font-semibold ${
                laLoiMoi ? 'bg-chrome-2 text-muted-2' : 'bg-acs text-ac'
              }`}
            >
              {/* Hàng lời mời chưa có tên để rút chữ cái đầu — một ô «?» trông như
                  dữ liệu hỏng. Phong bì nói đúng thứ hàng đó là.

                  `m.avatar` (2026-08-25): backend trả đúng avatar người đó đã set
                  ở «Hồ sơ & tuỳ chọn» — CÓ thì ảnh thay chữ cái (cùng khuôn
                  `noiDungAvatar` bên ops: phủ trọn ô tròn, `alt` rỗng vì span cha
                  đã `aria-hidden`). Backend cũ chưa trả ⇒ `undefined` ⇒ rơi về
                  chữ cái như cũ (khiên trường-mới). */}
              {laLoiMoi ? (
                '✉'
              ) : m.avatar ? (
                <img src={m.avatar} alt="" className="size-full rounded-full" />
              ) : (
                chuCai(m.name ?? m.email)
              )}
            </span>
            <div className="min-w-0">
              <div className="truncate font-semibold text-fg">
                {/* Hàng lời mời: EMAIL luôn là dòng chính (spec §7.2) — nó là định
                    danh THẬT của hàng này, đúng cái `guiLaiLoiMoi(m.email)` và
                    `thuHoiLoiMoi(m.email)` gửi đi. `invite_existing` CÓ tên (JOIN
                    `users`) nhưng để tên thắng ở đây thì admin không còn thấy email
                    nào trên hàng, và hai lời mời trùng tên hiển thị y hệt nhau. */}
                {laLoiMoi ? m.email : (m.name ?? m.email)}
                {laChinhMinh && (
                  <span className="ml-1.5 text-[12px] font-normal text-muted">(bạn)</span>
                )}
              </div>
              <div className={`truncate text-[12px] text-muted-2 ${laLoiMoi ? '' : 'font-mono'}`}>
                {laLoiMoi
                  ? // Tên (nếu có, `invite_existing`) đi CẠNH trạng thái tài khoản,
                    // không thay nó: biết thêm "mời ai" dễ đọc hơn hẳn một dòng
                    // trống, miễn dòng chính (email) vẫn là thứ đọc được ngay.
                    [m.name, m.userId === null ? 'chưa có tài khoản' : 'đã có tài khoản']
                      .filter(Boolean)
                      .join(' · ')
                  : m.email}
              </div>
              {dienThoai && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {vaiTro}
                  {trangThai}
                </div>
              )}
            </div>
          </div>
        </td>
        {dienThoai ? null : <td className={TD_PHU}>{vaiTro}</td>}
        {dienThoai ? null : <td className={TD}>{trangThai}</td>}
        <td className={`${TD} text-right`}>
          <MenuHang nhan={m.name ?? m.email} muc={muc} />
          {linkMoi && (
            <span className="mt-1 block break-all text-[11.5px] text-muted-2">{linkMoi}</span>
          )}
          {(go.error ?? moiLai.error ?? thuHoi.error) && (
            <span role="alert" className="mt-1 block text-[12px] text-badge-alert-fg">
              {(go.error ?? moiLai.error ?? thuHoi.error)?.message}
            </span>
          )}
        </td>
      </Hang>
      {hop === 'doi-vai-tro' && <DoiVaiTroDialog m={m} onDong={() => setHop(null)} />}
      {hop === 'go' && (
        <XacNhanGo
          ten={m.name ?? m.email}
          dangGui={go.isPending}
          onDong={() => setHop(null)}
          onGo={() => go.mutate()}
        />
      )}
    </>
  )
}

/**
 * Xác nhận gỡ — hộp thoại thật, KHÔNG `window.confirm`.
 *
 * Gỡ một người đang hoạt động là hành động không hoàn tác được và câu hỏi phải
 * nói rõ nó KHÔNG xoá tài khoản. `window.confirm` không cho định dạng, không
 * cho `role="dialog"`, và jsdom không render nó.
 */
function XacNhanGo({
  ten,
  dangGui,
  onDong,
  onGo,
}: {
  ten: string
  dangGui: boolean
  onDong: () => void
  onGo: () => void
}) {
  // `createPortal` — cùng lý do `DoiVaiTroDialog`: mở từ TRONG một `<tr>`, và
  // `<dialog>` không phải con hợp lệ của `<tbody>`.
  return createPortal(
    <HopThoai
      onDong={onDong}
      aria-label={`Gỡ ${ten} khỏi workspace`}
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 className="text-the font-semibold text-fg">Gỡ khỏi workspace?</h2>
      <p className="mt-1.5 text-than leading-[1.55] text-muted">
        <span className="font-semibold text-fg">{ten}</span> mất quyền ở workspace này ngay lập tức.
        Tài khoản của họ trong tổ chức vẫn còn, và quyền ở workspace khác không đổi.
      </p>
      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" className={NUT_PHU} onClick={onDong}>
          Huỷ
        </button>
        <button type="button" className={NUT_CHINH} disabled={dangGui} onClick={onGo}>
          Gỡ
        </button>
      </div>
    </HopThoai>,
    document.body,
  )
}

/**
 * Khung chờ — nhịp của bảng thật, không phải chữ Đang tải… đứng một mình.
 *
 * `aria-hidden` + `role="presentation"`: đây là hình, không phải nội dung.
 */
function KhungCho({ dong }: { dong: number }) {
  return (
    <div
      aria-hidden="true"
      className="space-y-2.5 rounded-xl border border-border bg-surface p-4"
      role="presentation"
    >
      {Array.from({ length: dong }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-8 w-8 flex-none rounded-full bg-border-soft" />
          <div className="h-3 flex-1 rounded bg-border-soft" />
          <div className="h-3 w-24 rounded bg-border-soft" />
        </div>
      ))}
    </div>
  )
}
