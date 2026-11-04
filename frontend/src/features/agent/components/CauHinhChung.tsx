/**
 * «Cấu hình chung» ở chế độ SỬA — mọi thứ CHUNG của agent, bất kể lĩnh vực nào:
 * system prompt (danh tính · giọng điệu · phạm vi), 3 kỹ năng chung, 6 rào chắn.
 *
 * THEO ROLE (backend `0966`/`0967`, người dùng chốt): Danh tính · Chuẩn hoá cách đọc ·
 * Rào chắn DÙNG CHUNG (`suaChung` ghi vào mọi role); Phạm vi · Giọng điệu · Kỹ năng chung
 * nằm trong khối có tab theo role và sửa RIÊNG role đang mở.
 *
 * Từ 2026-08-08 đây KHÔNG còn là thứ màn `/agent` hiện mặc định: mặc định là bản
 * tóm tắt chỉ-đọc (`TomTatCauHinh.tsx`), form này mở khi bấm «Sửa cấu hình». Hai
 * bên phải khai CÙNG các ô theo CÙNG thứ tự — lý do ở đầu `TomTatCauHinh.tsx`.
 *
 * Không phải một tab: người dùng chốt 2026-08-07 rằng tách nó ra tab riêng là
 * tách lĩnh vực khỏi agent. Kỹ năng lĩnh vực ở màn riêng `/ky-nang-bds`.
 */
import type { CauHinh, ConfigPayload, VaiTro, VaiTroMeta } from '../api'
import { KY_NANG_TAB_CHUNG } from '../kyNang'
import { KhoiVaiTro } from './KhoiVaiTro'
import { CongTacKyNang, O, Preset, RaoChan, The } from './form'
import { DO_DAI, GIONG_DIEU } from './hangChung'
import { NormalizationPreview } from './Normalization'
import { CAP_THE, LUOI_O } from './lop'

