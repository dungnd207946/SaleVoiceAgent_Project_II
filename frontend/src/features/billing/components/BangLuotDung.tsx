/**
 * Explorer mục ③ — MỘT bảng, BA chiều gộp (Task 5, spec §7).
 *
 * Bộ chuyển «Gộp theo» (`NhomTab`) đổi `thead`/`tbody` — giữ nguyên kỳ (`from`/
 * `to` do `UsageScreen` giải từ `tim.ky`) và giữ nguyên thẻ KPI phía trên. Ba
 * chiều gọi BA hook riêng (`useTheoKey`/`useTheoOwner`/`usePhien`), mỗi hook tự
 * tải/lỗi/rỗng — đổi tab không đụng tới hai chiều còn lại.
 *
 * BA LUẬT CỨNG của BE (hợp đồng `usage-billing.md` §9, nhắc lại ở đây vì đây là
 * chỗ chúng thật sự được thi hành, không phải chỉ mô tả):
 *
 * ① `agent_key_id`/`user_id` NULL = nhóm «Chưa phân loại» — KHÔNG ẨN, GHIM
 *    CUỐI bảng sau MỌI lần đổi sắp xếp (xem `ghimCuoiVaSap` — hàng null bị lọc
 *    RA khỏi tập được sort rồi nối lại ở cuối, nên nó không bao giờ trôi theo
 *    cột đang sắp). Không có control nào lọc bỏ nó — kể cả khi rỗng ở mọi cột.
 * ② Hàng Tổng của chiều «Khoá» dùng THẲNG `chi_phi_tong` của API. `Σ items[].
 *    chi_phi` chỉ tính ra để SO SÁNH (`soSanhTien`, BigInt — không qua `Number`,
 *    xem `dinh-dang.ts`) — lệch thì hiện dải cảnh báo, không phải tự chọn số
 *    nào để hiện. Chiều «Người tạo» KHÔNG có `chi_phi_tong` riêng từ API (kiểu
 *    `DongOwner[]` trần, xem `kieu.ts`) nên hàng Tổng ở đó là tổng tự cộng —
 *    không có gì để đối chiếu, không phải trường hợp lệch.
 * ③ KHÔNG cột `voice_sec`/thời lượng ở bảng chính: `vad`/`call`/`stt` đo những
 *    quãng audio CHỒNG LẤN nhau, cộng lại là tính một giây nhiều lần. Xem panel
 *    chi tiết phiên (Task 6) — ở đó tách theo component thì cộng mới có nghĩa.
 *
 * KHÔNG CÓ Ô TÌM Ở BẢN NÀY: task-5-brief chỉ giao NhomTab + ba bộ cột + phân
 * trang chiều Phiên, không giao ô lọc/tìm dù bản vẽ §7 có phác một ô `[tìm…]`
 * cạnh NhomTab. Thêm sau nếu backend/khoảng cần — cột `label`/`ten`/`email` đã
 * đủ để trình bày đúng, tìm kiếm là một lớp lọc riêng không ảnh hưởng cột nào.
 *
 * PHIÊN bấm được từ Task 6: `moPhien(sessionId, el)` truyền từ `UsageScreen`
 * xuống tận `HangPhien` — `el` là nút định danh của ĐÚNG hàng vừa bấm, để
 * `UsageScreen` giữ lại và trả focus về nó lúc slide-over đóng (khuôn
 * `oKichHoatRef` của `LightboxAnh`, xem docstring `ChiTietPhien.tsx`). Component
 * ở TỆP NÀY không biết gì về search param `phien` hay slide-over — nó chỉ
 * chuyển tiếp `moPhien` xuống đúng chỗ.
 */
import { useRef, useState } from 'react'
import {
  Bang,
  DauBang,
  Hang,
  NhomTab,
  PILL,
  TD,
  TD_PHU,
  TD_SO,
  TheBang,
  ThanhCong,
  VungCuon,
  type Cot,
  type MucTab,
  type SapXep,
} from '@/components/ui/Bang'
import { ChipKenh } from '@/components/ui/ChipKenh'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { LoiTai } from '@/components/ui/TrangThai'
import { usePhien, useTheoKey, useTheoOwner } from '../api'
import { nhanComponent } from '../component-hien'
import { SO, congTien, rong, soSanhTien, tien } from '../dinh-dang'
import type { DongKey, DongOwner, PhienUsage } from '../kieu'
// Type-only: không có vòng phụ thuộc RUNTIME (interface bị xoá lúc build).
import type { UsageTim } from './UsageScreen'
import { panelTab } from '@/components/ui/panelTab'

