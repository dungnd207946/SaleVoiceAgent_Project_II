/**
 * Markdown → React element, cho nội dung ĐÃ NẠP của kb_files (Task 15).
 *
 * NỘI DUNG DO KHÁCH TẢI LÊN — không tin được. AN TOÀN bằng cách KHÔNG parse
 * thẻ HTML thô và KHÔNG BAO GIỜ `dangerouslySetInnerHTML`: mọi phần tử dựng
 * qua JSX/`React.createElement`, nên một chuỗi kiểu `<img onerror=alert(1)>`
 * gõ tay trong .md chỉ là VĂN BẢN hiển thị nguyên văn — không có bước nào biến
 * chuỗi đó thành DOM thật để trình duyệt parse lại.
 *
 * Link chỉ nhận `href` khi scheme là http(s)/mailto (hoặc đường dẫn tương
 * đối); `javascript:`/`data:`… render thành chữ thường, không `<a>`. Ảnh dùng
 * ĐÚNG bộ lọc này cho `src` — mirror ảnh ngoài của backend cố ý giữ nguyên URL
 * gốc khi mirror thất bại, nên `src` một tài liệu khách tải lên không đáng
 * tin hơn `href`. Scheme bị chặn thì hiện một chú thích "bị chặn", không biến
 * mất im lặng. `<img>` hợp lệ luôn có `referrerPolicy="no-referrer"` — một
 * host ngoài hợp lệ (http/https) vẫn render bình thường, không có dấu hiệu
 * riêng: sau khi lọc scheme và bỏ Referer, rủi ro còn lại chỉ là một request
 * ảnh tới host đó, giống hệt bất kỳ ảnh nào nhúng trong tài liệu thật.
 *
 * Không phải một bộ parse Markdown đầy đủ — chỉ đủ hình dạng chunker
 * (`index/chunker.py`) thật sự sinh ra: tiêu đề, đoạn văn, ảnh, bảng, danh
 * sách, blockquote, in đậm/nghiêng/code.
 */
import { useState } from 'react'

const SCHEME_AN_TOAN = /^(https?:|mailto:)/i

function hrefAnToan(url: string): string | null {
  const gon = url.trim()
  if (gon.startsWith('/') || gon.startsWith('#')) return gon
  return SCHEME_AN_TOAN.test(gon) ? gon : null
}

function AnhAnToan({ src, alt }: { src: string | null; alt: string }) {
  const [loi, setLoi] = useState(false)
  if (src === null) {
    return (
      <span className="inline-block rounded border border-dashed border-border-strong px-2 py-1 text-phu text-muted">
        Ảnh bị chặn (đường dẫn không an toàn){alt ? `: ${alt}` : ''}
      </span>
    )
  }
  if (loi) {
    return (
      <span className="inline-block rounded border border-dashed border-border-strong px-2 py-1 text-phu text-muted">
        Ảnh không tải được{alt ? `: ${alt}` : ''}
      </span>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      className="my-2 block max-h-[480px] max-w-full rounded border border-border object-contain"
      onError={() => setLoi(true)}
    />
  )
}

const INLINE =
  /!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]*)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*]+)\*|_([^_]+)_|`([^`]+)`/g

function inline(text: string): React.ReactNode[] {
  const ra: React.ReactNode[] = []
  let cuoi = 0
  let khoa = 0
  const re = new RegExp(INLINE)
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > cuoi) ra.push(text.slice(cuoi, m.index))
    const [, altAnh, srcAnh, txtLink, hrefLink, boldA, boldB, itaA, itaB, code] = m
    khoa += 1
    if (srcAnh !== undefined) {
      ra.push(<AnhAnToan key={khoa} src={hrefAnToan(srcAnh)} alt={altAnh ?? ''} />)
    } else if (hrefLink !== undefined) {
      const href = hrefAnToan(hrefLink)
      ra.push(
        href ? (
          <a
            key={khoa}
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-ac underline"
          >
            {txtLink}
          </a>
        ) : (
          <span key={khoa}>{txtLink}</span>
        ),
      )
    } else if (boldA !== undefined || boldB !== undefined) {
      ra.push(<strong key={khoa}>{boldA ?? boldB}</strong>)
    } else if (itaA !== undefined || itaB !== undefined) {
      ra.push(<em key={khoa}>{itaA ?? itaB}</em>)
    } else if (code !== undefined) {
      ra.push(
        <code key={khoa} className="rounded bg-fill px-1 py-0.5 font-mono text-[0.9em]">
          {code}
        </code>,
      )
    }
    cuoi = re.lastIndex
  }
  if (cuoi < text.length) ra.push(text.slice(cuoi))
  return ra
}

type Block =
  | { readonly kind: 'heading'; readonly level: number; readonly text: string }
  | { readonly kind: 'paragraph'; readonly text: string }
  | { readonly kind: 'blockquote'; readonly lines: readonly string[] }
  | { readonly kind: 'ul'; readonly items: readonly string[] }
  | { readonly kind: 'ol'; readonly items: readonly string[] }
  | {
      readonly kind: 'table'
      readonly header: readonly string[]
      readonly rows: readonly (readonly string[])[]
    }
  | { readonly kind: 'code'; readonly text: string }

const RE_HEADING = /^(#{1,6})\s+(.*)$/
const RE_UL = /^\s*[-*+]\s+(.*)$/
const RE_OL = /^\s*\d+\.\s+(.*)$/
const RE_TABLE_ROW = /^\s*\|.*\|\s*$/
const RE_TABLE_SEP = /^\s*\|[\s\-:|]+\|\s*$/
const RE_QUOTE = /^\s*>\s?(.*)$/

function laHangBang(l: string): readonly string[] {
  return l
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())
}

function batDauKhoiKhac(dong: string): boolean {
  return (
    RE_HEADING.test(dong) ||
    RE_UL.test(dong) ||
    RE_OL.test(dong) ||
    RE_QUOTE.test(dong) ||
    dong.trim().startsWith('```')
  )
}