export function CauHinhChung(props: {
  cauHinh: CauHinh
  vaiTro: VaiTroMeta[]
  soRoleToiDa: number
  role: VaiTro
  doiRole: (r: VaiTro) => void
  /** Sửa trường RIÊNG của một role. */
  suaRole: (role: VaiTro, f: (c: ConfigPayload) => ConfigPayload) => void
  /** Sửa trường DÙNG CHUNG — ghi vào mọi role. */
  suaChung: (f: (c: ConfigPayload) => ConfigPayload) => void
  doiKyNang: (ten: string, bat: boolean, role?: VaiTro) => void
}) {
  const { role } = props
  // Phần chung đọc từ role nào cũng được — mọi bản luôn bằng nhau (`useBanNhap`).
  // `AgentStudio` chỉ truyền `role` có trong `cauHinh`, nên `!` ở đây không phải đoán.
  const form = props.cauHinh[role]!
  const sua = props.suaChung
  const suaRieng = (f: (c: ConfigPayload) => ConfigPayload) => props.suaRole(role, f)
  return (
    // Một cột dọc full-width — người dùng chốt: không chia màn trái/phải.
    <div className="flex flex-col gap-3.5">
      <The tieuDe="Danh tính">
        {/* Thứ tự và bề rộng khớp ĐÚNG bản tóm tắt (`TomTatCauHinh.tsx`): bấm Sửa
            là ô nằm đúng chỗ mắt vừa đọc. */}
        <div className={LUOI_O}>
          <O
            nhan="Tên agent"
            giaTri={form.danh_tinh.ten_agent}
            toiDa={40}
            doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, ten_agent: v } }))}
            goiYTrongO="VD: Trợ lý Minh Anh"
          />
          <O
            nhan="Tên thương hiệu"
            giaTri={form.danh_tinh.ten_thuong_hieu}
            toiDa={80}
            doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, ten_thuong_hieu: v } }))}
            goiYTrongO="VD: An Phú Land"
          />
          {/* Hai ô đại từ đứng CÙNG MỘT HÀNG với nhau, không đứng cạnh ô câu văn.
              Chúng chỉ chứa một từ (`maxLength` 20), và trước đây nằm chung hàng
              với Lời chào nên phải bóp còn `1fr` giữa một ô `2fr` — mép phải của
              khu này vì thế không thẳng với khu nào khác. Ghép cặp giải quyết cả
              hai: đều hàng, và vẫn không mời gõ cả câu vào ô đại từ. */}
          <O
            nhan="Agent tự xưng"
            giaTri={form.danh_tinh.tu_xung}
            toiDa={20}
            doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, tu_xung: v } }))}
            goiYTrongO="VD: em"
          />
          <O
            nhan="Gọi khách là"
            giaTri={form.danh_tinh.goi_khach}
            toiDa={20}
            doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, goi_khach: v } }))}
            goiYTrongO="VD: anh/chị"
          />
          <O
            rong
            nhan="Lời chào"
            giaTri={form.danh_tinh.loi_chao}
            toiDa={200}
            doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, loi_chao: v } }))}
            goiYTrongO="VD: Em chào anh/chị, em có thể tư vấn dự án và chính sách giá ạ."
          />
        </div>
      </The>

      {/* Khối RIÊNG theo role: tab là đầu khung, ba thẻ bên dưới là thân — xem
          `KhoiVaiTro.tsx`. Danh tính ở trên và Chuẩn hoá cách đọc ở dưới không đổi theo tab. */}
      <KhoiVaiTro
        vaiTro={props.vaiTro}
        soRoleToiDa={props.soRoleToiDa}
        dangMo={role}
        doi={props.doiRole}
      >
        <The phang tieuDe="Phạm vi">
          <div className={LUOI_O}>
            <O
              nhan="Agent làm gì"
              giaTri={form.pham_vi.lam_gi}
              toiDa={300}
              doi={(v) => suaRieng((c) => ({ ...c, pham_vi: { ...c.pham_vi, lam_gi: v } }))}
              goiYTrongO="VD: giới thiệu dự án, tra quỹ căn, báo giá niêm yết"
            />
            <O
              nhan="Agent không làm gì"
              giaTri={form.pham_vi.khong_lam_gi}
              toiDa={300}
              doi={(v) => suaRieng((c) => ({ ...c, pham_vi: { ...c.pham_vi, khong_lam_gi: v } }))}
              goiYTrongO="VD: cam kết lợi nhuận, duyệt vay, thương lượng giảm giá"
            />
            {/* Đây là chỗ duy nhất khai chuyện chuyển tiếp: khu «Phòng ban chuyển
              tiếp» đã bỏ (2026-08-08), tên đầu mối viết thẳng vào câu này. */}
            <O
              rong
              nhan="Câu từ chối ngoài phạm vi"
              giaTri={form.pham_vi.cau_tu_choi}
              toiDa={200}
              doi={(v) => suaRieng((c) => ({ ...c, pham_vi: { ...c.pham_vi, cau_tu_choi: v } }))}
              goiYTrongO="VD: Phần này em xin phép chuyển anh/chị sang phòng kinh doanh ạ."
            />
          </div>
        </The>

        <div className={CAP_THE}>
          <The phang tieuDe="Giọng điệu">
            {/* Trong thẻ nửa bề rộng, hai bộ chip xếp DỌC: chia đôi lần nữa thì ba
              chip của một bộ không đủ chỗ trên một dòng và tự xuống hàng. */}
            <div className="flex flex-col gap-4">
              <Preset
                nhan="Giọng điệu"
                cac={GIONG_DIEU}
                chon={form.giong.giong_dieu}
                doi={(v) => suaRieng((c) => ({ ...c, giong: { ...c.giong, giong_dieu: v } }))}
              />
              <Preset
                nhan="Độ dài trả lời"
                cac={DO_DAI}
                chon={form.giong.do_dai}
                doi={(v) => suaRieng((c) => ({ ...c, giong: { ...c.giong, do_dai: v } }))}
              />
            </div>
          </The>

          <The phang tieuDe="Kỹ năng chung của agent">
            <CongTacKyNang
              danhSach={KY_NANG_TAB_CHUNG}
              dangBat={form.tools.enabled}
              doi={(ten, bat) => props.doiKyNang(ten, bat, role)}
            />
          </The>
        </div>
      </KhoiVaiTro>

      <NormalizationPreview
        muc={form.tts_normalization}
        doi={(m) => sua((c) => ({ ...c, tts_normalization: m }))}
      />

      <RaoChan />
    </div>
  )
}
