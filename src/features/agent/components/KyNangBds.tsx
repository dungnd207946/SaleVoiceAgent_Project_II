/**
 * Màn «Kỹ năng» của lĩnh vực Bất động sản (M5, `/ky-nang-bds`).
 *
 * Mười kỹ năng riêng của vertical #1. Ba kỹ năng CHUNG (`kb_search`,
 * `update_customer`, `escalate`) ở màn Cấu hình chung — chia ở `kyNang.ts`, và
 * đó CHỈ là tầng hiển thị: payload gửi backend vẫn là một mảng `tools.enabled`
 * gộp, một bản nháp, một lần phát.
 *
 * MÀN NÀY KHÔNG CÓ KHỐI «KIẾN THỨC». Trước 2026-08-07 `TabLinhVuc` gộp Kiến
 * thức + Kỹ năng vào một thẻ, nhưng khối Kiến thức ở đó chưa bao giờ là ô sửa
 * được — nó là một đoạn mô tả cộng hai link sang `/projects` và `/kb`. Hai link
 * ấy giờ LÀ hai mục nav (mục «Kiến thức» trong khối «Bất động sản», và «Tài
 * liệu» ở khối chung), nên giữ lại đoạn mô tả là dựng một biển chỉ đường thứ
 * hai cạnh biển thứ nhất.
 *
 * HAI ROLE (backend `0966`): màn này CHƯA chia tab — bật/tắt ở đây áp cho CẢ HAI role
 * (`doiKyNang` không truyền role). Công tắc hiện theo `customer`; hai role luôn cùng
 * trạng thái với các kỹ năng BĐS vì chỉ màn này sửa chúng.
 *
 * Cảnh báo phụ thuộc tính ở đây vì mọi cặp trong `PHU_THUOC` hiện đều nội bộ
 * BĐS; nó HIỆN ra trong chính hàng của kỹ năng thiếu (`CongTacKyNang`), không
 * còn xếp thành chồng dưới đáy thẻ. Backend thêm phụ thuộc XUYÊN nhóm thì xem
 * lại cả chỗ tính lẫn chỗ hiện.
 */
import { thieuPhuThuoc } from '@/lib/tools'
import { KEY_ROLE_MAC_DINH } from '../api'
import { KY_NANG_TAB_BDS } from '../kyNang'
import { useBanNhap } from '../useBanNhap'
import { CongTacKyNang, The } from './form'
import { KhungSuaAgent } from './KhungSuaAgent'

export function KyNangBds() {
  const ban = useBanNhap()
  if (!ban.form) return <KhungSuaAgent ban={ban}>{null}</KhungSuaAgent>
  // Màn này chưa chia tab: bật/tắt áp cho MỌI role (`doiKyNang` không truyền role), còn
  // trạng thái công tắc đọc từ role mặc định.
  const dangBat = (ban.form[KEY_ROLE_MAC_DINH] ?? Object.values(ban.form)[0])?.tools.enabled ?? []

  return (
    <KhungSuaAgent ban={ban}>
      <The tieuDe="Kỹ năng Bất động sản">
        <CongTacKyNang
          danhSach={KY_NANG_TAB_BDS}
          dangBat={dangBat}
          doi={(ten, bat) => ban.doiKyNang(ten, bat)}
          thieu={thieuPhuThuoc(dangBat)}
        />
      </The>
    </KhungSuaAgent>
  )
}
