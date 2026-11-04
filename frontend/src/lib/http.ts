/**
 * Client HTTP dùng chung của MỌI module — một chỗ đọc hình dạng lỗi của API
 * (`{error:{code,message,fields?}}`, `portal/api/loi.py` ở repo backend).
 *
 * Trước 2026-10-06 mỗi module chép riêng một `LoiApi` + `goi()` (11 bản) vì luật
 * ranh giới cấm import ruột module khác — nhưng `lib/` thì mọi module import
 * được. Mười một class cũng nghĩa là `instanceof LoiApi` xuyên module luôn
 * `false`; một class thì hết lớp lỗi đó.
 *
 * Vì sao có `code`: màn đăng nhập cần phân biệt "sai mật khẩu" với "chưa thuộc
 * workspace nào" — bám vào `message` là bám vào chuỗi tiếng Việt sẽ đổi.
 */

/** Một lỗi trường của 422 `VALIDATION_ERROR` (`portal/api/loi.py::_than_loi_validate`). */
export interface LoiTruong {
  readonly field: string
  readonly reason: string
}

export class LoiApi extends Error {
  // Khai trường rồi gán trong thân hàm, KHÔNG dùng parameter property: tsconfig
  // bật `erasableSyntaxOnly`.
  readonly code: string
  /** Mã HTTP thô, KHÔNG suy từ `code`: 404 không envelope (route chưa có) và 404
   *  `NOT_FOUND` (route có, tài nguyên không) là hai sự thật khác nhau. */
  readonly status: number | undefined
  /** 422 có cấu trúc: đủ để tô đỏ ĐÚNG ô, không phải một câu chung ở đầu form. */
  readonly truong: readonly LoiTruong[]

  constructor(code: string, message: string, status?: number, truong: readonly LoiTruong[] = []) {
    super(message)
    this.code = code
    this.status = status
    this.truong = truong
  }

  loiCua(ten: string): string | undefined {
    return this.truong.find((x) => x.field === ten || x.field.endsWith(`.${ten}`))?.reason
  }
}

/**
 * Response hỏng → `LoiApi`. `?? 'UNKNOWN'` chứ không ném lỗi parse: 502 của reverse
 * proxy trả HTML, và thứ người dùng cần là một thông điệp, không phải một TypeError.
 */
export async function docLoi(res: Response, moTa: string): Promise<LoiApi> {
  const body = (await res.json().catch(() => null)) as {
    error?: { code?: string; message?: string; fields?: LoiTruong[] }
  } | null
  const e = body?.error
  return new LoiApi(
    e?.code ?? 'UNKNOWN',
    e?.message ?? `${moTa} → ${res.status}`,
    res.status,
    e?.fields ?? [],
  )
}

/**
 * `fetch` + đọc lỗi. Thân là CHUỖI ⇒ gắn `Content-Type: application/json`; `FormData`
 * thì để trình duyệt tự đặt boundary. 204 ⇒ `undefined`. `moTa` mở đầu câu dự phòng
 * khi lỗi không có envelope (`<moTa> → 502`).
 */
export async function goi<T>(duong: string, init: RequestInit = {}, moTa = duong): Promise<T> {
  const res = await fetch(
    duong,
    typeof init.body === 'string'
      ? { ...init, headers: { 'Content-Type': 'application/json', ...init.headers } }
      : init,
  )
  if (!res.ok) throw await docLoi(res, moTa)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
