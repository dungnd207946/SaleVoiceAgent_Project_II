/**
 * Dialog «Đổi avatar» — lưới 12 gợi ý DiceBear seed ngẫu nhiên từ server.
 *
 * Khuôn dialog theo `XoaWorkspaceDialog` (`HopThoai`). CHỌN rồi
 * LƯU chứ không lưu-ngay-khi-bấm: một cú bấm nhầm giữa lưới 12 ô không được
 * thành một cú ghi DB — người dùng phải thấy ô mình chọn sáng lên trước.
 *
 * «Dùng mặc định theo tên» gửi `avatarSeed: null` TƯỜNG MINH (hợp đồng backend:
 * null = xoá seed đã chọn, vắng khoá = không đổi) và không cần chọn ô nào.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { useLang } from '@/i18n'
import { LoiApi } from '@/lib/http'
import { layGoiYAvatar, suaHoSo } from '../api'

export function DoiAvatarDialog({ onDong }: { onDong: () => void }) {
  const { t } = useLang()
  const queryClient = useQueryClient()
  const [seedChon, setSeedChon] = useState<string | null>(null)

  const goiY = useQuery({ queryKey: ['avatar-goi-y'], queryFn: layGoiYAvatar, staleTime: 0 })

  const luu = useMutation({
    mutationFn: (avatarSeed: string | null) => suaHoSo({ avatarSeed }),
    onSuccess: (moi) => {
      queryClient.setQueryData(['session'], moi)
      onDong()
    },
  })

  return (
    <HopThoai
      onDong={onDong}
      aria-labelledby="doi-avatar-tieu-de"
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 id="doi-avatar-tieu-de" className="text-[16.5px] font-semibold leading-tight text-fg">
        {t({ vi: 'Đổi avatar', en: 'Change avatar' })}
      </h2>

      {goiY.error ? (
        <p role="alert" className="mt-4 text-[13px] text-badge-alert-fg">
          {t({
            vi: 'Không tải được gợi ý — thử lại.',
            en: 'Could not load suggestions — try again.',
          })}
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-6 gap-2.5">
          {(goiY.data ?? []).map((m, i) => (
            <button
              key={m.seed}
              type="button"
              aria-label={t({ vi: `Gợi ý ${i + 1}`, en: `Suggestion ${i + 1}` })}
              aria-pressed={seedChon === m.seed}
              onClick={() => setSeedChon(m.seed)}
              className={`overflow-hidden rounded-full border-2 transition
                            ${seedChon === m.seed ? 'border-ac' : 'border-transparent hover:border-border'}`}
            >
              <img src={m.avatar} alt="" className="aspect-square w-full" />
            </button>
          ))}
        </div>
      )}

      {luu.error && (
        <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
          {luu.error instanceof LoiApi
            ? luu.error.message
            : t({ vi: 'Không lưu được avatar', en: 'Could not save the avatar' })}
        </p>
      )}

      <div className={`${HANG_NUT} mt-5`}>
        {/* «Dùng mặc định» đẩy về TRÁI: nó là một lối thoát, không phải một
              trong cặp Huỷ/Lưu của hành động chính. */}
        <button
          type="button"
          onClick={() => luu.mutate(null)}
          disabled={luu.isPending}
          className="mr-auto text-[13px] text-muted underline-offset-2 hover:underline"
        >
          {t({ vi: 'Dùng mặc định theo tên', en: 'Use default from name' })}
        </button>
        <button
          type="button"
          onClick={() => goiY.refetch()}
          disabled={goiY.isFetching}
          className={NUT_PHU}
        >
          {t({ vi: 'Đảo bộ khác', en: 'Shuffle' })}
        </button>
        <button
          type="button"
          onClick={() => seedChon && luu.mutate(seedChon)}
          disabled={seedChon === null || luu.isPending}
          className={NUT_CHINH}
        >
          {luu.isPending
            ? t({ vi: 'Đang lưu…', en: 'Saving…' })
            : t({ vi: 'Lưu avatar', en: 'Save avatar' })}
        </button>
      </div>
    </HopThoai>
  )
}