/**
 * BE cũng khai hằng này (`NHAN_CHUA_PHAN_LOAI`, xem hợp đồng §9.1) — GIỮ NGUYÊN
 * chuỗi, đừng diễn giải lại nhãn. Dùng chung cho cả chiều «Khoá» (`agent_key_id
 * === null`) lẫn chiều «Người tạo» (`user_id === null`) — cùng một nhóm usage
 * chưa quy được về đâu, chỉ khác cách gộp đang xem.
 */
export const NHAN_CHUA_PHAN_LOAI = 'Chưa phân loại (không có khoá)'

const GHI_CHU_CHUA_PHAN_LOAI =
  'Usage được ghi trước khi phiên có hàng conversations — chưa quy được về khoá nào.'

export const NHAN_DU_LIEU_NGOAI = 'Dữ liệu ngoài (chạy tự động)'

const GHI_CHU_DU_LIEU_NGOAI = 'Thu thập bài báo, viết hồ sơ dự án và tra Google theo lịch chạy.'

/** Ô Tổng chi phí — `font-semibold` ở MỌI hàng của cột này (luật đậm 600 áp cho
 *  cả cột, không riêng hàng Tổng kỳ). Bảy cột dịch vụ đứng trước nó KHÔNG đậm —
 *  chúng là chi tiết, «Tổng chi phí» mới là số dẫn của hàng. */
function OChiPhi({ chiPhi }: { readonly chiPhi: string }) {
  return <span className="font-semibold">{tien(chiPhi)}</span>
}

/**
 * Bảy ô tiền theo dịch vụ (LLM/TTS/STT/Embed/Cuộc gọi/VAD/Xác thực giọng) của
 * MỘT hàng khoá, MỘT hàng người tạo, HOẶC MỘT hàng phiên — dùng chung cho cả
 * ba chiều (+ hàng «Chưa phân loại» của hai chiều đầu) để không chép tay 7
 * dòng `<td>` năm lần. Thứ tự + mã khớp ĐÚNG `repo.theo_key()`/`repo.theo_owner()`/
 * `repo.liet_ke_phien()`::`_COMPONENT_TIEN` phía BE (`KHOA_COT`/`OWNER_COT`/
 * `PHIEN_COT` dưới lấy NHÃN của cùng bảy cột này từ `nhanComponent()`, một
 * nguồn cho cả ba chỗ). Không đậm (khác `OChiPhi`): đây là chi tiết bổ trợ,
 * không phải số dẫn của hàng. */
function OCacTienComponent({ d }: { readonly d: DongKey | DongOwner | PhienUsage }) {
  return (
    <>
      <td className={TD_SO}>{tien(d.chi_phi_llm)}</td>
      <td className={TD_SO}>{tien(d.chi_phi_tts)}</td>
      <td className={TD_SO}>{tien(d.chi_phi_stt)}</td>
      <td className={TD_SO}>{tien(d.chi_phi_embed)}</td>
      <td className={TD_SO}>{tien(d.chi_phi_search ?? '0')}</td>
      <td className={TD_SO}>{tien(d.chi_phi_call)}</td>
      <td className={TD_SO}>{tien(d.chi_phi_vad)}</td>
      <td className={TD_SO}>{tien(d.chi_phi_speaker_verify)}</td>
    </>
  )
}

/** `nguoi_tao_ten ?? nguoi_tao`, rỗng ⇒ `—` (§7 chiều Khoá). Tách hàm vì `??`
 *  không trộn được với `||` mà không có ngoặc — viết tại chỗ dễ đọc sai. */
function hienNguoiTao(ten: string | null, ma: string): string {
  const v = ten ?? ma
  return rong(v || null)
}

/**
 * Đổi cột đang sắp: bấm cột MỚI → bắt đầu GIẢM DẦN (số lớn trước, đúng thói
 * quen đọc bảng tiền); bấm lại đúng cột đang sắp → đảo chiều.
 */
