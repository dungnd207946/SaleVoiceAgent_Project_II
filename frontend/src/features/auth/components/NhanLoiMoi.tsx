/**
 * Màn đặt mật khẩu từ link mời. CHƯA CÓ PHIÊN khi màn này render.
 *
 * Nên nó KHÔNG dùng `useSession()` và route của nó nằm NGOÀI `_app` — cùng lý lẽ
 * `routes/login.tsx` đã ghi: `_app` bọc `<SessionProvider>`, và provider đó đẩy
 * mọi thứ về `/login` khi `GET /me` trả 401. Đặt màn này bên trong sẽ tạo một
 * vòng: người được mời bấm link, bị đẩy về /login, và không có mật khẩu để vào.
 *
 * Ba trạng thái, ba màn khác nhau — và chúng phải khác nhau:
 *   · token còn hiệu lực  -> form đặt mật khẩu (hoặc nút xác nhận, xem `kind`)
 *   · token chết          -> câu giải thích + việc cần làm (xin link mới)
 *   · đặt xong            -> `invite_existing` vào thẳng app (backend đã đặt
 *     cookie phiên — người này ĐÃ có mật khẩu, không phải trường hợp vừa tạo
 *     nó ở đây); `signup`/`invite_new` vẫn đẩy sang /login như trước.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { LoiApi } from '@/lib/http'
import { nhanLoiMoi, xemLoiMoi } from '../api'

export function NhanLoiMoi({ token }: { token: string }) {
  const {
    data: loiMoi,
    error: loiTai,
    isPending,
  } = useQuery({
    queryKey: ['invite', token],
    queryFn: () => xemLoiMoi(token),
    // KHÔNG retry: 404 INVITE_INVALID là câu trả lời cuối cùng, không phải một sự
    // cố tạm thời. Thử lại chỉ làm người dùng chờ vô ích trước một màn lỗi.
    retry: false,
  })

  if (isPending) return <Khung>Đang kiểm tra lời mời…</Khung>

  if (loiTai) {
    const chet = loiTai instanceof LoiApi && loiTai.code === 'INVITE_INVALID'
    return (
      <Khung>
        <h1 className="text-[20px] font-semibold text-fg">
          {chet ? 'Lời mời không còn hiệu lực' : 'Không kiểm tra được lời mời'}
        </h1>
        <p role="alert" className="mx-auto mt-3 max-w-[420px] text-[14px] text-muted">
          {chet ? (
            // MỘT câu cho cả ba nguyên nhân (sai · đã dùng · hết hạn) — backend cố
            // ý không phân biệt, vì phân biệt cho một máy dò biết token nào đã từng
            // có thật. UI không được đoán thay.
            <>
              Link này đã được dùng, đã hết hạn (7 ngày), hoặc không đúng. Hãy đề nghị chủ tổ chức
              gửi lại một link mời mới.
            </>
          ) : (
            loiTai.message
          )}
        </p>
        <Link to="/login" className="mt-5 inline-block text-than font-semibold text-ac">
          Tới trang đăng nhập
        </Link>
      </Khung>
    )
  }

  return (
    <FormNhanLoiMoi
      token={token}
      email={loiMoi.email}
      ten={loiMoi.name}
      kind={loiMoi.kind}
      tenWorkspace={loiMoi.workspaceName}
    />
  )
}

/**
 * BA nhánh, và chúng phải khác nhau ở đúng những chỗ câu hỏi khác nhau:
 *   · `signup`          — «Hoàn tất đăng ký», ô mật khẩu, nút «Đặt mật khẩu»
 *   · `invite_new`      — «Tham gia workspace X», ô mật khẩu, nút «Tham gia workspace»
 *   · `invite_existing` — «Tham gia workspace X», KHÔNG ô mật khẩu, một nút
 *
 * `invite_existing` không có ô mật khẩu vì người này ĐÃ có mật khẩu. Hiện ô đó là
 * mời họ gõ một mật khẩu mới rồi tưởng nó đã đổi — backend trả 422
 * `INVITE_PASSWORD_NOT_ALLOWED` chính để chặn cái màn đó tồn tại.
 */
