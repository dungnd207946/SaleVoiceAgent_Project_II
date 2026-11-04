/**
 * Panel gán bộ giá cho workspace (Task 10) — mở từ nút «Gán workspace» ở dải
 * công cụ mục ② `BangGiaScreen.tsx`, cạnh «Bộ giá mới».
 *
 * KHUÔN LỚP NỔI cùng `PanelBoGia.tsx`/`ChiTietPhien.tsx`: đóng qua CẢ BA đường
 * (nút ×, bấm nền, Escape), trả focus về đúng phần tử đã mở nó. Vỏ dialog
 * (`<dialog>` qua `HopThoai`) dùng CHUNG `./PanelKhung` (review 2026-08-20 —
 * trước đó ba nơi giữ ba bản COPY NGUYÊN VĂN, xem docstring `PanelKhung.tsx`).
 *
 * KHÁC `PanelBoGia`: panel này KHÔNG gắn với một `id` — nó liệt kê TẤT CẢ
 * workspace của phiên (`useSession().workspaces`) trong một bảng, mỗi hàng tự
 * mang state chọn bộ giá + mốc hiệu lực + mutation riêng (`HangGan`).
 *
 * ⚠️ CỘT «Đang áp» — spec giao việc nói "bảng 4 cột" (Workspace · Bộ giá ·
 * Hiệu lực từ · nút Gán) NHƯNG đoạn ngay sau đó lại đòi một cột hiện `—` kèm
 * `title` giải thích vì sao không biết bộ giá/hiệu lực đang áp của từng
 * workspace. Hai câu chỏi nhau: đếm chữ thì đúng 4, nhưng "cột đó để `—` kèm
 * title" chỉ có nghĩa nếu có một Ô THẬT để đặt tooltip vào — không phải một
 * câu văn xuôi phía trên bảng (câu văn không cần `title`, cứ viết ra là đủ).
 * Chọn theo yêu cầu cụ thể hơn: thêm CỘT THỨ NĂM «Đang áp», KHÔNG gộp vào cột
 * «Bộ giá» — gộp thì `—` của "không biết trạng thái hiện tại" đứng cạnh một
 * `<select>` "chọn bộ giá mới" trong cùng ô, dễ đọc nhầm `—` thành placeholder
 * rỗng của chính ô chọn đó thay vì một sự thật riêng về workspace.
 *
 * ⚠️ KHÔNG có endpoint đọc `tenant_price_version` (`GET .../tenants/{id}/
 * price-version` không tồn tại) — cột «Đang áp» KHÔNG THỂ hiện bộ giá/hiệu
 * lực hiện hành thật. Để trống hoặc hiện "Chưa gán" đều SAI: cả hai đọc như
 * một khẳng định ("không có gì" / "chưa từng gán"), trong khi sự thật là
 * "không có cách nào biết". `—` + `title` nói đúng: một dấu KHÔNG XÁC ĐỊNH,
 * không phải một giá trị.
 *
 * ⚠️ `effectiveFrom` PHẢI tz-aware trước khi gửi — xem docstring `HangGan`.
 * ⚠️ Body gửi lên `priceVersionId`/`effectiveFrom` CẢ HAI camelCase (khác
 * `DongGiaIn` của Task 9, nơi chỉ 2/8 field camelCase) — xem `kieu.ts::GanBoGiaIn`.
 *
 * ⚠️ Gán KHÔNG được BE xác thực an toàn trước (không đòi bộ giá `active`,
 * không kiểm đủ giá) — chỉ chặn hai mốc: `MOC_QUA_KHU_DA_DINH_GIA` (lùi vào
 * kỳ đã định giá) và `MOC_TRUOC_KHOANG_DANG_MO` (mốc mới ≤ `effective_from`
 * của khoảng đang mở — BE giải thích vì sao mã này tồn tại trong
 * `docs/contracts/usage-billing.md`: câu UPDATE đóng khoảng cũ không hỏi
 * khoảng đó bắt đầu từ đâu, nên nếu khoảng đang mở bắt đầu SAU mốc mới thì
 * ràng buộc `effective_to > effective_from` vỡ và ném `CheckViolationError`
 * thô — dịch thành 409 đọc được thay vì 500). Cả hai message của BE đã nêu
 * đúng ngày và hướng xử lý — hiện NGUYÊN VĂN `err.message`, đừng viết lại.
 * `select`/nút chỉ chặn được INPUT rỗng, không chặn được hai lỗi nghiệp vụ
 * này — chúng chỉ lộ ra SAU khi bấm Gán.
 */
