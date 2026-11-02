/**
 * Xem bản ĐÃ NẠP của một tài liệu (Task 15) — thứ agent thật sự đọc, KHÔNG
 * phải tệp gốc khách gửi (ảnh trong tệp gốc trỏ S3 của họ, trình duyệt không
 * mở được; bản này đã mirror sang kho của mình).
 */
import { useQuery } from '@tanstack/react-query'
import { noiDungDaNap, type TaiLieu } from '../api'
import { HopThoai } from '@/components/ui/HopThoai'
import { Markdown } from '../markdown'

export function XemNoiDung({ t, onDong }: { t: TaiLieu; onDong: () => void }) {
  const q = useQuery({
    queryKey: ['kb', 'files', t.id, 'noidung'],
    queryFn: () => noiDungDaNap(t.id),
  })

  return (
    // Tự khai trọn className thay vì `KHUNG_HOP_THOAI`: khung này KHÔNG có `p-5` — dải
    // tiêu đề và vùng cuộn tự có đệm, để kẻ dưới tiêu đề chạy hết bề ngang.
    <HopThoai
      onDong={onDong}
      aria-label={`Nội dung đã nạp — ${t.tenFile}`}
      className="m-auto flex max-h-[calc(100dvh-3rem)] w-[calc(100%-3rem)] max-w-[720px] flex-col overflow-hidden rounded-lg border border-border bg-surface p-0 text-fg shadow-hop-thoai backdrop:bg-panel/45"
    >
      <div className="flex items-center justify-between border-b border-border-soft px-5 py-3">
        <h2 className="text-the font-semibold text-fg">{t.tenFile}</h2>
        <button
          type="button"
          className="rounded-md border border-border-field px-3 py-1.5 text-[13px]"
          onClick={onDong}
        >
          Đóng
        </button>
      </div>

      <div className="overflow-y-auto px-5 py-4">
        {q.isPending && <p className="text-[14px] text-muted">Đang tải nội dung…</p>}
        {q.error && <p className="text-[14px]">Không tải được nội dung đã nạp.</p>}
        {q.data && q.data.length === 0 && (
          <p className="text-[14px] text-muted">Tài liệu chưa có đoạn nào.</p>
        )}
        {q.data?.map((doan, i) => {
          // Nhãn mục chỉ hiện khi ĐỔI so với đoạn trước — lặp lại mỗi đoạn là
          // chính thứ scaffolding khiến tài liệu trông vụn ra.
          const tenMucMoi = doan.sectionPath !== (q.data![i - 1]?.sectionPath ?? '')
          return (
            <article
              key={doan.idx}
              data-testid="doan"
              className={i === 0 ? 'pt-0' : 'mt-2 border-t border-border-soft pt-2'}
            >
              <p className="mb-1 flex items-center gap-2 text-nhan text-muted-2">
                <span className="font-mono">#{doan.idx}</span>
                {tenMucMoi && doan.sectionPath && <span>{doan.sectionPath}</span>}
                {doan.overlapsPrev && (
                  <span className="italic">— trùng dòng đầu với đoạn trước (chunker mượn lại)</span>
                )}
              </p>
              <Markdown text={doan.text} />
            </article>
          )
        })}
      </div>
    </HopThoai>
  )
}
