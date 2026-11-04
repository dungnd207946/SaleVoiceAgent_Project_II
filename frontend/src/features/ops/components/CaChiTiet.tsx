/**
 * Khối chi tiết bên phải — thứ sale đọc trước khi bấm gọi.
 *
 * Thứ tự cố ý: ai · gọi được không · tóm tắt nhu cầu · TRÍCH HỘI THOẠI · ghi chú
 * đồng nghiệp. Câu hỏi đầu tiên của sale là "gọi ai, số nào", nên cảnh báo thiếu
 * số nằm NGAY dưới header chứ không nằm cuối trang.
 *
 * Trích đoạn nằm ngay dưới tóm tắt vì hai khối trả lời CÙNG một câu hỏi — khách
 * muốn gì — chỉ khác độ phân giải. Ghi chú đồng nghiệp trả lời câu khác (đã ai
 * làm gì chưa) nên xuống sau.
 */
import type { Ref } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { Icon } from '@/components/icons'
import { NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { type Ca, lichSuGhiChu, trichHoiThoai } from '../api'
import { mauCua, noiDungAvatar } from '../avatar'
import { ngayGio } from '../thoiGian'
import { ChipDangTomTat, NhanKyNang } from './caChip'
import { Transcript } from './Transcript'

const NHAN_KENH: Record<string, string> = { voice: 'Gọi thoại', chat: 'Chat' }

function LichSuGhiChu({ ca }: { ca: Ca }) {
  const ds = useQuery({ queryKey: ['escalation-notes', ca.id], queryFn: () => lichSuGhiChu(ca.id) })
  if (!ds.data?.length) return ca.ghiChu ? <MotGhiChu noiDung={ca.ghiChu} /> : null
  return (
    <>
      <TieuMuc>Ghi chú của sale</TieuMuc>
      <ol className="space-y-2">
        {ds.data.map((g) => (
          <li key={g.id} className="rounded-lg border border-border bg-bg px-4 py-3">
            <p className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-muted-2">
              <span className="font-medium text-muted">{g.nguoi ?? 'Không rõ người ghi'}</span>
              <span className="font-mono">{ngayGio(g.luc)}</span>
            </p>
            <p className="mt-1 text-than leading-[1.6]">{g.noiDung}</p>
          </li>
        ))}
      </ol>
    </>
  )
}

function MotGhiChu({ noiDung }: { noiDung: string }) {
  return (
    <>
      <TieuMuc>Ghi chú của sale</TieuMuc>
      <div className="rounded-lg border border-border bg-bg px-4 py-3">
        <p className="text-than leading-[1.6]">{noiDung}</p>
      </div>
    </>
  )
}

/**
 * Mấy lượt thoại ngay TRƯỚC lúc agent chuyển — bậc còn thiếu giữa bản tóm tắt
 * (một bản diễn giải, có thể hụt) và transcript đầy đủ (đúng nhưng phải rời màn).
 *
 * Dùng lại `Transcript`, KHÔNG viết bộ render thứ hai: nó nhận đúng `Luot[]` mà
 * endpoint trả về và mang sẵn phần phòng thủ cho dữ liệu do hệ khác ghi (`role`
 * không có CHECK, `meta` jsonb tuỳ ý, `Invalid Date`). Hai bộ render cho cùng một
 * dữ liệu là hai bộ sẽ lệch nhau — và sale bấm sang transcript đầy đủ phải thấy
 * cùng một cách bày, không phải hai kiểu chat cho cùng một cuộc gọi.
 *
 * Backend đã lọc sạch hàng `tool` và assistant rỗng ở tầng SQL, nên bộ máy khối
 * công cụ của `Transcript` không bao giờ kích hoạt ở đây. Đúng chiều: backend
 * quyết định CÁI GÌ được đọc, `Transcript` quyết định nó TRÔNG THẾ NÀO.
 */
function TrichHoiThoai({ ca }: { ca: Ca }) {
  const ds = useQuery({
    queryKey: ['escalation-trich', ca.id],
    queryFn: () => trichHoiThoai(ca.id),
  })
  const luot = ds.data ?? []

  return (
    <>
      <TieuMuc>Hội thoại</TieuMuc>
      <div className="rounded-lg border border-border bg-bg px-4 py-3">
        {ds.isPending ? (
          <p className="text-[13px] text-muted-2">Đang tải hội thoại…</p>
        ) : (
          <Transcript luot={luot} />
        )}
        {/* Lằn ranh nằm SAU lượt cuối vì `message_seq` được chụp lúc tool escalate
            đang chạy: câu «em chuyển cho chuyên viên» chưa nằm trong history, nên
            lượt cuối đọc được luôn là câu hỏi chưa được trả lời của khách. */}
        {luot.length > 0 && (
          <p className="mt-3 flex items-center gap-2.5">
            <span className="whitespace-nowrap text-nhan font-semibold text-acd">
              Agent chuyển ở đây
            </span>
            <span className="h-px flex-1 bg-ac/25" />
          </p>
        )}
      </div>

      <div className="mt-2.5 flex items-center justify-between gap-3 text-phu">
        <span className="font-mono text-muted-2">
          {luot.length} / {ca.soLuot} lượt
        </span>
        <Link
          to="/convos/$phone"
          params={{ phone: ca.phone ?? '_' }}
          search={{ session: ca.sessionId }}
          className="font-medium text-ac hover:text-acd max-md:inline-flex max-md:min-h-10 max-md:items-center"
        >
          Mở transcript đầy đủ →
        </Link>
      </div>
    </>
  )
}

function Muc({ nhan, children }: { nhan: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-phu text-muted">{nhan}</dt>
      <dd className="mt-0.5 text-than">{children}</dd>
    </div>
  )
}

/**
 * Tiêu đề khối + kẻ mảnh chạy nốt phần dòng còn lại.
 *
 * Bản trước tiêu đề và nhãn trường (`Muc`) đều là chữ HOA li ti giãn chữ, chỉ khác
 * màu và độ đậm — nên phải thêm một thanh dọc accent để tách hai bậc. Từ polish
 * 05/10 cả hai về chữ thường như mọi màn khác của portal (nhãn trường = `DongXem`:
 * 12,5px `muted`), và hai bậc tách bằng CỠ + ĐỘ ĐẬM + MÀU (13,5px đậm `fg` vs
 * 12,5px thường `muted`) cộng đường kẻ — thanh dọc hết việc, và gạch màu >1px
 * đầu một khối là kiểu craft floor cấm. Đường kẻ để TRUNG TÍNH (`bg-border`):
 * `theme.css` giữ accent cho HÀNH ĐỘNG.
 */
function TieuMuc({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2.5 mt-[18px] flex items-center gap-2.5 text-than font-semibold leading-tight text-fg">
      {children}
      <span className="h-px flex-1 bg-border" />
    </h3>
  )
}

/**
 * Nút đổi trạng thái của một ca + «Gọi». Dùng ở HAI chỗ: đầu khung chi tiết
 * (desktop) và hàng dán đáy (điện thoại — `HopThuSale`), nên tách khỏi
 * `CaChiTiet`.
 *
 * «Gọi» là `<a href="tel:">` — gọi lại khách là toàn bộ việc của CSKH, mà trước
 * đây số chỉ là chữ thường, phải đọc rồi bấm tay mười chữ số. Gọi một ca CHƯA
 * LIÊN HỆ thì TỰ NHẬN ca (người dùng chốt 05/10): hai người cùng mở một ca chưa
 * ai nhận rồi cùng gọi là hai cuộc gọi cho một khách. Nhận nhầm thì «Hoàn tác»
 * ở dải báo ngay trên.
 *
 * Một nút CHÍNH mỗi trạng thái: có số ⇒ «Gọi»; không số ⇒ việc chính của trạng
 * thái đó. Nút chính đứng CUỐI (luật hàng nút).
 */
export function NutCa({
  ca,
  nhan,
  moGhiChu,
  dangGui,
  them = '',
}: {
  ca: Ca
  nhan: (trangThai: 'new' | 'contacted') => void
  moGhiChu: () => void
  dangGui: boolean
  /** Lớp ghép thêm cho MỌI nút (hàng dán đáy: `flex-auto` — chia chỗ theo độ dài chữ, ba nút ở 390px thì «Đánh dấu xong» cần rộng hơn «Gọi» — + cao 44px). */
  them?: string
}) {
  // Ca đã xong thì thôi mời gọi: gọi tiếp là mở lại ca trước (một bước có chủ ý).
  const so = ca.trangThai === 'done' ? null : ca.phone
  const goiDuoc = so !== null
  const phu = `${NUT_PHU} whitespace-nowrap text-muted transition-colors hover:bg-bg disabled:opacity-50 ${them}`
  const chinh = `${NUT_CHINH} whitespace-nowrap transition-colors hover:bg-acd ${them}`
  return (
    <>
      {ca.trangThai === 'new' && (
        <button
          type="button"
          disabled={dangGui}
          onClick={() => nhan('contacted')}
          className={goiDuoc ? phu : chinh}
        >
          Nhận ca này
        </button>
      )}
      {ca.trangThai === 'contacted' && (
        <>
          <button type="button" disabled={dangGui} onClick={() => nhan('new')} className={phu}>
            Trả lại ca
          </button>
          <button
            type="button"
            disabled={dangGui}
            onClick={moGhiChu}
            className={goiDuoc ? phu : chinh}
          >
            Đánh dấu xong
          </button>
        </>
      )}
      {ca.trangThai === 'done' && (
        <button type="button" disabled={dangGui} onClick={() => nhan('contacted')} className={phu}>
          Mở lại ca
        </button>
      )}
      {so !== null && (
        <a
          href={`tel:${so.replace(/[^\d+]/g, '')}`}
          aria-label={`Gọi ${so}`}
          onClick={() => {
            if (ca.trangThai === 'new' && !dangGui) nhan('contacted')
          }}
          className={`${chinh} gap-2 hover:text-white`}
        >
          <Icon name="goiDien" className="size-4" />
          Gọi
        </a>
      )}
    </>
  )
}

export function CaChiTiet({
  ca,
  nhan,
  moGhiChu,
  dangGui,
  tieuDeRef,
  anNut = false,
}: {
  ca: Ca
  nhan: (trangThai: 'new' | 'contacted') => void
  moGhiChu: () => void
  dangGui: boolean
  /** Đích focus sau khi đổi trạng thái — `HopThuSale` đưa focus về đây. */
  tieuDeRef?: Ref<HTMLHeadingElement>
  /** Điện thoại: nút ca xuống hàng dán đáy — đứng cạnh tên ở 390px thì nút đè
   *  lên tên (đo critique 05/10: `<h2>` còn 22px ngang, mỗi chữ một dòng). */
  anNut?: boolean
}) {
  return (
    <div className="p-6 max-md:p-4">
      {/* `flex-wrap` + tên tối thiểu 10rem: khung chi tiết hẹp (tablet, desktop
          1024 có panel) thì cụm nút XUỐNG DÒNG, không bóp tên còn một chữ mỗi
          dòng. Ở 1440 vẫn một hàng như cũ. */}
      <div className="flex flex-wrap items-start gap-3.5">
        <span
          className={`flex size-[46px] shrink-0 items-center justify-center rounded-full text-[17px] font-semibold
                      ${ca.phone ? mauCua(ca.phone) : 'bg-border-soft text-muted-3'}`}
        >
          {noiDungAvatar(ca.ten)}
        </span>
        <div className="min-w-[10rem] flex-1">
          <h2
            ref={tieuDeRef}
            tabIndex={-1}
            className={`text-[18px] font-semibold outline-none ${ca.ten ? '' : 'text-muted'}`}
          >
            {ca.ten ?? 'Khách chưa cho tên'}
          </h2>
          <div
            className={`mt-0.5 text-[13px] ${ca.phone ? 'font-mono text-muted' : 'text-badge-alert-fg'}`}
          >
            {ca.phone ?? 'Chưa có số điện thoại'}
          </div>
        </div>
        {!anNut && (
          <div className="ml-auto flex shrink-0 gap-2">
            <NutCa ca={ca} nhan={nhan} moGhiChu={moGhiChu} dangGui={dangGui} />
          </div>
        )}
      </div>

      {!ca.phone && (
        <div className="mt-4 rounded-lg border border-badge-alert-fg/25 bg-badge-alert-bg px-4 py-3 text-[13px] text-badge-alert-fg">
          Không có số điện thoại để gọi lại.
        </div>
      )}

      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-border-soft pt-5">
        <Muc nhan="Chuyển lúc">
          <span className="font-mono">{ngayGio(ca.taoLuc)}</span>
        </Muc>
        <Muc nhan="Dự án">
          {ca.tenDuAn ?? ca.duAn ?? <span className="text-muted-2">Chưa rõ</span>}
          {ca.tenDuAn && ca.duAn && (
            <span className="ml-1.5 font-mono text-[12px] text-muted-2">{ca.duAn}</span>
          )}
        </Muc>
        <Muc nhan="Kênh">
          {ca.kenh ? (
            (NHAN_KENH[ca.kenh] ?? ca.kenh)
          ) : (
            <span className="text-muted-2">Chưa rõ</span>
          )}
        </Muc>
        <Muc nhan="Trạng thái">
          {ca.trangThai === 'new' ? (
            <span className="text-muted">Chưa liên hệ</span>
          ) : (
            <>
              {ca.trangThai === 'done' ? 'Xong' : 'Đang xử lý'}
              {ca.nguoiXuLy ? ` · ${ca.nguoiXuLy}` : ''}
            </>
          )}
        </Muc>
      </dl>

      <TieuMuc>Tóm tắt nhu cầu</TieuMuc>
      <div className="rounded-lg border border-border bg-bg px-4 py-3">
        <p className="text-than leading-[1.6] text-fg">{ca.summary ?? 'Chưa có tóm tắt.'}</p>
        {ca.summaryLuc === null && (
          <p className="mt-2.5">
            <ChipDangTomTat />
          </p>
        )}
      </div>

      {ca.toolThieuDuLieu && (
        <p className="mt-2.5">
          <NhanKyNang ten={ca.toolThieuDuLieu} />
        </p>
      )}

      <TrichHoiThoai ca={ca} />

      <LichSuGhiChu ca={ca} />
    </div>
  )
}
