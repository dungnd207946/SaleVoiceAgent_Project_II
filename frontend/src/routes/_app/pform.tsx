import { createFileRoute } from '@tanstack/react-router'
import { DuAnForm } from '@/features/realestate/components/DuAnForm'
import { tabHopLe, type TenTabDuAn } from '@/features/realestate/tabDuAn'

/**
 * Màn `pform` — form dự án (M4). `?code=VHOP2` mở dự án đó; không có `code` là
 * tạo mới. `?tab=quy-can` mở sẵn một tab con (`can` là id cũ, còn sống làm alias).
 *
 * VÌ SAO TAB NẰM TRONG URL, không phải `useState`: màn một căn (`/uform`) là một
 * route KHÁC, nên quay về `/pform` mà không mang theo tab thì người dùng bị đẩy
 * về Tổng quan và phải tự bấm lại Căn — mỗi lần sửa một căn. Cho tab vào
 * search param thì đường về trả đúng chỗ vừa rời đi, đồng thời Back/Forward của
 * trình duyệt và một link gửi cho đồng nghiệp cũng mở đúng tab.
 *
 * `validateSearch` phải LÀM SẠCH, không được ném lỗi: `?code=` (rỗng),
 * `?code[]=x` (mảng, do ai đó sửa URL) hay `?tab=xyz` đều là thứ trình duyệt gửi
 * tới được. Ném lỗi ở đây làm cả màn không render và người dùng thấy trang trắng
 * thay vì form tạo mới.
 */
export const Route = createFileRoute('/_app/pform')({
  validateSearch: (
    search: Record<string, unknown>,
  ): { code?: string | undefined; tab?: TenTabDuAn | undefined } => {
    const tab = tabHopLe(search.tab)
    const code = search.code
    // `tab` GIỮ LẠI dù chưa có `code`: từ 2026-08-21 không tab nào bị khoá, nên
    // `/pform?tab=phan-khu` là một địa chỉ hợp lệ của màn tạo mới. Bản trước trả
    // `{}` ở đây và `diToiTab` cũng gửi `search: {}`, nên bấm một tab lúc tạo mới
    // không đi đâu cả — vô hại khi 8 tab còn bị khoá, chết hẳn khi mở chúng ra.
    if (typeof code !== 'string' || code === '') return { tab }
    return { code, tab }
  },
  component: ManPform,
})

function ManPform() {
  const { code, tab } = Route.useSearch()
  return <DuAnForm code={code} tab={tab ?? 'tong-quan'} />
}
