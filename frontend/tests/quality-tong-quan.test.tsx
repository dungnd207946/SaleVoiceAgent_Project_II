import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FeedbackTongQuan } from '@/features/quality/components/FeedbackTongQuan'

describe('FeedbackTongQuan', () => {
  it('hiện điểm trung bình và tổng lượt', () => {
    render(
      <FeedbackTongQuan
        total={128}
        theoSao={{ '1': 4, '2': 5, '3': 10, '4': 30, '5': 79 }}
        diemTrungBinh={4.3}
      />,
    )
    // vi-VN: dấu PHẨY thập phân, hai chữ số lẻ — cùng cách ô «Đánh giá» ở Tổng quan in.
    expect(screen.getByText('4,30')).toBeInTheDocument()
    expect(screen.getByText(/128/)).toBeInTheDocument()
  })

  it('tổng lượt có nhóm hàng nghìn (dấu chấm), không in số thô', () => {
    render(
      <FeedbackTongQuan
        total={1199}
        theoSao={{ '1': 0, '2': 0, '3': 0, '4': 0, '5': 1199 }}
        diemTrungBinh={5}
      />,
    )
    expect(screen.getByText('1.199 lượt đánh giá')).toBeInTheDocument()
    expect(screen.getByTestId('phan-bo-5')).toHaveTextContent('1.199')
  })

  it('hiện đủ 5 dòng phân bố, kể cả sao có đếm 0', () => {
    render(
      <FeedbackTongQuan
        total={5}
        theoSao={{ '1': 0, '2': 0, '3': 0, '4': 0, '5': 5 }}
        diemTrungBinh={5}
      />,
    )
    // Mỗi dòng phân bố có `data-sao-hang="N"` — móc test, xem component.
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByTestId(`phan-bo-${n}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('phan-bo-1')).toHaveTextContent('0')
    expect(screen.getByTestId('phan-bo-5')).toHaveTextContent('5')
  })

  it('khối tổng quan xếp dọc ở mobile', async () => {
    render(
      <FeedbackTongQuan
        total={5}
        theoSao={{ '1': 0, '2': 0, '3': 0, '4': 0, '5': 5 }}
        diemTrungBinh={5}
      />,
    )
    const diem = await screen.findByText(/Người dùng đánh giá/)
    const cotTrai = diem.parentElement!
    expect(cotTrai.className).toContain('max-md:w-full')
    expect(cotTrai.parentElement!.className).toContain('max-md:flex-col')
  })
})
