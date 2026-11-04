/**
 * Dải trạng thái kịch bản của workspace (spec đợt 3 §4a): mẫu / bản riêng / có mẫu mới, công tắc dùng kịch bản theo
 * role, Áp lại mẫu. Công tắc role ở ĐÂY chứ không ở tab role `/agent`: màn đó gom thay đổi vào bản nháp + «Lưu và
 * áp dụng», còn công tắc này ghi ngay bằng `PUT /playbook/role-dung` (CHUNG `version` với mọi lần ghi kịch bản) — xem `CLAUDE.md`.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import { CAU_HINH_QUERY, docCauHinh } from '@/features/agent/contracts'
import { useDangGhiKichBan, useGhiKichBan, type KichBan } from '../api'
import type { SoMau } from '../khuon'
import { gio } from '../logic'
import { cauLoi } from '../useGhi'
import { XacNhan } from '@/components/ui/XacNhan'

interface Props {
  kichBan: KichBan
  so: SoMau | null
  suaDuoc: boolean
  onSoMau: () => void
}

export function DaiTrangThai({ kichBan, so, suaDuoc, onSoMau }: Props) {
  const { apDung, roleDung } = useGhiKichBan()
  const dangGhi = useDangGhiKichBan()
  const cauHinh = useQuery({ queryKey: CAU_HINH_QUERY, queryFn: docCauHinh })
  const vaiTro = cauHinh.data?.vaiTro ?? []
  const [hoiApLai, setHoiApLai] = useState(false)
  const rieng = kichBan.trangThai === 'rieng'
  const moi = rieng && kichBan.coTemplateMoi
  const loai = so ? Object.values(so.loai) : []
  const soKhac = loai.filter((l) => l === 'khac').length
  const soRieng = loai.filter((l) => l === 'rieng').length

  const doiRole = (key: string, bat: boolean) =>
    // Chỉ gửi role workspace ĐANG có: role trong `roleDung` mà đã bị xoá ở `/agent` thì BE trả 422.
    roleDung.mutate({
      version: kichBan.version,
      roles: vaiTro
        .map((v) => v.key)
        .filter((k) => (k === key ? bat : kichBan.roleDung.includes(k))),
    })

  // Chỉ lỗi của lần ghi MỚI NHẤT — lỗi Áp lại cũ không được đứng lại sau một lần đổi role thành công.
  const loi = (roleDung.submittedAt >= apDung.submittedAt ? roleDung : apDung).error
  // Hộp xác nhận đứng NGOÀI `<section>`: `<dialog>` là con cuối của khối `space-y-2` thì phần tử trước nó nhận
  // thêm margin — dải cao thêm 8px sau nền mờ mỗi lần hộp mở.
  return (
    <>
      <section
        aria-label="Trạng thái kịch bản"
        data-testid="dai-trang-thai"
        className={`space-y-2 rounded-lg border px-4 py-3 ${moi ? 'border-badge-warn-fg/40 bg-badge-warn-bg' : 'border-border bg-surface'}`}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="text-than text-fg">
            {!rieng
              ? 'Đang dùng kịch bản mẫu NobleX — agent tự nhận bản mẫu mới.'
              : moi
                ? 'NobleX có bản mẫu mới.'
                : `Bản riêng của workspace${kichBan.capNhatLuc ? ` · sửa lần cuối ${gio(kichBan.capNhatLuc)}` : ''}`}
          </p>
          {!rieng && suaDuoc ? (
            <p className="text-phu text-muted">
              Sửa một tình huống bất kỳ sẽ tạo bản riêng cho workspace.
            </p>
          ) : null}
          {rieng ? (
            <div className="ml-auto flex flex-wrap gap-2">
              <button
                type="button"
                disabled={!so}
                onClick={onSoMau}
                className={`${moi ? NUT_CHINH : NUT_PHU} cursor-pointer`}
              >
                {so ? `So với mẫu (${soKhac} khác · ${so.chuaCo.length} chưa có)` : 'So với mẫu'}
              </button>
              {suaDuoc ? (
                <button
                  type="button"
                  onClick={() => setHoiApLai(true)}
                  className={`${NUT_PHU} cursor-pointer`}
                >
                  Áp lại mẫu NobleX
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-than">
          <span className="text-muted">Agent dùng kịch bản khi nói chuyện với:</span>
          {vaiTro.map((v) => (
            <span key={v.key} className="flex items-center gap-2">
              {v.ten}
              <CongTac
                bat={kichBan.roleDung.includes(v.key)}
                nhan={`Dùng kịch bản với ${v.ten}`}
                dangGui={!suaDuoc || dangGhi}
                doi={(b) => doiRole(v.key, b)}
              />
            </span>
          ))}
          {cauHinh.isError ? (
            <span className="text-phu text-muted">Không tải được danh sách role.</span>
          ) : null}
        </div>
        {vaiTro.length > 0 && !vaiTro.some((v) => kichBan.roleDung.includes(v.key)) ? (
          <p className="text-phu text-muted">Agent không dùng kịch bản với role nào.</p>
        ) : null}
        {loi ? (
          <p role="alert" className="text-phu text-badge-alert-fg">
            {cauLoi(loi)}
          </p>
        ) : null}
      </section>
      {hoiApLai ? (
        <XacNhan
          tieuDe="Áp lại mẫu NobleX?"
          nutChinh="Áp lại"
          phaHuy
          dangGui={dangGhi}
          onHuy={() => setHoiApLai(false)}
          onDongY={() => apDung.mutate(kichBan.version, { onSettled: () => setHoiApLai(false) })}
        >
          <p>
            {so
              ? `${soKhac} tình huống khác mẫu trở về bản mẫu · ${soRieng} tình huống riêng bị xoá · ${so.chuaCo.length} tình huống trong mẫu được thêm.`
              : 'Bản riêng sẽ bị thay bằng bản mẫu hiện tại.'}
          </p>
          <p>Số đo các tình huống đổi chữ đếm lại từ đầu.</p>
        </XacNhan>
      ) : null}
    </>
  )
}
