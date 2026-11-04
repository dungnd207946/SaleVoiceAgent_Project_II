/**
 * Màn API Keys (M8) — khoá đấu nối agent.
 *
 * Nav của màn này đã có sẵn ở `features/platform/nav.ts` với
 * `requiredActions: [ACTIONS.WORKSPACE_ADMIN]`. Đó là action thứ 13 của PQ_01, và
 * nhãn của nó trong bảng gốc là "Khoá API · Thành viên · Cài đặt workspace" — nên
 * màn này thuộc đúng nhóm quyền ấy, không phải `agent_config.*` (nhóm 10-12 là
 * cấu hình NỘI DUNG agent, không phải đường đấu nối).
 *
 * ⚠️ FE ẩn nav là tiện mắt (PQ_01 §BR-Q03); BE chặn request là bảo vệ. Ba endpoint
 * `/agent/keys` đều khai `require(ACTIONS.WORKSPACE_ADMIN)` — nên vào đây bằng URL
 * trực tiếp thì bảng trả 403 và khối lỗi dưới đây nói đúng lý do.
 *
 * KHOÁ THÔ KHÔNG VÀO REACT QUERY. `taoKhoa` là mutation; kết quả nằm trong
 * `useState` của component này và bị xoá khi dialog đóng. Query `['agent-keys']`
 * chỉ chứa tiền tố — xem docstring `api.ts`.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bang,
  DauBang,
  Hang,
  NUT_CHINH,
  NutIcon,
  PILL,
  TD,
  TD_PHU,
  ThanhCong,
  TheBang,
  VungCuon,
} from '@/components/ui/Bang'
import { KhoRong } from '@/components/ui/TrangThai'
import { useLang } from '@/i18n'
import { LoiApi } from '@/lib/http'
import {
  DUONG_TAI_LIEU_GATEWAY,
  KHOA_QUERY,
  WS_URL_CHAT_MAC_DINH,
  WS_URL_VOICE_MAC_DINH,
  datTrangThaiKhoa,
  dinhDangLuc,
  nhanDungCuoi,
  taiKhoa,
  taoKhoa,
  xoayKhoa,
} from '../api'
import type { Khoa, KhoaDaTao, TrangThaiKhoa } from '../api'
import { XacNhan } from '@/components/ui/XacNhan'
import { useSaoChep } from '@/lib/saoChep'
import { KhoaMoiDialog } from './KhoaMoiDialog'
import { TaoKhoaDialog } from './TaoKhoaDialog'

/**
 * Thẻ thông tin + tiêu đề TRONG thẻ — cùng khuôn `HoSoScreen`/`CaiDatWorkspace`
 * (hai màn anh em gần nhất, cùng chép từ `NhomTruong`). Không import từ đó:
 * Luật 3 (`tests/module-boundaries.test.ts`) cấm `platform` lấy ruột `auth`.
 * 15px cho tiêu đề thẻ thông tin; 16px là của đầu bảng (`ThanhCong`) ngay dưới.
 */
const THE = 'rounded-xl border border-border bg-surface p-5'
const TIEU_DE_THE = 'mb-4 text-the font-semibold text-fg'
/** Lưới nhãn-trên-giá-trị của thẻ thông tin — cùng số đo `LUOI` của `HoSoScreen`. */
const LUOI = 'grid gap-x-6 gap-y-4 md:grid-cols-2'
/** Nhãn ô — cùng số đo `NHAN` của `HoSoScreen`/`CaiDatWorkspace`. */
const NHAN = 'mb-1.5 block text-phu text-muted'
/** Ô giá trị mono — chép nguyên `O` của `realestate/components/OToken.tsx`. */
const O_GIA_TRI =
  'flex min-w-0 flex-1 items-center rounded-md border border-border-field bg-surface px-3 py-2 font-mono text-phu leading-[1.5]'

