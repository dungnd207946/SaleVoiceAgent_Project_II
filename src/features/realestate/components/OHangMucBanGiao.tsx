/**
 * Tiêu chuẩn bàn giao (`projects.handover_standard`, jsonb mảng): mỗi dòng một hạng mục người
 * dùng tự đặt tên, kèm vật liệu, hãng, xuất xứ, ghi chú. Gõ thì đổi state, rời ô thì lưu; thêm
 * dòng chưa lưu (tên còn trống), xoá dòng lưu ngay.
 */
import { useId } from 'react'
import type { HangMucBanGiao } from '../api'
import { HANG_MUC_TRONG } from '../banGiao'
import { O_CHUNG } from '@/components/ui/Truong'
import { NUT_PHU, NutIcon } from '@/components/ui/Bang'

const GOI_Y_HANG_MUC = [
  'Sàn phòng khách',
  'Sàn phòng ngủ',
  'Sàn và tường WC',
  'Sơn tường, trần',
  'Cửa chính',
  'Khoá cửa',
  'Cửa sổ, kính',
  'Thiết bị vệ sinh',
  'Tủ bếp',
  'Thiết bị bếp',
  'Điều hoà',
  'Bình nóng lạnh',
  'Tủ quần áo',
  'Đèn, công tắc, ổ cắm',
  'Internet, truyền hình',
  'Nhà thông minh',
  'Báo cháy',
  'Ban công, lan can',
  'Mặt ngoài',
]

const COT = [
  { k: 'item', nhan: 'Hạng mục', goiY: 'Sàn phòng ngủ' },
  { k: 'material', nhan: 'Vật liệu, quy cách', goiY: 'Gỗ kỹ thuật 12mm' },
  { k: 'brand', nhan: 'Hãng', goiY: 'Kronotex' },
  { k: 'origin', nhan: 'Xuất xứ', goiY: 'Đức' },
  { k: 'note', nhan: 'Ghi chú', goiY: 'Phòng ngủ master' },
] as const

const LUOI = 'grid gap-2 md:grid-cols-[1.3fr_1.5fr_1fr_0.8fr_1.3fr_auto] md:items-center'

export function OHangMucBanGiao({
  khoa,
  giaTri,
  doi,
  xong,
  doiVaLuu,
  loi,
}: {
  khoa: boolean
  giaTri: readonly HangMucBanGiao[]
  doi: (ds: HangMucBanGiao[]) => void
  xong: () => void
  doiVaLuu: (ds: HangMucBanGiao[]) => void
  loi?: string | undefined
}) {
  const idGoiY = useId()

  if (khoa) {
    return (
      <div>
        <div className="mb-2.5 flex items-baseline gap-2">
          <span className="text-than font-semibold text-fg">Tiêu chuẩn bàn giao</span>
          {giaTri.length > 0 && (
            <span className="text-phu text-muted-2">{giaTri.length} hạng mục</span>
          )}
        </div>
        {giaTri.length === 0 ? (
          <p className="text-than text-muted-3">—</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full border-collapse text-than">
              <thead className="bg-fill-strong">
                <tr>
                  {['Hạng mục', 'Vật liệu, thiết bị', 'Thương hiệu'].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left text-nhan font-semibold tracking-[0.05em] text-muted uppercase"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {giaTri.map((h, i) => (
                  <tr key={i} className="border-t border-rule align-top">
                    <td className="w-[26%] px-3 py-2 font-medium">{h.item}</td>
                    <td className="px-3 py-2">
                      {h.material || '—'}
                      {h.note && <span className="block text-phu text-muted-2">{h.note}</span>}
                    </td>
                    <td className="w-[24%] px-3 py-2">
                      {h.brand || '—'}
                      {h.origin && <span className="block text-phu text-muted-2">{h.origin}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }

  const sua = (i: number, k: keyof HangMucBanGiao, x: string) =>
    doi(giaTri.map((h, j) => (j === i ? { ...h, [k]: x } : h)))

  return (
    <fieldset>
      <legend className="mb-1.5 block text-phu text-muted">Tiêu chuẩn bàn giao</legend>
      <div className={`${LUOI} mb-1 max-md:hidden`} aria-hidden="true">
        {COT.map((c) => (
          <span key={c.k} className="text-nhan text-muted-2">
            {c.nhan}
          </span>
        ))}
        <span />
      </div>
      <div className="space-y-2">
        {giaTri.map((h, i) => (
          <div key={i} className={LUOI}>
            {COT.map((c) => (
              <input
                key={c.k}
                className={O_CHUNG}
                aria-label={`${c.nhan} — dòng ${i + 1}`}
                list={c.k === 'item' ? idGoiY : undefined}
                placeholder={c.goiY}
                value={h[c.k]}
                onChange={(e) => sua(i, c.k, e.target.value)}
                onBlur={xong}
              />
            ))}
            <NutIcon
              icon="trash"
              nhan={`Xoá hạng mục dòng ${i + 1}`}
              phaHuy
              onClick={() => doiVaLuu(giaTri.filter((_, j) => j !== i))}
            />
          </div>
        ))}
      </div>
      <datalist id={idGoiY}>
        {GOI_Y_HANG_MUC.map((g) => (
          <option key={g} value={g} />
        ))}
      </datalist>
      <button
        type="button"
        className={`${NUT_PHU} mt-2`}
        onClick={() => doi([...giaTri, { ...HANG_MUC_TRONG }])}
      >
        Thêm hạng mục
      </button>
      {loi && <p className="mt-1 text-phu font-medium text-badge-alert-fg">{loi}</p>}
    </fieldset>
  )
}
