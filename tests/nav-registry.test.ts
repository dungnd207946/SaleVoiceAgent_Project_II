/**
 * Canh nav registry khớp thiết kế và khớp cây route.
 *
 * VÌ SAO CÓ FILE NÀY: "sidebar khớp prototype" và "mục nav nào cũng khai quyền"
 * là hai lời hứa dễ vỡ âm thầm — thêm màn mà quên khai nav thì không ai thấy,
 * và một mục nav thiếu `requiredActions` thì lúc M2b vào sẽ hiện với người
 * không có quyền. Test biến hai lời hứa đó thành thứ CI kiểm được.
 *
 * Cùng khuôn với `odyssey-portal-backend/tests/isolation/test_isolation_catalog.py`: quét
 * ĐỘNG, không có danh sách viết cứng thứ hai.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { createRouter } from '@tanstack/react-router'
import { ALL_ACTIONS } from '../src/lib/actions'
import { NAV, OFF_NAV } from '../src/lib/nav-registry'
import { flattenLeaves } from '../src/lib/nav-types'
import { routeTree } from '../src/routeTree.gen'
import { qualityNav } from '@/features/quality/nav'

/** Route CẤP MỘT của layout `_app`, đọc từ cây route thật — route con (`/convos/$phone`) không tính. */
const DUONG_APP = Object.values(createRouter({ routeTree }).routesById)
  .filter((r) => r.parentRoute?.id === '/_app')
  .map((r) => r.fullPath)

/**
 * Đúng thứ tự rail + panel, đọc mảng từ trên xuống rồi mục trong mảng từ trên
 * xuống (spec 2026-08-07 «làm lại layout portal»).
 *
 * KHÁC thứ tự sidebar của `design/Tenant Portal.dc.html` — prototype gom theo
 * module sở hữu, bản này gom theo câu hỏi người dùng hỏi. Lý do từng mảng ghi
 * ở đầu `lib/nav-registry.ts`.
 */
const RAIL_ORDER = [
  // ▸ Vận hành — `appts` («Lịch hẹn») đã rời nav 2026-08-13, xem `OFF_NAV`.
  'dashboard',
  'convos',
  'chuyen-sale',
  'quality',
  // ▸ Agent — khối CHUNG (áp cho mọi lĩnh vực)
  'agent',
  'kb',
  'thu-agent',
  // ▸ Agent — khối «Bất động sản»: Kiến thức + Dữ liệu ngoài + Kỹ năng + Kịch bản
  'projects',
  'du-lieu-ngoai',
  'ky-nang-bds',
  'kich-ban',
  // ▸ Agent — khối HỆ THỐNG, xuống cuối
  'api',
  'domains',
  // ▸ Quản trị
  // `users` («Thành viên») TRỞ LẠI 2026-08-17. Bị ẩn 2026-08-15 với lý do "khối
  // `/users*` ở backend đóng bằng cờ `USERS_ADMIN_ENABLED`" — lý do đó sai đối
  // tượng: màn này chạy trên seam `/members` (gate `WORKSPACE_ADMIN`), không trên
  // `/users*`. Ẩn nó là chặn đường vào DUY NHẤT tới việc mời người vào workspace.
  'users',
  'audit',
  // `usage` và `billing` tách từ một mục «Gói cước & Usage» (2026-08-09) — hai
  // câu hỏi khác nhau, xem `features/billing/nav.ts`. Un-defer 2026-08-20 (spec
  // usage-billing-fe); từ 2026-08-21 cả hai nằm CÙNG khối với `users`/`audit`,
  // không còn segment riêng — xem `lib/nav-registry.ts`. Thứ tự đảo lại
  // `billing` trước `usage` (người dùng chốt) — xem `khoi(...)` ở đó.
  'billing',
  'usage',
  // `pricing` KHÔNG còn ở đây (2026-08-21): user của portal không được đặt giá,
  // giá do migration `0949` của backend seed. Route còn nên nó chuyển sang
  // `OFF_NAV` — bài `route ↔ nav` bên dưới canh việc đó.
  // «Cài đặt workspace» khép mảng lại — thứ dựng một lần rồi thôi xuống cuối,
  // và mục ĐẦU của mảng là đích của cú bấm rail nên nó phải ở lại «Thành viên».
  'workspace',
] as const

