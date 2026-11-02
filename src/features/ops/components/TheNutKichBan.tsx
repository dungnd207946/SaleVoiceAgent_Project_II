import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { docDe, useTenKichBan } from '@/features/kich-ban/contracts'
import type { NhanKichBan } from '../nhanKichBan'

function Dong({ nhan, ds }: { nhan: string; ds: string }) {
  return (
    <>
      <dt className="text-muted-3">{nhan}</dt>
      <dd>{ds}</dd>
    </>
  )
}

export function TheNutKichBan({ nhan }: { nhan: NhanKichBan }) {
  const [mo, setMo] = useState(false)
  // Tên tình huống như `/kich-ban` in, không mã thô; chữ classifier ghi (đã làm / còn
  // thiếu…) có thể chứa tên tool + mã nút ⇒ dịch bằng CÙNG `docDe` của màn đó.
  const kb = useTenKichBan()
  const ten = (id: string) => kb.ten[id] ?? id
  const doc = (ds: string[]) => ds.map((s) => docDe(s, kb.ten)).join('; ')
  const buoc = nhan.buoc ? kb.buoc(nhan.nut, nhan.buoc) : null
  // Kết quả bằng CHỮ, không ✓/✗: hai ký tự đó chỉ khác nhau ở hình, trình đọc màn hình
  // đọc «check mark» / «multiplication sign».
  const ketQua = nhan.loi
    ? 'chưa chấm được'
    : nhan.dat === true
      ? 'Đạt'
      : nhan.dat === false
        ? 'Chưa đạt'
        : 'chưa chấm'
  return (
    <div
      data-testid="the-nut"
      className="max-w-[76%] self-start rounded-lg border border-border bg-acs px-3 py-1.5 text-[12px] text-muted"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span>Kịch bản</span>
        <Link to="/kich-ban" search={{ nut: nhan.nut }} className="font-semibold text-fg underline">
          {ten(nhan.nut)}
        </Link>
        {buoc && <span>· {buoc}</span>}
        <span className="text-fg">{ketQua}</span>
        <button
          type="button"
          onClick={() => setMo(!mo)}
          aria-expanded={mo}
          className="ml-auto text-muted-2"
        >
          {mo ? 'Ẩn chi tiết' : 'Xem chi tiết'}
        </button>
      </div>
      {mo && (
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-2 border-t border-border-soft pt-1.5">
          {nhan.daLam.length > 0 && <Dong nhan="Đã làm" ds={doc(nhan.daLam)} />}
          {nhan.thieu.length > 0 && <Dong nhan="Còn thiếu" ds={doc(nhan.thieu)} />}
          {nhan.viPhamCam.length > 0 && <Dong nhan="Phạm cấm" ds={doc(nhan.viPhamCam)} />}
          {nhan.thieuDuLieu && <Dong nhan="Dữ liệu" ds="thiếu dữ liệu để làm đúng" />}
          {nhan.jevNut && nhan.jevNut !== nhan.nut && (
            <Dong nhan="Agent chọn" ds={ten(nhan.jevNut)} />
          )}
          {nhan.doTin !== null && <Dong nhan="Độ tin" ds={`${Math.round(nhan.doTin * 100)}%`} />}
        </dl>
      )}
    </div>
  )
}
