/** Thẻ một phần của hồ sơ dự án: tiêu đề in hoa nhỏ có đường kẻ kéo dài, nút của thẻ ở cuối đường kẻ. */
import { useId, type ReactNode } from 'react'

// Viết đủ chuỗi từng biến thể: Tailwind quét văn bản nguồn, class ghép động không vào CSS.
const GRID = {
  1: 'grid gap-4',
  2: 'grid gap-x-7 gap-y-[18px] md:grid-cols-2',
  3: 'grid gap-x-7 gap-y-[18px] md:grid-cols-2 lg:grid-cols-3',
  4: 'grid gap-x-7 gap-y-[18px] md:grid-cols-2 lg:grid-cols-4',
}

export function SectionCard({
  title,
  actions,
  cols = 3,
  children,
}: {
  title?: string | undefined
  actions?: ReactNode
  cols?: 1 | 2 | 3 | 4 | undefined
  children: ReactNode
}) {
  const id = useId()
  return (
    <section
      role={title ? 'group' : undefined}
      aria-labelledby={title ? id : undefined}
      className="rounded-xl border border-border bg-surface px-5 pt-[18px] pb-5"
    >
      {(title || actions) && (
        <div className="mb-3.5 flex items-center gap-3.5">
          {title && (
            <h2
              id={id}
              className="flex flex-1 items-center gap-3 text-phu font-bold tracking-[0.06em] text-n10 uppercase after:h-px after:flex-1 after:bg-border-strong after:content-['']"
            >
              {title}
            </h2>
          )}
          {actions && <div className="ml-auto flex flex-none items-center gap-3.5">{actions}</div>}
        </div>
      )}
      <div className={GRID[cols]}>{children}</div>
    </section>
  )
}
