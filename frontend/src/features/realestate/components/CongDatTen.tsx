/**
 * Một ô hỏi tên, hiện THAY CHO nội dung của sáu tab cần dự án đã tồn tại.
 *
 * VÌ SAO KHÔNG KHOÁ TAB (spec 2026-08-21 issue 1): tab xám không nói được người
 * dùng phải làm gì, chỉ nói họ không được làm. Sáu tab này POST vào
 * `/projects/{code}/…` nên chúng thật sự cần một dự án — nhưng thứ còn thiếu là
 * MỘT ô, không phải một quy trình, nên hỏi đúng ô đó tại chỗ.
 *
 * VÌ SAO CHỈ HỎI TÊN: mã dự án suy từ tên (`core/ma_ban_ghi.py`), và `name` là
 * trường duy nhất `POST /projects` cần. Hỏi thêm gì nữa là dựng lại đúng cái cửa
 * chặn vừa bỏ.
 *
 * ĐÂY LÀ ĐƯỜNG TẠO DUY NHẤT, kể cả ở tab Tổng quan: mọi ô khác tự lưu bằng PATCH,
 * mà chưa có hàng thì không có gì để PATCH.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { taoDuAn } from '../api'
import { cauLoi, loiO } from '../thongDiep'
import { DongTrangThai, NhomTruong, OChu } from '@/components/ui/Truong'
import { HANG_NUT_DAN, NUT_CHINH } from '@/components/ui/Bang'

interface Props {
  nhanTab: string
  daTao: (projectCode: string) => void
}

export function CongDatTen({ nhanTab, daTao }: Props) {
  const qc = useQueryClient()
  const [name, setName] = useState('')

  const mTao = useMutation({
    mutationFn: () => taoDuAn({ name }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ['re', 'projects'] })
      daTao(d.projectCode)
    },
  })

  return (
    <form
      className="flex min-h-0 flex-1 flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (!name.trim()) return
        mTao.mutate()
      }}
    >
      <NhomTruong tieuDe="Dự án này tên gì?" cot={1}>
        <OChu
          ten="name"
          nhan="Tên thương mại"
          batBuoc
          giaTri={name}
          doi={setName}
          loi={loiO(mTao.error, 'name')}
          goiYTrongO="Tên khách nghe trên thị trường, VD: Vinhomes Ocean Park 2"
        />
      </NhomTruong>

      <DongTrangThai mau="warn">
        {nhanTab} thuộc về một dự án, nên cần đặt tên trước. Mã dự án sinh tự động từ tên.
      </DongTrangThai>

      {mTao.error && <DongTrangThai mau="alert">{cauLoi(mTao.error, 'tạo dự án')}</DongTrangThai>}

      <div data-testid="pform-day" className={HANG_NUT_DAN}>
        <button type="submit" className={NUT_CHINH} disabled={mTao.isPending}>
          {mTao.isPending ? 'Đang tạo…' : 'Tiếp'}
        </button>
      </div>
    </form>
  )
}