/** Ba mảng của rail, đúng thứ tự. */
const RAIL_GROUPS = ['ops', 'agent', 'admin'] as const

describe('route ↔ nav', () => {
  /**
   * Route nằm trong cây mà không ở NAV lẫn OFF_NAV thì rail tô nhầm mảng và
   * topbar không có tiêu đề; mục nav trỏ vào path không có route thì bấm ra 404.
   */
  it('mỗi route của `_app` có đúng một chỗ: mục nav hoặc OFF_NAV', () => {
    const coCho = [...flattenLeaves(NAV).map((l) => l.path), ...OFF_NAV.map((o) => o.path)]
    expect(coCho.sort()).toEqual([...DUONG_APP].sort())
  })

  // `quality` un-defer 2026-08-12 (Task 9): backend chấm quyền
  // `GET /agent/feedback` bằng `ACTIONS.CONVOS_READ` (PQ_01 nhóm 2), không phải
  // `OVERVIEW_READ` (placeholder từ lúc màn chưa có backend thật).
  it('quality dùng đúng quyền convos.read (khớp GET /agent/feedback)', () => {
    expect(qualityNav.requiredActions).toEqual(['convos.read'])
  })
})

describe('nav registry khớp rail + panel', () => {
  const leaves = flattenLeaves(NAV)

  it('đúng thứ tự và đúng số mục', () => {
    expect(leaves.map((l) => l.key)).toEqual([...RAIL_ORDER])
  })

  it('đúng ba mảng, đúng thứ tự, mảng nào cũng có icon và ít nhất một mục', () => {
    expect(NAV.map((g) => g.key)).toEqual([...RAIL_GROUPS])
    for (const g of NAV) {
      expect(g.icon, `mảng ${g.key}`).toBeTruthy()
      expect(flattenLeaves([g]).length, `mảng ${g.key}`).toBeGreaterThan(0)
    }
  })

  /**
   * Khối rỗng không được tồn tại NGAY TỪ registry — `useNavGroups` cũng lọc
   * khối rỗng lúc chạy, nhưng đó là lọc theo quyền. Một khối khai sẵn mà quên
   * bỏ mục vào là một nhãn treo trên khoảng trống với MỌI người dùng.
   */
  it('không khối nào rỗng, và khối đầu của mảng không có nhãn', () => {
    for (const g of NAV) {
      expect(g.segments.length, `mảng ${g.key}`).toBeGreaterThan(0)
      expect(g.segments[0]?.label, `khối đầu của ${g.key} phải không nhãn`).toBeNull()
      for (const [i, s] of g.segments.entries()) {
        expect(s.entries.length, `khối ${i} của mảng ${g.key}`).toBeGreaterThan(0)
      }
    }
  })

  /**
   * Mảng Agent phải giữ được phân biệt CHUNG ↔ RIÊNG TỪNG LĨNH VỰC — đó là lý
   * do duy nhất khối tồn tại. Xoá nhãn khối đi thì cấu trúc vẫn chạy, vẫn xanh
   * mọi bài khác, và mất đúng thứ nó sinh ra để nói.
   */
  it('mảng Agent có khối chung + một khối CÓ NHÃN cho mỗi lĩnh vực', () => {
    const agent = NAV.find((g) => g.key === 'agent')
    expect(agent).toBeDefined()

    const coNhan = agent?.segments.filter((s) => s.label !== null) ?? []
    expect(coNhan.map((s) => s.label?.vi)).toEqual(['Bất động sản'])

    // `/kb` là tài liệu của CẢ workspace — phải ở khối chung, không nằm trong
    // khối của một lĩnh vực (nav không được hứa một phạm vi backend không có).
    const chung = agent?.segments[0]?.entries.map((e) => e.key) ?? []
    expect(chung).toContain('kb')
  })

  it('khoá mảng không trùng nhau', () => {
    expect(new Set(NAV.map((g) => g.key)).size).toBe(NAV.length)
  })

  /**
   * `OFF_NAV` trả lời hai câu cho màn không có mục nav: rail tô sáng mảng nào,
   * topbar hiện tiêu đề gì. Sai một `group` thì rail lặng lẽ tô sáng nhầm mảng
   * — không có màn nào đỏ, chỉ có người dùng thấy mình đang ở nơi mình không ở.
   */
  it('OFF_NAV trỏ vào mảng có thật', () => {
    for (const o of OFF_NAV) {
      expect(
        NAV.map((g) => g.key),
        `màn ${o.path}`,
      ).toContain(o.group)
    }
  })

  it('OFF_NAV không giẫm lên path của mục nav nào', () => {
    const navPaths = new Set(leaves.map((l) => l.path))
    for (const o of OFF_NAV) {
      expect(navPaths.has(o.path), `${o.path} vừa ở NAV vừa ở OFF_NAV`).toBe(false)
    }
  })

  it('5 màn ngoài nav: pform · pricing · roles · settings · uform', () => {
    // `roles` gộp vào `/users` (tab Vai trò, 2026-08-06) — route vẫn tồn tại
    // (redirect), chỉ không còn là mục nav riêng. Xem spec
    // docs/superpowers/specs/2026-08-06-gop-man-users-roles-thanh-vien-phan-quyen-design.md §4.
    // `users` KHÔNG còn ở đây từ 2026-08-17 — nó trở lại nav, xem `RAIL_ORDER`.
    //
    // `pricing` VÀO đây 2026-08-21: user của portal KHÔNG ĐƯỢC PHÉP làm việc đó — giá do migration `0949` của backend seed. Đường vào
    // duy nhất còn lại là gõ URL, có chủ đích.
    expect(OFF_NAV.map((o) => o.path).sort()).toEqual([
      '/pform',
      '/pricing',
      '/roles',
      '/settings',
      '/uform',
    ])
  })
})

