import { useMemo } from 'react'
import { LoiApi } from '@/lib/http'
import {
  useDangGhiKichBan,
  useGhiKichBan,
  type DuLieuKichBan,
  type GioiHan,
  type NutVao,
} from './api'
import { boSale, heThong, kiemBo } from './khuon'
import { tenNut } from './logic'

export interface KetQuaGhi {
  ok: boolean
  /** Lỗi cả bộ phát hiện phía client — chưa gửi gì. */
  loiBo: string[]
  /** Lỗi của lời gọi (`LoiApi` 409/422…, lỗi mạng). */
  loi: unknown
  /** Bộ đã gửi — để đổi `body.nut[i]` của 422 ra tình huống. */
  moi: NutVao[]
}

/**
 * Câu báo cho một lần ghi hỏng: `LoiApi` mang câu tiếng Việt của BE; lỗi mạng, hoặc thân không phải lỗi của BE
 * (`UNKNOWN` — 502/504 của gateway trả HTML, câu dự phòng là «PUT /playbook → 502») thì câu chung (spec §7).
 */
export const cauLoi = (e: unknown) =>
  e instanceof LoiApi && e.code !== 'UNKNOWN' ? e.message : 'Chưa lưu được — thử lại.'

/**
 * MỘT đường ghi cho mọi thao tác trên tình huống (spec đợt 3 §3): bộ sale lấy từ lần tải `GET /playbook` mới nhất
 * (`data` của màn), áp `bienDoi`, kiểm cả bộ phía client, rồi `PUT` với `version` của chính lần tải đó. Mutation
 * chờ tải lại xong mới hết `isPending` (`useGhiKichBan`) ⇒ nút ghi khoá tới lúc `data` mang `version` mới.
 * Đừng giữ bản sao bộ nút trong state: bản sao cũ là cách ghi đè lần lưu của người khác.
 */
export function useGhi(data: DuLieuKichBan | undefined, gioiHan: GioiHan | undefined) {
  const { luu } = useGhiKichBan()
  const dangGhi = useDangGhiKichBan()
  const ten = useMemo(
    () => Object.fromEntries((data?.nodes ?? []).map((n) => [n.id, tenNut(n)])),
    [data],
  )
  async function ghi(bienDoi: (bo: NutVao[]) => NutVao[]): Promise<KetQuaGhi> {
    if (!data || !gioiHan)
      return { ok: false, loiBo: ['Chưa tải xong kịch bản — thử lại.'], loi: null, moi: [] }
    const moi = bienDoi(boSale(data.nodes))
    const loiBo = kiemBo(moi, heThong(data.nodes), gioiHan, ten)
    if (loiBo.length) return { ok: false, loiBo, loi: null, moi }
    try {
      await luu.mutateAsync({ version: data.kichBan.version, nut: moi })
      return { ok: true, loiBo: [], loi: null, moi }
    } catch (e) {
      return { ok: false, loiBo: [], loi: e, moi }
    }
  }
  return { ghi, dangGhi, ten }
}
