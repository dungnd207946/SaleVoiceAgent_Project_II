/**
 * ⌘K — nhảy tới bất kỳ màn nào bằng bàn phím.
 *
 * PALETTE LÀ TẤM GƯƠNG CỦA RAIL: cùng bốn mảng, cùng thứ tự, cùng icon, đọc từ
 * cùng `useNavGroups()` nên cùng phép lọc quyền. Học một cái là học cái kia, và
 * không có màn nào lọt vào đây mà rail đã ẩn.
 *
 * Đây cũng là thứ trả giá cho quyết định "bấm rail là điều hướng": rail không
 * cho ngó mảng khác mà không rời màn, palette cho — không cần rời tay khỏi bàn
 * phím.
 *
 * BỎ DẤU KHI TÌM. Gõ "hoi thoai" phải ra «Hội thoại», gõ "du an" phải ra «Dự
 * án». Người Việt gõ nhanh thì không bỏ dấu, và một ô tìm kiếm bắt gõ đủ dấu
 * mới khớp là một ô tìm kiếm không ai dùng lần thứ hai.
 *
 * A11y (2026-10-05): vỏ là `HopThoai` (nền inert, Esc, trả focus); bên trong là mô
 * hình COMBOBOX của WAI-ARIA — ô nhập `role="combobox"` giữ focus suốt, mục đang
 * sáng nói qua `aria-activedescendant`, danh sách `listbox` › `group` › `option`.
 * Bản trước đặt `aria-selected` trên `<button>` và ô nhập không trỏ vào đâu: trình
 * đọc màn hình không biết ↑↓ vừa chọn mục nào. Số màn khớp đọc qua `role="status"`.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { HopThoai } from '@/components/ui/HopThoai'
import { useLang } from '@/i18n'
import type { NavGroup, NavLeaf } from '@/lib/nav-types'
import { boDau } from '@/lib/boDau'
import { useNavGroups } from './useNavGroups'

/**
 * Một tiêu đề trong palette + các mục dưới nó.
 *
 * Tiêu đề là «Mảng» hoặc «Mảng · Khối» — palette phải soi đúng cấu trúc panel,
 * kể cả cấp khối. Gộp «Kỹ năng» của Bất động sản chung một tiêu đề «AGENT» với
 * kỹ năng chung là xoá đúng phân biệt mà khối sinh ra để giữ.
 */
interface Hit {
  readonly key: string
  readonly icon: NavGroup['icon']
  readonly tieuDe: string
  readonly items: readonly NavLeaf[]
}

