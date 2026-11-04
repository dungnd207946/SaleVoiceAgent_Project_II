/**
 * Màn «Quản lý lĩnh vực» (`/domains`) — bật/tắt từng lĩnh vực của agent.
 *
 * TẮT LÀ TẮT THẬT, và màn này phải nói ra hết cả hai hệ quả trước khi người
 * dùng bấm:
 *   ① khối lĩnh vực biến mất khỏi panel Agent (Kiến thức + Kỹ năng của nó)
 *   ② kỹ năng của nó KHÔNG vào payload gửi agent nữa — khách hỏi về lĩnh vực
 *      đó thì agent không trả lời được
 *
 * Hệ quả ② chỉ có hiệu lực SAU lần «Lưu và áp dụng» kế tiếp: nó được lọc lúc
 * xuất bản (`useBanNhap.ts`), không lúc bấm công tắc. Nói rõ điều đó trên màn —
 * một công tắc trông như tức thời mà thật ra chờ một hành động khác ở màn khác
 * là đúng loại hứa hẹn sai mà AG_01 §BR09 cấm.
 *
 * KHÔNG có thêm/xoá lĩnh vực. Sổ lĩnh vực hôm nay là hai hằng số của sản phẩm
 * (vertical #1 đã có, #2 chưa), không phải thứ tenant tự đẻ ra — và một nút
 * «Thêm lĩnh vực» sẽ hứa rằng thêm xong là agent biết làm gì đó, trong khi kỹ
 * năng và dữ liệu của một vertical mới là việc của backend.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { docLinhVuc, datLinhVuc, type LinhVuc } from '../linhVuc'
import { Canh } from './form'

function CongTac({
  bat,
  nhan,
  dangGui,
  doi,
}: {
  bat: boolean
  nhan: string
  dangGui: boolean
  doi: (v: boolean) => void
}) {
  return (
    <label className="flex flex-none cursor-pointer items-center gap-2.5">
      <input
        type="checkbox"
        role="switch"
        checked={bat}
        disabled={dangGui}
        aria-label={nhan}
        onChange={(e) => doi(e.target.checked)}
        className="peer sr-only"
      />
      {/* Rãnh + núm. `peer-focus-visible` vẽ vòng focus vì input thật là
          `sr-only` — không có nó thì bàn phím đi tới đây là mất dấu.

          NÚM LÀ `after:` CỦA RÃNH, KHÔNG PHẢI MỘT `<span>` CON. Bản trước lồng
          núm vào trong rãnh rồi gắn `peer-checked:translate-x-4` lên nó — mà
          `peer-*` biên dịch ra `.peer:checked ~ .x`, tức một selector ANH EM.
          Núm lồng bên trong là con của anh em, không phải anh em, nên luật đó
          không bao giờ khớp: đo mép trái núm so với mép trái rãnh ra +3px ở CẢ
          HAI trạng thái — núm đứng yên trong khi rãnh đã xanh. Chữ «BẬT»/«TẮT»
          cạnh công tắc đang che đúng lỗi này; bỏ chữ đi là nó lộ ra.

          ⚠ Đo bằng HÌNH HỌC (`getBoundingClientRect`), đừng đọc `transform`:
          Tailwind v4 sinh ra thuộc tính `translate` chứ không phải `transform`,
          nên `transform` trả về `none` kể cả khi công tắc đang chạy đúng — đọc
          nhầm chỗ đó là kết luận cả `/ky-nang-bds` cũng hỏng, trong khi nó chạy.

          Cách viết dưới đây là cách `CongTacKyNang` đã dùng và chạy đúng: rãnh
          LÀ anh em của input, nên `peer-checked:after:` khớp. Đo lại sau khi
          sửa: `translate` = 16px khi bật, `none` khi tắt. */}
      <span className="relative h-[22px] w-[38px] flex-none rounded-full bg-border-field transition-colors peer-checked:bg-ac peer-disabled:opacity-50 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ac after:absolute after:left-[3px] after:top-[3px] after:size-4 after:rounded-full after:bg-surface after:transition-transform peer-checked:after:translate-x-4" />
      {/* KHÔNG có chữ «BẬT»/«TẮT» cạnh công tắc (2026-08-08). Chín công tắc kỹ
          năng ở `/ky-nang-bds` — cùng hình dạng 38px, cùng vai trò — không có
          chữ nào, nên hai màn cạnh nhau trong cùng một menu đang dùng hai kiểu
          công tắc. Trạng thái đã nói bằng vị trí núm và màu rãnh; trình đọc màn
          hình đọc `role="switch"` + `aria-label` nên nó cũng không phải chỗ chữ
          đó gánh việc. */}
    </label>
  )
}

