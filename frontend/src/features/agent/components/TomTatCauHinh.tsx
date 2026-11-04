/**
 * «Cấu hình chung» ở chế độ XEM — thứ màn `/agent` hiện MẶC ĐỊNH (2026-08-08).
 *
 * VÌ SAO CÓ CHẾ ĐỘ NÀY. Trước đây mở `/agent` ra là tám ô nhập đang mở sẵn, kể
 * cả khi người dùng chỉ muốn kiểm xem agent đang được dặn những gì — mà đó là lý
 * do mở màn này thường xuyên nhất. Một form mở sẵn nói «hãy điền», trong khi
 * việc thật là «hãy đọc»; nó còn mời gõ nhầm vào một cấu hình đang chạy đúng.
 *
 * BẢN TÓM TẮT NÀY GIỮ ĐÚNG THỨ TỰ VÀ ĐÚNG NHÃN CỦA FORM. Không rút gọn nhãn,
 * không gộp ô: người bấm Sửa phải tìm lại đúng ô mình vừa đọc, và hai cách gọi
 * cho một ô là bắt họ dịch giữa hai từ vựng.
 *
 * Đọc từ `form` (state cục bộ) chứ không đọc thẳng query: đó là cùng một nguồn
 * mà chế độ sửa ghi vào, nên xem ↔ sửa không bao giờ nói hai điều khác nhau —
 * và nó giữ nguyên tính chất mà `ManTheoWorkspace` (routes/_app.tsx) dựa vào,
 * rằng đổi workspace là dựng lại state chứ không chỉ nạp lại cache.
 *
 * THEO ROLE (backend `0966`/`0967`): cùng khối tab theo role như form, cùng chỗ — Danh
 * tính và Chuẩn hoá cách đọc ở ngoài khối vì chúng dùng chung.
 *
 * KHÔNG PHẢI một form bị khoá. Ô nhập `disabled` vẫn trông như ô nhập, vẫn chiếm
 * chỗ như ô nhập, và vẫn nói «đáng lẽ bạn gõ được vào đây». Đây là văn bản.
 */
import type { CauHinh, VaiTro, VaiTroMeta } from '../api'
import { nhanCua } from '@/lib/tools'
import { KY_NANG_TAB_CHUNG } from '../kyNang'
import { KhoiVaiTro } from './KhoiVaiTro'
import { Dong, GiaTri, RaoChan, The } from './form'
import { nhanDoDai, nhanGiongDieu } from './hangChung'
import { NormalizationPreview } from './Normalization'
import { CAP_THE, LUOI_XEM } from './lop'

export function TomTatCauHinh({
  cauHinh,
  vaiTro,
  soRoleToiDa,
  role,
  doiRole,
}: {
  cauHinh: CauHinh
  vaiTro: VaiTroMeta[]
  soRoleToiDa: number
  role: VaiTro
  doiRole: (r: VaiTro) => void
}) {
  // `AgentStudio` chỉ truyền `role` có trong `cauHinh`.
  const form = cauHinh[role]!
  const bat = KY_NANG_TAB_CHUNG.filter((k) => form.tools.enabled.includes(k.ten))
  const tat = KY_NANG_TAB_CHUNG.filter((k) => !form.tools.enabled.includes(k.ten))

  return (
    <div className="flex flex-col gap-3.5">
      <The tieuDe="Danh tính">
        <dl className={`${LUOI_XEM} text-[14px]`}>
          <Dong nhan="Tên agent">
            <GiaTri>{form.danh_tinh.ten_agent}</GiaTri>
          </Dong>
          <Dong nhan="Tên thương hiệu">
            <GiaTri>{form.danh_tinh.ten_thuong_hieu}</GiaTri>
          </Dong>
          <Dong nhan="Agent tự xưng">
            <GiaTri>{form.danh_tinh.tu_xung}</GiaTri>
          </Dong>
          <Dong nhan="Gọi khách là">
            <GiaTri>{form.danh_tinh.goi_khach}</GiaTri>
          </Dong>
          <Dong nhan="Lời chào" rong>
            <GiaTri>{form.danh_tinh.loi_chao}</GiaTri>
          </Dong>
        </dl>
      </The>

      <KhoiVaiTro vaiTro={vaiTro} soRoleToiDa={soRoleToiDa} dangMo={role} doi={doiRole}>
        <The phang tieuDe="Phạm vi">
          <dl className={`${LUOI_XEM} text-[14px]`}>
            <Dong nhan="Agent làm gì">
              <GiaTri>{form.pham_vi.lam_gi}</GiaTri>
            </Dong>
            <Dong nhan="Agent không làm gì">
              <GiaTri>{form.pham_vi.khong_lam_gi}</GiaTri>
            </Dong>
            <Dong nhan="Câu từ chối ngoài phạm vi" rong>
              <GiaTri>{form.pham_vi.cau_tu_choi}</GiaTri>
            </Dong>
          </dl>
        </The>

        {/* Cùng cặp thẻ như chế độ sửa — bấm Sửa thì bố cục không nhảy. */}
        <div className={CAP_THE}>
          <The phang tieuDe="Giọng điệu">
            <dl className="flex flex-col gap-3 text-[14px]">
              <Dong nhan="Giọng điệu">{nhanGiongDieu(form.giong.giong_dieu)}</Dong>
              <Dong nhan="Độ dài trả lời">{nhanDoDai(form.giong.do_dai)}</Dong>
            </dl>
          </The>

          <The phang tieuDe="Kỹ năng chung của agent">
            {bat.length > 0 ? (
              <ul aria-label="Kỹ năng chung đang bật" className="flex flex-wrap gap-1.5">
                {bat.map((k) => (
                  <li
                    key={k.ten}
                    className="rounded-full bg-acs px-3 py-[5px] text-[13px] font-medium text-ac"
                  >
                    {k.nhan}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-than text-muted">Chưa bật kỹ năng chung nào.</p>
            )}
            {/* Kỹ năng ĐANG TẮT phải hiện ra, mờ hơn nhưng có mặt: một danh sách chỉ
              gồm cái đang bật không phân biệt được «đã cân nhắc rồi tắt» với «chưa
              biết là có». Người kiểm cấu hình cần biết cả hai. */}
            {tat.length > 0 && (
              <p className="mt-3 border-t border-border-soft pt-3 text-[13px] text-muted-2">
                Đang tắt: {tat.map((k) => nhanCua(k.ten)).join(' · ')}
              </p>
            )}
          </The>
        </div>
      </KhoiVaiTro>

      <NormalizationPreview muc={form.tts_normalization} />

      <RaoChan />
    </div>
  )
}
