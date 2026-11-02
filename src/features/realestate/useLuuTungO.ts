/**
 * Tự lưu từng ô: ô chữ/số lưu khi RỜI ô, ô chọn lưu ngay lúc đổi.
 *
 * Rời ô chứ không debounce — bấm sang tab khác thì trình duyệt phát `blur` trước
 * `click`, nên phần vừa gõ đã lên đường trước khi tab đổi.
 *
 * PATCH mang đúng ô vừa đổi. Backend `exclude_unset=True`, nên gửi cả form là
 * gửi lại những giá trị không ai sửa — trong đó có thể có ô vừa bị đổi ở nơi khác.
 */
import { useCallback, useRef, useState } from 'react'
import { useKhungSua, type SaveEvent } from './khungSua'

export interface LuuTungO<T> {
  v: T
  /** Gõ: đổi state, chưa gửi. */
  doi: <K extends keyof T>(k: K, x: T[K]) => void
  /** Rời ô: gửi nếu khác giá trị đã lưu. */
  xong: (k: keyof T) => void
  /** Ô chọn / media: đổi và gửi ngay. */
  doiVaLuu: <K extends keyof T>(k: K, x: T[K]) => void
  /** Một thao tác đổi NHIỀU ô cùng lúc (vd chọn tệp đặt luôn tiêu đề). */
  doiNhieuVaLuu: (patch: Partial<T>) => void
  dangLuu: boolean
  vuaLuu: boolean
  loi: unknown
}

export function useLuuTungO<T extends object>(
  banDau: T,
  luu: (patch: Partial<T>) => Promise<unknown>,
  /**
   * Danh tính của bản ghi. Đổi ⇒ nạp lại `banDau`. Cần cho màn nào TẢI bản ghi
   * sau lần render đầu (`/uform`): không có nó thì state đóng băng ở giá trị
   * lúc chưa có dữ liệu. Component nào có `key` riêng thì bỏ qua tham số này.
   */
  khoa?: unknown,
  /** Báo lượt lưu khi màn tự dựng provider của nó (`/uform`); vắng thì báo qua context. */
  report?: (event: SaveEvent) => void,
): LuuTungO<T> {
  // Báo lượt lưu lên đầu trang. Ngoài provider đây là một no-op.
  const ctx = useKhungSua()
  const reportSave = report ?? ctx.reportSave
  const [v, setV] = useState<T>(banDau)
  // Bản mới nhất đọc được NGAY trong callback: `blur` chạy sau render nhưng
  // trước lượt render kế, và đặt side effect vào updater của `setV` thì
  // StrictMode gọi hai lần ⇒ hai PATCH.
  const hienTai = useRef<T>(banDau)
  const daLuu = useRef<T>(banDau)
  const [dangLuu, setDangLuu] = useState(false)
  const [vuaLuu, setVuaLuu] = useState(false)
  const [loi, setLoi] = useState<unknown>(null)

  // Đặt state TRONG lúc render, có canh — khuôn «derived state» của React; dùng
  // `useEffect` ở đây là render một lượt với dữ liệu của bản ghi cũ. Khoá cũ giữ bằng state, không
  // bằng ref: StrictMode render hai lần, ref đổi ở lượt đầu làm lượt sau bỏ qua việc nạp bản ghi.
  const [khoaTruoc, setKhoaTruoc] = useState(khoa)
  if (khoaTruoc !== khoa) {
    setKhoaTruoc(khoa)
    hienTai.current = banDau
    daLuu.current = banDau
    setV(banDau)
  }

  const gui = useCallback(
    (patch: Partial<T>) => {
      setDangLuu(true)
      setLoi(null)
      reportSave('start')
      void luu(patch)
        .then(() => {
          daLuu.current = { ...daLuu.current, ...patch }
          setVuaLuu(true)
          reportSave('done')
        })
        .catch((e: unknown) => {
          setLoi(e)
          reportSave('error')
        })
        .finally(() => setDangLuu(false))
    },
    [luu, reportSave],
  )

  const dat = useCallback(<K extends keyof T>(k: K, x: T[K]) => {
    hienTai.current = { ...hienTai.current, [k]: x }
    setV(hienTai.current)
    setVuaLuu(false)
  }, [])

  const xong = useCallback(
    (k: keyof T) => {
      if (hienTai.current[k] !== daLuu.current[k])
        gui({ [k]: hienTai.current[k] } as unknown as Partial<T>)
    },
    [gui],
  )

  const doiVaLuu = useCallback(
    <K extends keyof T>(k: K, x: T[K]) => {
      dat(k, x)
      gui({ [k]: x } as unknown as Partial<T>)
    },
    [dat, gui],
  )

  const doiNhieuVaLuu = useCallback(
    (patch: Partial<T>) => {
      hienTai.current = { ...hienTai.current, ...patch }
      setV(hienTai.current)
      setVuaLuu(false)
      gui(patch)
    },
    [gui],
  )

  return { v, doi: dat, xong, doiVaLuu, doiNhieuVaLuu, dangLuu, vuaLuu, loi }
}