function doiCotSap(hienTai: SapXep | null, cot: string): SapXep {
  if (hienTai && hienTai.cot === cot) return { cot, giam: !hienTai.giam }
  return { cot, giam: true }
}

/**
 * Ghim hàng «Chưa phân loại» xuống CUỐI, rồi mới sắp phần còn lại theo cột
 * đang chọn. Hàng ghim bị lọc RA trước khi sort nên nó không bao giờ trôi vào
 * giữa danh sách — đúng luật «bất kể cột nào đang sort» (§9.1).
 */
function ghimCuoiVaSap<T>(
  items: readonly T[],
  laChuaPhanLoai: (t: T) => boolean,
  sapXep: SapXep | null,
  soSanh: Readonly<Record<string, (a: T, b: T) => number>>,
): T[] {
  const thuong = items.filter((t) => !laChuaPhanLoai(t))
  const chuaPhanLoai = items.filter(laChuaPhanLoai)
  const cmp = sapXep ? soSanh[sapXep.cot] : undefined
  if (cmp) thuong.sort((a, b) => (sapXep!.giam ? cmp(b, a) : cmp(a, b)))
  return [...thuong, ...chuaPhanLoai]
}

/**
 * Bộ so sánh của mọi cột có `sap` — `sap` LÀ tên trường: số đếm (`so_*`) trừ thẳng,
 * tiền so bằng BigInt (`chi_phi_search` vắng ở BE cũ ⇒ `'0'`). Thêm cột chỉ sửa danh sách cột.
 */
function soSanhTheoCot<T extends object>(
  cot: readonly Cot[],
): Readonly<Record<string, (a: T, b: T) => number>> {
  const gia = (d: T, k: string) => (d as Record<string, number | string | undefined>)[k] ?? '0'
  return Object.fromEntries(
    cot.flatMap(({ sap: k }) =>
      k === undefined
        ? []
        : [
            [
              k,
              (a: T, b: T) => {
                const x = gia(a, k)
                const y = gia(b, k)
                return typeof x === 'number' && typeof y === 'number'
                  ? x - y
                  : soSanhTien(String(x), String(y))
              },
            ],
          ],
    ),
  )
}

// ─── Chiều 1 — «Khoá» (mặc định) ────────────────────────────────────────────

const KHOA_COT: readonly Cot[] = [
  { nhan: 'Khoá', rong: 'w-full' },
  { nhan: 'Người tạo' },
  { nhan: 'Phiên', phai: true, sap: 'so_phien' },
  { nhan: nhanComponent('llm'), phai: true, sap: 'chi_phi_llm' },
  { nhan: nhanComponent('tts'), phai: true, sap: 'chi_phi_tts' },
  { nhan: nhanComponent('stt'), phai: true, sap: 'chi_phi_stt' },
  { nhan: nhanComponent('embed'), phai: true, sap: 'chi_phi_embed' },
  { nhan: nhanComponent('search'), phai: true, sap: 'chi_phi_search' },
  { nhan: nhanComponent('call'), phai: true, sap: 'chi_phi_call' },
  { nhan: nhanComponent('vad'), phai: true, sap: 'chi_phi_vad' },
  { nhan: nhanComponent('speaker_verify'), phai: true, sap: 'chi_phi_speaker_verify' },
  { nhan: 'Tổng chi phí', phai: true, sap: 'chi_phi' },
]

const SAP_KHOA = soSanhTheoCot<DongKey>(KHOA_COT)

