/**
 * Hộp thoại hiện khoá vừa tạo — TRUNG TÂM CỦA TÍNH NĂNG.
 *
 * Khoá thô về đây trong response `POST /agent/keys`. ⚠ Từ migration `0918`
 * (backend) nó KHÔNG còn là cơ hội duy nhất — `liet_ke_khoa_cua_tenant()` trả
 * cả `api_key` thô cho mọi khoá còn sống, `/thu-agent` đọc lại được bất cứ lúc
 * nào (xem đoạn dưới về việc bỏ câu cảnh báo «chỉ hiện một lần»). Ba khoá đóng
 * dưới đây vẫn giữ nguyên có chủ ý: đây vẫn là chỗ SẠCH NHẤT và NHANH NHẤT để
 * lấy khoá — ép người dùng dừng lại lưu nó ngay tại đây tốt hơn là để họ vòng
 * qua `/thu-agent` sau.
 *
 * BA CHỖ CỐ Ý KHÁC MỌI DIALOG KHÁC TRONG APP:
 *
 *   1. `Escape` KHÔNG đóng. `TaoWorkspaceDialog:48` đăng ký Escape vì đóng nó chỉ
 *      mất một cái tên đang gõ. Đóng cái này mất một bí mật không lấy lại được.
 *   2. Bấm ra ngoài KHÔNG đóng. Cả hai đều do `khoaDong` của `HopThoai` lo.
 *   3. Nút Đóng disabled tới khi tick Tôi đã lưu khoá. Một checkbox không
 *      chặn được người vô tâm, nhưng nó biến "đóng nhầm" thành "đóng có chủ ý".
 *
 * ── MỘT GIÁ TRỊ, KHÔNG PHẢI BA (2026-08-27, người dùng chốt) ────────────────
 * ĐẢO chốt 2026-08-24 vốn thêm `WS_URL_CHAT`/`WS_URL_VOICE` vào đây. Lý do đảo
 * không phải đổi ý về nội dung mà là màn nền đã tự trả lời: thẻ «Kết nối WS
 * Gateway» ở `TichHopApiScreen` — thêm 2026-08-25, tức ĐÚNG MỘT NGÀY SAU — hiện
 * cả hai URL kèm nút copy, thường trực, đọc lại được bất cứ lúc nào. Hai bản sao
 * trong dialog vì thế chỉ còn làm loãng thứ DUY NHẤT không đọc lại được.
 *
 * ⚠ Đừng đưa chúng về. Phép thử: giá trị đó đóng dialog rồi còn xem lại được
 * không? Còn ⇒ nó thuộc về màn, không thuộc về đây. Chỉ khoá thô trượt phép thử.
 *
 * ⚠ VẪN KHÔNG PHẢI `ENDPOINT_CHAT_URL`/`ENDPOINT_VOICE_URL` (bỏ 2026-08-21).
 * Hai field ĐÓ backend sinh theo `url_endpoint_agent()` — subdomain riêng mỗi
 * tenant, lỗi thời từ 2026-08-10 — nên chúng bị bỏ vì SAI, không vì thừa. Chúng
 * vẫn về từ `/agent/keys` và vẫn nằm trong `KhoaDaTao`; dialog vẫn KHÔNG đọc,
 * và có bài test canh đúng chiều đó.
 *
 * ── «CHỈ HIỆN MỘT LẦN» ĐÃ BỎ (2026-09-11, người dùng chốt) ──────────────────
 * Câu cảnh báo `role="alert"` treo dưới ô khoá đã BỎ HẲN — tiền đề của nó
 * (`liet_ke_khoa_cua_tenant()` "không đường nào đọc lại được, kể cả admin")
 * không còn đúng từ migration `0918`: endpoint liệt kê khoá trả CẢ `api_key`
 * thô cho mọi khoá còn sống (`repo.py::liet_ke_khoa_cua_tenant`), đúng khoá
 * này `/thu-agent` đang dùng để dựng `<select>` chọn theo tên. Khoá rời dialog
 * này rồi vẫn xem lại được, chỉ không còn ở ĐÂY nữa.
 *
 * Dialog rộng lại **480 → 560px** để chuỗi 50 ký tự (`ody_ag_` + 43 ký tự
 * base64url, `bi_mat.py::sinh_khoa`) nằm trọn MỘT DÒNG (`whitespace-nowrap`
 * thay `break-all`) — xem chú thích tại ô `<code>` bên dưới.
 *
 * MỘT Ô = ĐÚNG MỘT THỨ: giá trị TRẦN, kèm nút copy hình icon ở mép phải (kiểu
 * OpenAI — người dùng chốt 2026-08-24). Hai bản trước đều nhồi thêm chữ vào ô:
 * bản đầu in trọn dòng `<pre>AGENT_API_KEY=…</pre>`, bản sau tách thành thẻ hai
 * hàng có nhãn «Tên biến» / «Giá trị khoá». Cả hai bắt mắt người đọc lọc chữ mới
 * thấy khoá. TÊN BIẾN vẫn phải nói ra — bên agent không tự đoán được — nên nó là
 * NHÃN trên ô, không phải một cột trong ô.
 *
 * ⚠ KHÔNG còn `HangGiaTri` (component 7 prop dùng chung ba hàng): còn đúng một
 * hàng thì một khuôn tổng quát hoá là trừu tượng cho một chỗ dùng. Ngày nào có
 * giá trị thứ hai THẬT SỰ chỉ hiện một lần thì hẵng tách lại.
 *
 * ⚠ NÚT COPY ĐƯA ĐÚNG GIÁ TRỊ, không kèm tiền tố `AGENT_API_KEY=` — chỗ người
 * ta dán nó vào thường là một ô nhập (`/thu-agent`, secret manager), ở đó tiền tố
 * là rác phải xoá tay. Ai dán vào `.env` thì tự gõ tên biến trên nhãn.
 *
 * ⚠ ICON ✓ TỰ TRỞ VỀ ICON COPY SAU `GIU_DA_COPY` — copy được nhiều lần. Một dấu ✓
 * đứng vĩnh viễn nói «xong rồi» về một nút vẫn bấm được, và người dán vào hai chỗ
 * (secret manager rồi `.env`) mất chỗ bấm lần hai. 1600ms là số ĐÃ DÙNG ở ba chỗ
 * copy khác của portal (`OToken` · `ChiTietPhien` · `HangHanhDong` ở
 * `ThuAgentScreen`) — cùng một cử chỉ thì cùng một nhịp.
 *
 * `daLuu` KHÔNG trở về theo đồng hồ ✓: họ đã mang khoá ra khỏi trang thật, và bỏ
 * tick hộ người dùng là khoá lại nút Đóng vì một cái đồng hồ.
 *
 * Ô giá trị `select-all`: một cú click chọn trọn chuỗi, cho người không tin nút
 * copy hoặc ở ngữ cảnh không có `navigator.clipboard` (http:// khác localhost).
 *
 * `PORTAL_URL` CỐ Ý KHÔNG có ở đây — xem `TEN_BIEN_KHOA` ở `api.ts` để biết đủ
 * vế, và `docs/contracts/dau-noi-agent.md` §1 ở repo backend.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { useSaoChep } from '@/lib/saoChep'
import { Icon } from '@/components/icons'
import { HANG_NUT, NUT_CHINH } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { useLang } from '@/i18n'
import { TEN_BIEN_KHOA } from '../api'
import type { KhoaDaTao } from '../api'

/**
 * Nút copy trong ô khoá.
 *
 * `cursor-pointer`: Tailwind v4 KHÔNG tự đặt cho `<button>` nữa.
 *
 * `rounded-sm` — nút nhỏ nằm TRONG một hàng, đúng bậc 1 của thang bo góc (luật 2
 * của Design token). Bản trước để `rounded-lg`, tức bậc dành cho thẻ/hộp thoại,
 * nên một nút 32px bo cong như một cái thẻ.
 *
 * `border-border-field` NẰM NGAY TRONG HẰNG, không tách ra nhánh ternary: `border`
 * trần vẽ viền bằng MÀU CHỮ (bẫy `currentColor` của v4) và `tests/vien-tran.test.ts`
 * canh đúng chỗ này. Viền vì thế KHÔNG đổi màu lúc đã copy — chỉ icon đổi sắc; hai
 * thứ cùng đổi là nhấp nháy cả cái nút cho một phản hồi 1.6 giây.
 */