/**
 * Một WS URL trên thẻ thông tin: nhãn xám → ô giá trị mono + `NutIcon` copy
 * đứng NGOÀI ô — đúng khuôn `OToken` (token đẩy dữ liệu ở `/projects`), tức
 * pattern «giá trị để copy» sẵn có của các màn danh sách.
 *
 * KHÔNG CÒN CHÉP `HangGiaTri` của `KhoaMoiDialog` (sửa 2026-08-25, người dùng
 * chê «khác hẳn concept portal»). Khuôn đó — nhãn mono in đậm, ô `rounded-xl`
 * nền `fill`, nút copy vuông riêng, dòng biên nhận giữ chỗ 17px — được chốt cho
 * MỘT hộp thoại hiện bí mật một lần, nơi mọi thứ phải to và chậm. Đặt nó lên
 * thẻ thường thì nó là ô nhập lạc giữa các thẻ thông tin, và nút copy của nó
 * không giống nút `power` ở bảng ngay dưới dù cùng một vai (icon vuông 28px).
 *
 * Biên nhận copy đi vào `nhan` của `NutIcon` (title + aria-label đổi thành «Đã
 * copy …») như `OToken`/`ChiTietPhien`; chỉ LỖI copy mới hiện thành chữ, và chỉ
 * khi xảy ra — không giữ chỗ trống. Hai URL không phải bí mật chỉ-hiện-một-lần
 * nên cũng không có khái niệm «đã lưu» để gắn vào cú copy.
 */
function HangUrl({
  nhan,
  giaTri,
  testid,
  nhanCopy,
  nhanDaCopy,
}: {
  nhan: string
  giaTri: string
  testid: string
  nhanCopy: string
  nhanDaCopy: string
}) {
  const { t } = useLang()
  const { daCopy, loiCopy, copy } = useSaoChep()

  return (
    <div>
      <dt className={NHAN}>{nhan}</dt>
      <dd className="flex items-center gap-1.5">
        {/* `select-all`: một cú click chọn trọn chuỗi — cùng lý lẽ `HangGiaTri`. */}
        <span className={O_GIA_TRI}>
          <code data-testid={testid} className="min-w-0 truncate select-all text-fg">
            {giaTri}
          </code>
        </span>
        <NutIcon
          icon={daCopy ? 'check' : 'copy'}
          nhan={daCopy ? nhanDaCopy : nhanCopy}
          onClick={() => void copy(giaTri)}
        />
      </dd>
      {loiCopy && (
        <p role="alert" className="mt-1 text-[12px] text-badge-alert-fg">
          {t({
            vi: 'Trình duyệt không cho copy. Bôi đen giá trị ở trên rồi Ctrl+C.',
            en: 'Browser blocked copying. Select the value above and press Ctrl+C.',
          })}
        </p>
      )}
    </div>
  )
}

/**
 * Ô khoá trong bảng danh sách — che sẵn, mắt mở TẠI CHỖ (không dialog, không
 * cú bấm thứ hai). Khoá tạo TRƯỚC migration `0918` không có bản thô
 * (`api_key: null`, xem docstring `Khoa` ở `api.ts`) — không có gì để mở nên
 * những hàng đó giữ nguyên tiền tố cũ, không có nút mắt.
 *
 * Số chấm che BẰNG ĐÚNG độ dài khoá thật (khác `OToken` — chọn có chủ ý,
 * ngược lại): cột này nằm trong một BẢNG, và số chấm cố định làm bề rộng cột
 * nhảy giữa hai trạng thái ẩn/hiện (cột tự co theo nội dung dài nhất) — bấm
 * mắt ở một hàng kéo giãn/co hẹp cả cột, xô lệch mọi hàng khác. `OToken` đứng
 * một mình trong một ô giá trị có bề rộng cố định nên không gặp vấn đề này.
 */
