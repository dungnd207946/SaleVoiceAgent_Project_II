/**
 * Thanh lọc màn Nhật ký: nhóm · từ ngày · đến hết ngày · công tắc hành động máy.
 *
 * `<select>`/`<input type=date>` trần với lớp `O_LOC` (như `realestate/ThanhTrang.tsx`),
 * không qua `OChon`/`Khung` của `Truong.tsx` — đó là primitive FORM (nhãn trên,
 * gợi ý, lỗi), còn đây là một thanh lọc nằm ngang.
 *
 * «Đến HẾT ngày»: người dùng nghĩ theo ngày đóng hai đầu; API nhận cận trên MỞ —
 * phép `+1` nằm ở `duongNhatKy`, không ở đây.
 */
import { O_LOC } from '@/components/ui/Bang'
import { NHOM_LOC } from '../so-hanh-dong'
import type { LocNhatKy } from '../nhatKy'

const NHAN = 'flex flex-col gap-1 text-phu text-muted'

export function BoLocNhatKy({
  loc,
  doi,
}: {
  readonly loc: LocNhatKy
  readonly doi: (l: LocNhatKy) => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Bộ lọc nhật ký">
      <label className={NHAN}>
        Nhóm
        <select
          aria-label="Nhóm hành động"
          className={`o-chon ${O_LOC} bg-surface`}
          value={loc.nhom ?? ''}
          onChange={(e) => doi({ ...loc, nhom: e.target.value || null })}
        >
          <option value="">Tất cả</option>
          {NHOM_LOC.map((n) => (
            <option key={n.ma} value={n.ma}>
              {n.nhan}
            </option>
          ))}
        </select>
      </label>
      <label className={NHAN}>
        Từ ngày
        <input
          type="date"
          aria-label="Từ ngày"
          className={`${O_LOC} bg-surface`}
          value={loc.tu ?? ''}
          max={loc.denHet ?? undefined}
          onChange={(e) => doi({ ...loc, tu: e.target.value || null })}
        />
      </label>
      <label className={NHAN}>
        Đến hết ngày
        <input
          type="date"
          aria-label="Đến hết ngày"
          className={`${O_LOC} bg-surface`}
          value={loc.denHet ?? ''}
          min={loc.tu ?? undefined}
          onChange={(e) => doi({ ...loc, denHet: e.target.value || null })}
        />
      </label>
      <label className="flex h-9 items-center gap-2 text-than">
        <input
          type="checkbox"
          checked={loc.may}
          onChange={(e) => doi({ ...loc, may: e.target.checked })}
        />
        Hiện hoạt động của agent
      </label>
    </div>
  )
}
