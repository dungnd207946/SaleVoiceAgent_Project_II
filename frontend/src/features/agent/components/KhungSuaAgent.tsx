/**
 * Vỏ chung của mọi màn sửa agent: trạng thái tải · cảnh báo toàn cục · thân màn
 * (`children`) · hàng hành động ở CUỐI · dialog xem lại.
 *
 * KHÔNG CÒN THANH TRẠNG THÁI TRÊN CÙNG (người dùng chốt 2026-08-08). Nó từng
 * mang tiêu đề + chip + số version + một câu mô tả; cả bốn đã bị cắt qua ba
 * lượt, và lượt cuối bỏ nốt cái hàng. Nút chuyển xuống dưới nội dung — đọc/điền
 * từ trên xuống rồi mới quyết, đúng thứ tự thao tác của một form.
 *
 * VÌ SAO LÀ MỘT COMPONENT chứ không chép hai lần: `/agent` và `/ky-nang-bds`
 * sửa cùng một bản nháp và cùng phát bằng một `POST /publish`. Hai thanh trạng
 * thái viết rời nhau là hai chỗ để một cái nói «Sẵn sàng» còn cái kia nói «Đang
 * áp dụng» cho cùng một agent.
 *
 * HAI MÀN DÙNG NÓ THEO HAI KIỂU (2026-08-08):
 *   · `/agent` truyền `che` — header đổi theo chế độ xem/sửa.
 *   · `/ky-nang-bds` không truyền — luôn ở chế độ sửa, y như trước.
 *
 * Luồng (AG_01, backend `0966`): sửa -> [Lưu và áp dụng] -> dialog xem lại (liệt kê
 * thay đổi, tính ở client) -> [Xác nhận áp dụng] -> `PUT /config` ghi MỌI role ->
 * agent nạp cho phiên tiếp theo. Không còn bản nháp hay bước publish riêng.
 *
 * ⚠ SỐ VERSION KHÔNG CÒN Ở TRẠNG THÁI NGHỈ (người dùng chốt 2026-08-08). Thanh
 * này từng luôn hiện «khách đang dùng vN». Portal KHÔNG có lịch sử version,
 * KHÔNG có nút quay lại bản cũ, KHÔNG có phép so hai bản — nên con số đó không
 * dẫn tới hành động nào. Nó chỉ có nghĩa đúng một khoảnh khắc: ngay sau khi
 * phát, làm bằng chứng lệnh phát đã chạy thật (trước 2026-08-05 endpoint trả
 * 202 + jobId và worker không chạy, nên «im lặng» là toàn bộ phản hồi). Vì thế
 * `vuaApDung` vẫn mang số, còn `trangThai.data.version` thì không hiện nữa.
 * Ngày nào có màn lịch sử/rollback thì đó là chỗ số version quay lại.
 */
import { useEffect, useRef, type ReactNode } from 'react'
import type { TrangThaiAgent } from '../api'
import type { useBanNhap } from '../useBanNhap'
import { Canh } from './form'
import { HANG_NUT } from '@/components/ui/Bang'
import { NUT_CHINH, NUT_PHU } from './lop'
import { LuuApDungDialog } from './LuuApDungDialog'

/** AG_01 §II.3 — bốn chip báo trạng thái agent trên thanh trạng thái.
 * Màu chip nói đúng mức độ: sẵn sàng xanh, đang chuyển động vàng, mất kết nối
 * đỏ. Ba sắc thái badge của prototype, không thêm màu thứ tư. */
const CHIP: Record<TrangThaiAgent, { nhan: string; lop: string }> = {
  dang_cap: { nhan: 'Đang cấp', lop: 'bg-badge-warn-bg text-badge-warn-fg' },
  dang_ap_dung: { nhan: 'Đang áp dụng', lop: 'bg-badge-warn-bg text-badge-warn-fg' },
  san_sang: { nhan: 'Sẵn sàng', lop: 'bg-acs text-ac' },
  mat_ket_noi: { nhan: 'Mất kết nối', lop: 'bg-badge-alert-bg text-badge-alert-fg' },
}

