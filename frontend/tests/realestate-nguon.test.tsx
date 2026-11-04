/**
 * Tab «Nguồn dữ liệu» của màn Kiến thức (`/projects?tab=nguon`).
 *
 * Boot qua ROUTER thật, không render component trần: tab nằm trong search param
 * và `validateSearch` là chỗ dễ vỡ nhất của thiết kế này (nó cố ý TRẢ `{}` cho
 * tab mặc định — xem `routes/_app/projects.tsx`). Render thẳng component sẽ bỏ
 * qua đúng phần cần canh. Cùng lý lẽ đã ghi ở đầu `re-fixture.tsx`.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RESET_NGUON_GIA } from '../src/features/realestate/msw'
import { cachDay } from '../src/features/realestate/nguonDinhDang'
import { boot, datApiDoc } from './re-fixture'

beforeEach(() => {
  RESET_NGUON_GIA()
  datApiDoc()
})

/** Bảng tra theo `aria-label` của `<table>` — ba bảng của tab đều có tên riêng. */
const bang = (nhan: string) => screen.findByRole('table', { name: nhan })

describe('Nguồn dữ liệu — đường vào', () => {
  it('`/projects` trần mở bảng dự án, KHÔNG có hàng tab nào', async () => {
    boot('/projects')
    expect(await screen.findByRole('link', { name: 'Thêm dự án' })).toBeInTheDocument()
    // Hai tab là hai thứ NGANG HÀNG, mà bảng dự án là bản thân kiến thức còn
    // cổng nạp là đường ống — nó là một TUỲ CHỌN, không phải nửa màn.
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
    expect(screen.queryByText('Endpoint')).not.toBeInTheDocument()
  })

  it('nút «Nạp qua API» đứng cạnh «Thêm dự án» và mở màn con, URL mang `?nap`', async () => {
    const router = boot('/projects')
    await userEvent.click(await screen.findByRole('link', { name: 'Nạp qua API' }))

    expect(await screen.findByText('Endpoint')).toBeInTheDocument()
    // URL đổi thật ⇒ gửi link cho đồng nghiệp mở đúng chỗ, Back chạy đúng.
    expect(router.state.location.searchStr).toContain('nap')
  })

  it('đường về mang đúng nhãn nav «Kiến thức», trả lại bảng và dọn `?nap` khỏi URL', async () => {
    const router = boot('/projects?nap=1')
    await userEvent.click(await screen.findByRole('link', { name: '‹ Kiến thức' }))

    expect(await screen.findByRole('link', { name: 'Thêm dự án' })).toBeInTheDocument()
    expect(router.state.location.searchStr).toBe('')
  })

  /**
   * ⚠️ BÀI NÀY BẮT ĐƯỢC LỖI THẬT Ở BẢN `?tab=` TRƯỚC ĐÓ, đừng hạ xuống cho gọn.
   *
   * `validateSearch` bản đầu trả `{}` cho giá trị mặc định. Router TRỘN kết quả
   * validate lên search thô chứ không THAY, nên khoá bị bỏ đi thì giá trị thô
   * sống sót và component nhận nguyên chuỗi lạ. Xem `routes/_app/projects.tsx`.
   */
  it('`?nap=` giá trị lạ rơi về bảng dự án, không để màn trống', async () => {
    boot('/projects?nap=khong-ton-tai')
    expect(await screen.findByRole('link', { name: 'Thêm dự án' })).toBeInTheDocument()
    expect(screen.queryByText('Endpoint')).not.toBeInTheDocument()
  })
})