function BangTheoKhoa({ from, to }: { readonly from: string; readonly to: string }) {
  const q = useTheoKey(from, to)
  const [sapXep, setSapXep] = useState<SapXep | null>({ cot: 'chi_phi', giam: true })

  if (q.isPending) return <SkeletonBang />
  if (q.error)
    return (
      <VungCuon>
        <div className="p-4">
          <LoiTai viec="lượt dùng theo khoá" thuLai={() => void q.refetch()} />
        </div>
      </VungCuon>
    )

  const { items, chi_phi_tong } = q.data
  const hang = ghimCuoiVaSap(
    items,
    (d) => d.agent_key_id === null || !!d.du_lieu_ngoai,
    sapXep,
    SAP_KHOA,
  )
  // §9.1 phần "đối chiếu": Σ items[].chi_phi CHỈ để so — chi_phi_tong của API
  // mới là số hiện lên hàng Tổng, dù hai số này có lệch hay không.
  const tongTuCong = congTien(items.map((d) => d.chi_phi))
  const lech = soSanhTien(tongTuCong, chi_phi_tong) !== 0

  return (
    <>
      {lech && (
        <div
          role="status"
          className="border-b border-badge-alert-fg/40 bg-badge-alert-bg px-4 py-2.5 text-phu text-badge-alert-fg"
        >
          Cảnh báo: tổng các dòng ({tien(tongTuCong)}) khác Tổng chi phí API trả về (
          {tien(chi_phi_tong)}) — Báo kỹ thuật kiểm tra.
        </div>
      )}
      <VungCuon>
        <Bang nhan="Lượt dùng theo khoá">
          <DauBang cot={KHOA_COT} sapXep={sapXep} doiSap={(c) => setSapXep(doiCotSap(sapXep, c))} />
          <tbody>
            {hang.map((d) =>
              d.du_lieu_ngoai ? (
                <tr
                  key="du-lieu-ngoai"
                  className="border-t border-rule align-top"
                  title={GHI_CHU_DU_LIEU_NGOAI}
                >
                  <td className={TD}>{NHAN_DU_LIEU_NGOAI}</td>
                  <td className={TD_PHU}>—</td>
                  <td className={TD_SO}>—</td>
                  <OCacTienComponent d={d} />
                  <td className={TD_SO}>
                    <OChiPhi chiPhi={d.chi_phi} />
                  </td>
                </tr>
              ) : d.agent_key_id === null ? (
                <tr
                  key="chua-phan-loai"
                  className="border-t border-rule align-top text-muted"
                  title={GHI_CHU_CHUA_PHAN_LOAI}
                >
                  <td className={TD}>{NHAN_CHUA_PHAN_LOAI}</td>
                  <td className={TD}>—</td>
                  <td className={TD_SO}>{SO(d.so_phien)}</td>
                  <OCacTienComponent d={d} />
                  <td className={TD_SO}>
                    <OChiPhi chiPhi={d.chi_phi} />
                  </td>
                </tr>
              ) : (
                <Hang key={d.agent_key_id}>
                  <td className={TD}>
                    <div>{d.label}</div>
                    <div className="font-mono text-phu text-muted">{d.key_prefix}</div>
                    {d.da_thu_hoi && (
                      <span className={`${PILL} mt-1 bg-badge-neutral-bg text-badge-neutral-fg`}>
                        Đã thu hồi
                      </span>
                    )}
                  </td>
                  <td className={TD_PHU}>{hienNguoiTao(d.nguoi_tao_ten, d.nguoi_tao)}</td>
                  <td className={TD_SO}>{SO(d.so_phien)}</td>
                  <OCacTienComponent d={d} />
                  <td className={TD_SO}>
                    <OChiPhi chiPhi={d.chi_phi} />
                  </td>
                </Hang>
              ),
            )}
          </tbody>
          <tfoot>
            {/* `bg-fill` (cùng nền `thead`) đứng ở hàng TỔNG — hàng chốt số của
                cả bảng — chứ không ở hàng «Chưa phân loại» phía trên. Trước đây
                cả hai câu đều gán `bg-fill`, nên mắt đọc "Chưa phân loại" thành
                một hàng có thứ bậc như header trong khi "Tổng kỳ" lại trần. */}
            <tr className="border-t border-rule bg-fill font-semibold">
              {/* 11 = Khoá + Người tạo + Phiên + 8 cột dịch vụ — mọi cột trước
                  «Tổng chi phí». Đổi số cột của KHOA_COT thì đổi số này theo. */}
              <td className={TD} colSpan={11}>
                Tổng kỳ
              </td>
              <td className={TD_SO}>{tien(chi_phi_tong)}</td>
            </tr>
          </tfoot>
        </Bang>
      </VungCuon>
    </>
  )
}

// ─── Chiều 2 — «Người tạo» ──────────────────────────────────────────────────