/**
 * Màn có HAI CHẾ ĐỘ thì truyền `che` vào; màn chỉ-sửa (Kỹ năng BĐS) thì bỏ trống.
 *
 * Vì sao là một prop của vỏ chứ không phải mỗi màn tự dựng header: chế độ quyết
 * định cả nút, cả câu mô tả, cả việc có mở được dialog phát hay không. Ba thứ đó
 * nằm trong header — để màn tự dựng là chép lại cả header, tức là mở lại đúng
 * cái nguy cơ hai thanh trạng thái nói hai điều khác nhau mà file này sinh ra để
 * đóng.
 */
interface CheXemSua {
  dangXem: boolean
  onSua: () => void
  onHuy: () => void
}

export function KhungSuaAgent({
  ban,
  che,
  children,
}: {
  ban: ReturnType<typeof useBanNhap>
  che?: CheXemSua
  children: ReactNode
}) {
  const { nhap, trangThai, goc, form, mApDung, moDialog, setMoDialog, vuaApDung, vaiTro } = ban
  const dangXem = che?.dangXem ?? false

  // Đổi chế độ thì nút vừa bấm UNMOUNT («Sửa cấu hình» ↔ «Huỷ»/«Lưu và áp dụng»), và
  // focus rơi về <body> — người dùng bàn phím phải Tab lại từ đầu trang (audit 05/10).
  // Vào sửa ⇒ focus ô đầu tiên của form; về xem ⇒ focus nút «Sửa cấu hình».
  // `null` = chưa có `che` (đang tải): lần đầu nhận chế độ KHÔNG giành focus.
  const noiDung = useRef<HTMLDivElement>(null)
  const nutSua = useRef<HTMLButtonElement>(null)
  const cheTruoc = useRef<boolean | null>(null)
  const cheNay = che ? dangXem : null
  useEffect(() => {
    const truoc = cheTruoc.current
    cheTruoc.current = cheNay
    if (truoc === null || cheNay === null || truoc === cheNay) return
    if (cheNay) nutSua.current?.focus()
    else noiDung.current?.querySelector<HTMLElement>('input, textarea, select')?.focus()
  }, [cheNay])

  if (nhap.isPending || trangThai.isPending)
    return <p className="px-7 pt-[26px] text-[14px] text-muted max-md:px-4">Đang tải…</p>
  if (nhap.error)
    return <p className="px-7 pt-[26px] text-[14px] max-md:px-4">Không tải được cấu hình agent.</p>
  if (!form || !goc) return null

  // ER_03 theo TỪNG role: một role tắt hết kỹ năng là agent của role đó không làm được gì.
  const roleKhongKyNang = vaiTro.filter((r) => form[r.key]?.tools.enabled.length === 0)

  const tt = trangThai.data?.trangThaiAgent ?? 'dang_cap'

  /**
   * Chip trạng thái chỉ hiện khi pod KHÔNG ở trạng thái bình thường.
   *
   * `Sẵn sàng` là trạng thái nghỉ — nó đúng gần như mọi lúc, nên hiện nó thường
   * trực là dạy người dùng bỏ qua chỗ này, và đúng lúc nó chuyển thành «Mất kết
   * nối» thì không ai còn nhìn nữa. BR09 («nói THẬT trạng thái áp dụng») không
   * đòi phải khoe lúc mọi thứ ổn; nó đòi đừng giấu lúc không ổn.
   */
  const chip = tt === 'san_sang' ? null : CHIP[tt]
  /** Tạm ẩn chip trạng thái pod ở hàng nút — đổi lại `true` để bật. */
  const HIEN_CHIP = false

  /** Câu bên trái hàng nút — chỉ có mặt khi CÓ chuyện để nói. */
  const loi = mApDung.error
    ? 'Chưa áp dụng được — chưa có gì thay đổi, thử lại lần nữa.'
    : vuaApDung !== null
      ? `Đã áp dụng v${vuaApDung} cho mọi role. Agent nạp cấu hình mới cho phiên tiếp theo.`
      : null

  return (
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      {/* Cảnh báo toàn cục — TRÊN nội dung, luôn thấy được (ER_03). Ở CẢ HAI màn:
          "không bật kỹ năng nào" là tình trạng của agent, không phải của một
          màn, và người đang ở màn Cấu hình chung cũng cần biết.
          `-mt-2.5` khử `mt` sẵn có của `Canh` — ở đây nó là phần tử ĐẦU của
          màn, không phải một dòng nối sau một ô nhập như mọi chỗ dùng khác. */}
      {roleKhongKyNang.length > 0 && (
        <div className="-mt-2.5 mb-3.5">
          <Canh mau="alert">
            Agent cho {roleKhongKyNang.map((r) => r.ten).join(', ')} sẽ không làm được gì — bật ít
            nhất một kỹ năng.
          </Canh>
        </div>
      )}

      <div ref={noiDung}>{children}</div>

      {/* ── Hàng hành động, ở CUỐI MÀN ───────────────────────────────────────
          Người dùng chốt 2026-08-08: nút xuống dưới, thanh trạng thái trên cùng
          bỏ hẳn. Đọc/điền từ trên xuống rồi mới quyết — đúng thứ tự thao tác của
          một form, và nó trả lại đầu màn cho nội dung.

          Mọi thứ NÓI VỀ hành động cũng dồn về đây, vì đây là chỗ mắt đang nhìn
          lúc bấm: xác nhận «Đã áp dụng vN», báo hỏng, và chip trạng thái pod khi
          nó bất thường — cái cuối là thứ quyết định lệnh phát có tác dụng thật
          hay không, nên nó phải nằm cạnh chính cái nút phát.

          Căn phải + nút chính đứng cuối, qua hằng `HANG_NUT` — cùng khuôn với
          mọi hàng nút khác của portal (người dùng chốt 2026-08-08). */}
      <div className="mt-4 border-t border-border-soft pt-4">
        {/* Chip trạng thái pod đứng THÀNH HÀNG RIÊNG phía trên, không chen vào
            hàng nút: nó là tình trạng của hệ thống, cùng bậc với `DongTrangThai`
            mà `TongQuanTab`/`CanForm` đặt ngay trên hàng nút của chúng. */}
        {/* Tạm ẩn chip trạng thái pod — bật lại bằng cách xoá `HIEN_CHIP &&`. */}
        {HIEN_CHIP && chip && (
          <div className="mb-3">
            <span className={`rounded-full px-2 py-[2px] text-[11.5px] font-semibold ${chip.lop}`}>
              Agent: {chip.nhan}
            </span>
          </div>
        )}

        <div className={HANG_NUT}>
          {/* Câu ngắn đi TRƯỚC cụm nút (`mr-auto` đẩy nó về trái) — nó là kết quả
              của lần bấm trước, không phải một hành động. Cùng chỗ với «Đã lưu.»
              của `TongQuanTab`.
              Lỗi phải ĐỎ, không mờ như câu xác nhận: là chữ trần trên nền trang,
              một câu báo hỏng màu `muted` sẽ trôi lẫn vào phần còn lại. */}
          {/* Vùng `role="status"` TỒN TẠI SẴN (rỗng khi chưa có gì để nói): trình đọc
              màn hình chỉ đọc chữ đổ VÀO một vùng đã có — vùng mount cùng lúc với chữ
              thì thường bị bỏ qua, và «Đã áp dụng vN» trước đây không ai nghe thấy. */}
          <p
            role="status"
            className={`mr-auto min-w-0 text-than ${
              mApDung.error ? 'font-medium text-badge-alert-fg' : 'text-muted'
            }`}
          >
            {loi}
          </p>
          {dangXem ? (
            <button ref={nutSua} type="button" className={NUT_CHINH} onClick={che?.onSua}>
              Sửa cấu hình
            </button>
          ) : (
            <>
              {/* Huỷ chỉ có ở màn HAI CHẾ ĐỘ. Ở màn chỉ-sửa nó không có nghĩa:
                  không có chế độ nào để quay về, và «huỷ» ở đó sẽ đọc thành
                  «rời màn». */}
              {che && (
                <button
                  type="button"
                  className={NUT_PHU}
                  disabled={mApDung.isPending}
                  onClick={che.onHuy}
                >
                  Huỷ
                </button>
              )}
              <button
                type="button"
                className={NUT_CHINH}
                disabled={mApDung.isPending}
                onClick={() => {
                  mApDung.reset()
                  setMoDialog(true)
                }}
              >
                Lưu và áp dụng
              </button>
            </>
          )}
        </div>
      </div>

      {moDialog && (
        <LuuApDungDialog
          goc={goc}
          form={form}
          vaiTro={vaiTro}
          dangGui={mApDung.isPending}
          loiApDung={mApDung.isError}
          onDong={() => setMoDialog(false)}
          onXacNhan={() => mApDung.mutate()}
        />
      )}
    </div>
  )
}
