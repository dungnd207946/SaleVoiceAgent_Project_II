// Kịch bản trên ĐIỆN THOẠI — cùng cây gốc → nhóm → tình huống với `DoThi`, vẽ thành danh sách.
//
// Vì sao không co sơ đồ cho vừa (audit impeccable 05/10, P1 #2): cây rộng ~1000 đơn vị, «vừa khung»
// ở 390px là hệ số ~0,35 nên nhãn còn ~5px; mở ở cỡ đọc được thì thấy gốc với tên nhóm, còn tình
// huống — thứ cần đọc — nằm ngoài màn, phải kéo ngang từng đoạn. Trên điện thoại, cây là DANH SÁCH
// thụt lề: cùng thứ tự, cùng nhóm, cùng màu chấm, và tỷ lệ đạt ghi bằng chữ ngay cạnh tên.
//
// Không mất gì so với sơ đồ: đường chuyển tiếp của một tình huống đã có ở «Đi tiếp/Đến từ» trong
// bảng chi tiết, mở bằng một cú chạm.
import { useMemo } from 'react'
import type { NutKichBan, SoDoNut } from '../api'
import { HAU_TO_MAU, type LoaiMau } from '../khuon'
import { TEN_NHOM, boCucCay, khop, mauTiLe, pct, tenNut, type Mau } from '../logic'

const MAU_CHAM: Record<Mau, string> = {
  xanh: 'bg-ac',
  vang: 'bg-badge-warn-fg',
  do: 'bg-badge-alert-fg',
  xam: 'bg-n6',
}

interface Props {
  nodes: NutKichBan[]
  soDo: Record<string, SoDoNut>
  chon: string | undefined
  q: string
  onChon: (id: string) => void
  /** So với mẫu (bản riêng) — vắng ở trạng thái mẫu. */
  loaiMau?: Record<string, LoaiMau> | undefined
}

export function DanhSachNut({ nodes, soDo, chon, q, onChon, loaiMau }: Props) {
  const bc = useMemo(() => boCucCay(nodes), [nodes])
  const nhom = bc.nhom
    .map((g) => ({
      ...g,
      nut: nodes
        .filter((n) => n.nhom === g.nhom && khop(n, q))
        .sort((a, b) => bc.nut[a.id]!.y - bc.nut[b.id]!.y),
    }))
    .filter((g) => g.nut.length > 0)

  if (nhom.length === 0)
    return (
      <p className="rounded-lg border border-border bg-surface px-4 py-6 text-center text-[14px] text-muted">
        Không có tình huống nào khớp «{q.trim()}».
      </p>
    )

  return (
    <nav aria-label="Các tình huống kịch bản theo nhóm" className="space-y-4">
      {nhom.map((g) => (
        <section
          key={g.nhom}
          aria-labelledby={`nhom-${g.nhom}`}
          className="overflow-hidden rounded-lg border border-border bg-surface"
        >
          <h2
            id={`nhom-${g.nhom}`}
            className="flex items-baseline justify-between border-b border-border-soft px-4 py-2.5 text-[14px] font-semibold text-fg"
          >
            {TEN_NHOM[g.nhom] ?? g.nhom}
            <span className="font-mono text-phu font-normal text-muted">{g.so}</span>
          </h2>
          <ul>
            {g.nut.map((n) => {
              const nhap = n.trang_thai === 'nhap'
              const s = soDo[n.id]
              const dangChon = chon === n.id
              return (
                <li key={n.id} className="border-t border-border-soft first:border-t-0">
                  <button
                    type="button"
                    data-testid={`dong-${n.id}`}
                    aria-pressed={dangChon}
                    onClick={() => onChon(n.id)}
                    className={`flex min-h-12 w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left ${
                      dangChon ? 'bg-acs' : 'active:bg-fill'
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`size-2.5 flex-none rounded-full ${
                        nhap ? 'border border-dashed border-n6' : MAU_CHAM[mauTiLe(s, nhap)]
                      }`}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-the leading-snug text-fg">
                        {tenNut(n)}
                        {n.loai === 'luong' ? <span className="text-muted"> ▸</span> : null}
                        {HAU_TO_MAU[loaiMau?.[n.id] ?? 'giong'] ? (
                          <span className="text-phu text-muted">
                            {HAU_TO_MAU[loaiMau?.[n.id] ?? 'giong']}
                          </span>
                        ) : null}
                      </span>
                      <span className="block text-phu text-muted">
                        {nhap ? 'Đang tắt' : pct(s)} · {s?.soLuot ?? 0} lượt
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </nav>
  )
}