function OKhoaBang({ khoa }: { readonly khoa: Khoa }) {
  const { t } = useLang()
  const [hien, setHien] = useState(false)
  const { daCopy, loiCopy, copy } = useSaoChep()

  if (khoa.api_key === null) {
    return <span>{khoa.key_prefix}…</span>
  }

  // Chép vào biến cục bộ: TS không giữ được thu hẹp `!== null` của
  // `khoa.api_key` xuyên qua closure `onClick` bên dưới.
  const apiKey = khoa.api_key
  const moTa = khoa.label || khoa.key_prefix

  return (
    <div>
      <div className="flex items-center gap-1.5">
        <span className={`whitespace-nowrap ${hien ? 'text-fg' : ''}`}>
          {hien ? apiKey : '•'.repeat(apiKey.length)}
        </span>
        <NutIcon
          icon={hien ? 'cheBiMat' : 'hienBiMat'}
          nhan={
            hien
              ? t({ vi: `Che khoá ${moTa}`, en: `Hide key ${moTa}` })
              : t({ vi: `Hiện khoá ${moTa}`, en: `Show key ${moTa}` })
          }
          onClick={() => setHien((v) => !v)}
        />
        <NutIcon
          icon={daCopy ? 'check' : 'copy'}
          nhan={
            daCopy
              ? t({ vi: `Đã copy khoá ${moTa}`, en: `Key ${moTa} copied` })
              : t({ vi: `Copy khoá ${moTa}`, en: `Copy key ${moTa}` })
          }
          onClick={() => void copy(apiKey)}
        />
      </div>
      {loiCopy && (
        <p role="alert" className="mt-1 text-[12px] text-badge-alert-fg">
          {t({
            vi: 'Trình duyệt không cho copy. Bấm con mắt rồi bôi đen chuỗi.',
            en: 'Browser blocked copying. Click the eye then select the value.',
          })}
        </p>
      )}
    </div>
  )
}

/**
 * Khung ngoài của màn. Layout `_app` CỐ Ý không pad (`<main>` chỉ có overflow) —
 * mỗi màn tự pad, và `px-7 py-6` là số đo chung của các màn thật (`DuAnList:76`,
 * `UserAdmin:112`). Thiếu class này là nội dung dán sát topbar/sidebar — đã xảy
 * ra với chính màn này ở bản đầu.
 */
const KHUNG_MAN = 'px-7 py-6 max-md:px-4 max-md:py-4'

/** Tiền tố + nhãn của khoá đang hỏi — người bấm phải chắc là đúng khoá. */
function TienToKhoa({ khoa }: { readonly khoa: Khoa }) {
  return (
    <p className="rounded-lg border border-border-field bg-fill px-3 py-2 font-mono text-phu text-fg">
      {khoa.key_prefix}…
      {khoa.label && <span className="ml-2 font-sans text-muted">· {khoa.label}</span>}
    </p>
  )
}

function thongDiep(err: unknown, macDinh: string): string {
  if (err instanceof LoiApi) return err.message
  return err instanceof Error ? err.message : macDinh
}

