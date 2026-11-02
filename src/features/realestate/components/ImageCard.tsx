/** Thẻ một ảnh (ảnh cover, mặt bằng phân khu…): chế độ xem bấm ảnh để xem cỡ lớn, chế độ sửa hiện ô chọn ảnh. */
import { useState, type ReactNode } from 'react'
import { nguonAnh, type MediaKem } from '../api'
import { AnhLon } from './AnhLon'
import { SectionCard } from './SectionCard'

const LINK = 'text-than font-medium text-ac hover:text-acd'

export function ImageCard({
  title,
  media,
  editing,
  editor,
}: {
  title: string
  media: MediaKem | null | undefined
  editing: boolean
  editor: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const has = !!media?.mediaUrl
  return (
    <SectionCard
      title={title}
      cols={1}
      actions={
        !editing && has ? (
          <button type="button" className={LINK} onClick={() => setOpen(true)}>
            Xem ảnh lớn
          </button>
        ) : undefined
      }
    >
      {editing ? (
        editor
      ) : has ? (
        <button
          type="button"
          className="block w-full cursor-zoom-in overflow-hidden rounded-lg bg-fill-strong"
          aria-label={`Xem ${title.toLowerCase()} cỡ lớn`}
          onClick={() => setOpen(true)}
        >
          <img
            src={nguonAnh(media.thumbUrl || media.mediaUrl)}
            alt={media.caption || title}
            className="block aspect-[16/10] w-full object-cover"
          />
        </button>
      ) : (
        <div className="grid aspect-[16/10] place-items-center rounded-lg bg-fill-strong text-than text-muted-2">
          Chưa có ảnh
        </div>
      )}
      {open && has && (
        <AnhLon
          anh={[{ src: nguonAnh(media.mediaUrl), caption: media.caption ?? '' }]}
          batDau={0}
          onDong={() => setOpen(false)}
        />
      )}
    </SectionCard>
  )
}