const OWNER_COT: readonly Cot[] = [
  { nhan: 'Người', rong: 'w-full' },
  { nhan: 'Email' },
  { nhan: 'Số khoá', phai: true, sap: 'so_key' },
  { nhan: 'Phiên', phai: true, sap: 'so_phien' },
  { nhan: nhanComponent('llm'), phai: true, sap: 'chi_phi_llm' },
  { nhan: nhanComponent('tts'), phai: true, sap: 'chi_phi_tts' },
  { nhan: nhanComponent('stt'), phai: true, sap: 'chi_phi_stt' },
  { nhan: nhanComponent('embed'), phai: true, sap: 'chi_phi_embed' },
  { nhan: nhanComponent('search'), phai: true, sap: 'chi_phi_search' },
  { nhan: nhanComponent('call'), phai: true, sap: 'chi_phi_call' },
  { nhan: nhanComponent('vad'), phai: true, sap: 'chi_phi_vad' },
  { nhan: nhanComponent('speaker_verify'), phai: true, sap: 'chi_phi_speaker_verify' },
  { nhan: 'Tổng chi phí', phai: true, sap: 'chi_phi' },
]

const SAP_OWNER = soSanhTheoCot<DongOwner>(OWNER_COT)

function BangTheoNguoiTao({ from, to }: { readonly from: string; readonly to: string }) {
  const q = useTheoOwner(from, to)
  const [sapXep, setSapXep] = useState<SapXep | null>({ cot: 'chi_phi', giam: true })

  if (q.isPending) return <SkeletonBang />
  if (q.error)
    return (
      <VungCuon>
        <div className="p-4">
          <LoiTai viec="lượt dùng theo người tạo" thuLai={() => void q.refetch()} />
        </div>
      </VungCuon>
    )

  const items = q.data
  const hang = ghimCuoiVaSap(
    items,
    (d) => d.user_id === null || !!d.du_lieu_ngoai,
    sapXep,
    SAP_OWNER,
  )
  // KHÔNG có `chi_phi_tong` riêng cho chiều này (`DongOwner[]` trần, xem
  // `kieu.ts`) — hàng Tổng ở đây LÀ tổng tự cộng, không có gì để đối chiếu.
  const tongTuCong = congTien(items.map((d) => d.chi_phi))

  return (
    <VungCuon>
      <Bang nhan="Lượt dùng theo người tạo">
        <DauBang cot={OWNER_COT} sapXep={sapXep} doiSap={(c) => setSapXep(doiCotSap(sapXep, c))} />
        <tbody>
          {hang.map((d) =>
            d.du_lieu_ngoai ? (
              <tr
                key="du-lieu-ngoai"
                className="border-t border-rule align-top"
                title={GHI_CHU_DU_LIEU_NGOAI}
              >
                <td className={TD}>{NHAN_DU_LIEU_NGOAI}</td>
                <td className={TD_PHU}>—</td>
                <td className={TD_SO}>—</td>
                <td className={TD_SO}>—</td>
                <OCacTienComponent d={d} />
                <td className={TD_SO}>
                  <OChiPhi chiPhi={d.chi_phi} />
                </td>
              </tr>
            ) : d.user_id === null ? (
              <tr
                key="chua-phan-loai"
                className="border-t border-rule align-top text-muted"
                title={GHI_CHU_CHUA_PHAN_LOAI}
              >
                <td className={TD}>{NHAN_CHUA_PHAN_LOAI}</td>
                <td className={TD}>—</td>
                <td className={TD_SO}>{SO(d.so_key)}</td>
                <td className={TD_SO}>{SO(d.so_phien)}</td>
                <OCacTienComponent d={d} />
                <td className={TD_SO}>
                  <OChiPhi chiPhi={d.chi_phi} />
                </td>
              </tr>
            ) : (
              <Hang key={d.user_id}>
                <td className={TD}>{d.ten ?? '—'}</td>
                {/* Sans, KHÔNG mono: email là chữ của người, không phải định danh máy. */}
                <td className={TD_PHU}>{rong(d.email)}</td>
                <td className={TD_SO}>{SO(d.so_key)}</td>
                <td className={TD_SO}>{SO(d.so_phien)}</td>
                <OCacTienComponent d={d} />
                <td className={TD_SO}>
                  <OChiPhi chiPhi={d.chi_phi} />
                </td>
              </Hang>
            ),
          )}
        </tbody>
        <tfoot>
          {/* `bg-fill` ở hàng TỔNG, không ở hàng «Chưa phân loại» — cùng lý do
              đã sửa ở `BangTheoKhoa` phía trên (2026-08-26). */}
          <tr className="border-t border-rule bg-fill font-semibold">
            <td className={TD} colSpan={12}>
              Tổng kỳ
            </td>
            <td className={TD_SO}>{tien(tongTuCong)}</td>
          </tr>
        </tfoot>
      </Bang>
    </VungCuon>
  )
}

