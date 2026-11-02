import type { Media, MediaKem } from './api'

/** Bản ghi media đã lưu → giá trị của ô chọn ảnh. */
export function mediaKem(m: Media | undefined): MediaKem | null {
  return m
    ? {
        mediaUrl: m.mediaUrl,
        caption: m.caption,
        fileName: m.fileName,
        contentType: m.contentType,
        thumbUrl: m.thumbUrl,
      }
    : null
}
