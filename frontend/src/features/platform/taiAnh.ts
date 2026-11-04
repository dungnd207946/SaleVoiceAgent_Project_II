/**
 * Tải TRƯỚC ảnh của album sân khấu (`send_media`) — album chỉ được đưa một ảnh
 * lên khi ảnh đó đã tải xong, để thẻ không bao giờ là một ô trắng trong lúc
 * đồng hồ tự lướt vẫn chạy như thể đã có ảnh (người dùng báo 2026-10-02).
 *
 * Gọi `onTai(url)` cho TỪNG ảnh ngay khi nó tải xong (theo thứ tự xong, không
 * theo thứ tự gửi); ảnh lỗi (link chết, CORS…) bị bỏ qua im lặng. Trả hàm huỷ:
 * card mới tới / cuộc gọi mới / rời màn thì ảnh của card cũ tải xong muộn cũng
 * không được chen vào album mới.
 */
export function taiTruocAnh(ds: readonly string[], onTai: (url: string) => void): () => void {
  let huy = false
  const anh = ds.map((u) => {
    const im = new Image()
    im.onload = () => {
      if (!huy) onTai(u)
    }
    im.src = u
    return im
  })
  return () => {
    huy = true
    for (const im of anh) im.onload = null
  }
}