// ─── Chiều 3 — «Phiên» ──────────────────────────────────────────────────────

const GIOI_HAN_PHIEN = 10

const PHIEN_COT: readonly Cot[] = [
  { nhan: 'Phiên', rong: 'w-full' },
  { nhan: 'Khách' },
  { nhan: 'Kênh' },
  { nhan: 'Bắt đầu', phai: true },
  { nhan: 'Lượt', phai: true },
  { nhan: nhanComponent('llm'), phai: true },
  { nhan: nhanComponent('tts'), phai: true },
  { nhan: nhanComponent('stt'), phai: true },
  { nhan: nhanComponent('embed'), phai: true },
  { nhan: nhanComponent('search'), phai: true },
  { nhan: nhanComponent('call'), phai: true },
  { nhan: nhanComponent('vad'), phai: true },
  { nhan: nhanComponent('speaker_verify'), phai: true },
  { nhan: 'Tổng chi phí', phai: true },
]

/** `bat_dau` là ISO CÓ offset (`2026-08-14T09:12:00+07:00`). Đọc THẲNG từ
 *  chuỗi — không qua `Date`/múi giờ trình duyệt, để giờ hiện luôn khớp giờ BE
 *  đã ghi bất kể máy chạy (test hay người dùng) ở múi giờ nào. */
function hienGio(iso: string | null): string {
  if (!iso) return '—'
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  if (!m) return '—'
  const [, thang, ngay, gio, phut] = m
  return `${ngay}/${thang} ${gio}:${phut}`
}

function HangPhien({
  p,
  moPhien,
}: {
  readonly p: PhienUsage
  /** Không truyền ⇒ hàng KHÔNG bấm được (khuôn cũ Task 5) — giữ lại để test
   *  dựng `BangLuotDung` độc lập không bắt buộc phải khai prop này. */
  readonly moPhien?: ((sessionId: string, el: HTMLElement | null) => void) | undefined
}) {
  // Ref SỐNG Ở ĐÂY (một instance mỗi hàng): dù cú bấm mở tới từ chính nút này
  // hay từ một chỗ khác trong hàng (`Hang mo=`), phần tử trả focus luôn là
  // đúng nút định danh của hàng — không phải toạ độ click.
  const oNutRef = useRef<HTMLButtonElement>(null)
  const mo = moPhien ? () => moPhien(p.session_id, oNutRef.current) : undefined
  return (
    <Hang mo={mo}>
      <td className={TD}>
        {moPhien ? (
          <button
            ref={oNutRef}
            type="button"
            title={p.session_id}
            onClick={() => moPhien(p.session_id, oNutRef.current)}
            className="font-mono text-phu underline-offset-2 hover:underline"
          >
            {p.session_id.slice(0, 12)}
          </button>
        ) : (
          <span className="font-mono text-phu" title={p.session_id}>
            {p.session_id.slice(0, 12)}
          </span>
        )}
      </td>
      <td className={TD_PHU}>{p.customer_name ?? p.phone ?? '—'}</td>
      <td className={TD}>
        <ChipKenh source={p.channel} />
      </td>
      <td className={`${TD_SO} text-phu`}>{hienGio(p.bat_dau)}</td>
      <td className={TD_SO}>{SO(p.so_turn)}</td>
      <OCacTienComponent d={p} />
      <td className={TD_SO}>
        <OChiPhi chiPhi={p.chi_phi} />
        {/* `exact === true` KHÔNG có badge — đúng là mặc định, một pill xanh ở
            mọi hàng là nhiễu và làm hàng `false` khó thấy hơn (ngược mục đích). */}
        {!p.exact && (
          <span
            className={`${PILL} ml-2 bg-badge-warn-bg text-badge-warn-fg`}
            title="Usage đo được KHÔNG đầy đủ cho phiên này — một phần token/giây bị mất do lỗi ghi nhận."
          >
            Đo thiếu
          </span>
        )}
      </td>
    </Hang>
  )
}