import { useId, useState, type ReactNode } from 'react'
import { Bang, DauBang, NUT_PHU, TD, type Cot } from '@/components/ui/Bang'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { DongTrangThai, O_CHUNG } from '@/components/ui/Truong'
import { useSession, type Workspace } from '@/lib/session'
import { useBoGia, useGanChoWorkspace } from '../api'
import { thongDiep } from '../loi'
import type { BoGia } from '../kieu'
import { PanelKhung } from './PanelKhung'

const COT_GAN: readonly Cot[] = [
  { nhan: 'Workspace' },
  { nhan: 'Đang áp' },
  { nhan: 'Bộ giá' },
  { nhan: 'Hiệu lực từ' },
  { nhan: '', phai: true },
] as const

/**
 * Một hàng — workspace + form gán riêng (chọn bộ giá, mốc hiệu lực, nút Gán).
 *
 * ⚠️ `datetime-local` trả chuỗi NAIVE (vd `'2026-09-01T00:00'`, không mang
 * timezone). Gửi thẳng chuỗi đó là gửi một mốc KHÔNG tz-aware — BE có
 * `field_validator` ném `422` nếu `tzinfo is None`, và (nguy hiểm hơn cả 422)
 * asyncpg sẽ encode một datetime naive theo giờ HOST chạy backend nếu
 * validator không chặn kịp — cùng bài học `occurredAt` của module `ingest`
 * (Change Log 2026-08-15 repo backend): mốc SAI giờ ở đây làm SAI luôn
 * khoảng hiệu lực nào áp cho usage nào, không chỉ sai một trường hiển thị.
 * `new Date(local).toISOString()` gắn offset (quy về UTC, hậu tố `Z`) trước
 * khi rời tay FE — ĐÃ KIỂM NGƯỢC: bỏ dòng `.toISOString()` (gửi thẳng chuỗi
 * `datetime-local`) làm bài test tz-aware trong `tests/billing-gia.test.tsx`
 * đỏ đúng vào assertion so khớp `effectiveFrom` gửi lên, xác nhận cổng bắt
 * được lớp lỗi này trước khi hoàn nguyên lại `.toISOString()`.
 */