function FormNhanLoiMoi({
  token,
  email,
  ten,
  kind,
  tenWorkspace,
}: {
  token: string
  email: string
  ten: string | null
  kind: 'signup' | 'invite_new' | 'invite_existing'
  tenWorkspace: string | null
}) {
  const navigate = useNavigate()
  const [matKhau, setMatKhau] = useState('')
  const [nhapLai, setNhapLai] = useState('')
  const [loiKhop, setLoiKhop] = useState<string | null>(null)

  const canMatKhau = kind !== 'invite_existing'
  const laDangKy = kind === 'signup'

  const dat = useMutation({
    // `null` chứ không `''` cho nhánh không mật khẩu: `''` đi vào thân request
    // thành `password: ""` và ăn 422 — một chuỗi rỗng vẫn là một giá trị.
    mutationFn: () => nhanLoiMoi(token, canMatKhau ? matKhau : null),
    // CHỈ `invite_existing` có phiên ngay sau lượt này (backend đặt cookie —
    // xem docstring router `nhan_loi_moi`), nên chỉ nhánh đó vào thẳng app.
    // `signup`/`invite_new` vẫn đẩy về `/login`: mật khẩu vừa đặt, chưa có phiên.
    // Đích là `/dashboard`, KHÔNG `/`: từ 2026-08-10 `/` là trang giới thiệu công
    // khai (ngoài `_app`), cùng đích `LoginForm` dùng sau khi đăng nhập thường.
    onSuccess: () => void navigate({ to: kind === 'invite_existing' ? '/dashboard' : '/login', replace: true }),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoiKhop(null)
    if (canMatKhau && matKhau !== nhapLai) {
      setLoiKhop('Hai lần nhập mật khẩu không giống nhau')
      return
    }
    dat.mutate()
  }

  const tieuDe = laDangKy
    ? 'Hoàn tất đăng ký'
    : `Bạn được mời tham gia workspace ${tenWorkspace ?? ''}`.trim()

  return (
    <Khung>
      <form onSubmit={onSubmit} className="mx-auto w-full max-w-[360px] text-left">
        <h1 className="text-[20px] font-semibold text-fg">{tieuDe}</h1>
        <p className="mt-2 text-[14px] text-muted">
          {/* Lời chào theo tên CHỈ khi có tên. `invite_new` không có hàng `users`
              nào, nên «Chào null,» là chỗ dễ lọt nhất của màn này. */}
          {ten !== null && (
            <>
              Chào <span className="font-medium text-fg">{ten}</span>,{' '}
            </>
          )}
          {laDangKy
            ? 'hãy đặt mật khẩu để hoàn tất đăng ký.'
            : canMatKhau
              ? 'hãy đặt mật khẩu để tạo tài khoản và tham gia.'
              : 'bạn xác nhận tham gia workspace này chứ? Mật khẩu của bạn không thay đổi.'}
        </p>

        {/* Email hiện ra để người dùng biết họ đang đặt mật khẩu cho tài khoản nào
            — và nó CHỈ ĐỌC: đổi email ở đây thì token không còn trỏ vào ai.

            ⚠ NỀN LÀ `bg-chrome-2`, TUYỆT ĐỐI KHÔNG `bg-panel`. Hai token đều được
            gọi là "panel" trong theme.css và chúng NGƯỢC NHAU: `--color-chrome-2`
            (#f8f6f1) là panel nav sáng — chính cái comment của nó ghi "panel";
            còn `--color-panel` (#1a1c20) là mặt TỐI, chỉ dành cho khối «Thử ngay»
            và lớp phủ modal. Ô này từng dùng `bg-panel` và ra một ô gần như đen:
            `text-muted` trên nền đó đo được 2.90, dưới sàn AA 4.5, tức ô email
            không đọc được. Trên `chrome-2` là 5.44.

            Vẫn tô khác hai ô mật khẩu (`bg-surface`) chứ không đồng màu: đó là
            thứ duy nhất nói cho người dùng biết ô này không gõ được. */}
        <label htmlFor="nlm-email" className="mt-5 block text-than font-semibold text-fg">
          Email đăng nhập
        </label>
        <input
          id="nlm-email"
          readOnly
          value={email}
          autoComplete="username"
          className="mt-1.5 w-full rounded-md border border-border bg-chrome-2 px-3 py-2 font-mono text-than text-muted"
        />

        {canMatKhau && (
          <>
            <label htmlFor="nlm-mk" className="mt-4 block text-than font-semibold text-fg">
              Mật khẩu mới
            </label>
            <input
              id="nlm-mk"
              type="password"
              required
              autoComplete="new-password"
              placeholder="Nhập mật khẩu"
              value={matKhau}
              onChange={(e) => setMatKhau(e.target.value)}
              className="mt-1.5 w-full rounded-md border border-border-field bg-surface px-3 py-2 text-[14px]"
            />

            <label htmlFor="nlm-mk2" className="mt-4 block text-than font-semibold text-fg">
              Xác nhận mật khẩu
            </label>
            <input
              id="nlm-mk2"
              type="password"
              required
              autoComplete="new-password"
              placeholder="Xác nhận lại mật khẩu"
              value={nhapLai}
              onChange={(e) => setNhapLai(e.target.value)}
              className="mt-1.5 w-full rounded-md border border-border-field bg-surface px-3 py-2 text-[14px]"
            />
          </>
        )}

        {(loiKhop ?? dat.error) && (
          <p role="alert" className="mt-4 text-than text-badge-alert-fg">
            {loiKhop ?? cauLoiNhan(dat.error)}
          </p>
        )}

        <button
          type="submit"
          disabled={dat.isPending}
          className="mt-6 w-full rounded-md bg-ac px-4 py-2.5 text-[14px] font-semibold text-white hover:bg-acd disabled:opacity-60"
        >
          {dat.isPending ? 'Đang xử lý…' : laDangKy ? 'Đặt mật khẩu' : 'Tham gia workspace'}
        </button>
      </form>
    </Khung>
  )
}

/** Ba mã lỗi cần một câu riêng; còn lại dùng thông điệp của backend. */
function cauLoiNhan(e: unknown): string | undefined {
  if (!(e instanceof LoiApi)) return (e as Error | undefined)?.message
  if (e.code === 'INVITE_INVALID')
    return 'Lời mời vừa hết hiệu lực — hãy xin Quản trị workspace một link mới.'
  if (e.code === 'EMAIL_DA_CO_TAI_KHOAN')
    // 409 của ca đua: ai đó vừa đăng ký chính email này trong lúc lời mời còn treo.
    return 'Địa chỉ này giờ đã có tài khoản. Hãy đăng nhập rồi đề nghị Quản trị mời lại.'
  return e.message
}

/** Cùng khung căn giữa với `LoginForm` — hai màn này đứng cạnh nhau trong luồng. */
function Khung({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-bg px-6 text-center text-noi text-muted">
      <div>{children}</div>
    </div>
  )
}
