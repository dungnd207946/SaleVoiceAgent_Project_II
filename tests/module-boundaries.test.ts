/**
 * Ranh giới module, bản frontend — song song với
 * `odyssey-portal-backend/tests/test_module_boundaries.py` (Luật 3).
 *
 * LUẬT: `features/<a>` chỉ được import `features/<a>/…`, `lib/…`,
 * `components/…`, `i18n/…`. Muốn dùng thứ của module khác thì import
 * `features/<b>/contracts` — mặt tiền công khai của nó.
 *
 * VÌ SAO TEST CHỨ KHÔNG CHỈ ESLINT: eslint bắt đường tương đối (`../agent/x`),
 * nhưng dev viết `@/features/agent/x` thì luật `no-restricted-imports` theo
 * pattern không thấy. Test quét văn bản nên bắt cả hai. Backend cũng làm y vậy.
 *
 * NGOẠI LỆ DUY NHẤT: `lib/nav-registry.ts` — chỗ được thiết kế để gom nav của
 * mọi module (spec §4⑤).
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(import.meta.dirname, '../src')
const FEATURES = join(SRC, 'features')

/** File được phép import chéo module. */
const ALLOWLIST = [
  'lib/nav-registry.ts',
  // Seam phiên: `switchWorkspace` phải gọi API thật (spec M2a §4.1). Client HTTP
  // của seam đó sống ở features/auth/api.ts vì module auth sở hữu nó. Ngược lại —
  // đặt client vào lib/ — thì lib/ biết hình dạng endpoint của một module, tệ hơn.
  'lib/session.tsx',
  // Điểm GOM FAKE, cùng vai trò với `nav-registry.ts` gom nav (spec §4②): mỗi
  // module ship `features/<tên>/msw.ts` rồi cắm vào `HANDLERS` ở đây — chính
  // header của tệp đó khai như vậy. Trước 2026-08-12 nó chỉ import ĐÚNG MỘT
  // module (`ops`) nên chưa chạm luật này; module thứ hai (`quality`) làm nó lộ
  // ra. Không phải lỗ hổng mới mở: gom fake là việc file này SINH RA để làm, và
  // nó chỉ nối mảng handler chứ không đọc hình dạng dữ liệu của module nào.
  'lib/msw/handlers.ts',
]

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.tsx?$/.test(full) ? [full] : []
  })
}

/** Mọi specifier import/export-from trong một file. */
function importsOf(file: string): string[] {
  const text = readFileSync(file, 'utf8')
  return [...text.matchAll(/(?:from|import)\s*['"]([^'"]+)['"]/g)].map((m) => m[1] ?? '')
}

/** `@/features/realestate/nav` | `../realestate/nav` → 'realestate' */
function targetFeature(spec: string, ownFeature: string): string | null {
  const alias = /^@\/features\/([^/]+)/.exec(spec)
  if (alias) return alias[1] ?? null
  // đường tương đối trèo ra khỏi module hiện tại
  const rel = /^\.\.\/([^./][^/]*)\//.exec(spec)
  if (rel && rel[1] !== ownFeature) return rel[1] ?? null
  return null
}

describe('ranh giới module FE — Luật 3', () => {
  const featureDirs = readdirSync(FEATURES).filter((d) => statSync(join(FEATURES, d)).isDirectory())

  it('có ít nhất một module để kiểm (test không được rỗng mà vẫn xanh)', () => {
    expect(featureDirs.length).toBeGreaterThan(0)
  })

  it('không module nào import ruột module khác', () => {
    const viPham: string[] = []

    for (const feature of featureDirs) {
      for (const file of walk(join(FEATURES, feature))) {
        for (const spec of importsOf(file)) {
          const target = targetFeature(spec, feature)
          if (target === null || target === feature) continue
          // chỉ `contracts` là mặt tiền công khai
          if (/\/contracts(\/|$)/.test(spec)) continue
          viPham.push(`${relative(SRC, file)} → ${spec}`)
        }
      }
    }

    expect(viPham, 'chỉ được import features/<khác>/contracts').toEqual([])
  })

  it('shell không viết cứng tên màn nào — thêm màn phải qua nav-registry', () => {
    // Shell chỉ được biết CẤU TRÚC (mảng, mục, quyền), không được biết
    // 'projects' là gì. Quét CẢ thư mục `components/shell/`, không chỉ một tệp:
    // trước 2026-08-07 chỉ `Sidebar.tsx` bị canh, và đúng lúc đó `Topbar.tsx`
    // đang giữ một bảng `EXTRA_TITLES` viết cứng bốn path màn — ngoại lệ ấy
    // sống được vì cổng chỉ nhìn một tệp. Bảng đó giờ ở `nav-registry`.
    const KEYS = ['dashboard', 'convos', 'projects', 'kb', 'agent', 'users', 'billing']
    const shellDir = join(SRC, 'components/shell')
    const viPham: string[] = []

    for (const file of walk(shellDir)) {
      const src = readFileSync(file, 'utf8')
      // Bỏ chú thích trước khi soi: comment ĐƯỢC quyền nhắc tên màn để giải
      // thích một quyết định (và nhiều comment trong shell làm đúng thế). Cổng
      // này canh CODE viết cứng, không canh văn xuôi.
      const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
      for (const key of KEYS) {
        if (code.includes(`'${key}'`) || code.includes(`"${key}"`)) {
          viPham.push(`${relative(SRC, file)} nhắc tên màn '${key}'`)
        }
      }
    }

    expect(viPham, 'shell phải đọc màn qua nav-registry, không viết cứng').toEqual([])
  })

  it('chỉ nav-registry được import nav của nhiều module', () => {
    const nguoiViPham: string[] = []

    for (const file of walk(SRC)) {
      const relPath = relative(SRC, file)
      if (ALLOWLIST.includes(relPath)) continue
      if (relPath.startsWith('features/')) continue // đã kiểm ở test trên

      const featuresImported = new Set(
        importsOf(file)
          .map((s) => /^@\/features\/([^/]+)/.exec(s)?.[1])
          .filter((f): f is string => f !== undefined),
      )
      if (featuresImported.size > 1) {
        nguoiViPham.push(`${relPath} import ${[...featuresImported].join(' + ')}`)
      }
    }

    expect(nguoiViPham, 'gom nav là việc của lib/nav-registry.ts').toEqual([])
  })
})