function Hang({ lv, dangGui, doi }: { lv: LinhVuc; dangGui: boolean; doi: (v: boolean) => void }) {
  return (
    <div className="flex items-center gap-4 border-b border-rule px-5 py-4 last:border-b-0">
      <div className="min-w-0 flex-1">
        <p className="text-noi font-semibold">{lv.ten}</p>
        <p className="mt-[3px] text-phu text-muted-2">
          {/* Con số dùng font mono — luật của portal cho MỌI con số. */}
          <span>
            <span className="font-mono">{lv.soKyNang}</span> kỹ năng
          </span>
          {' · '}
          {/* Trạng thái dữ liệu trong `<span>` RIÊNG: nó là một mệnh đề trọn
              vẹn, và gói riêng thì nó cũng thành thứ truy vấn được bằng đúng
              câu chữ người dùng đọc — trộn vào cùng text node với số kỹ năng
              thì mọi truy vấn phải khớp cả cụm "9 kỹ năng · …". */}
          <span>{lv.coDuLieu ? 'đã có dữ liệu' : 'chưa có dữ liệu để agent tra'}</span>
        </p>
      </div>
      <CongTac bat={lv.bat} nhan={lv.ten} dangGui={dangGui} doi={doi} />
    </div>
  )
}

export function QuanLyLinhVuc() {
  const qc = useQueryClient()
  const ds = useQuery({ queryKey: ['linh-vuc'], queryFn: docLinhVuc })

  const mDoi = useMutation({
    mutationFn: ({ ma, bat }: { ma: string; bat: boolean }) => datLinhVuc(ma, bat),
    // Nạp lại CẢ danh sách chứ không vá một hàng: `useNavGroups` đọc đúng khoá
    // query này để dựng khối lĩnh vực trong panel, nên panel phải đổi theo ngay
    // trong cùng nhịp — người dùng tắt một lĩnh vực và thấy khối của nó biến
    // mất là lời xác nhận rõ nhất rằng công tắc có tác dụng.
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['linh-vuc'] }),
  })

  if (ds.isPending)
    return <p className="px-7 pt-[26px] text-[14px] text-muted max-md:px-4">Đang tải…</p>
  if (ds.error)
    return (
      <p className="px-7 pt-[26px] text-[14px] max-md:px-4">Không đọc được danh sách lĩnh vực.</p>
    )

  const soBat = (ds.data ?? []).filter((l) => l.bat).length

  return (
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      {/* ⚠ KHÔNG CÒN DẢI CẢNH BÁO ĐỘ TRỄ (người dùng chốt 2026-08-09).
          Nó nói: menu đổi ngay, còn phần agent chỉ đổi sau lần «Lưu và áp dụng»
          kế tiếp ở màn Cấu hình chung.

          ĐIỀU ĐÓ VẪN ĐÚNG TRONG CODE — kỹ năng của lĩnh vực đang tắt bị lọc lúc
          XUẤT BẢN (`useBanNhap.ts`), không lúc bấm công tắc. Nay màn không nói
          ra nữa, nên người dùng tắt một lĩnh vực rồi hỏi thử agent vẫn thấy nó
          trả lời, và không có gì trên màn giải thích vì sao. Đây là chỗ AG_01
          §BR09 («nói THẬT trạng thái áp dụng») không còn được giao diện gánh —
          ghi lại để ai gặp báo lỗi «tắt rồi mà agent vẫn trả lời» biết đó không
          phải bug của công tắc. Bài test canh câu này đã xoá cùng lúc. */}
      {soBat === 0 && (
        <Canh mau="alert">
          Không lĩnh vực nào đang bật — agent chỉ còn ba kỹ năng chung, không tra được dữ liệu
          nghiệp vụ nào.
        </Canh>
      )}

      <div className="mt-3.5 overflow-hidden rounded-lg border border-border bg-surface">
        {(ds.data ?? []).map((lv) => (
          <Hang
            key={lv.ma}
            lv={lv}
            dangGui={mDoi.isPending}
            doi={(bat) => mDoi.mutate({ ma: lv.ma, bat })}
          />
        ))}
      </div>

      {/* `role="alert"` ở vỏ chứ không trong `Canh`: `Canh` cũng dùng cho cảnh báo
          TĨNH (ER_03) — gắn alert vào đó là đọc to mọi cảnh báo lúc màn mở. */}
      <div role="alert">
        {mDoi.error && (
          <Canh mau="alert">Chưa đổi được — trạng thái giữ nguyên, thử lại lần nữa.</Canh>
        )}
      </div>
    </div>
  )
}
