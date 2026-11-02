/**
 * Bảng «Lượt dùng chi tiết» của màn `/usage` — ba chiều gộp, bộ cột LƯỢNG.
 *
 * KHÔNG dùng lại `BangLuotDung` (`/billing`): bảng đó chở cột `chi_phi` ở cả ba
 * chiều và một hàng Tổng có tiền. Ở đây không một đồng nào — thêm một prop
 * `anTien` vào bảng kia là dựng một component hai tính cách, và cột tiền sẽ quay
 * lại ở lần sửa sau vì "dữ liệu có sẵn rồi".
 *
 * Tiêu đề + hàng tab nằm TRONG thẻ (`ThanhCong`). Chữ trần trên nền trang giữa
 * hai thẻ là đúng lỗi `/api-keys` đã sửa 2026-08-08 (thẻ → chữ trần → thẻ).
 *
 * ⚠️ Hàng «Chưa phân loại (không có khoá)» KHÔNG được ẩn: bất biến của bảng này
 * là mọi cột cộng đúng bằng hàng Tổng. Ẩn nó là tổng dòng < tổng hiển thị, và
 * lệch im lặng — BE cố ý giữ nhóm `agent_key_id IS NULL` cho đúng việc đó.
 */
import {
  Bang,
  ChanBang,
  DauBang,
  HANG_NUT,
  Hang,
  NUT_PHU,
  NhomTab,
  TD,
  TD_SO,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
  type MucTab,
} from '@/components/ui/Bang'
import { ChipKenh } from '@/components/ui/ChipKenh'
import { SO, dinhDangLuc, giay, rong, token } from '../dinh-dang'
import type { DanhSachKey, DanhSachPhien, DongKey, DongOwner, PhienUsage } from '../kieu'
import { panelTab } from '@/components/ui/panelTab'

export type ChieuGop = 'khoa' | 'nguoi' | 'phien'

const TAB_CHIEU: readonly MucTab<ChieuGop>[] = [
  { id: 'khoa', nhan: 'Khoá' },
  { id: 'nguoi', nhan: 'Người tạo' },
  { id: 'phien', nhan: 'Phiên' },
]

export const NHAN_CHUA_PHAN_LOAI = 'Chưa phân loại (không có khoá)'
const NHAN_DU_LIEU_NGOAI = 'Dữ liệu ngoài (chạy tự động)'

/**
 * Sáu cột LƯỢNG dùng chung chiều «Khoá» và «Người tạo» — CÙNG thứ tự, CÙNG nhãn.
 * Người bấm từ chiều này sang chiều kia phải tìm lại đúng những cột vừa đọc; đó
 * cũng là cả lý do BE phải mở rộng `DongOwnerOut` thay vì FE tự gộp.
 */
const COT_LUONG: readonly Cot[] = [
  { nhan: 'Phiên', phai: true },
  { nhan: 'In', phai: true },
  { nhan: 'Out', phai: true },
  { nhan: 'Cache read', phai: true },
  { nhan: 'Thời gian gọi', phai: true },
]

export function BangLuotDungUsage({
  chieu,
  datChieu,
  khoa,
  nguoi,
  phien,
  trang,
  datTrang,
  moPhien,
  soMoiTrang,
}: {
  readonly chieu: ChieuGop
  readonly datChieu: (c: ChieuGop) => void
  readonly khoa: DanhSachKey | undefined
  readonly nguoi: readonly DongOwner[] | undefined
  readonly phien: DanhSachPhien | undefined
  readonly trang: number
  readonly datTrang: (t: number) => void
  readonly moPhien: (sessionId: string) => void
  readonly soMoiTrang: number
}) {
  return (
    <TheBang>
      <ThanhCong>
        <h2 className="m-0 text-muc font-semibold tracking-[-0.012em]">Lượt dùng chi tiết</h2>
        <span className="ml-auto text-phu text-muted">Gộp theo</span>
        <NhomTab
          nhan="Chiều gộp"
          muc={TAB_CHIEU}
          dangMo={chieu}
          doi={datChieu}
          idPanel="tab-chieu-usage"
        />
      </ThanhCong>

      <VungCuon {...panelTab('tab-chieu-usage', chieu)}>
        {chieu === 'khoa' ? <BangKhoa items={khoa?.items ?? []} /> : null}
        {chieu === 'nguoi' ? <BangNguoi items={nguoi ?? []} /> : null}
        {chieu === 'phien' ? <BangPhien items={phien?.items ?? []} moPhien={moPhien} /> : null}
      </VungCuon>

      {/* Phân trang CHỈ ở chiều «Phiên» — hai chiều kia gộp về vài hàng, không
          phân trang, nên một thanh phân trang ở đó là một điều khiển không đi
          tới đâu. */}
      {chieu === 'phien' && phien ? (
        <ChanBang>
          <div className={HANG_NUT}>
            <span className="mr-auto text-phu text-muted">
              {phien.items.length === 0
                ? '0 phiên'
                : `${trang * soMoiTrang + 1}–${trang * soMoiTrang + phien.items.length} / ${SO(phien.total)} phiên`}
            </span>
            <button
              type="button"
              className={NUT_PHU}
              disabled={trang === 0}
              onClick={() => datTrang(trang - 1)}
            >
              ← Trang trước
            </button>
            <button
              type="button"
              className={NUT_PHU}
              disabled={(trang + 1) * soMoiTrang >= phien.total}
              onClick={() => datTrang(trang + 1)}
            >
              Trang sau →
            </button>
          </div>
        </ChanBang>
      ) : null}
    </TheBang>
  )
}