export function TichHopApiScreen() {
  const { t } = useLang()
  const qc = useQueryClient()

  // Khoá thô vừa tạo. `null` = không có dialog nào mở. Sống ĐÚNG ở đây và không
  // đi đâu khác — không cache, không localStorage, không URL.
  const [khoaMoi, setKhoaMoi] = useState<KhoaDaTao | null>(null)
  const [moTao, setMoTao] = useState(false)
  const [dinhThuHoi, setDinhThuHoi] = useState<Khoa | null>(null)
  const [dinhXoay, setDinhXoay] = useState<Khoa | null>(null)

  const { data, error, isPending, refetch } = useQuery({
    queryKey: KHOA_QUERY,
    queryFn: taiKhoa,
  })

  const mTao = useMutation({
    mutationFn: taoKhoa,
    onSuccess: (k) => {
      // Đóng dialog nhãn TRƯỚC, mở dialog khoá SAU — hai dialog không được cùng
      // hiện, cả hai đều `z-70` và cái sau sẽ nằm chồng lên cái trước.
      setMoTao(false)
      setKhoaMoi(k)
      void qc.invalidateQueries({ queryKey: KHOA_QUERY })
    },
  })

  const mDatTrangThai = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TrangThaiKhoa }) =>
      datTrangThaiKhoa(id, status),
    onSuccess: () => {
      setDinhThuHoi(null)
      void qc.invalidateQueries({ queryKey: KHOA_QUERY })
    },
  })

  const mXoay = useMutation({
    mutationFn: xoayKhoa,
    onSuccess: (k) => {
      // Cùng thứ tự với `mTao`: đóng dialog xác nhận TRƯỚC, mở dialog khoá mới
      // SAU — hai dialog `z-70` không được cùng hiện.
      setDinhXoay(null)
      setKhoaMoi(k)
      void qc.invalidateQueries({ queryKey: KHOA_QUERY })
    },
  })

  const COT = [
    { nhan: t({ vi: 'Nhãn', en: 'Label' }) },
    { nhan: t({ vi: 'Khoá', en: 'Key' }) },
    { nhan: t({ vi: 'Trạng thái', en: 'Status' }) },
    { nhan: t({ vi: 'Tạo lúc', en: 'Created' }) },
    { nhan: t({ vi: 'Dùng cuối', en: 'Last used' }) },
    { nhan: '', phai: true },
  ] as const

  // CỐ Ý KHÔNG có `<h1>`: `Topbar.tsx:43` đã render một `<h1>` từ nhãn nav
  // (API Keys), và comment ở đó ghi "mỗi màn phải có đúng một tiêu đề
  // cấp". Thêm `<h1>` nữa ở đây là hai tiêu đề cấp một cho một màn — đúng lỗi đã
  // được sửa một lần cho `UserAdmin` (xem boot.test.tsx, mục `users`).
  //
  // CŨNG KHÔNG CÒN CÂU MÔ TẢ dưới tiêu đề (người dùng chốt 2026-08-08). Nó từng
  // là «Đường đấu nối giữa workspace này và pod agent bên ngoài.» và đứng ở cả
  // ba nhánh (đang tải · lỗi · bình thường). Hai thẻ bên dưới đã tự giới thiệu
  // mình, và ghi chú của thẻ endpoint vẫn nói đúng phần «pod agent của workspace
  // bạn» — nên câu này chỉ còn là một dòng xám lơ lửng trên nền trang.

  if (isPending)
    return (
      <div className={KHUNG_MAN}>
        <p className="rounded-xl border border-border bg-surface p-5 text-[14px] text-muted">
          {t({ vi: 'Đang tải…', en: 'Loading…' })}
        </p>
      </div>
    )

  if (error) {
    // Hai nguyên nhân, hai câu. Backend chết mà UI báo "không có quyền" thì người
    // dùng đi xin quyền và không ai báo sự cố — cùng lý lẽ `MemberList.tsx:88`.
    const khongCoQuyen = error instanceof LoiApi && error.code === 'FORBIDDEN'
    return (
      <div className={KHUNG_MAN}>
        <div
          role="alert"
          className="rounded-xl border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px] text-badge-alert-fg"
        >
          <p>
            {khongCoQuyen
              ? t({
                  vi: 'Bạn không có quyền quản lý khoá đấu nối của workspace này.',
                  en: 'You do not have permission to manage connection keys for this workspace.',
                })
              : t({
                  vi: `Không tải được danh sách khoá: ${error.message}`,
                  en: `Could not load keys: ${error.message}`,
                })}
          </p>
          {!khongCoQuyen && (
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-2 rounded border border-border-field px-3 py-1.5 text-[14px]"
            >
              {t({ vi: 'Thử lại', en: 'Retry' })}
            </button>
          )}
        </div>
      </div>
    )
  }

  const bayGio = new Date()

  return (
    <div className={KHUNG_MAN}>
      {/* HAI THẺ (khôi phục 2026-08-25): thẻ WS Gateway ở trên + thẻ bảng khoá
          ở dưới, đúng vị trí thẻ endpoint từng đứng trước khi bị bỏ 2026-08-20
          — chỉ khác là lần này hiện hai hằng ĐÚNG (`WS_URL_CHAT_MAC_DINH`/
          `WS_URL_VOICE_MAC_DINH`, domain gateway chung) thay vì model
          subdomain-mỗi-tenant đã lỗi thời của trường `endpoint_*_url`. */}
      <div className="space-y-3.5">
        <section className={THE}>
          <h2 className={TIEU_DE_THE}>
            {t({ vi: 'Kết nối WS Gateway', en: 'WS Gateway connection' })}
          </h2>
          {/* Hai URL xếp CẠNH NHAU, nhãn trên giá trị — lưới của mọi thẻ thông
              tin (`HoSoScreen`, bản tóm tắt `/agent`). Xếp chồng thì mỗi ô mono
              35 ký tự (~265px) kéo dài trọn bề rộng thẻ, và thẻ cao gấp đôi cho
              đúng hai dòng dữ liệu. */}
          <dl className={LUOI}>
            <HangUrl
              nhan={t({ vi: 'WS URL chat', en: 'Chat WS URL' })}
              giaTri={WS_URL_CHAT_MAC_DINH}
              testid="gia-tri-ws-chat-list"
              nhanCopy={t({ vi: 'Copy WS URL chat', en: 'Copy chat WS URL' })}
              nhanDaCopy={t({ vi: 'Đã copy WS URL chat', en: 'Chat WS URL copied' })}
            />
            <HangUrl
              nhan={t({ vi: 'WS URL voice', en: 'Voice WS URL' })}
              giaTri={WS_URL_VOICE_MAC_DINH}
              testid="gia-tri-ws-voice-list"
              nhanCopy={t({ vi: 'Copy WS URL voice', en: 'Copy voice WS URL' })}
              nhanDaCopy={t({ vi: 'Đã copy WS URL voice', en: 'Voice WS URL copied' })}
            />
          </dl>

          {/* Cùng khuôn link «Tài liệu API» của tab Nguồn dữ liệu: gạch ngăn mảnh
              rồi một link chữ, không phải nút — nó dẫn ra ngoài, không làm gì. */}
          <div className="mt-4 border-t border-border-soft pt-3">
            <a
              href={DUONG_TAI_LIEU_GATEWAY}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="link-tai-lieu-gateway"
              className="text-[13px] font-medium text-ac hover:underline"
            >
              {t({ vi: 'Tài liệu API', en: 'API reference' })}
            </a>
          </div>
        </section>

        {/* ── Khoá ─────────────────────────────────────────────────────────
              TIÊU ĐỀ VÀ NÚT NẰM TRONG THẺ, trên dải `ThanhCong` — cùng khuôn với
              `/projects`, `/users`, `/kb`. Trước 2026-08-08 chúng đứng trần trên
              nền trang phía trên thẻ, nên đọc từ trên xuống là: thẻ (endpoint) →
              chữ trần → thẻ (bảng khoá), ba hình dạng cho hai khối nội dung.

              Đoạn «Mỗi khoá cho phép một pod xác thực… Khoá chỉ hiện một lần lúc
              tạo.» ĐÃ BỎ: vế đầu nhắc lại chính tiêu đề, vế sau là bản sao của
              `TaoKhoaDialog` (nói lúc sắp tạo) và `KhoaMoiDialog` (nói lúc khoá
              đang hiện). Cả hai chỗ kia đều đúng thời điểm hơn một câu đọc lúc
              không tạo khoá. */}
        <TheBang>
          <ThanhCong>
            <h2 className="mr-auto text-muc font-semibold text-fg">
              {t({ vi: 'Khoá đấu nối agent', en: 'Agent connection keys' })}
            </h2>
            <button
              type="button"
              onClick={() => {
                mTao.reset()
                setMoTao(true)
              }}
              className={`${NUT_CHINH} flex-none`}
            >
              {t({ vi: 'Tạo khoá mới', en: 'Create key' })}
            </button>
          </ThanhCong>

          {data.keys.length === 0 ? (
            // Kho rỗng NẰM TRONG thẻ, cùng lối `TaiLieuList`. Không kèm nút hành
            // động: «Tạo khoá mới» đã đứng ngay trên nó, cách vài chục pixel.
            <div className="p-4">
              <KhoRong
                tieuDe={t({
                  vi: 'Chưa có khoá đấu nối nào.',
                  en: 'No connection keys yet.',
                })}
                // «hai ENDPOINT_URL ở trên» đã bỏ khỏi câu này: hai khối đó rời màn
                // từ 2026-08-20, nên chữ «ở trên» trỏ vào hư không — và từ 2026-08-21
                // khối env lúc tạo khoá cũng không còn mang chúng.
                huongDan={t({
                  vi: 'Tạo một khoá rồi gửi cho bên agent.',
                  en: 'Create a key and send it to the agent team.',
                })}
              />
            </div>
          ) : (
            <VungCuon>
              <Bang>
                <DauBang cot={COT} />
                <tbody>
                  {data.keys.map((k) => (
                    <Hang key={k.id}>
                      <td className={`${TD} font-semibold text-fg`}>
                        {k.label || <span className="font-normal text-muted-3">—</span>}
                      </td>
                      <td className={`${TD} font-mono text-phu text-muted-2`}>
                        <OKhoaBang khoa={k} />
                      </td>
                      <td className={TD}>
                        {/* Khoá tắt tô TRUNG TÍNH, không tô đỏ: nó là trạng thái
                              nghỉ do người dùng chủ động đặt, không phải sự cố.
                              Cùng lối `MAU_TRANG_THAI` của M6 đã chọn. */}
                        <span
                          className={`${PILL} ${
                            k.status === 'active'
                              ? 'bg-acs text-ac'
                              : 'bg-badge-neutral-bg text-badge-neutral-fg'
                          }`}
                        >
                          {k.status === 'active'
                            ? t({ vi: 'Đang dùng', en: 'Active' })
                            : t({ vi: 'Đã tắt', en: 'Inactive' })}
                        </span>
                      </td>
                      <td className={TD_PHU}>{dinhDangLuc(k.created_at)}</td>
                      <td className={TD_PHU}>
                        {nhanDungCuoi(
                          k.last_used_at,
                          bayGio,
                          t({ vi: 'Chưa dùng', en: 'Never used' }),
                        )}
                      </td>
                      <td className={`${TD} text-right`}>
                        <div className="flex items-center justify-end gap-1">
                          {/* Xoay có mặt ở CẢ HAI trạng thái — phát khoá mới không
                              phụ thuộc khoá cũ còn bật hay đã tắt. */}
                          <NutIcon
                            icon="xoay"
                            nhan={t({ vi: 'Xoay khoá', en: 'Rotate key' })}
                            onClick={() => {
                              mXoay.reset()
                              setDinhXoay(k)
                            }}
                          />
                          {k.status === 'active' ? (
                            <NutIcon
                              icon="power"
                              nhan={t({ vi: 'Tắt khoá', en: 'Deactivate key' })}
                              phaHuy
                              onClick={() => {
                                mDatTrangThai.reset()
                                setDinhThuHoi(k)
                              }}
                            />
                          ) : (
                            /* Bật lại KHÔNG hỏi xác nhận: nó không phá gì, và
                                 chính nó là chiều hoàn tác của việc tắt. Bắt xác
                                 nhận cả hai chiều là bắt người dùng trả giá hai lần
                                 cho một quyết định họ đã sửa. */
                            <NutIcon
                              icon="power"
                              nhan={t({ vi: 'Bật lại khoá', en: 'Reactivate key' })}
                              disabled={mDatTrangThai.isPending}
                              onClick={() => mDatTrangThai.mutate({ id: k.id, status: 'active' })}
                            />
                          )}
                        </div>
                      </td>
                    </Hang>
                  ))}
                </tbody>
              </Bang>
            </VungCuon>
          )}
        </TheBang>
        {/* KHÔNG có link sang `/thu-agent` ở đây, dù người vừa tạo khoá xong
            thường muốn đi thử ngay. Lý do là một ràng buộc thật chứ không phải
            quên: `tests/khoa-dau-noi.test.tsx` dựng màn này KHÔNG có
            `RouterProvider` (nó chỉ cần bảng khoá), nên một `<Link>` ở đây làm
            đổ cả 12 bài của tệp đó. Đường vào màn thử là mục «Thử agent» trong
            menu — đủ dùng. Muốn thêm link thì phải dựng router cho tệp test kia
            trước, và đó là việc riêng. */}
      </div>

      {moTao && (
        <TaoKhoaDialog
          dangGui={mTao.isPending}
          loi={
            mTao.error
              ? thongDiep(mTao.error, t({ vi: 'Không tạo được khoá', en: 'Could not create key' }))
              : null
          }
          onDong={() => setMoTao(false)}
          onTao={(label) => mTao.mutate(label)}
        />
      )}

      {khoaMoi && <KhoaMoiDialog khoa={khoaMoi} onDong={() => setKhoaMoi(null)} />}

      {/* TẮT chứ không XOÁ: backend không bao giờ xoá hàng khoá — gateway cần thấy
          `active=false` để vô hiệu bản cache. Hỏi lại dù hoàn tác được vì hậu quả nằm ở
          pod người bấm không thấy; câu chữ nói đúng lúc pod đứt (hết TTL, không ngay). */}
      {dinhThuHoi && (
        <XacNhan
          tieuDe={t({ vi: 'Tắt khoá này?', en: 'Deactivate this key?' })}
          nutPhu={t({ vi: 'Huỷ', en: 'Cancel' })}
          nutChinh={
            mDatTrangThai.isPending
              ? t({ vi: 'Đang tắt…', en: 'Deactivating…' })
              : t({ vi: 'Tắt khoá', en: 'Deactivate key' })
          }
          phaHuy
          dangGui={mDatTrangThai.isPending}
          loi={
            mDatTrangThai.error
              ? thongDiep(
                  mDatTrangThai.error,
                  t({ vi: 'Không tắt được khoá', en: 'Could not deactivate key' }),
                )
              : null
          }
          onHuy={() => setDinhThuHoi(null)}
          onDongY={() => mDatTrangThai.mutate({ id: dinhThuHoi.id, status: 'inactive' })}
        >
          <TienToKhoa khoa={dinhThuHoi} />
          <p>
            {t({
              vi: 'Khoá ở lại trong danh sách với trạng thái Đã tắt, và bật lại được bất cứ lúc nào. Pod đang dùng khoá này KHÔNG đứt ngay: credential nó đã lấy vẫn sống tới hết chu kỳ TTL (khoảng 1 giờ), nó mất kết nối ở lần làm mới kế tiếp.',
              en: 'The key stays in the list marked Inactive, and you can reactivate it at any time. A pod using this key will NOT disconnect immediately: the credentials it already fetched stay valid until its TTL expires (about 1 hour), and it loses access at the next refresh.',
            })}
          </p>
        </XacNhan>
      )}

      {/* Xoay = khoá MỚI cùng nhãn + tắt khoá cũ trong một lượt; xong thì `KhoaMoiDialog`. */}
      {dinhXoay && (
        <XacNhan
          tieuDe={t({ vi: 'Xoay khoá này?', en: 'Rotate this key?' })}
          nutPhu={t({ vi: 'Huỷ', en: 'Cancel' })}
          nutChinh={
            mXoay.isPending
              ? t({ vi: 'Đang xoay…', en: 'Rotating…' })
              : t({ vi: 'Xoay khoá', en: 'Rotate key' })
          }
          dangGui={mXoay.isPending}
          loi={
            mXoay.error
              ? thongDiep(
                  mXoay.error,
                  t({ vi: 'Không xoay được khoá', en: 'Could not rotate key' }),
                )
              : null
          }
          onHuy={() => setDinhXoay(null)}
          onDongY={() => mXoay.mutate(dinhXoay.id)}
        >
          <TienToKhoa khoa={dinhXoay} />
          <p>
            {t({
              vi: 'Portal phát một khoá mới cùng tên và tắt khoá này. Mọi hệ thống đang dùng khoá này phải đổi sang khoá mới. Không hoàn tác được.',
              en: 'The portal issues a new key with the same name and turns this one off. Every system using this key must switch to the new one. This cannot be undone.',
            })}
          </p>
        </XacNhan>
      )}
    </div>
  )
}
