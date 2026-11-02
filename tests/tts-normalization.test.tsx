/**
 * Từ điển cách đọc TTS — `chuanHoa()` phải sinh mặc định `[]`.
 *
 * Backend cũ (chưa deploy) trả payload KHÔNG có trường này. Không có mặc định thì
 * `undefined` chảy vào `.map()` của bảng và màn trắng — không phải một lỗi đọc được.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { chuanHoaChoTest } from '../src/features/agent/useBanNhap'
import { NormalizationPreview } from '../src/features/agent/components/Normalization'

const PAYLOAD_KHONG_CO_TRUONG = {
  schema_version: 3,
  danh_tinh: {
    ten_agent: 'Mai',
    ten_thuong_hieu: 'An Phú Land',
    tu_xung: 'em',
    goi_khach: 'anh/chị',
    loi_chao: '',
  },
  pham_vi: {
    linh_vuc: 'realestate',
    lam_gi: '',
    khong_lam_gi: '',
    phong_ban: [{ ten: 'CSKH', khi_nao: '' }],
    cau_tu_choi: '',
  },
  giong: { giong_dieu: 'than_thien', do_dai: 'trung_binh' },
  tools: { enabled: ['find_project', 'kb_search'] },
}

describe('chuanHoa · tts_normalization', () => {
  it('payload thiếu trường thì thành danh sách rỗng', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ra = chuanHoaChoTest(PAYLOAD_KHONG_CO_TRUONG as any)

    expect(ra.tts_normalization).toEqual([])
  })

  it('giữ nguyên danh sách khi payload đã có', () => {
    const vao = {
      ...PAYLOAD_KHONG_CO_TRUONG,
      tts_normalization: [{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }],
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ra = chuanHoaChoTest(vao as any)

    expect(ra.tts_normalization).toEqual([{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }])
  })

  it('giá trị không phải mảng cũng thành mảng rỗng', () => {
    const vao = { ...PAYLOAD_KHONG_CO_TRUONG, tts_normalization: null }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ra = chuanHoaChoTest(vao as any)

    expect(ra.tts_normalization).toEqual([])
  })
})

const NAM_MUC = [
  { term: 'NCLB', read_as: 'Noble Crystal Long Biên' },
  { term: 'SSLC', read_as: 'Sunshine Legend City' },
  { term: 'NPTH', read_as: 'Noble Palace Tây Hồ' },
  { term: 'NCRS', read_as: 'Noble Crystal Riverside' },
  { term: 'NPTTL', read_as: 'Noble Palace Tây Thăng Long' },
]

describe('NormalizationPreview', () => {
  it('rỗng thì nói agent đang dùng bộ mặc định của nền tảng', () => {
    render(<NormalizationPreview muc={[]} />)

    expect(screen.getByText(/bộ mặc định của nền tảng/i)).toBeInTheDocument()
  })

  it('hiện đúng 3 dòng đầu và nói còn bao nhiêu mục nữa', () => {
    render(<NormalizationPreview muc={NAM_MUC} />)

    expect(screen.getByText('NCLB')).toBeInTheDocument()
    expect(screen.getByText('NPTH')).toBeInTheDocument()
    expect(screen.queryByText('NCRS')).not.toBeInTheDocument()
    expect(screen.getByText(/còn 2 mục nữa/i)).toBeInTheDocument()
  })

  it('nút mở dialog mang số mục và mở ra bảng đầy đủ', async () => {
    const nd = userEvent.setup()
    render(<NormalizationPreview muc={NAM_MUC} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(5\)/i }))

    const hop = screen.getByRole('dialog')
    expect(within(hop).getByText('NCRS')).toBeInTheDocument()
    expect(within(hop).getByText('Noble Crystal Riverside')).toBeInTheDocument()
  })

  it('chỉ-đọc thì dialog không có nút xoá và không có ô thêm', async () => {
    const nd = userEvent.setup()
    render(<NormalizationPreview muc={NAM_MUC} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(5\)/i }))

    const hop = screen.getByRole('dialog')
    expect(within(hop).queryByRole('button', { name: /^xoá/i })).not.toBeInTheDocument()
    expect(within(hop).queryByRole('button', { name: 'Thêm' })).not.toBeInTheDocument()
    expect(within(hop).queryByLabelText(/từ hoặc mã/i)).not.toBeInTheDocument()
  })

  it('sửa được thì thêm một mục gọi doi với mục mới ở cuối', async () => {
    const nd = userEvent.setup()
    const daGoi: unknown[] = []
    render(<NormalizationPreview muc={[]} doi={(m) => daGoi.push(m)} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(0\)/i }))
    const hop = screen.getByRole('dialog')
    await nd.type(within(hop).getByLabelText(/từ hoặc mã/i), 'NCLB')
    await nd.type(within(hop).getByLabelText(/đọc thành/i), 'Noble Crystal Long Biên')
    await nd.click(within(hop).getByRole('button', { name: 'Thêm' }))

    expect(daGoi).toEqual([[{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }]])
  })

  it('chặn khoá trùng ngay tại chỗ, không đợi 422 của backend', async () => {
    const nd = userEvent.setup()
    const daGoi: unknown[] = []
    render(
      <NormalizationPreview
        muc={[{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }]}
        doi={(m) => daGoi.push(m)}
      />,
    )

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(1\)/i }))
    const hop = screen.getByRole('dialog')
    await nd.type(within(hop).getByLabelText(/từ hoặc mã/i), 'nclb')
    await nd.type(within(hop).getByLabelText(/đọc thành/i), 'Khác')
    await nd.click(within(hop).getByRole('button', { name: 'Thêm' }))

    expect(daGoi).toEqual([])
    expect(within(hop).getByText(/đã có mục này/i)).toBeInTheDocument()
  })

  it('nút duy nhất trong dialog là Thêm — không có Xong, không có Lưu', async () => {
    const nd = userEvent.setup()
    render(<NormalizationPreview muc={[]} doi={() => {}} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(0\)/i }))

    const hop = screen.getByRole('dialog')
    expect(within(hop).getByRole('button', { name: 'Thêm' })).toBeInTheDocument()
    expect(within(hop).queryByRole('button', { name: /xong|lưu/i })).not.toBeInTheDocument()
  })

  it('Enter trong ô vẫn thêm được dù nút chỉ còn là icon', async () => {
    const nd = userEvent.setup()
    const daGoi: unknown[] = []
    render(<NormalizationPreview muc={[]} doi={(m) => daGoi.push(m)} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(0\)/i }))
    const hop = screen.getByRole('dialog')
    await nd.type(within(hop).getByLabelText(/từ hoặc mã/i), 'NCLB')
    await nd.type(within(hop).getByLabelText(/đọc thành/i), 'Noble Crystal Long Biên{Enter}')

    expect(daGoi).toEqual([[{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }]])
  })

  it('xoá một mục gọi doi với danh sách còn lại', async () => {
    const nd = userEvent.setup()
    const daGoi: unknown[] = []
    render(<NormalizationPreview muc={NAM_MUC} doi={(m) => daGoi.push(m)} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(5\)/i }))
    const hop = screen.getByRole('dialog')
    await nd.click(within(hop).getByRole('button', { name: 'Xoá SSLC' }))

    expect(daGoi).toEqual([NAM_MUC.filter((m) => m.term !== 'SSLC')])
  })
})