function TenPhu({ ten, phu }: { readonly ten: string; readonly phu: string }) {
  return (
    <span className="flex min-w-0 flex-col gap-px">
      <b className="text-than font-medium">{ten}</b>
      <span className="font-mono text-nhan text-muted-2">{phu}</span>
    </span>
  )
}

function BangKhoa({ items }: { readonly items: readonly DongKey[] }) {
  return (
    <Bang nhan="Lượt dùng theo khoá">
      <DauBang cot={[{ nhan: 'Khoá', rong: 'w-full' }, { nhan: 'Người tạo' }, ...COT_LUONG]} />
      <tbody>
        {items.map((k) => (
          <Hang key={k.du_lieu_ngoai ? 'du-lieu-ngoai' : (k.agent_key_id ?? 'chua-phan-loai')}>
            <td className={TD}>
              {k.du_lieu_ngoai ? (
                <span className="text-muted-2">{NHAN_DU_LIEU_NGOAI}</span>
              ) : k.agent_key_id === null ? (
                <span className="text-muted-2">{NHAN_CHUA_PHAN_LOAI}</span>
              ) : (
                <TenPhu ten={rong(k.label)} phu={k.key_prefix} />
              )}
            </td>
            <td className={TD}>{rong(k.nguoi_tao_ten ?? k.nguoi_tao)}</td>
            <td className={TD_SO}>{k.du_lieu_ngoai ? '—' : SO(k.so_phien)}</td>
            <td className={TD_SO}>{token(k.input_tokens)}</td>
            <td className={TD_SO}>{token(k.output_tokens)}</td>
            <td className={TD_SO}>{token(k.cache_read_tokens)}</td>
            <td className={TD_SO}>{giay(k.voice_sec)}</td>
          </Hang>
        ))}
      </tbody>
      <ChanTong
        cotChu={2}
        so={[
          SO(cong(items, 'so_phien')),
          token(cong(items, 'input_tokens')),
          token(cong(items, 'output_tokens')),
          token(cong(items, 'cache_read_tokens')),
          giay(cong(items, 'voice_sec')),
        ]}
      />
    </Bang>
  )
}

function BangNguoi({ items }: { readonly items: readonly DongOwner[] }) {
  return (
    <Bang nhan="Lượt dùng theo người tạo">
      <DauBang
        cot={[{ nhan: 'Người tạo', rong: 'w-full' }, { nhan: 'Khoá', phai: true }, ...COT_LUONG]}
      />
      <tbody>
        {items.map((o) => (
          <Hang key={o.du_lieu_ngoai ? 'du-lieu-ngoai' : (o.user_id ?? 'chua-phan-loai')}>
            <td className={TD}>
              {o.du_lieu_ngoai ? (
                <span className="text-muted-2">{NHAN_DU_LIEU_NGOAI}</span>
              ) : o.user_id === null ? (
                <span className="text-muted-2">{NHAN_CHUA_PHAN_LOAI}</span>
              ) : (
                <TenPhu ten={o.ten ?? o.user_id} phu={o.email ?? ''} />
              )}
            </td>
            <td className={TD_SO}>{o.du_lieu_ngoai ? '—' : SO(o.so_key)}</td>
            <td className={TD_SO}>{o.du_lieu_ngoai ? '—' : SO(o.so_phien)}</td>
            <td className={TD_SO}>{token(o.input_tokens)}</td>
            <td className={TD_SO}>{token(o.output_tokens)}</td>
            <td className={TD_SO}>{token(o.cache_read_tokens)}</td>
            <td className={TD_SO}>{giay(o.voice_sec)}</td>
          </Hang>
        ))}
      </tbody>
      <ChanTong
        cotChu={1}
        so={[
          SO(cong(items, 'so_key')),
          SO(cong(items, 'so_phien')),
          token(cong(items, 'input_tokens')),
          token(cong(items, 'output_tokens')),
          token(cong(items, 'cache_read_tokens')),
          giay(cong(items, 'voice_sec')),
        ]}
      />
    </Bang>
  )
}

