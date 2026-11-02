/**
 * Dòng «Hồ sơ dữ liệu ngoài» dưới tiêu đề dự án đã phát hành — số chủ đề có dữ liệu, lần cập nhật, link sang
 * đúng dự án ở màn «Dữ liệu ngoài». Không có quyền xem màn đó (403) thì không hiện gì.
 */
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ngayThangNam } from '@/lib/dinhDang'
import { docHoSoNgoai } from '../api'

function ngay(iso: string): string {
  return ngayThangNam(new Date(iso))
}

export function HoSoNgoai({ code }: { code: string }) {
  const q = useQuery({ queryKey: ['re', 'ho-so-ngoai'], queryFn: docHoSoNgoai, retry: false, staleTime: 60_000 })
  const d = q.data?.find((x) => x.code === code)
  if (!d) return null
  return (
    <p data-testid="ho-so-ngoai" className="text-phu text-muted">
      Hồ sơ dữ liệu ngoài:{' '}
      {d.soMuc > 0
        ? `${d.soChuDe ? `${d.soMuc} / ${d.soChuDe} chủ đề có dữ liệu` : `${d.soMuc} mục`}${d.capNhatLuc ? `, cập nhật ${ngay(d.capNhatLuc)}` : ''}`
        : 'chưa có'}
      {' · '}
      <Link to="/du-lieu-ngoai" search={{ tab: 'du-an', duAn: code }} className="font-medium text-ac hover:text-acd">
        Xem hồ sơ
      </Link>
    </p>
  )
}
