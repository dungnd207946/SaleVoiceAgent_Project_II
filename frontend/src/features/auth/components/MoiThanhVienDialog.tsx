/**
 * Hộp thoại mời — NHIỀU email, MỘT vai trò, MỘT bước.
 *
 * Lối của ElevenLabs · Linear · Vercel: vai trò chọn NGAY trong bước mời, nên
 * quyền được khoanh từ cú bấm đầu tiên. Trước 2026-08-09 mình là hai bước — tạo
 * user cấp tổ chức, rồi gán membership ở một form khác.
 *
 * MỘT vai trò cho cả lô là có chủ ý: muốn hai vai trò thì mời hai lượt. Cho mỗi
 * email một vai trò biến hộp thoại thành một bảng con — đúng thứ vừa bị cắt.
 *
 * ⚠ PANEL KẾT QUẢ LÀ CHỖ DUY NHẤT LỆCH VỚI BA HỆ KIA. Backend không có bộ gửi
 * mail (`grep -rEi 'smtp|sendgrid|mailgun|send_email' src` → rỗng, 2026-08-09),
 * nên admin phải tự copy link đi gửi. Ngày có mailer, `invitePath` về `null` và
 * CHỈ panel này đổi thành một dòng «Đã gửi email tới N người» — không đụng gì
 * khác trong màn. Đừng để logic mailer rò ra ngoài file này.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { LoiApi } from '@/lib/http'
import { khoaVaiTro, layDanhSachVaiTro } from '../api'
import { KHOA_TV, moiThanhVien, urlMoi, type KetQuaMoi, type LoiMoiTungDong } from '../thanhVien'

/** Tách theo dấu phẩy, chấm phẩy, khoảng trắng, xuống dòng — dán từ Excel vẫn chạy. */
function tachEmail(tho: string): string[] {
  return tho
    .split(/[\s,;]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
}

export function MoiThanhVienDialog({ onDong }: { onDong: () => void }) {
  const queryClient = useQueryClient()
  const [emails, setEmails] = useState<string[]>([])
  const [dangGo, setDangGo] = useState('')
  const [roleId, setRoleId] = useState('')
  const [ketQua, setKetQua] = useState<KetQuaMoi[] | null>(null)
  const [loiTungDong, setLoiTungDong] = useState<LoiMoiTungDong[]>([])
  const { data: vaiTro } = useQuery({ queryKey: khoaVaiTro.tatCa, queryFn: layDanhSachVaiTro })

  function nhan(tho: string) {
    // `Set` chứ không `includes`: dán 40 email từ Excel thì phép lọc O(n²) đủ
    // chậm để thấy được, và trùng lặp là chuyện thường khi dán.
    const co = new Set(emails)
    const them = tachEmail(tho).filter((e) => !co.has(e))
    if (them.length > 0) setEmails([...emails, ...them])
    setDangGo('')
  }

  const gui = useMutation({
    mutationFn: (ds: readonly string[]) => moiThanhVien(ds, roleId),
    onSuccess: (ra) => {
      setKetQua(ra.invites)
      // `?? []` — khiên cho test/handler cũ chưa trả `loi` (trường MỚI
      // 2026-08-17): khoá vắng đọc thành `undefined`, không phải mảng rỗng.
      setLoiTungDong(ra.loi ?? [])
      void queryClient.invalidateQueries({ queryKey: KHOA_TV })
    },
  })

  function guiDi() {
    // Gom ô đang gõ dở NGAY TẠI ĐÂY, không dựa vào `onBlur` kịp chạy trước
    // `onClick`: hai sự kiện đó đến từ CÙNG một cú bấm, và thứ tự flush state
    // giữa chúng là chi tiết cài đặt của React, không phải hợp đồng. Bản trước
    // đúng hay sai tuỳ nhịp — và một email bị nuốt im lặng thì không ai thấy.
    const con = tachEmail(dangGo).filter((e) => !emails.includes(e))
    gui.mutate(con.length > 0 ? [...emails, ...con] : emails)
  }

  return (
    <HopThoai
      onDong={onDong}
      aria-label="Mời thành viên"
      className={`${KHUNG_HOP_THOAI} max-w-[520px]`}
    >
      {ketQua ? (
        <PanelKetQua ketQua={ketQua} loi={loiTungDong} onDong={onDong} />
      ) : (
        <>
          <h2 className="text-the font-semibold text-fg">Mời thành viên</h2>

          <label htmlFor="moi-email" className="mt-4 block text-than font-medium text-fg">
            Email
          </label>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded-md border border-border-field px-2 py-1.5 focus-within:border-ac">
            {emails.map((e) => (
              <span
                key={e}
                className="inline-flex items-center gap-1 rounded-sm bg-fill px-2 py-1 text-phu text-fg"
              >
                {e}
                <button
                  type="button"
                  aria-label={`Bỏ ${e}`}
                  onClick={() => setEmails(emails.filter((x) => x !== e))}
                  className="text-muted"
                >
                  ×
                </button>
              </span>
            ))}
            <input
              id="moi-email"
              type="email"
              value={dangGo}
              placeholder={emails.length === 0 ? 'lan@anphuland.vn' : ''}
              onChange={(e) => setDangGo(e.target.value)}
              // Enter · phẩy · Tab đều chốt một chip; `blur` chốt nốt cái đang
              // gõ dở. Thiếu vế `blur` thì bấm thẳng «Gửi» sẽ bỏ rơi email cuối
              // mà không báo gì.
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ',' || e.key === 'Tab') {
                  if (dangGo.trim() === '') return
                  e.preventDefault()
                  nhan(dangGo)
                }
              }}
              onBlur={() => dangGo.trim() !== '' && nhan(dangGo)}
              onPaste={(e) => {
                e.preventDefault()
                nhan(e.clipboardData.getData('text'))
              }}
              className="min-w-[160px] flex-1 bg-transparent py-1 text-[14px] outline-none"
            />
          </div>

          <p className="mt-4 text-than font-medium text-fg">Vai trò</p>
          <div className="mt-1.5 space-y-1" role="radiogroup" aria-label="Vai trò">
            {(vaiTro ?? []).map((v) => (
              <label
                key={v.id}
                className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 hover:bg-fill"
              >
                <input
                  type="radio"
                  name="moi-vai-tro"
                  value={v.id}
                  checked={roleId === v.id}
                  onChange={() => setRoleId(v.id)}
                />
                <span className="text-[14px] text-fg">{v.name}</span>
              </label>
            ))}
          </div>

          {gui.error && (
            <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
              {gui.error instanceof LoiApi ? gui.error.message : 'Không gửi được lời mời'}
            </p>
          )}

          <div className={`${HANG_NUT} mt-5`}>
            <button type="button" className={NUT_PHU} onClick={onDong}>
              Huỷ
            </button>
            <button
              type="button"
              className={NUT_CHINH}
              // `emails.length === 0 && dangGo.trim() === ''` chứ không chỉ
              // `emails.length === 0`: một email đang gõ dở (chưa Enter) vẫn
              // là một email — khoá nút vì nó nằm ngoài mảng `emails` là ép
              // người dùng bấm Enter thêm một lần chỉ để mở khoá nút Gửi.
              disabled={
                (emails.length === 0 && dangGo.trim() === '') || roleId === '' || gui.isPending
              }
              onClick={guiDi}
            >
              Gửi lời mời
            </button>
          </div>
        </>
      )}
    </HopThoai>
  )
}