function BangTheoPhien({
  from,
  to,
  trang,
  datTrang,
  moPhien,
}: {
  readonly from: string
  readonly to: string
  readonly trang: number
  readonly datTrang: (trang: number) => void
  readonly moPhien?: ((sessionId: string, el: HTMLElement | null) => void) | undefined
}) {
  const offset = (trang - 1) * GIOI_HAN_PHIEN
  const q = usePhien(from, to, GIOI_HAN_PHIEN, offset)

  if (q.isPending) return <SkeletonBang />
  if (q.error)
    return (
      <VungCuon>
        <div className="p-4">
          <LoiTai viec="danh sách phiên" thuLai={() => void q.refetch()} />
        </div>
      </VungCuon>
    )

  const { items, total } = q.data
  const soTrang = Math.max(1, Math.ceil(total / GIOI_HAN_PHIEN))

  return (
    <>
      <VungCuon>
        <Bang nhan="Lượt dùng theo phiên">
          <DauBang cot={PHIEN_COT} />
          <tbody>
            {items.map((p) => (
              <HangPhien key={p.session_id} p={p} moPhien={moPhien} />
            ))}
          </tbody>
        </Bang>
      </VungCuon>
      <ThanhTrang
        trang={trang}
        soTrang={soTrang}
        total={total}
        soHang={GIOI_HAN_PHIEN}
        doiTrang={datTrang}
      />
    </>
  )
}

// ─── Vỏ chung + bộ chuyển «Gộp theo» ────────────────────────────────────────

function SkeletonBang() {
  return (
    <VungCuon>
      <div className="flex flex-col gap-2 p-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-8 animate-pulse rounded-md bg-fill" />
        ))}
      </div>
    </VungCuon>
  )
}

const GOP_TAB: readonly MucTab<UsageTim['gop']>[] = [
  { id: 'khoa', nhan: 'Khoá' },
  { id: 'nguoi', nhan: 'Người tạo' },
  { id: 'phien', nhan: 'Phiên' },
]

export function BangLuotDung({
  tim,
  datTim,
  from,
  to,
  moPhien,
}: {
  readonly tim: UsageTim
  /** CHUNG với `UsageScreen` — xem `routes/_app/billing.tsx`: đổi `gop` (kèm
   *  reset `trang: 1`) là REPLACE, đổi MỘT MÌNH `trang` (phân trang) là PUSH.
   *  Component này không tự quyết push/replace — nó chỉ gọi đúng shape đối
   *  tượng, còn route mẹ đọc shape đó để chọn. */
  readonly datTim: (t: Partial<UsageTim>) => void
  readonly from: string
  readonly to: string
  /** Mở slide-over chi tiết phiên (Task 6) — xem docstring đầu file. Không
   *  truyền ⇒ hàng Phiên tĩnh như Task 5 (dùng cho test dựng bảng độc lập). */
  readonly moPhien?: ((sessionId: string, el: HTMLElement | null) => void) | undefined
}) {
  return (
    <TheBang>
      <ThanhCong>
        <NhomTab
          muc={GOP_TAB}
          dangMo={tim.gop}
          doi={(g) => datTim({ gop: g, trang: 1 })}
          nhan="Gộp theo"
          idPanel="tab-gop-billing"
        />
      </ThanhCong>
      {/* Bọc để làm `tabpanel`: ba bảng là ba component, mỗi cái tự có vùng cuộn +
          chân bảng. `flex-col flex-1` nối tiếp chuỗi flex của `TheBang`. */}
      <div className="flex min-h-0 flex-1 flex-col" {...panelTab('tab-gop-billing', tim.gop)}>
        {tim.gop === 'khoa' && <BangTheoKhoa from={from} to={to} />}
        {tim.gop === 'nguoi' && <BangTheoNguoiTao from={from} to={to} />}
        {tim.gop === 'phien' && (
          <BangTheoPhien
            from={from}
            to={to}
            trang={tim.trang}
            datTrang={(trang) => datTim({ trang })}
            moPhien={moPhien}
          />
        )}
      </div>
    </TheBang>
  )
}
