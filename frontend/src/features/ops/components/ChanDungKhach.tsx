/**
 * Chân dung khách — những gì AGENT đã khai thác về MỘT số, gộp qua mọi phiên. Chỉ đọc.
 *
 * Tự gọi query của mình: `PhienKhach` không phải chờ thêm một request mới vẽ được
 * transcript, và chân dung hỏng thì chỉ panel này báo hỏng.
 */
import { useQuery } from '@tanstack/react-query'
import { chanDungKhach, type ChanDung } from '../api'
import { chuaCoGi, ghiChuCua, nhanTinHieu, nhomChanDung } from '../chanDung'
import { ngayGio } from '../thoiGian'

/** Tiêu đề nhóm: chữ thường, đậm — tách khỏi nhãn dòng (13px thường `muted`) bằng độ
 *  đậm + màu. Không mang màu riêng để ô «Agent ghi nhớ» tô sắc của nó (polish 05/10). */
const TIEU_DE = 'text-phu font-semibold'

export function ChanDungKhach({
  phone,
  tenDuAn,
  className = '',
}: {
  phone: string
  tenDuAn: ReadonlyMap<string, string>
  className?: string
}) {
  const q = useQuery({
    queryKey: ['convos', 'chan-dung', phone],
    queryFn: () => chanDungKhach(phone),
  })
  return (
    <aside aria-label="Thông tin khách" className={`min-h-0 overflow-y-auto p-4 ${className}`}>
      <h2 className="text-than font-semibold">Thông tin khách</h2>
      {q.isPending && <p className="mt-3 text-[13px] text-muted">Đang tải…</p>}
      {q.error && <p className="mt-3 text-[13px]">Không tải được thông tin khách.</p>}
      {q.data && <NoiDung cd={q.data} tenDuAn={tenDuAn} />}
    </aside>
  )
}

function NoiDung({ cd, tenDuAn }: { cd: ChanDung; tenDuAn: ReadonlyMap<string, string> }) {
  const nhom = nhomChanDung(cd.hoSo, tenDuAn)
  const ghiChu = ghiChuCua(cd.hoSo)
  // Không gì cả ⇒ một câu nói thẳng, KHÔNG phải mười dòng «Chưa khai thác».
  if (!cd.ghiNho && chuaCoGi(nhom) && ghiChu.length === 0 && cd.tinHieu.length === 0)
    return (
      <p className="mt-3 text-[13px] text-muted">Agent chưa ghi nhận thông tin nào về khách này.</p>
    )
  return (
    <div className="mt-3 space-y-4">
      {cd.ghiNho && (
        // Cùng khuôn ô «Tóm tắt của agent» ở `PhienKhach` — đều là lời agent tự viết.
        <section className="rounded-lg border border-badge-neutral-bg bg-badge-neutral-bg px-3 py-2.5 text-[13px] leading-[1.55]">
          <h3 className={`mb-1 ${TIEU_DE} text-badge-neutral-fg`}>Agent ghi nhớ</h3>
          <p>{cd.ghiNho}</p>
        </section>
      )}
      {nhom.map((n) => (
        <section key={n.tieuDe}>
          <h3 className={TIEU_DE}>{n.tieuDe}</h3>
          <dl className="mt-1.5 space-y-1">
            {n.dong.map((d) => (
              <div
                key={d.nhan}
                className="grid grid-cols-[112px_1fr] gap-2 text-[13px] leading-[1.5]"
              >
                <dt className="text-muted">{d.nhan}</dt>
                <dd className={d.gia === null ? 'italic text-muted-3' : undefined}>
                  {d.gia ?? 'Chưa khai thác'}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
      {ghiChu.length > 0 && (
        <section>
          <h3 className={TIEU_DE}>Ghi chú</h3>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[13px] leading-[1.5]">
            {ghiChu.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </section>
      )}
      {cd.tinHieu.length > 0 && (
        <section>
          <h3 className={TIEU_DE}>Tín hiệu lead</h3>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {cd.tinHieu.map((t) => (
              <span
                key={t}
                className="rounded-full bg-badge-neutral-bg px-2 py-0.5 text-[12px] text-badge-neutral-fg"
              >
                {nhanTinHieu(t)}
              </span>
            ))}
          </div>
        </section>
      )}
      {cd.capNhatLuc && (
        <p className="text-[11.5px] text-muted-2">Cập nhật {ngayGio(cd.capNhatLuc)}</p>
      )}
    </div>
  )
}
