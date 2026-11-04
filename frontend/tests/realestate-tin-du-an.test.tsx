/**
 * Dòng trạng thái dự án ở cuối MỌI tab — nay chỉ còn ĐÚNG MỘT ca: lưu trữ.
 *
 * ⚠️ HAI CÂU ĐÃ BỎ (người dùng chốt 2026-08-21): «Agent sẽ thôi đọc dự án này —
 * còn thiếu …» và «Agent đã đọc dữ liệu này — sẽ dùng dự án này khi trả lời
 * khách». Chúng nói lại thứ chip trạng thái và dấu `*` ở từng ô đã nói, và câu
 * xanh khẳng định hiện ở cuối mọi tab nên nó thành nền, không thành tin.
 *
 * Ca lưu trữ ở LẠI vì nó là ca duy nhất không có chỗ nào khác nói: chip ghi «Lưu
 * trữ» nhưng không nói rằng đổi lại là việc phải làm ở chip.
 *
 * File này vì thế canh CẢ HAI CHIỀU — ca lưu trữ còn, hai câu kia đi.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { DU_AN, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'
import { server } from '../vitest.setup'

const TAB = ['Tổng quan', 'Vị trí', 'Ảnh 360', 'Mặt bằng', 'Phân khu', 'Quỹ căn', 'Media', 'Tiến độ', 'Tài liệu']

function dat(project: object) {
  datApiDoc({ project, media: trang([]), zones: trang([]), documents: trang([]), units: trang([]) })
}

describe('lưu trữ ⇒ nói ở mọi tab', () => {
  it.each(TAB)('tab %s cũng nói dự án đã lưu trữ', async (nhan) => {
    dat({ ...DU_AN, status: 'archived' })
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: nhan }))

    expect(await screen.findByText(/đã lưu trữ nên agent không đọc/)).toBeInTheDocument()
  })

  it('nằm ngoài khối đỉnh', async () => {
    dat({ ...DU_AN, status: 'archived' })
    boot('/pform?code=VHOP2')

    const tin = await screen.findByTestId('pform-tin')
    expect(screen.getByTestId('pform-dinh')).not.toContainElement(tin)
  })

  it('không kể trường còn thiếu — đó là việc của dấu `*` tại ô', async () => {
    dat({ ...DU_AN, status: 'archived', region: '' })
    boot('/pform?code=VHOP2&tab=media')
    await screen.findByText(/đã lưu trữ nên agent không đọc/)

    expect(screen.queryByText(/còn thiếu/)).not.toBeInTheDocument()
  })
})

describe('ba trạng thái còn lại đều IM LẶNG', () => {
  it('published và đủ trường ⇒ không khẳng định gì', async () => {
    dat(DU_AN)
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByRole('tab', { name: 'Quỹ căn' })

    expect(screen.queryByText(/Agent đã đọc dữ liệu này/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('pform-tin')).not.toBeInTheDocument()
  })

  it('published mà THIẾU trường cũng im — chip và dấu `*` đã nói', async () => {
    dat({ ...DU_AN, region: '' })
    boot('/pform?code=VHOP2')
    await screen.findByRole('tab', { name: 'Tổng quan' })

    expect(screen.queryByText(/Agent sẽ thôi đọc/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('pform-tin')).not.toBeInTheDocument()
  })

  it('nháp ⇒ im lặng ở mọi tab', async () => {
    dat({ ...DU_AN, status: 'draft', region: '' })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await screen.findByRole('tab', { name: 'Tài liệu' })

    expect(screen.queryByTestId('pform-tin')).not.toBeInTheDocument()
  })

  it('xoá trắng một ô cổng rồi rời ô cũng KHÔNG sinh cảnh báo nào', async () => {
    // Bài này từng canh chiều ngược lại (cảnh báo phải hiện đúng lúc rời ô). Giữ
    // lại ở chiều mới vì đường đọc-bản-ghi-đã-lưu vẫn còn: nếu ai dựng lại câu
    // cảnh báo từ state local thì nó nổ ngay ở đây.
    let region = DU_AN.region
    datApiDoc({ media: trang([]) })
    server.use(
      http.get('/api/v1/projects/:code', () => HttpResponse.json({ ...DU_AN, region })),
      http.patch('/api/v1/projects/:code', async ({ request }) => {
        const b = (await request.json()) as { region?: string }
        if (b.region !== undefined) region = b.region
        return HttpResponse.json({ ...DU_AN, region })
      }),
    )
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Khu vực/ }))
    await userEvent.tab()

    await waitFor(() => expect(screen.getByTestId('pform-dinh')).toHaveTextContent(/Đã lưu lúc/))
    expect(screen.queryByText(/Agent sẽ thôi đọc/)).not.toBeInTheDocument()
  })
})

describe('lỗi lưu vẫn nói ở tab của nó', () => {
  it('PATCH lỗi ⇒ câu lỗi hiện', async () => {
    dat(DU_AN)
    server.use(
      http.patch('/api/v1/projects/:code', () =>
        HttpResponse.json({ error: { code: 'X', message: 'Máy chủ từ chối' } }, { status: 500 }),
      ),
    )
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    const o = screen.getByRole('textbox', { name: /Chủ đầu tư/ })
    await userEvent.type(o, 'X')
    await userEvent.tab()

    await waitFor(() => expect(screen.getByText(/Máy chủ từ chối/)).toBeInTheDocument())
  })
})
