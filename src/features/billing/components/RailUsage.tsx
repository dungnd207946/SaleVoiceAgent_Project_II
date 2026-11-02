/**
 * Rail chỉ số của màn `/usage` — bảy mục DỌC, bấm được.
 *
 * Mỗi mục làm HAI việc: chở con số tổng của một thứ đo, VÀ là bộ chọn của biểu
 * đồ bên phải. Hai vai trong một chỗ là cả lý do màn này không còn dải KPI ngang
 * (`TheKpi`, nay thuộc `/billing`) — dải đó là một khối chỉ để bày số, và bảy
 * khung nhỏ cạnh nó là bảy biểu đồ không ai đọc nổi.
 *
 * ⚠️ Trạng thái đang chọn nói bằng NỀN + VẠCH accent bên trái, KHÔNG bằng chữ
 * đậm: con số vốn đã `font-medium`, thêm một nấc nữa thì hai mục đọc ra thành
 * hai KIỂU CHỮ chứ không ra một trạng thái — đúng bài học `SO_LON` (`lop.ts`)
 * đã ghi cho thẻ «Tổng chi phí» của `/billing`.
 *
 * ⚠️ Dòng phụ CHỈ chở SỐ. Màn này không có một câu giảng nghĩa nào (người dùng
 * chốt qua sáu vòng) — cái gì là bẫy làm SAI SỐ thì nằm ở `title`, không nằm
 * trên màn.
 */
import { SO_LON } from './lop'
import { bienMau } from '../truc-usage'
import { DINH_DANG, TAB_USAGE } from '../so-tab-usage'
import type { ChuoiTab } from '../chuoi-usage'

/**
 * Rút gọn riêng cho dòng phụ của tab đơn vị `token` — làm tròn MỘT chữ số lẻ ở
 * MỌI mức, luôn dấu CHẤM, hậu tố `K`/`M` viết liền. Khác `token()`
 * (`dinh-dang.ts`): hàm đó chỉ rút gọn từ 10.000 trở lên và dùng dấu phẩy
 * kiểu vi-VN dưới ngưỡng đó (`167,903` — phẩy ở đây là THẬP PHÂN, không phải
 * nhóm nghìn) — đúng cỡ mà một "trung bình/ngày" hay rơi vào, và dễ đọc nhầm
 * thành một số nguyên gần 168 nghìn.
 */
function gonToken(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(1)
}

const MUC =
  'relative w-full text-left px-[18px] pt-[13px] pb-[14px] flex flex-col gap-[3px] ' +
  'border-b border-rule last:border-b-0 hover:bg-fill ' +
  'aria-pressed:bg-acs before:absolute before:left-0 before:inset-y-0 before:w-[3px] ' +
  'aria-pressed:before:bg-[var(--c)]'

export function RailUsage({
  chuoi,
  dangChon,
  datTab,
  phuThem,
  themPhu,
}: {
  /** Chuỗi đã dẫn xuất của CẢ BẢY tab, khoá theo mã. */
  readonly chuoi: Record<string, ChuoiTab>
  readonly dangChon: string
  readonly datTab: (ma: string) => void
  /** Dòng phụ ĐÈ cho một số tab (tab Token dùng in/out/cache thay vì đỉnh). */
  readonly phuThem?: Record<string, readonly string[]> | undefined
  /** Mục nối THÊM vào dòng phụ (không thay) — vd phần của dữ liệu ngoài. */
  readonly themPhu?: Record<string, readonly string[]> | undefined
}) {
  return (
    <div className="flex flex-col border-r border-rule" role="group" aria-label="Chọn chỉ số">
      {TAB_USAGE.map((t) => {
        const c = chuoi[t.ma]
        const fmt = DINH_DANG[t.donVi]
        // NĂM tab đo lượng chỉ chở MỘT mục: trung bình mỗi ngày (người dùng
        // chốt 2026-08-25). Trước đó là `đỉnh … · N/M ngày` — hai con số cho
        // một dòng phụ 10.5px, và cả hai đều là thứ người ta tra khi đã quan
        // tâm chứ không phải thứ cần thấy khi đang quét bảy mục.
        //
        // HAI tab đè bằng `phuThem`, mỗi tab một lý do KHÁC NHAU:
        //   · Token — `in/out/cache` là TÁCH LOẠI của chính con số dẫn (cộng
        //     lại đúng bằng nó), không phải một chỉ số thứ hai.
        //   · STT   — `stream`/`conversation` là hai ĐỒNG HỒ vendor thu song
        //     song, mỗi cái một đơn vị. Một số trung bình gộp cả hai là con số
        //     không tồn tại, nên tab này KHÔNG có `Trung bình …/ngày`.
        const phu = [
          ...(phuThem?.[t.ma] ?? [
            t.donVi === 'token'
              ? `Token trung bình ${gonToken(c?.tbMoiNgay ?? 0)}/ngày`
              : `Trung bình ${fmt(c?.tbMoiNgay ?? 0)}/ngày`,
          ]),
          ...(themPhu?.[t.ma] ?? []),
        ]
        return (
          <button
            key={t.ma}
            type="button"
            className={MUC}
            style={bienMau(t.ma)}
            aria-pressed={t.ma === dangChon}
            data-tab={t.ma}
            onClick={() => datTab(t.ma)}
          >
            <span className="flex items-center gap-[7px]">
              <i
                aria-hidden
                className="size-[7px] flex-none rounded-full"
                style={{ background: 'linear-gradient(135deg,var(--a),var(--b))' }}
              />
              <span className="text-nhan font-semibold tracking-[0.06em] text-muted-2 uppercase">
                {t.nhan}
              </span>
            </span>
            <span className={`${SO_LON} text-[23px] text-[var(--c)]`}>{fmt(c?.tong ?? 0)}</span>
            <span
              data-phu
              className="flex flex-wrap gap-x-[9px] gap-y-px font-mono text-nhan text-muted-2"
            >
              {phu.map((x) => (
                <span key={x}>{x}</span>
              ))}
            </span>
          </button>
        )
      })}
    </div>
  )
}
