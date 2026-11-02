/** Thẻ «Kiến thức cho agent» ở tab Tổng quan. Trạng thái đang nạp và lỗi nạp chỉ báo ở đầu trang. */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { NUT_PHU } from '@/components/ui/Bang'
import { so } from '@/lib/dinhDang'
import { syncKb } from '../api'
import { KB_KEY, useKbStatus } from '../useKbStatus'
import { HoSoNgoai } from './HoSoNgoai'
import { SectionCard } from './SectionCard'

export function KbCard({ code, published }: { code: string; published: boolean }) {
  const qc = useQueryClient()
  const tt = useKbStatus().byCode[code]
  const sync = useMutation({
    mutationFn: () => syncKb(code, 'delta'),
    onSuccess: () => void qc.invalidateQueries({ queryKey: KB_KEY }),
  })
  const pct = tt && tt.total > 0 ? Math.round((tt.done / tt.total) * 100) : 0

  return (
    <SectionCard title="Kiến thức cho agent" cols={1}>
      <div className="space-y-3">
        <div>
          <span className="mb-1 block text-phu text-muted">Đã tới agent</span>
          {!tt || tt.total <= 0 ? (
            <span className="text-than text-muted-2">Chưa có gì để nạp</span>
          ) : (
            <span className="flex items-center gap-2 text-noi">
              <span className="block h-[5px] w-[72px] overflow-hidden rounded-full bg-fill-strong">
                <span className="block h-full rounded-full bg-ac" style={{ width: `${pct}%` }} />
              </span>
              <span className="font-mono tabular-nums">
                {so(tt.done)}/{so(tt.total)}
              </span>
              mục
            </span>
          )}
        </div>
        {published && <HoSoNgoai code={code} />}
        <div>
          <button
            type="button"
            className={NUT_PHU}
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            Nạp lại
          </button>
          {sync.error && (
            <span className="mt-1 block text-phu text-badge-alert-fg">
              Không gửi được yêu cầu. Thử lại.
            </span>
          )}
        </div>
      </div>
    </SectionCard>
  )
}
