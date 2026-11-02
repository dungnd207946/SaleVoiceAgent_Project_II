import { createFileRoute } from '@tanstack/react-router'
import { TaiLieuList } from '@/features/kb/components/TaiLieuList'

// Màn thứ ba có nội dung thật. Hai tab Agent đã trích dẫn và Không tìm được
// làm cùng Gói G — chúng đọc dữ liệu mà kb_search phải ghi, và kb_search chạy
// trong tiến trình agent. Xem docstring của TaiLieuList.
export const Route = createFileRoute('/_app/kb')({
  component: TaiLieuList,
})
