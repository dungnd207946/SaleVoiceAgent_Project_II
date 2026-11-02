/**
 * Công tắc bật/tắt dùng chung — cùng hình với công tắc ở «Quản lý lĩnh vực» và «Kỹ năng».
 * Input thật `sr-only` + `role="switch"`; rãnh và núm là `after:` của rãnh (xem chú ở
 * `features/agent/components/QuanLyLinhVuc.tsx` vì sao núm không được là `<span>` con).
 */
export function CongTac({
  bat,
  nhan,
  dangGui,
  doi,
}: {
  bat: boolean
  nhan: string
  dangGui?: boolean | undefined
  doi: (v: boolean) => void
}) {
  return (
    <label className="relative flex flex-none cursor-pointer items-center gap-2.5">
      <input
        type="checkbox"
        role="switch"
        checked={bat}
        disabled={dangGui}
        aria-label={nhan}
        onChange={(e) => doi(e.target.checked)}
        className="peer sr-only"
      />
      <span className="relative h-[22px] w-[38px] flex-none rounded-full bg-border-strong transition-colors peer-checked:bg-ac peer-disabled:opacity-50 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ac after:absolute after:left-[3px] after:top-[3px] after:size-4 after:rounded-full after:bg-surface after:transition-transform peer-checked:after:translate-x-4" />
    </label>
  )
}