describe('route không đụng proxy /api của dev server', () => {
  /**
   * Đã gặp thật: proxy khai khoá `'/api'` (chuỗi thường ⇒ Vite khớp theo TIỀN
   * TỐ) cuốn luôn route `/api-keys`, nên mở màn API Keys ra là proxy
   * chuyển tới backend và trả 500. Sửa bằng RegExp `'^/api/'`.
   *
   * Test này canh việc đó không quay lại — dev server hỏng theo kiểu chỉ thấy
   * khi mở đúng một màn là kiểu hỏng nằm lâu nhất.
   */
  it('không path màn nào bị proxy nuốt', () => {
    const config = readFileSync(join(import.meta.dirname, '../vite.config.ts'), 'utf8')
    const proxyBlock = /proxy:\s*\{([^}]*\{[^}]*\}[^}]*)\}/.exec(config)?.[1] ?? ''
    const keys = [...proxyBlock.matchAll(/'([^']+)':\s*\{/g)].map((m) => m[1] ?? '')

    expect(keys.length, 'không đọc được khoá proxy nào — sửa regex của test').toBeGreaterThan(0)

    for (const key of keys) {
      const matches = key.startsWith('^')
        ? (p: string) => new RegExp(key).test(p)
        : (p: string) => p.startsWith(key)

      for (const p of DUONG_APP) {
        expect(matches(p), `proxy '${key}' nuốt route '${p}'`).toBe(false)
      }
    }
  })
})

describe('mọi mục nav khai quyền — PQ_01 §BR-Q03', () => {
  it('requiredActions không rỗng', () => {
    for (const leaf of flattenLeaves(NAV)) {
      expect(leaf.requiredActions.length, `mục ${leaf.key}`).toBeGreaterThan(0)
    }
  })

  it('mọi action dùng trong nav đều nằm trong 17 nhóm (PQ_01 §3.1 + billing.read + audit.read + kb_web.*)', () => {
    for (const leaf of flattenLeaves(NAV)) {
      for (const a of leaf.requiredActions) {
        expect(ALL_ACTIONS, `mục ${leaf.key}`).toContain(a)
      }
    }
  })

  // 13 của PQ_01 §3.1 + `billing.read` (spec 2026-08-20 usage-billing-fe, mọc
  // ngoài PQ_01 — xem docstring `lib/actions.ts`) + `audit.read` (spec BE
  // 2026-08-25 nhat-ky-hoat-dong).
  it('có đúng 17 nhóm hành động', () => {
    expect(ALL_ACTIONS).toHaveLength(17)
  })
})