export function CommandPalette() {
  const { t } = useLang()
  const groups = useNavGroups()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [chon, setChon] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const id = useId()

  // Trả focus về chỗ vừa rời là việc của `HopThoai` — nó nhớ `activeElement` lúc mở.
  const dong = useCallback(() => {
    setOpen(false)
    setQ('')
    setChon(0)
  }, [])

  // ⌘K (macOS) / Ctrl+K. `metaKey || ctrlKey` chứ không tách nền tảng: bàn phím
  // ngoài cắm vào máy Mac vẫn có thể là bàn phím PC.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((truoc) => !truoc)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const hits: readonly Hit[] = useMemo(() => {
    const tu = boDau(q.trim())
    return groups
      .flatMap((group) =>
        group.segments.map((seg, i) => ({
          key: `${group.key}:${seg.label ? seg.label.vi : i}`,
          icon: group.icon,
          tieuDe: seg.label ? `${t(group.label)} · ${t(seg.label)}` : t(group.label),
          items: tu ? seg.entries.filter((e) => boDau(t(e.label)).includes(tu)) : seg.entries,
        })),
      )
      .filter((h) => h.items.length > 0)
  }, [groups, q, t])

  // Danh sách phẳng để ↑↓ đi qua — chỉ số chạy XUYÊN mảng, không dừng ở biên
  // nhóm. Người dùng thấy một danh sách, không thấy bốn.
  const phang = useMemo(() => hits.flatMap((h) => h.items), [hits])
  const dangChon = phang[Math.min(chon, phang.length - 1)]
  const idMuc = (key: string) => `${id}-${key}`

  // Mục sáng chạy ra ngoài khung cuộn thì kéo khung theo. `?.()`: jsdom không có
  // `scrollIntoView`.
  useEffect(() => {
    if (dangChon)
      document.getElementById(idMuc(dangChon.key))?.scrollIntoView?.({ block: 'nearest' })
  })

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setChon((i) => (phang.length === 0 ? 0 : (i + 1) % phang.length))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setChon((i) => (phang.length === 0 ? 0 : (i - 1 + phang.length) % phang.length))
    } else if (e.key === 'Enter' && dangChon) {
      e.preventDefault()
      const path = dangChon.path
      dong()
      void navigate({ to: path })
    }
  }

  if (!open) return null

  return (
    // Neo ở 12vh từ đỉnh chứ không căn giữa: danh sách co giãn theo chữ gõ, hộp
    // căn giữa sẽ nhảy lên xuống theo từng phím.
    <HopThoai
      onDong={dong}
      aria-label={t({ vi: 'Tìm màn', en: 'Find a screen' })}
      className="mx-auto mt-[12vh] mb-auto flex max-h-[64vh] w-[calc(100%-2rem)] max-w-[520px] flex-col overflow-hidden rounded-lg border border-border-field bg-surface text-fg shadow-hop-thoai backdrop:bg-fg/25 max-md:mt-4 max-md:max-h-[calc(100dvh-2rem)]"
    >
      {/* `onKeyDown` ở khối bọc chứ không ở `<dialog>`: HopThoai không nhận prop đó. */}
      <div className="flex min-h-0 flex-1 flex-col" onKeyDown={onKeyDown}>
        {/* Ô nhập luôn giữ focus, nên chỉ báo focus là đường kẻ dưới đổi sang accent
            (`focus-within`) — vòng `:focus-visible` quanh một ô không viền trông
            như một hộp lạc vào giữa thanh tìm. */}
        <div className="flex items-center gap-2.5 border-b border-border-soft px-3.5 py-3 focus-within:border-ac">
          <Icon name="search" className="size-4 flex-none text-muted-2" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls={`${id}-ds`}
            aria-autocomplete="list"
            aria-activedescendant={dangChon ? idMuc(dangChon.key) : undefined}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setChon(0)
            }}
            placeholder={t({ vi: 'Gõ để tìm màn…', en: 'Type to find a screen…' })}
            aria-label={t({ vi: 'Tìm màn', en: 'Find a screen' })}
            className="min-w-0 flex-1 bg-transparent text-noi outline-none placeholder:text-muted-3 max-md:text-base"
          />
          <kbd className="flex-none rounded-sm border border-border px-1.5 py-px font-mono text-nhan text-muted-2">
            esc
          </kbd>
        </div>

        {/* MỘT vùng `role="status"` tồn tại sẵn: không khớp gì thì nó chính là câu
            hiện ra cho mắt, khớp thì nó chỉ còn số màn cho trình đọc màn hình. Hai
            phần tử nói cùng một câu là hai lần đọc. */}
        <p
          role="status"
          className={
            phang.length === 0 ? 'px-3 py-6 text-center text-than text-muted-2' : 'sr-only'
          }
        >
          {phang.length === 0
            ? t({ vi: 'Không có màn nào khớp', en: 'No screen matches' })
            : t({ vi: `${phang.length} màn`, en: `${phang.length} screens` })}
        </p>

        <div
          id={`${id}-ds`}
          role="listbox"
          aria-label={t({ vi: 'Màn', en: 'Screens' })}
          className={phang.length === 0 ? 'hidden' : 'flex-1 overflow-auto p-1.5'}
        >
          {hits.map((h) => (
            <div key={h.key} role="group" aria-labelledby={`${id}-${h.key}-nhom`}>
              <div
                id={`${id}-${h.key}-nhom`}
                className="flex items-center gap-1.5 px-2.5 pb-1 pt-2 text-nhan font-semibold uppercase tracking-[0.08em] text-muted-2"
              >
                <Icon name={h.icon} className="size-3.5 flex-none" />
                {h.tieuDe}
              </div>
              {h.items.map((item) => (
                // `option` chứ không `<button>`: focus ở lại ô nhập, mục chỉ là thứ
                // `aria-activedescendant` trỏ vào. Chuột vẫn bấm được.
                <div
                  key={item.key}
                  id={idMuc(item.key)}
                  role="option"
                  data-cmd={item.key}
                  aria-selected={item.key === dangChon?.key}
                  // Rê chuột vào là chọn — nếu không, con trỏ nằm trên một
                  // dòng còn ↵ mở dòng khác.
                  onMouseEnter={() => setChon(phang.findIndex((p) => p.key === item.key))}
                  onClick={() => {
                    const path = item.path
                    dong()
                    void navigate({ to: path })
                  }}
                  className={`flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-than ${
                    item.key === dangChon?.key ? 'bg-acs text-ac' : 'text-nav'
                  }`}
                >
                  <Icon name={item.icon} className="size-4 flex-none opacity-85" />
                  <span className="truncate">{t(item.label)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>

        <div className="flex items-center gap-3.5 border-t border-border-soft px-3.5 py-2 text-nhan text-muted-2">
          <span>↑↓ {t({ vi: 'chọn', en: 'select' })}</span>
          <span>↵ {t({ vi: 'mở', en: 'open' })}</span>
        </div>
      </div>
    </HopThoai>
  )
}