function parseBlocks(text: string): Block[] {
  const lines = text.split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const dong = lines[i]!
    if (dong.trim() === '') {
      i++
      continue
    }

    if (dong.trim().startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i]!.trim().startsWith('```')) {
        buf.push(lines[i]!)
        i++
      }
      i++
      blocks.push({ kind: 'code', text: buf.join('\n') })
      continue
    }

    const h = RE_HEADING.exec(dong)
    if (h) {
      blocks.push({ kind: 'heading', level: h[1]!.length, text: h[2]! })
      i++
      continue
    }

    if (RE_TABLE_ROW.test(dong) && i + 1 < lines.length && RE_TABLE_SEP.test(lines[i + 1]!)) {
      const header = laHangBang(dong)
      i += 2
      const rows: (readonly string[])[] = []
      while (i < lines.length && RE_TABLE_ROW.test(lines[i]!)) {
        rows.push(laHangBang(lines[i]!))
        i++
      }
      blocks.push({ kind: 'table', header, rows })
      continue
    }

    if (RE_QUOTE.test(dong)) {
      const buf: string[] = []
      while (i < lines.length && RE_QUOTE.test(lines[i]!)) {
        buf.push(RE_QUOTE.exec(lines[i]!)![1]!)
        i++
      }
      blocks.push({ kind: 'blockquote', lines: buf })
      continue
    }

    if (RE_UL.test(dong)) {
      const items: string[] = []
      while (i < lines.length && RE_UL.test(lines[i]!)) {
        items.push(RE_UL.exec(lines[i]!)![1]!)
        i++
      }
      blocks.push({ kind: 'ul', items })
      continue
    }

    if (RE_OL.test(dong)) {
      const items: string[] = []
      while (i < lines.length && RE_OL.test(lines[i]!)) {
        items.push(RE_OL.exec(lines[i]!)![1]!)
        i++
      }
      blocks.push({ kind: 'ol', items })
      continue
    }

    const buf: string[] = []
    while (
      i < lines.length &&
      lines[i]!.trim() !== '' &&
      !batDauKhoiKhac(lines[i]!) &&
      !(RE_TABLE_ROW.test(lines[i]!) && RE_TABLE_SEP.test(lines[i + 1] ?? ''))
    ) {
      buf.push(lines[i]!)
      i++
    }
    blocks.push({ kind: 'paragraph', text: buf.join(' ') })
  }
  return blocks
}

function CapTieuDe({ level, children }: { level: number; children: React.ReactNode }) {
  // +2 cấp: tiêu đề trong chunk là của TÀI LIỆU KHÁCH — hạ xuống để không lấn
  // <h1>/<h2> của chính trang portal đang bọc nó.
  const cap = Math.min(level + 2, 6)
  const cls = 'mb-2 mt-4 font-semibold text-fg first:mt-0'
  switch (cap) {
    case 3:
      return <h3 className={cls}>{children}</h3>
    case 4:
      return <h4 className={cls}>{children}</h4>
    case 5:
      return <h5 className={cls}>{children}</h5>
    default:
      return <h6 className={cls}>{children}</h6>
  }
}

function KhoiRender({ b }: { b: Block }) {
  switch (b.kind) {
    case 'heading':
      return <CapTieuDe level={b.level}>{inline(b.text)}</CapTieuDe>
    case 'paragraph':
      return <p className="mb-2 leading-[1.6] text-fg">{inline(b.text)}</p>
    case 'blockquote':
      return (
        <blockquote className="mb-2 border-l-2 border-border-strong pl-3 text-muted">
          {b.lines.map((l, j) => (
            <p key={j}>{inline(l)}</p>
          ))}
        </blockquote>
      )
    case 'ul':
      return (
        <ul className="mb-2 list-disc space-y-1 pl-5">
          {b.items.map((it, j) => (
            <li key={j}>{inline(it)}</li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol className="mb-2 list-decimal space-y-1 pl-5">
          {b.items.map((it, j) => (
            <li key={j}>{inline(it)}</li>
          ))}
        </ol>
      )
    case 'code':
      return (
        <pre className="mb-2 overflow-x-auto rounded bg-fill p-2 text-phu">
          <code>{b.text}</code>
        </pre>
      )
    case 'table':
      return (
        <div className="mb-2 overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                {b.header.map((c, j) => (
                  <th
                    key={j}
                    className="border border-border bg-fill px-2 py-1 text-left font-semibold"
                  >
                    {inline(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r, j) => (
                <tr key={j}>
                  {r.map((c, jj) => (
                    <td key={jj} className="border border-border px-2 py-1">
                      {inline(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
  }
}

export function Markdown({ text }: { text: string }) {
  const blocks = parseBlocks(text)
  return (
    <>
      {blocks.map((b, i) => (
        <KhoiRender key={i} b={b} />
      ))}
    </>
  )
}