function HangGan({
  ws,
  boGiaActive,
}: {
  readonly ws: Workspace
  readonly boGiaActive: readonly BoGia[]
}) {
  const [priceVersionId, setPriceVersionId] = useState('')
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const gan = useGanChoWorkspace(ws.id)
  const idChonBoGia = useId()
  const idHieuLuc = useId()

  const hopLe = priceVersionId !== '' && effectiveFrom !== ''

  function guiGan() {
    if (gan.isPending || !hopLe) return
    gan.mutate(
      {
        priceVersionId: Number(priceVersionId),
        // ⚠️ KHÔNG gửi thẳng `effectiveFrom` — xem docstring hàm này.
        effectiveFrom: new Date(effectiveFrom).toISOString(),
      },
      {
        onSuccess: () => {
          setPriceVersionId('')
          setEffectiveFrom('')
        },
      },
    )
  }

  return (
    <>
      <tr className="border-t border-rule align-top">
        <td className={TD}>
          <p className="font-medium text-fg">{ws.name}</p>
          <p className="font-mono text-phu text-muted">{ws.slug}</p>
        </td>
        <td className={TD}>
          {/* Xem docstring đầu file — KHÔNG có endpoint đọc `tenant_price_version`.
              `—` là dấu KHÔNG XÁC ĐỊNH, không phải "chưa gán". */}
          <span
            className="text-than text-muted-3"
            title="Chưa có endpoint đọc `tenant_price_version` — không biết bộ giá đang áp hay hiệu lực từ hiện hành của workspace này (không phải nghĩa là chưa gán)."
          >
            —
          </span>
        </td>
        <td className={TD}>
          <label htmlFor={idChonBoGia} className="sr-only">
            Bộ giá cho {ws.name}
          </label>
          <select
            id={idChonBoGia}
            value={priceVersionId}
            disabled={gan.isPending}
            onChange={(e) => setPriceVersionId(e.target.value)}
            className={`${O_CHUNG} o-chon`}
          >
            <option value="">Chọn bộ giá</option>
            {boGiaActive.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </td>
        <td className={TD}>
          <label htmlFor={idHieuLuc} className="sr-only">
            Hiệu lực từ cho {ws.name}
          </label>
          <input
            id={idHieuLuc}
            type="datetime-local"
            value={effectiveFrom}
            disabled={gan.isPending}
            onChange={(e) => setEffectiveFrom(e.target.value)}
            className={O_CHUNG}
          />
        </td>
        <td className={`${TD} text-right`}>
          <button
            type="button"
            onClick={guiGan}
            disabled={gan.isPending || !hopLe}
            className={NUT_PHU}
          >
            {gan.isPending ? 'Đang gán…' : 'Gán'}
          </button>
        </td>
      </tr>
      {(gan.isError || gan.isSuccess) && (
        <tr className="border-t border-rule">
          <td colSpan={COT_GAN.length} className="px-4 pb-3">
            {gan.isError ? (
              // Hiện NGUYÊN VĂN message của BE (`409 MOC_QUA_KHU_DA_DINH_GIA` /
              // `409 MOC_TRUOC_KHOANG_DANG_MO` đã nêu đúng ngày + hướng xử lý)
              // — đừng viết lại.
              <DongTrangThai mau="alert">
                {thongDiep(gan.error, `Không gán được bộ giá cho ${ws.name}`)}
              </DongTrangThai>
            ) : (
              <DongTrangThai mau="ok">Đã gán bộ giá cho {ws.name}.</DongTrangThai>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export function PanelGanWorkspace({ onDong }: { readonly onDong: () => void }) {
  const { session } = useSession()
  const boGia = useBoGia()
  const idTieuDe = useId()
  const boGiaActive = (boGia.data ?? []).filter((b) => b.status === 'active')

  let noiDung: ReactNode
  if (boGia.isPending) {
    noiDung = (
      <div className="flex flex-col gap-2 p-5">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="h-10 animate-pulse rounded-md bg-fill" />
        ))}
      </div>
    )
  } else if (boGia.error) {
    noiDung = (
      <div className="p-5">
        <LoiTai viec="danh sách bộ giá" thuLai={() => void boGia.refetch()} />
      </div>
    )
  } else if (session.workspaces.length === 0) {
    noiDung = (
      <div className="p-5">
        <KhoRong tieuDe="Chưa có workspace nào" huongDan="Không có workspace nào để gán bộ giá." />
      </div>
    )
  } else {
    noiDung = (
      <div className="min-h-0 flex-1 overflow-y-auto">
        {boGiaActive.length === 0 && (
          <p className="px-5 pt-4 text-phu text-muted-2">
            Chưa có bộ giá nào đang «Đang dùng» — kích hoạt một bộ giá ở mục ② trước khi gán.
          </p>
        )}
        <div className="p-5">
          <Bang nhan="Gán bộ giá cho workspace">
            <DauBang cot={COT_GAN} />
            <tbody>
              {session.workspaces.map((ws) => (
                <HangGan key={ws.id} ws={ws} boGiaActive={boGiaActive} />
              ))}
            </tbody>
          </Bang>
        </div>
      </div>
    )
  }

  return (
    <PanelKhung idTieuDe={idTieuDe} onDong={onDong}>
      <div className="flex flex-none items-start justify-between gap-4 border-b border-border-soft px-5 py-4 pr-14">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 id={idTieuDe} className="text-muc font-semibold text-fg">
            Gán bộ giá cho workspace
          </h2>
          <p className="text-phu text-muted">
            Mốc hiệu lực áp dụng NGAY khi gán — không có bước duyệt.
          </p>
        </div>
      </div>
      {noiDung}
    </PanelKhung>
  )
}
