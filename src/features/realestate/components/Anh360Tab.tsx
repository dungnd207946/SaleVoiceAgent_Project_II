/**
 * Tab Ảnh 360 — khung xem tour và ô `link360`.
 *
 * Ô link và nút Xoá link chỉ hiện khi đang sửa. Xoá link cần một bước xác nhận: link mất là mất hẳn.
 */
import { useCallback, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { suaDuAn, type DuAn } from '../api'
import { cauLoi, loiO } from '../thongDiep'
import { useLuuTungO } from '../useLuuTungO'
import { DongTrangThai, OChu } from '@/components/ui/Truong'
import { NUT_PHU, TAB_DAY } from '@/components/ui/Bang'
import { useKhungSua } from '../khungSua'
import { SectionCard } from './SectionCard'

interface Link360 {
  link360: string
}

const LINK = 'text-than font-medium text-ac hover:text-acd'

function nhungDuoc(url: string): boolean {
  return /^https:\/\//i.test(url)
}

function rutGon(url: string): string {
  try {
    const u = new URL(url)
    return `${u.host}${u.pathname}`
  } catch {
    return url
  }
}

export function Anh360Tab({ duAn, projectCode }: { duAn: DuAn; projectCode: string }) {
  const qc = useQueryClient()
  const { dangSua } = useKhungSua()
  const [hoiXoa, setHoiXoa] = useState(false)
  const khungRef = useRef<HTMLIFrameElement>(null)

  const luu = useCallback(
    async (patch: Partial<Link360>) => {
      const d = await suaDuAn(projectCode, patch)
      void qc.invalidateQueries({ queryKey: ['re', projectCode] })
      return d
    },
    [projectCode, qc],
  )

  const o = useLuuTungO<Link360>({ link360: duAn.link360 }, luu)

  return (
    <div className={`${TAB_DAY} flex flex-col gap-4 pb-2`}>
      <SectionCard cols={1}>
        {dangSua && (
          <div className="flex items-end gap-2.5 max-md:flex-col max-md:items-stretch">
            <div className="min-w-0 flex-1">
              <OChu
                ten="link360"
                nhan="Link tham quan 360"
                giaTri={o.v.link360}
                doi={(x) => o.doi('link360', x)}
                xong={() => o.xong('link360')}
                loi={loiO(o.loi, 'link360')}
                goiYTrongO="https://kuula.co/share/collection/…"
              />
            </div>
            {duAn.link360 &&
              (hoiXoa ? (
                <div className="flex flex-none gap-2">
                  <button type="button" className={NUT_PHU} onClick={() => setHoiXoa(false)}>
                    Thôi
                  </button>
                  <button
                    type="button"
                    className={NUT_PHU}
                    disabled={o.dangLuu}
                    onClick={() => {
                      o.doiVaLuu('link360', '')
                      setHoiXoa(false)
                    }}
                  >
                    Xoá hẳn
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className={`${NUT_PHU} flex-none`}
                  onClick={() => setHoiXoa(true)}
                >
                  Xoá link
                </button>
              ))}
          </div>
        )}
        {duAn.link360 ? (
          <div className="space-y-3">
            {nhungDuoc(duAn.link360) && (
              <iframe
                ref={khungRef}
                title="Tham quan 360"
                src={duAn.link360}
                loading="lazy"
                allowFullScreen
                className="h-[70vh] w-full rounded-lg border border-border bg-fill-strong"
              />
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="min-w-0 truncate font-mono text-[12px] text-muted-2">
                {rutGon(duAn.link360)}
              </span>
              <span className="flex flex-none items-center gap-4">
                {nhungDuoc(duAn.link360) && (
                  <button
                    type="button"
                    className={LINK}
                    onClick={() => {
                      khungRef.current?.requestFullscreen().catch(() => {})
                    }}
                  >
                    Toàn màn hình
                  </button>
                )}
                <a href={duAn.link360} target="_blank" rel="noreferrer" className={LINK}>
                  Mở ở tab mới
                </a>
              </span>
            </div>
          </div>
        ) : (
          <p className="text-than text-muted-2">
            {dangSua
              ? 'Chưa có link tham quan 360 — dán vào ô trên.'
              : 'Chưa có link tham quan 360.'}
          </p>
        )}
      </SectionCard>

      {o.loi != null && <DongTrangThai mau="alert">{cauLoi(o.loi, 'lưu link 360')}</DongTrangThai>}
    </div>
  )
}