/** Câu cho từng mã lỗi ở `loi[].ma` — MỘT chỗ dịch, thêm mã mới thì thêm ở đây. */
function cauLoiTungDong(email: string, ma: string): string {
  switch (ma) {
    case 'USER_PENDING_SIGNUP':
      return `${email} đang chờ hoàn tất đăng ký. Khi họ đặt xong mật khẩu, hãy mời lại.`
    case 'USER_SUSPENDED':
      return `${email} đang bị đình chỉ nên không thể mời vào workspace này.`
    case 'USER_ALREADY_MEMBER':
      // Trước 2026-08-22 ca này im lặng thành công (UPSERT membership) — mời lại
      // người đã ở trong nhà cũng trả `daCo=true`. Nay nó nói ra.
      return `${email} đã là thành viên của workspace này rồi.`
    default:
      return `${email} — không mời được (${ma}).`
  }
}

function PanelKetQua({
  ketQua,
  loi,
  onDong,
}: {
  ketQua: readonly KetQuaMoi[]
  loi: readonly LoiMoiTungDong[]
  onDong: () => void
}) {
  // Từ 2026-08-22 CẢ HAI nhánh (đã có tài khoản hay chưa) đều phát token khi
  // mailer tắt — KHÔNG còn nhánh nào thêm thẳng vào workspace. `daCo` giờ chỉ
  // chọn CÂU, không còn chọn có hiện link hay không (xem docstring `KetQuaMoi`
  // ở `thanhVien.ts`). Vòng lặp link dưới đây phải chạy trên TOÀN BỘ `ketQua`
  // — lọc theo `!daCo` như bản trước sẽ giấu mất link của người ĐÃ có tài
  // khoản, đúng cái mà bài test `email đã có tài khoản` canh.
  //
  // ⚠ CÂU TỔNG HỢP "đã gửi thư xác nhận tham gia" CHỈ ĐÚNG khi thư THẬT SỰ đã
  // gửi (`invitePath === null`). Round 1 review bắt một mâu thuẫn: bản trước
  // lọc khối này CHỈ theo `daCo`, nên một người `daCo:true` mà mailer TẮT
  // (`invitePath` khác `null`) vừa được panel nói "đã gửi thư xác nhận tham
  // gia", vừa được đưa một ô link ngay dưới banner "Chưa gửi được email tự
  // động — gửi link này cho họ" — hai câu ngược nhau cho CÙNG một người, và
  // admin không biết tin câu nào (tin nhầm câu "đã gửi" thì không ai forward
  // link, lời mời không tới ai). Lọc thêm `invitePath === null` để câu tổng
  // hợp chỉ nói về những người thư ĐÃ đi thật.
  const daCoThuDaGui = ketQua.filter((k) => k.daCo && k.invitePath === null)
  // Chỉ để hiện/ẩn câu dẫn «Chưa gửi được email tự động…» — KHÔNG dùng để gate
  // cả khối link. Gate cả khối (kiểu cũ) từng làm một người biến mất khỏi
  // TOÀN BỘ panel nếu họ là người DUY NHẤT và `invitePath` của họ là `null`
  // (`coLink` = false ⇒ cả khối, kể cả fallback bên dưới, không render) — bài
  // học đó vẫn đúng dù biến nguồn đổi từ `moi` sang `ketQua`.
  const coLink = ketQua.some((k) => k.invitePath !== null)

  return (
    <>
      <h2 className="text-the font-semibold text-fg">Đã gửi {ketQua.length} lời mời</h2>
      <p className="mt-1.5 text-than leading-[1.55] text-muted">
        {/* Câu này nói cho Quản trị biết luật vừa đổi: không ai được thêm vào
            workspace cho tới khi chính họ bấm xác nhận trong thư — kể cả
            người đã có tài khoản. */}
        Người nhận sẽ vào workspace sau khi bấm xác nhận trong thư. Lời mời có hiệu lực 7 ngày.
      </p>

      {coLink && (
        <p className="mt-3 text-than leading-[1.55] text-muted">
          Chưa gửi được email tự động — gửi link này cho họ.
        </p>
      )}
      <div className="mt-3 space-y-2">
        {ketQua.map((k) => {
          const url = urlMoi(k.invitePath)
          if (url === null) {
            // `invitePath === null` = mailer đã gửi thư THẬT. Người ĐÃ có tài
            // khoản được nêu tên ở khối `daCoThuDaGui` ngay dưới (câu đúng cho
            // họ: "đã gửi thư xác nhận tham gia", KHÔNG phải "đặt mật khẩu
            // mới" — họ đã có mật khẩu từ trước) — `return null` ở đây để
            // tránh nói hai câu khác nhau cho cùng một người. Người CHƯA có
            // tài khoản thì đây là chỗ DUY NHẤT nêu tên họ, nên không được bỏ
            // qua: nếu ngày mailer về NỬA VỜI (gửi được vài người, lỗi vài
            // người khác) thì họ vẫn không rơi mất khỏi panel một cách im
            // lặng.
            if (k.daCo) return null
            return (
              <p key={k.email} className="text-phu text-muted-2">
                {k.email} — đã gửi thư xác nhận tham gia.
              </p>
            )
          }
          // `invitePath` khác `null` ⇒ mailer TẮT cho người này — admin phải
          // tự forward link, nên KHÔNG câu nào ở hàng này được nói "đã gửi
          // thư". Người ĐÃ có tài khoản vẫn cần được nêu SỰ THẬT đó (giải
          // thích vì sao hàng này khác — họ không cần đặt mật khẩu mới), nhưng
          // ghi NGAY TRONG hàng thay vì một câu tổng hợp riêng: nêu tên họ ở
          // hai nơi cùng lúc là dư (Minor round 1 review).
          return (
            <div key={k.email} className="flex flex-wrap items-center gap-2">
              <span className="min-w-[150px] font-mono text-phu text-muted-2">
                {k.email}
                {k.daCo && <span className="text-muted"> · đã có tài khoản</span>}
              </span>
              {/* `k.email`, KHÔNG `k.userId`: `userId` nay `null` cho email
                  chưa có tài khoản, và hai `id="link-null"` là hai `htmlFor`
                  trỏ vào cùng một ô — email thì luôn khác nhau giữa các hàng. */}
              <label className="sr-only" htmlFor={`link-${k.email}`}>
                Link mời của {k.email}
              </label>
              <input
                id={`link-${k.email}`}
                readOnly
                value={url}
                onFocus={(e) => e.currentTarget.select()}
                className="min-w-[200px] flex-1 rounded-md border border-border-field bg-surface px-3 py-2 font-mono text-phu outline-none focus:border-fg"
              />
              <button
                type="button"
                className={NUT_PHU}
                onClick={() => void navigator.clipboard.writeText(url).catch(() => {})}
              >
                Sao chép
              </button>
            </div>
          )
        })}
      </div>

      {daCoThuDaGui.length > 0 && (
        <p className="mt-3.5 text-[13px] leading-[1.55] text-muted">
          {daCoThuDaGui.map((k) => k.email).join(' · ')} — đã có tài khoản, đã gửi thư xác nhận tham
          gia.
        </p>
      )}

      {/* Lỗi TỪNG DÒNG (2026-08-17) — một email hỏng không kéo cả lô rớt theo,
          nên đây là khối RIÊNG cạnh khối link/`daCo` ở trên, không phải một
          nhánh lỗi chặn cả panel. */}
      {loi.length > 0 && (
        <div role="alert" className="mt-3.5 space-y-1 text-[13px] leading-[1.55] text-muted">
          {loi.map((l) => (
            <p key={l.email}>{cauLoiTungDong(l.email, l.ma)}</p>
          ))}
        </div>
      )}

      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" className={NUT_CHINH} onClick={onDong}>
          Xong
        </button>
      </div>
    </>
  )
}
