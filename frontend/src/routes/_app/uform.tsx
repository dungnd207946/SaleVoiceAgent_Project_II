import { createFileRoute } from '@tanstack/react-router'
import { Link } from '@tanstack/react-router'
import { CanForm } from '@/features/realestate/components/CanForm'

/**
 * Màn `uform` — form một căn (M4). `?code=VHOP2` bắt buộc; `?unit=41` để sửa,
 * không có là tạo mới.
 *
 * `unit` là `id` (surrogate), KHÔNG phải `unit_code`: mã căn không unique
 * (`02a §4.3`), nên `?unit=A-12` không xác định được căn nào.
 *
 * `Number(...)` cho `unit` phải kiểm `Number.isInteger`: `?unit=abc` ra `NaN`, và
 * `NaN` đi vào URL của request thành `/units/NaN` — backend trả 422 về một tham số
 * người dùng không hề nhập. Bỏ nó đi thì màn mở ra ở chế độ tạo mới, đúng thứ
 * dùng được nhất từ một URL sai.
 */
export const Route = createFileRoute('/_app/uform')({
  validateSearch: (
    search: Record<string, unknown>,
  ): { code?: string | undefined; unit?: number | undefined } => {
    const code = typeof search.code === 'string' && search.code !== '' ? search.code : undefined
    const thoUnit = Number(search.unit)
    const unit = Number.isInteger(thoUnit) && thoUnit > 0 ? thoUnit : undefined
    return code ? { code, unit } : {}
  },
  component: ManUform,
})

function ManUform() {
  const { code, unit } = Route.useSearch()

  // Không có `code` thì không có dự án nào để gắn căn vào — `POST` sẽ đi tới
  // `/projects//units`. Chặn ở đây và chỉ đường về, thay vì render một form gửi
  // đi là 404.
  if (!code) {
    return (
      <div className="space-y-3 p-6 text-[14px]">
        <p>Thiếu mã dự án trong đường dẫn — mọi căn đều thuộc về một dự án.</p>
        <Link
          to="/projects"
          className="inline-block rounded border border-border-field px-3 py-1.5"
        >
          Về danh sách dự án
        </Link>
      </div>
    )
  }

  return <CanForm projectCode={code} unitId={unit} />
}
