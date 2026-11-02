/**
 * ═══════════════════════════════════════════════════════════════════════════
 *  SEAM PHIÊN — M2a-BE thay ruột của file này, KHÔNG ai khác phải sửa gì
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Hôm nay `GET /api/v1/me` do MSW trả (xem `lib/msw/handlers.ts`): một user
 * giả + 3 workspace giả + `actions` = đủ 15 nhóm. Nhờ vậy dev FE của M4/M5/M6/
 * M7 dựng được màn mà chưa cần backend nào — spec §4②.
 *
 * M2a-BE làm gì: dựng endpoint thật cùng hình dạng, tắt MSW (`VITE_MSW=0`).
 * Không phải sửa `useSession()`, không phải sửa màn nào.
 *
 * ⚠ `actions` ở đây CHỈ để ẩn mục nav cho đỡ rối mắt (PQ_01 §BR-Q03). Không
 * bao giờ dùng nó thay cho check quyền ở API.
 * ⚠ PQ_01 §BR-Q04: vai trò đọc từ DB MỖI request, không từ phiếu đăng nhập.
 * Nên `staleTime` phải ngắn — gỡ quyền không được có cửa sổ 15 phút.
 */
import { useEffect, createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useNavigate } from '@tanstack/react-router'
// NGOẠI LỆ ranh giới module, đã khai ở tests/module-boundaries.test.ts ALLOWLIST:
// `switchWorkspace` phải gọi API thật, và client HTTP của seam auth sống ở
// features/auth vì module đó sở hữu nó. Chiều ngược lại — nhét client vào lib/ —
// làm lib/ biết hình dạng endpoint của một module, tệ hơn.
import { dangXuat as goiDangXuat, doiWorkspace } from '@/features/auth/api'
import type { Action } from './actions'

export interface Workspace {
  readonly id: string
  /** Slug hiện dưới tên workspace, font mono. */
  readonly slug: string
  readonly name: string
  /**
   * Tên gói — `null` ở MVP.
   *
   * `control.tenants` CỐ Ý không có cột `plan`: "hoá đơn không được gắn vào khoá
   * cách ly" (migration 0002), và màn `billing` đã hoãn khỏi MVP. Đường lùi đã để
   * sẵn là bảng `accounts` PHÍA TRÊN tenants. Xem spec M2a §4.3①.
   *
   * Prototype vẽ anphu · Growth; trả 'Growth' cứng là bơm dữ liệu giả vào một
   * luồng đăng nhập thật — đúng loại thứ sống sót tới lúc demo cho khách.
   */
  readonly plan: string | null
}

export interface SessionUser {
  readonly id: string
  readonly name: string
  readonly email: string
  /** Hai chữ trên avatar vuông ở chân sidebar. */
  readonly initials: string
  /** Data URI SVG DiceBear seed bằng `name` — backend cũ chưa trả ⇒ vắng khoá
   *  (khiên trường-mới), khi đó `UserMenu` rơi về ô chữ `initials` như trước. */
  readonly avatar?: string | null
  /** `false` = tài khoản Google-only, không có mật khẩu để đổi. Backend cũ chưa
   *  trả ⇒ vắng khoá — màn Hồ sơ coi như CÓ mật khẩu (đa số user), gõ sai lắm
   *  thì ăn 409 có thông điệp rõ. */
  readonly coMatKhau?: boolean
  /** Hai cột 0103, backend cũ chưa trả ⇒ vắng khoá — màn Hồ sơ hiện «Chưa đặt». */
  readonly phone?: string | null
  readonly jobTitle?: string | null
}

/**
 * `Organization` và `OrgRole` ĐÃ XOÁ 2026-08-15 cùng tầng tổ chức ở backend
 * (migration 0105/0106). Chỉ còn MỘT trục quyền: vai trò trong workspace hiện
 * tại, và nó đã nằm trong `actions`.
 */
export interface Session {
  readonly user: SessionUser
  readonly workspaces: readonly Workspace[]
  /**
   * `null` = chưa thuộc workspace nào (vừa tự đăng ký).
   *
   * Đây là điều kiện FE dùng để đưa tới màn "Tạo workspace đầu tiên" thay vì một
   * dashboard rỗng. Trước 2026-08-15 backend trả 409 NO_WORKSPACE cho trường hợp
   * này nên trường luôn có giá trị.
   */
  readonly currentWorkspaceId: string | null
  /** Quyền của user TRONG workspace hiện tại. Rỗng khi chưa có workspace. */
  readonly actions: readonly Action[]
}