function BangPhien({
  items,
  moPhien,
}: {
  readonly items: readonly PhienUsage[]
  readonly moPhien: (sessionId: string) => void
}) {
  return (
    <Bang nhan="Lượt dùng theo phiên">
      <DauBang
        cot={[
          { nhan: 'Phiên' },
          { nhan: 'Khách', rong: 'w-full' },
          { nhan: 'Kênh' },
          { nhan: 'Bắt đầu' },
          { nhan: 'Turn', phai: true },
          { nhan: 'In', phai: true },
          { nhan: 'Out', phai: true },
          { nhan: 'Thời gian gọi', phai: true },
        ]}
      />
      <tbody>
        {items.map((p) => (
          <Hang key={p.session_id} mo={() => moPhien(p.session_id)}>
            <td className={TD}>
              {/* Nút chứ không `<span>`: `Hang mo=` chỉ bắt CHUỘT — bàn phím không có
                  đường nào mở phiên (audit 05/10). Khuôn của `BangLuotDung` (/billing). */}
              <button
                type="button"
                onClick={() => moPhien(p.session_id)}
                className="font-mono text-[12px] underline-offset-2 hover:underline"
              >
                {p.session_id}
              </button>
            </td>
            <td className={TD}>{rong(p.customer_name)}</td>
            <td className={TD}>
              <ChipKenh source={p.channel} anKhiLa />
            </td>
            <td className={TD}>
              <span className="font-mono text-[12px] text-muted">
                {p.bat_dau ? dinhDangLuc(p.bat_dau) : '—'}
              </span>
            </td>
            <td className={TD_SO}>{SO(p.so_turn)}</td>
            <td className={TD_SO}>
              {token(p.input_tokens)}
              {p.exact ? null : (
                <span
                  className="ml-[5px] inline-flex size-[15px] items-center justify-center rounded-full bg-badge-warn-bg align-middle text-nhan font-bold text-badge-warn-fg"
                  title="exact=false — đo THIẾU token, không phải 0"
                >
                  !
                </span>
              )}
            </td>
            <td className={TD_SO}>{token(p.output_tokens)}</td>
            <td className={TD_SO}>{giay(p.voice_sec)}</td>
          </Hang>
        ))}
      </tbody>
    </Bang>
  )
}

/**
 * Hàng Tổng. `cotChu` = số cột CHỮ đứng trước cụm số; nhãn «Tổng» chiếm cột đầu,
 * các cột chữ còn lại để rỗng.
 *
 * ⚠️ Cộng từ CHÍNH các hàng đang hiện, KHÔNG lấy từ một trường tổng của API:
 * hai nguồn cho một con số là hai chỗ để lệch nhau, và ở bảng này phép cộng là
 * bất biến người đọc kiểm được bằng mắt — nó phải đúng với thứ họ thấy.
 */
function ChanTong({ cotChu, so }: { readonly cotChu: number; readonly so: readonly string[] }) {
  const O = 'border-t border-border-strong bg-fill px-4 py-3 text-phu'
  return (
    <tfoot>
      <tr>
        <td className={O}>
          <b className="font-medium">Tổng</b>
        </td>
        {Array.from({ length: cotChu - 1 }, (_, i) => (
          <td key={i} className={O} />
        ))}
        {so.map((x, i) => (
          <td
            key={i}
            className={`${O} text-right font-mono font-semibold tabular-nums whitespace-nowrap`}
          >
            {x}
          </td>
        ))}
      </tr>
    </tfoot>
  )
}

function cong<T>(hang: readonly T[], cot: keyof T): number {
  return hang.reduce((a, h) => a + (Number(h[cot]) || 0), 0)
}
