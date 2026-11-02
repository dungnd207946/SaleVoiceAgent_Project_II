/**
 * Màn «Cấu hình chung» của agent (M5, `/agent`). Nguồn nghiệp vụ: AG_01.
 *
 * PHẠM VI: mọi thứ áp cho MỌI lĩnh vực — danh tính, giọng điệu, phạm vi, ba kỹ
 * năng chung, sáu rào chắn. Kỹ năng RIÊNG của một lĩnh vực ở màn khác
 * (`/ky-nang-bds`), cùng bản nháp, cùng một nút Lưu và áp dụng — xem
 * `useBanNhap.ts` và `KhungSuaAgent.tsx`.
 *
 * ── XEM TRƯỚC, SỬA SAU (2026-08-08) ────────────────────────────────────────
 * Mặc định màn hiện BẢN TÓM TẮT chỉ-đọc; form tám ô chỉ mở khi bấm «Sửa cấu
 * hình». Lý do: việc thường làm ở màn này là ĐỌC xem agent đang được dặn gì, còn
 * form mở sẵn nói «hãy điền» và mời gõ nhầm vào một cấu hình đang chạy đúng.
 *
 * MỞ THẲNG VÀO FORM khi `laMacDinh` — ít nhất một role chưa ai cấu hình, những giá trị
 * đó là bộ platform sinh. Trình bày chúng như «cấu hình hiện tại» là báo đã xong một
 * việc chưa làm. (Ca `nhapSchemaCu` cũ đã hết cùng bản nháp — backend `0966`.)
 *
 * THEO ROLE (backend `0966`/`0967`): mỗi role một tab chọn role cho các khu riêng; role
 * do workspace tự thêm/đổi tên/xoá ngay trên hàng tab (`KhoiVaiTro`). State tab ở ĐÂY,
 * không ở từng chế độ: bấm Sửa/Huỷ/Lưu thì tab đang mở giữ nguyên. Tab đang mở bị xoá (ở
 * tab trình duyệt khác) thì rơi về role mặc định thay vì trỏ vào hư không.
 *
 * Chế độ chốt MỘT LẦN lúc bản nháp về, không phải mỗi lần render: `laMacDinh`
 * thành `false` ngay sau lần áp dụng đầu tiên, và một `dangSua` tính lại theo nó
 * sẽ tự đóng form ngay giữa lúc người dùng đang gõ.
 *
 * BA THỨ MÀN NÀY CỐ TÌNH KHÔNG LÀM, và mỗi cái là một lời hứa:
 *   · Không có ô nào nhận markdown hay prompt thô (BR02). Người dùng là trưởng
 *     phòng kinh doanh sàn BĐS — cho sửa thẳng prompt là giao cho họ một thứ họ
 *     không đánh giá được hậu quả.
 *   · Sáu rào chắn hiện ra nhưng KHÔNG có công tắc (BR08).
 *   · Bước Xem trước (AG_01 §II.1) không còn là một nút riêng — dialog Lưu và
 *     áp dụng liệt kê những gì sẽ đổi (tính ở client, `useBanNhap.thayDoi`).
 *
 * BỐ CỤC: một dòng chảy dọc full-width, không chia màn hai cột. Thẻ trắng bo
 * 12px viền `border` vẫn của prototype cũ (`design/Tenant Portal.dc.html`, khối
 * `data-s="agent"`). Mọi con số spacing/màu là số của prototype hoặc token
 * trong `styles/theme.css`.
 *
 * KHU «LĨNH VỰC» CÓ TAB ĐÃ BỎ (2026-08-07). Tab giấu lĩnh vực thứ hai sau một
 * cú bấm và giấu luôn ranh giới chung ↔ riêng — cái ranh giới đó giờ nằm ngay
 * trong nav, thành khối có nhãn. Xem `lib/nav-registry.ts`.
 */
import { useState } from 'react'
import { KEY_ROLE_MAC_DINH, type VaiTro } from '../api'
import { CauHinhChung } from './CauHinhChung'
import { KhungSuaAgent } from './KhungSuaAgent'
import { TomTatCauHinh } from './TomTatCauHinh'
import { useBanNhap } from '../useBanNhap'

export function AgentStudio() {
  // `null` = bản nháp chưa về nên chưa quyết được; chốt ở lần render đầu tiên có
  // dữ liệu rồi giữ nguyên tới khi màn dựng lại.
  const [dangSua, setDangSua] = useState<boolean | null>(null)
  const [role, setRole] = useState<VaiTro>(KEY_ROLE_MAC_DINH)
  const ban = useBanNhap({ onApDungXong: () => setDangSua(false) })

  if (!ban.form) return <KhungSuaAgent ban={ban}>{null}</KhungSuaAgent>

  const sua = dangSua ?? ban.laMacDinh
  // Chỉ mở role CÓ trong cả danh sách lẫn form; không thì role gốc — xem đầu file.
  const roleMo = ban.vaiTro.some((v) => v.key === role)
    ? role
    : (ban.vaiTro.find((v) => v.macDinh)?.key ?? ban.vaiTro[0]?.key ?? KEY_ROLE_MAC_DINH)

  return (
    <KhungSuaAgent
      ban={ban}
      che={{
        dangXem: !sua,
        onSua: () => setDangSua(true),
        // Huỷ trả bản nháp về đúng thứ đang nằm trên server — bấm Huỷ mà phần
        // vừa gõ còn nguyên trong state thì lần bấm Sửa sau đó mở ra một form
        // «đã có sẵn» những chữ người dùng vừa từ chối.
        onHuy: () => {
          ban.huy()
          setDangSua(false)
        },
      }}
    >
      {sua ? (
        <CauHinhChung
          cauHinh={ban.form}
          vaiTro={ban.vaiTro}
          soRoleToiDa={ban.soRoleToiDa}
          role={roleMo}
          doiRole={setRole}
          suaRole={ban.sua}
          suaChung={ban.suaChung}
          doiKyNang={ban.doiKyNang}
        />
      ) : (
        <TomTatCauHinh
          cauHinh={ban.form}
          vaiTro={ban.vaiTro}
          soRoleToiDa={ban.soRoleToiDa}
          role={roleMo}
          doiRole={setRole}
        />
      )}
    </KhungSuaAgent>
  )
}