interface SessionContextValue {
  readonly session: Session
  readonly currentWorkspace: Workspace
  /** Đúng khi user có TẤT CẢ action truyền vào. */
  readonly can: (required: readonly Action[]) => boolean
  /** Request THẬT tới `POST /api/v1/me/workspace`, không phải state client. */
  readonly switchWorkspace: (id: string) => Promise<void>
  /**
   * Request THẬT tới `POST /api/v1/auth/logout`, rồi mới xoá cache và rời màn.
   *
   * NÉM LỖI khi request hỏng, và cố ý không nuốt: gọi được hàm này xong mà phiên
   * vẫn sống trong Redis là trạng thái người dùng PHẢI biết. Người gọi hiện lỗi
   * tại chỗ và giữ nguyên màn — xem WorkspaceSwitcher.
   */
  readonly dangXuat: () => Promise<void>
}

const SessionContext = createContext<SessionContextValue | null>(null)

/**
 * Lỗi "chưa đăng nhập" — khác lỗi hạ tầng, và phải xử lý khác.
 *
 * 401 nghĩa là "đi đăng nhập đi"; 500 nghĩa là "backend hỏng, thử lại có nghĩa".
 * Gộp hai thứ làm một thì một sự cố hạ tầng trông như bị đăng xuất, và người dùng
 * gõ đúng mật khẩu nhiều lần rồi báo "hệ thống không cho tôi vào".
 */
export class ChuaDangNhap extends Error {}

async function fetchSession(): Promise<Session> {
  const res = await fetch('/api/v1/me')
  if (res.status === 401) throw new ChuaDangNhap('chưa đăng nhập')
  // Fail loud (spec §6.2): lỗi store nổi lên UI thành lỗi, không thành phiên rỗng.
  if (!res.ok) throw new Error(`GET /api/v1/me → ${res.status}`)
  return (await res.json()) as Session
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ['session'],
    queryFn: fetchSession,
    // BR-Q04 — vai trò không được cache lâu.
    staleTime: 30_000,
    // Cố tình KHÔNG khai `retry` ở đây: nó thuộc chính sách của QueryClient
    // (xem main.tsx). Khai lại tại chỗ thì test không đặt được `retry: false`
    // và mỗi lần thử nhánh lỗi phải chờ hết thời gian retry thật.
  })

  if (isPending) return <SessionSplash>Đang tải phiên…</SessionSplash>

  // Chưa đăng nhập KHÔNG phải lỗi hạ tầng — đẩy về /login, đừng hiện màn lỗi có
  // nút Thử lại. Bấm Thử lại khi chưa đăng nhập thì thử bao nhiêu lần cũng vậy.
  if (error instanceof ChuaDangNhap) return <Navigate to="/login" replace />

  if (error || !data) {
    return (
      <SessionSplash>
        <p className="font-semibold text-fg">Không tải được phiên đăng nhập</p>
        <p className="mx-auto mt-2 max-w-md text-muted">
          {error instanceof Error ? error.message : 'Lỗi không rõ'}
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-4 rounded-md bg-ac px-4 py-2 text-[14px] font-semibold text-white"
        >
          Thử lại
        </button>
      </SessionSplash>
    )
  }

  return <SessionReady session={data}>{children}</SessionReady>
}

/**
 * Tách khỏi `SessionProvider` để hook không nằm sau nhánh return sớm.
 *
 * `currentWorkspaceId` đến TỪ SERVER, không giữ ở client nữa: bản ghi phiên ở
 * Redis mới là nguồn sự thật (spec M2a §1 quyết định 2). Giữ một bản ở client
 * nghĩa là mở hai tab rồi đổi workspace ở tab này thì tab kia vẫn tưởng mình ở
 * workspace cũ — và mọi request của nó lại đi theo workspace mới.
 */