const NUT_COPY =
  'flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-sm border border-border-field bg-surface transition-colors'

export function KhoaMoiDialog({ khoa, onDong }: { khoa: KhoaDaTao; onDong: () => void }) {
  const { t } = useLang()
  const [daLuu, setDaLuu] = useState(false)
  const { daCopy, loiCopy, copy: saoChep } = useSaoChep()
  const idTieuDe = useId()
  const nutRef = useRef<HTMLButtonElement>(null)

  // Focus vào nút Copy khi mở: đó là việc người dùng gần như chắc chắn muốn làm,
  // và nó cũng đưa focus vào trong dialog cho người dùng bàn phím.
  useEffect(() => {
    nutRef.current?.focus()
  }, [])

  async function copy() {
    // Copy được thì coi như đã lưu: họ vừa mang khoá ra khỏi trang.
    if (await saoChep(khoa.api_key)) setDaLuu(true)
  }

  return (
    // `khoaDong` CỐ Ý luôn bật: Esc và bấm ra ngoài đều KHÔNG đóng dialog này — một
    // đường đóng bằng một cú click lệch là một đường mất khoá. Chỉ nút Đóng (mở khi
    // `daLuu`) đóng được.
    <HopThoai
      onDong={onDong}
      khoaDong
      aria-labelledby={idTieuDe}
      className={`${KHUNG_HOP_THOAI} max-w-[560px]`}
    >
      <h2 id={idTieuDe} className="text-[16.5px] font-semibold leading-tight text-fg">
        {t({ vi: 'Khoá đấu nối đã tạo', en: 'Connection key created' })}
      </h2>

      {/* Tên biến là NHÃN của ô ngay dưới — bên agent cần đúng chuỗi này, còn ô
            thì chỉ giữ một thứ: giá trị. */}
      <p className="mt-4 font-mono text-phu font-semibold leading-none text-fg">{TEN_BIEN_KHOA}</p>

      <div className="mt-2 flex items-start gap-2 rounded-md border border-border-field bg-fill p-2 pl-3">
        {/* `select-all`: một cú click chọn trọn chuỗi — kéo chuột qua 40 ký tự mono
              là chỗ người ta copy thiếu ký tự cuối.

              `whitespace-nowrap`, KHÔNG `break-all`: khoá luôn đúng 50 ký tự
              (`ody_ag_` + 43 ký tự base64url, `bi_mat.py::sinh_khoa`). Dialog
              rộng `560px` để 50 ký tự mono 14.5px (~8,7px/ký tự ⇒ ~435px) nằm
              lọt MỘT DÒNG cùng nút copy — xuống dòng giữa chuỗi là chỗ người ta
              copy thiếu, bôi đen nhầm. */}
        <code
          data-testid="gia-tri-khoa"
          className="min-w-0 flex-1 select-all whitespace-nowrap pt-[3px] font-mono text-noi leading-[1.5] text-fg"
        >
          {khoa.api_key}
        </code>
        <button
          ref={nutRef}
          type="button"
          onClick={copy}
          aria-label={t({ vi: 'Copy key', en: 'Copy key' })}
          title={t({ vi: 'Copy key', en: 'Copy key' })}
          className={`${NUT_COPY} ${daCopy ? 'text-ac' : 'text-muted hover:border-fg hover:text-fg'}`}
        >
          {/* `Icon` chứ không svg tự vẽ: hai mark này đã có trong `icons.tsx`. */}
          <Icon name={daCopy ? 'check' : 'copy'} className="size-4" />
        </button>
      </div>

      {/* Một vùng `role="status"` cho CẢ HAI kết cục của nút icon: icon đổi hình
            thì người dùng chuột thấy, còn người dùng trình đọc màn hình thì không. */}
      <p role="status" className="mt-1.5 min-h-[17px] text-phu">
        {daCopy && <span className="text-ac">{t({ vi: 'Đã copy khoá', en: 'Key copied' })}</span>}
        {loiCopy && (
          <span className="text-badge-alert-fg">
            {t({
              vi: 'Trình duyệt không cho copy. Bôi đen giá trị ở trên rồi Ctrl+C.',
              en: 'Browser blocked copying. Select the value above and press Ctrl+C.',
            })}
          </span>
        )}
      </p>

      {/* Công tắc mở khoá đứng CÙNG HÀNG với nút nó mở, đẩy trái bằng `mr-auto`
            (hằng `HANG_NUT`, luật 5): hai thứ ở hai đầu hai hàng khác nhau thì
            quan hệ «tick cái này ⇒ bấm được cái kia» phải tự đoán. */}
      <div className={`${HANG_NUT} mt-3`}>
        <label className="mr-auto flex cursor-pointer items-center gap-2 text-than text-fg">
          <input
            type="checkbox"
            checked={daLuu}
            onChange={(e) => setDaLuu(e.target.checked)}
            className="size-4 accent-ac"
          />
          {t({ vi: 'Tôi đã lưu khoá', en: 'I have saved the key' })}
        </label>
        <button type="button" onClick={onDong} disabled={!daLuu} className={NUT_CHINH}>
          {t({ vi: 'Đóng', en: 'Close' })}
        </button>
      </div>
    </HopThoai>
  )
}