describe('Nguồn dữ liệu — điểm nạp và tình trạng', () => {
  it('hiện URL endpoint và ba con số 24 giờ — không dòng đối soát, không nút copy', async () => {
    boot('/projects?nap=1')

    expect(await screen.findByText(/POST https:\/\/ingest\.noblex\.vn/)).toBeInTheDocument()
    expect(screen.getByText('1.284')).toBeInTheDocument()
    expect(screen.getByText('1.281')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()

    // Dòng ĐỐI SOÁT đã bỏ khỏi giao diện (người dùng chốt 2026-08-14) — cơ chế
    // vẫn thuộc backend, chỉ dòng chữ đi. Nó khoe cả lúc không có việc, đúng thứ
    // luật của `/agent` cấm. Xem chú thích ở `ThongKeNap`.
    expect(screen.queryByText(/Đối soát/)).not.toBeInTheDocument()
    // Endpoint là chữ bôi đen được, KHÔNG có nút copy — nó vào tay dev bên khách
    // đúng một lần lúc đấu nối, khác chuỗi token vốn là thứ copy thật sự.
    expect(screen.queryByRole('button', { name: /Copy điểm nạp/ })).not.toBeInTheDocument()
  })

  it('tài liệu API là MỘT LINK ra Swagger, không phải bảng dựng lại trong portal', async () => {
    boot('/projects?nap=1')
    const link = await screen.findByRole('link', { name: 'Tài liệu API' })

    // Swagger CỦA RIÊNG cổng nạp (backend phục vụ dưới `/api/v1/…`, 2026-08-21)
    // — không còn neo hash vào trang docs chung của cả portal.
    expect(link).toHaveAttribute('href', expect.stringContaining('/api/v1/ingest/'))
    expect(link).toHaveAttribute('href', expect.stringContaining('/docs'))
    // Mở tab mới: dev bên khách đọc hợp đồng SONG SONG với bảng lỗi ở màn này.
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('KHÔNG có nút «Tải OpenAPI» — đã bỏ 2026-08-21, spec lấy qua link openapi.json của chính trang Swagger', async () => {
    boot('/projects?nap=1')
    await screen.findByRole('link', { name: 'Tài liệu API' })
    expect(screen.queryByRole('link', { name: 'Tải OpenAPI' })).not.toBeInTheDocument()
  })

  it('KHÔNG dựng lại bảng trường trong portal — nguồn sự thật là backend', async () => {
    boot('/projects?nap=1')
    await screen.findByText('Endpoint')

    // Bản trước chép tay hai bảng này từ `contracts.py`/`enums.ts`, không có
    // cổng parity nào canh: backend thêm một trường là portal nói sai mà không
    // ai biết. Bài này khoá lại quyết định bỏ chúng.
    expect(screen.queryByText('Vỏ bản ghi')).not.toBeInTheDocument()
    expect(screen.queryByText('Trường của data')).not.toBeInTheDocument()
    expect(screen.queryByText(/curl -X POST/)).not.toBeInTheDocument()
  })
})

describe('Nguồn dữ liệu — token đẩy dữ liệu', () => {
  it('hai cột Tên · Token, chuỗi CHE SẴN, không dòng phụ nào', async () => {
    boot('/projects?nap=1')
    const b = await bang('Token đẩy dữ liệu')
    expect(within(b).getAllByRole('row')).toHaveLength(3) // 1 đầu bảng + 2 khoá

    // Chuỗi thô KHÔNG được hiện lúc mở màn — mặc định là che.
    expect(within(b).queryByText(/ody_in_4Rt8_9wKmZq/)).not.toBeInTheDocument()
    // «Tạo bởi … lúc …» đã bỏ: siêu dữ liệu kiểm toán là việc của Nhật ký.
    expect(within(b).queryByText(/Tạo bởi/)).not.toBeInTheDocument()

    // Ba cột cũ đã bỏ — mỗi cái vì một lý do riêng, xem docstring `NguonToken`.
    for (const cot of ['Tiền tố', 'Trạng thái', 'Dùng cuối', 'API key']) {
      expect(within(b).queryByText(cot)).not.toBeInTheDocument()
    }
  })

  it('bấm con mắt mở chuỗi TẠI CHỖ, bấm lần nữa che lại — không hộp thoại nào', async () => {
    boot('/projects?nap=1')
    const b = await bang('Token đẩy dữ liệu')
    const ten = 'ERP Anphu — job đẩy quỹ căn'

    await userEvent.click(within(b).getByRole('button', { name: `Hiện token ${ten}` }))
    expect(within(b).getByText('ody_in_4Rt8_9wKmZq2vLxNbHc7pJf3dSgYaEuTiOr5A')).toBeInTheDocument()
    // Mở tại chỗ, không mở dialog — đó là cả lý do bỏ `XemKhoaNapDialog`.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await userEvent.click(within(b).getByRole('button', { name: `Che token ${ten}` }))
    expect(within(b).queryByText(/ody_in_4Rt8_9wKmZq/)).not.toBeInTheDocument()
  })

  it('nút mở/copy mang TÊN TOKEN — nhiều hàng thì các nút phải phân biệt được', async () => {
    boot('/projects?nap=1')
    const b = await bang('Token đẩy dữ liệu')
    // Tên trần («Hiện khoá») ở bảng nhiều hàng là nhiều lựa chọn giống hệt nhau
    // với trình đọc màn hình, và `getByRole` cũng không phân biệt nổi.
    expect(within(b).getAllByRole('button', { name: /^Hiện token / })).toHaveLength(2)
    expect(within(b).getAllByRole('button', { name: /^Copy token / })).toHaveLength(2)
  })

  it('tạo token xong KHÔNG bật hộp thoại nào — token mới vào thẳng bảng', async () => {
    boot('/projects?nap=1')
    await userEvent.click(await screen.findByRole('button', { name: 'Tạo token' }))

    // Hộp thoại chỉ còn tiêu đề + một ô + hai nút — không câu giảng giải nào
    // (người dùng chốt 2026-08-14, cùng hướng `/agent`·`/api-keys`·`/kb` đã đi).
    expect(screen.getByRole('dialog')).not.toHaveTextContent(/không đọc được hội thoại/)

    await userEvent.type(screen.getByLabelText('Nhãn'), 'CRM Đất Xanh')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo' }))

    expect(within(await bang('Token đẩy dữ liệu')).getByText('CRM Đất Xanh')).toBeInTheDocument()
    // Khác `agent_keys`: khoá mở lại xem được bất cứ lúc nào nên không cần một
    // dialog «đây là lần duy nhất bạn thấy chuỗi này».
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('xoá token thì hàng biến mất hẳn — không để lại dòng vô hiệu nào', async () => {
    boot('/projects?nap=1')
    const b = await bang('Token đẩy dữ liệu')
    const ten = 'ERP Anphu — job đẩy quỹ căn'
    await userEvent.click(within(b).getByRole('button', { name: `Xoá token ${ten}` }))

    const hop = await screen.findByRole('dialog', { name: 'Xoá token đẩy dữ liệu' })
    // Hộp thoại KHÔNG còn câu mô tả nào — nhưng tiêu đề phải nói đang xoá CÁI
    // NÀO, nếu không chữ «này» trỏ vào hư không giữa một bảng nhiều hàng.
    expect(within(hop).getByRole('heading')).toHaveTextContent(`Xoá ${ten}?`)
    await userEvent.click(within(hop).getByRole('button', { name: 'Xoá' }))

    const sau = await bang('Token đẩy dữ liệu')
    expect(within(sau).queryByText(ten)).not.toBeInTheDocument()
    expect(within(sau).getAllByRole('row')).toHaveLength(2) // 1 đầu bảng + 1 khoá còn lại
  })
})

describe('Nguồn dữ liệu — bản ghi bị từ chối', () => {
  it('lỗi cấp BẢN GHI (không thuộc trường nào) nói thành chữ, không để ô trắng', async () => {
    boot('/projects?nap=1')
    const b = await bang('Bản ghi bị từ chối')
    expect(within(b).getByText('DOC-CSBH-07')).toBeInTheDocument()
    // Ô trắng ở cột Trường đọc y hệt một hàng chưa nạp xong.
    expect(within(b).getByText('cả bản ghi')).toBeInTheDocument()
  })

  it('lý do phải đủ cho bên khách tự sửa — nêu cả giá trị gây lỗi', async () => {
    boot('/projects?nap=1')
    const b = await bang('Bản ghi bị từ chối')
    expect(within(b).getByText(/nhận được chuỗi "4,85 tỷ"/)).toBeInTheDocument()
    // Lỗi enum phải LIỆT KÊ giá trị hợp lệ ngay trong lý do — dev bên khách sửa
    // được mà không phải mở lại bảng hợp đồng.
    expect(
      within(b).getByText(/không hợp lệ — chỉ nhận available · booked · sold/),
    ).toBeInTheDocument()
    // Tên trường là tên trong HỢP ĐỒNG của mình, không phải tên bên khách:
    // adapter bên họ đã dịch xong trước khi gửi.
    expect(within(b).getByText('saleStatus')).toBeInTheDocument()
  })
})

describe('cachDay — mốc «nhận cuối» đọc bằng mắt', () => {
  const moc = new Date('2026-08-14T10:00:00.000Z')

  it('phủ đủ bốn bậc và ca chưa nhận lần nào', () => {
    expect(cachDay(null, moc)).toBe('chưa nhận lần nào')
    expect(cachDay('2026-08-14T09:59:30.000Z', moc)).toBe('vừa xong')
    expect(cachDay('2026-08-14T09:30:00.000Z', moc)).toBe('30 phút trước')
    expect(cachDay('2026-08-14T04:00:00.000Z', moc)).toBe('6 giờ trước')
    expect(cachDay('2026-08-11T10:00:00.000Z', moc)).toBe('3 ngày trước')
  })

  it('mốc ở tương lai (đồng hồ hai máy lệch nhau) KHÔNG ra số âm', () => {
    expect(cachDay('2026-08-14T10:05:00.000Z', moc)).toBe('vừa xong')
  })
})
