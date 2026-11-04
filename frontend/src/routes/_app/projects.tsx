import { createFileRoute } from '@tanstack/react-router'
import { DuAnList } from '@/features/realestate/components/DuAnList'

/**
 * Màn `projects` — Kiến thức của lĩnh vực Bất động sản (M4).
 *
 * `?nap=1` mở màn con «Nạp qua API» (điểm nạp · token · bản ghi bị từ chối) THAY
 * cho bảng dự án. Không có `nap` là bảng dự án như thường.
 *
 * ⚠️ KHÔNG PHẢI HAI TAB. Bản trước dựng một `NhomTab` «Dự án» · «Nguồn dữ liệu»
 * và người dùng chốt bỏ (2026-08-14): hai tab là hai thứ NGANG HÀNG, mà đây thì
 * không — tab «Dự án» là bản thân kiến thức (và hiện MỌI dự án, bất kể vào bằng
 * tay hay qua API), còn cái kia là đường ống, không chứa một mẩu kiến thức nào.
 * Nó là một TUỲ CHỌN của màn này, nên nó đứng cạnh «Thêm dự án» chứ không chia
 * đôi màn.
 *
 * VÌ SAO SEARCH PARAM chứ không phải `useState`: cùng lý lẽ `?tab=` của `/pform`
 * — link gửi cho đồng nghiệp phải mở đúng chỗ, và Back/Forward của trình duyệt
 * phải trả về đúng nơi vừa rời đi.
 *
 * BA MÀN PHẲNG, không route lồng: `tests/nav-registry.test.ts` so danh sách file
 * .tsx trong thư mục này với 18 `path` của `lib/screens.ts`, nên thêm một file
 * route ở đây là test đỏ. Form dự án ở `/pform?code=…`, form căn ở `/uform?…`.
 */
export const Route = createFileRoute('/_app/projects')({
  // Làm SẠCH, không ném: `?nap=xyz` từ URL sửa tay cũng tới được, và ném lỗi ở
  // đây là cả màn không render — người dùng thấy trang trắng thay vì danh sách.
  //
  // ⚠️ LUÔN TRẢ KHOÁ `nap`, kể cả khi `false`. Router TRỘN kết quả validate lên
  // search thô chứ không THAY nó, nên khoá mình bỏ đi thì giá trị thô sống sót —
  // đo được ở bản `?tab=` trước đó: `?tab=xyz` tới thẳng component nguyên văn và
  // không tab nào mở. `validateSearch` chỉ làm sạch được khoá nào nó TRẢ VỀ.
  //
  // ⚠️ NHẬN CẢ BỐN DẠNG `1` · `'1'` · `true` · `'true'`, và đó không phải phòng
  // thủ thừa: TanStack tự parse search string, nên `?nap=1` GÕ TAY về thành SỐ
  // `1` còn `<Link search={{ nap: true }}>` sinh ra `?nap=true` rồi về thành
  // BOOLEAN. So mỗi chuỗi `'1'` là màn con mở được bằng nút mà không mở được
  // bằng URL — đã đỏ đúng vì thế.
  //
  // ⚠️ TRẢ `{}` KHI TẮT, khác luật «luôn trả khoá» mà `?tab=` trước đó phải theo.
  // Luật kia sinh ra vì router TRỘN kết quả validate lên search thô: khoá mình bỏ
  // đi thì giá trị thô sống sót. Ở đây điều đó VẪN đúng — `?nap=xyz` vẫn tới
  // component nguyên văn — nhưng vô hại, vì chỗ dùng so `=== true` (xem
  // `ManProjects`), nên mọi giá trị lạ đều rơi về bảng dự án.
  //
  // Khác biệt với `?tab=`: `tab` có nhiều giá trị hợp lệ nên một chuỗi lạ không
  // khớp cái nào và màn thành KHÔNG TAB NÀO MỞ. `nap` chỉ là một công tắc, và
  // «không phải bật» đã là một trạng thái đúng. Đổi lại được một URL sạch ở đúng
  // màn hay vào nhất — `/projects` chứ không phải `/projects?nap=false`.
  validateSearch: (search: Record<string, unknown>): { nap?: true | undefined } => {
    const v = search['nap']
    return v === 1 || v === '1' || v === true || v === 'true' ? { nap: true } : {}
  },
  component: ManProjects,
})

function ManProjects() {
  const { nap } = Route.useSearch()
  // `=== true`, KHÔNG phải `??  false` hay ép boolean: giá trị thô lọt qua
  // `validateSearch` (xem chú thích trên) có thể là một chuỗi bất kỳ, và mọi thứ
  // không phải `true` đều phải rơi về bảng dự án.
  return <DuAnList nap={nap === true} />
}