function SessionReady({ session, children }: { session: Session; children: ReactNode }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const current = session.workspaces.find((w) => w.id === session.currentWorkspaceId)
  const chuaCoWorkspace = session.currentWorkspaceId === null

  // ĐẢO NGƯỢC 2026-08-15 (spec bo-organization §5.0). Bản cũ:
  //
  //     if (!current) throw new Error('Phiên không có workspace nào')
  //
  // vì PQ_01 Q01 chốt "phiên không workspace là trạng thái HỎNG" và backend trả
  // 409 NO_WORKSPACE trước đó. Tự đăng ký làm nó thành đường CHÍNH: người vừa
  // tạo tài khoản LUÔN ở trạng thái này, và ném lỗi là chặn họ ngay ở bước đầu.
  //
  // Hai nhánh, KHÔNG gộp:
  //   · `currentWorkspaceId === null` → hợp lệ, đưa đi tạo workspace đầu tiên.
  //   · id CÓ giá trị nhưng không khớp workspace nào → vẫn là HỎNG (phiên trỏ
  //     tới một workspace không còn thấy được), giữ nguyên `throw`.
  useEffect(() => {
    if (chuaCoWorkspace) void navigate({ to: '/tao-workspace-dau-tien', replace: true })
  }, [chuaCoWorkspace, navigate])

  if (chuaCoWorkspace) return null
  if (!current) throw new Error('Phiên trỏ tới một workspace không thấy được')

  const value: SessionContextValue = {
    session,
    currentWorkspace: current,
    can: (required) => required.every((a) => session.actions.includes(a)),
    switchWorkspace: async (id) => {
      const moi = await doiWorkspace(id)

      // XOÁ CACHE CỦA WORKSPACE CŨ, và xoá TRƯỚC khi đặt phiên mới. Hai chi tiết,
      // mỗi cái sửa một lỗi thật đã đo được trên trình duyệt:
      //
      // ① `removeQueries` chứ không `invalidateQueries`. Invalidate chỉ ĐÁNH DẤU
      //    stale — dữ liệu cũ VẪN NẰM TRONG CACHE và vẫn được trả về ngay lập tức
      //    cho mọi observer, trong lúc chờ refetch. Màn nào sao dữ liệu đó vào
      //    `useState` (Agent Studio sao cả 8 ô) thì nó chốt luôn bản của workspace
      //    CŨ, và dữ liệu đúng về sau đó không đẩy được nó ra.
      //
      // ② Xoá TRƯỚC `setQueryData`. Đặt phiên mới là render lại cả cây, kể cả
      //    remount theo `key` ở routes/_app.tsx. Nếu lúc render đó cache cũ còn
      //    nguyên thì màn vừa dựng lại đọc trúng nó — remount không cứu được.
      //
      // Loại trừ ['session'] vì ngay dưới đây nó được đặt giá trị mới; không loại
      // trừ thì mỗi lần bấm switcher kéo thêm một GET /api/v1/me thừa.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'session' })
      queryClient.setQueryData(['session'], moi)
    },
    dangXuat: async () => {
      // KHÔNG bọc try/catch. Request hỏng nghĩa là phiên còn sống trong Redis;
      // xoá cache và rời màn lúc đó là báo với người dùng rằng họ đã thoát trong
      // khi chưa. Trên máy dùng chung, đó là lời nói dối tốn kém nhất trong file
      // này. Lỗi nổi lên cho người gọi hiện tại chỗ.
      await goiDangXuat()

      // Rời màn TRƯỚC khi xoá cache. Xoá trước thì cây `_app` render lại trong
      // lúc chưa có phiên, `useSession()` ném giữa chừng và người dùng thấy màn
      // lỗi chớp qua trên đường tới /login.
      await navigate({ to: '/login', replace: true })

      // Xoá SẠCH, kể cả ['session']: người đăng nhập tiếp theo trên cùng tab là
      // một người KHÁC, giữ lại query nào là để dữ liệu của người trước sống sang
      // phiên của người sau.
      //
      // TRỪ ĐÚNG MỘT NHÁNH: ['auth', ...]. `clear()` trần chạy ở đây là chạy SAU
      // `navigate('/login')` — tức là sau khi <NutGoogle> đã mount và đã bắn
      // `GET /api/v1/auth/providers`. Nó huỷ luôn query đang bay, response về sau
      // đó rơi vào hư không, observer nằm lại với `data === undefined`; mà
      // `staleTime: Infinity` cộng với việc component không remount thì không gì
      // gọi fetch lại nữa. Kết quả: nút «Tiếp tục với Google» mất tăm cho tới khi
      // người dùng tự F5. Đảo thứ tự (xoá trước, rời màn sau) không cứu được —
      // xem lý do ngay bên trên.
      //
      // Giữ nhánh này lại KHÔNG rò gì: `/auth/providers` trả cờ cấu hình của
      // SERVER (Google bật hay tắt), không phải dữ liệu của người vừa thoát.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
    },
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

function SessionSplash({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-bg px-6 text-center text-noi text-muted">
      <div>{children}</div>
    </div>
  )
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession() phải nằm trong <SessionProvider>')
  return ctx
}
