/** Chi phí dữ liệu ngoài trên /billing: dòng phụ thẻ, dịch vụ Tra Google, hàng hệ thống trong bảng theo khoá. */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { LangProvider } from '@/i18n'
import { routeTree } from '@/routeTree.gen'
import type { DanhSachKey, DongKey, PhanTich, TongQuan } from '@/features/billing/kieu'
import { server } from '../vitest.setup'

function boot() {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: ['/billing'] }) })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

const TONG: TongQuan = {
  input_tokens: 2_000_000,
  output_tokens: 10_000,
  cache_read_tokens: 0,
  voice_sec: 0,
  so_phien: 12,
  so_key: 1,
  chi_phi: '20000.0000000000',
  chi_phi_du_lieu_ngoai: '9880.0000000000',
  currency: 'VND',
  canh_bao: { thieu_gia: 0, nhan_chua_phan_loai: 0, event_khong_so_do: 0, llm_khong_chinh_xac: 0 },
}

const PHAN_TICH: PhanTich = {
  theo_ngay: [],
  theo_component: [
    {
      component: 'llm',
      so_event: 10,
      input_tokens: 2_000_000,
      output_tokens: 10_000,
      cache_read_tokens: 0,
      audio_sec: 0,
      text_units: 0,
      units: 0,
      chi_phi: '10900.0000000000',
      chi_phi_du_lieu_ngoai: '780.0000000000',
    },
    {
      component: 'search',
      so_event: 1,
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      audio_sec: 0,
      text_units: 0,
      units: 10,
      chi_phi: '9100.0000000000',
      chi_phi_du_lieu_ngoai: '9100.0000000000',
    },
  ],
  chi_phi_tong: '20000.0000000000',
  currency: 'VND',
}

function dong(o: Partial<DongKey>): DongKey {
  return {
    agent_key_id: 1,
    label: 'K-web',
    key_prefix: 'ody_ag_1',
    nguoi_tao: 'u1',
    nguoi_tao_ten: 'Quân',
    da_thu_hoi: false,
    so_phien: 12,
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    voice_sec: 0,
    so_event: 0,
    chi_phi: '0',
    chi_phi_llm: '0',
    chi_phi_tts: '0',
    chi_phi_stt: '0',
    chi_phi_embed: '0',
    chi_phi_search: '0',
    chi_phi_call: '0',
    chi_phi_vad: '0',
    chi_phi_speaker_verify: '0',
    ...o,
  }
}

const KHOA: DanhSachKey = {
  items: [
    dong({ chi_phi: '10120.0000000000', chi_phi_llm: '10120.0000000000' }),
    dong({
      agent_key_id: null,
      du_lieu_ngoai: true,
      label: '',
      key_prefix: '',
      nguoi_tao: '',
      nguoi_tao_ten: null,
      so_phien: 0,
      chi_phi: '9880.0000000000',
      chi_phi_llm: '780.0000000000',
      chi_phi_search: '9100.0000000000',
    }),
  ],
  total: 2,
  chi_phi_tong: '20000.0000000000',
  currency: 'VND',
}

function datApi() {
  server.use(
    http.get('/api/v1/billing/summary', () => HttpResponse.json(TONG)),
    http.get('/api/v1/billing/breakdown', () => HttpResponse.json(PHAN_TICH)),
    http.get('/api/v1/billing/by-key', () => HttpResponse.json(KHOA)),
  )
}

describe('chi phí dữ liệu ngoài trên /billing', () => {
  it('thẻ chi phí nói phần của dữ liệu ngoài', async () => {
    datApi()
    boot()
    expect(await screen.findByText(/gồm 9\.880 ₫ dữ liệu ngoài/)).toBeInTheDocument()
  })

  it('thẻ theo dịch vụ có Tra Google và dòng phụ dữ liệu ngoài', async () => {
    datApi()
    boot()
    expect(await screen.findByText('toàn bộ là dữ liệu ngoài')).toBeInTheDocument()
    expect(screen.getByText('gồm 780 ₫ dữ liệu ngoài')).toBeInTheDocument()
    expect(screen.getByText(/10 lượt/)).toBeInTheDocument()
  })

  it('bảng theo khoá có cột Tra Google và hàng Dữ liệu ngoài riêng', async () => {
    datApi()
    boot()
    const bang = await screen.findByRole('table', { name: 'Lượt dùng theo khoá' })
    expect(within(bang).getByRole('columnheader', { name: /Tra Google/ })).toBeInTheDocument()
    const hang = within(bang).getByText('Dữ liệu ngoài (chạy tự động)').closest('tr')!
    expect(within(hang).getByText('9.100')).toBeInTheDocument()
    expect(within(bang).queryByText('Chưa phân loại (không có khoá)')).not.toBeInTheDocument()
  })
})
