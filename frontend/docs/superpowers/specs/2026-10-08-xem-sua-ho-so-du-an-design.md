# Hồ sơ dự án: chế độ xem dạng chữ và bố cục lại các tab

Ngày: 2026-10-08 · Trạng thái: đã duyệt · Phạm vi: portal-frontend (`/pform`, `/uform`) và một trường ở portal-backend

Mockup đã duyệt: `~/Desktop/mockup-kien-thuc-du-an.html` trên máy người làm (không commit vì nhúng ảnh, 2,7 MB). Dữ
liệu trong mockup là dự án Masteri Grand Coast của workspace `aina_demo` ở local.

## Mục tiêu

Màn hồ sơ dự án dễ đọc hơn. Khi chưa bấm Sửa, giá trị hiện dạng chữ, không còn ô nhập bị khoá. Bấm Sửa thì hiện ô
nhập, dấu bắt buộc và các nút thêm, sửa, xoá; mỗi ô vẫn tự lưu khi rời ô như hôm nay.

Đạt khi: mở một dự án ở chế độ xem, các tab trong phạm vi và ba màn chi tiết (phân khu, toà, căn) không có
`input`, `select`, `textarea` nào; bấm Sửa thì có đủ ô như hiện tại.

## Quyết định (người dùng chốt qua mockup, 2026-10-08)

1. Một nút Sửa/Xong cho cả màn, đặt cuối hàng tab, luôn thấy khi cuộn. Bỏ thanh dán ở đáy (`DayTuLuu`). Khi đang sửa:
   giờ lưu gần nhất hiện cạnh nút, và một dải báo «Đang sửa dự án» nằm dưới hàng tab. `/uform` dùng cùng nút ở cùng
   chỗ. Chỉ báo nạp kiến thức (`KbBadge`, đang ở thanh đáy) chuyển lên cạnh nút Sửa, chỉ hiện khi đang nạp hoặc lỗi,
   để lỗi nạp vẫn thấy được ở mọi tab.
2. Hàng tab giữ kiểu thanh hiện tại (`NhomTab`), nằm ngay dưới tên dự án. Tab không có số đếm.
3. Đầu trang: breadcrumb `Kiến thức › Dự án`, tên dự án làm tiêu đề, dòng phụ gồm mã dự án (chữ mono), chip giai
   đoạn bán và chip loại hình. Chip trạng thái (Đã phát hành ▾) nằm bên phải tiêu đề. Không có dải ô thông tin tóm
   tắt.
4. Tiêu đề mỗi phần (thẻ): chữ in hoa 12,5px đậm, giãn chữ 0,06em, màu chữ chính (`n10`). Sau chữ là một đường kẻ
   mảnh kéo tới mép thẻ. Nút của thẻ (Xem ảnh lớn, Thêm ảnh…) nằm cuối đường kẻ. Tab chỉ có một phần thì không lặp
   tên tab làm tiêu đề: Mặt bằng, Ảnh 360, Phân khu, Toà.
5. Số hiện kèm đơn vị: dấu chấm hàng nghìn, dấu phẩy thập phân, đơn vị đứng sau số (72.498 m², 13.500 tỷ đồng,
   16.500 đ/m²/tháng). Nhãn ô bỏ phần đơn vị trong ngoặc. Ở chế độ sửa, đơn vị nằm cuối ô nhập.
6. Ảnh cover, bản đồ vị trí và mặt bằng: bấm vào là xem cỡ lớn, dùng lại `AnhLon` (có ‹ › khi nhiều ảnh). Bản đồ và
   mặt bằng chiếm hết chiều ngang thẻ, không cắt ảnh.
7. Tiến độ và Media giữ nguyên như hiện tại, kể cả nút sửa, xoá trên ảnh luôn hiện.

## Từng tab

**Tổng quan** — hai cột. Cột chính: Thông tin chung (tên thương mại, trạng thái kinh doanh, loại hình, chủ đầu tư,
đơn vị phát triển, mã dự án), Giới thiệu dự án (gập ở 6 dòng, nút Xem thêm), Tiện ích, Quy mô và mật độ, Phí dịch
vụ, Sở hữu và bàn giao (tiêu chuẩn bàn giao là bảng 3 cột: hạng mục; vật liệu, thiết bị, ghi chú ở dòng phụ;
thương hiệu, xuất xứ ở dòng phụ). Cột phải: Ảnh cover (nút Xem ảnh lớn; khi sửa là Thay ảnh, Xoá), Kiến thức cho
agent (thanh `done/total` mục, hồ sơ dữ liệu ngoài, nút Nạp lại; đang nạp và lỗi nạp chỉ báo ở đầu trang theo
quyết định 1, thẻ không nhắc lại), Cập nhật (ngày tạo, giờ sửa lần cuối). Ảnh cover lấy theo `coverMediaId` trong
danh sách media của dự án (query `['re', code, 'media']` sẵn có).

**Vị trí** — thẻ Vị trí dự án (khu vực, địa chỉ; khu vực dạng mã như `mien_nam` hiện thành «Miền Nam» ở chế độ
xem) và thẻ Bản đồ vị trí: ảnh to hết chiều ngang, mô tả ngay dưới, link Mở ảnh gốc; khi sửa có Thêm ảnh, Sửa mô
tả, Xoá.

**Ảnh 360** — không tiêu đề. Khung xem rộng hết thẻ như hôm nay; dưới khung là tên miền của link, Toàn màn hình,
Mở ở tab mới. Ô link và nút Xoá link chỉ có khi đang sửa.

**Mặt bằng** — không tiêu đề. Ảnh chính to hết chiều ngang, mô tả, Mở ảnh gốc, dải ảnh nhỏ để chuyển ảnh. Khi sửa
có Thêm ảnh, Sửa mô tả, Xoá.

**Phân khu** — bảng không có dòng tiêu đề: Phân khu, Loại hình, Toà, Căn đã nhập, Tổng số căn, Giai đoạn bán. Bỏ
dòng mã UUID dưới tên. Xếp theo tên. Bấm một hàng mở màn chi tiết. Nút Thêm phân khu và cột Sửa, Xoá chỉ hiện khi
đang sửa. Cột Toà ghép từ danh sách toà sẵn có.

**Chi tiết phân khu** — link ‹ Danh sách phân khu; tên phân khu kèm chip giai đoạn bán; dòng phụ là mã phân khu và
giờ sửa lần cuối. Cột chính: Thông tin phân khu (tên, loại hình, giai đoạn bán, tổng số căn, số toà, căn đã nhập
chỉ đọc, quy mô phân khu), Vị trí và tiện ích, Tổng quan phân khu. Cột phải: Ảnh cover, Mặt bằng phân khu (ảnh lấy
theo `coverMediaId`/`mapMediaId` như ở dự án).

**Toà** — bảng không có dòng tiêu đề: Toà, Phân khu, Số tầng, Thang máy (`4 khách · 2 hàng`), Căn đã nhập, Giai
đoạn bán. Xếp theo mã toà. Màn chi tiết: link ‹ Danh sách toà; «Toà L1» kèm chip; dòng phụ là phân khu và giờ sửa
lần cuối. Thẻ Thông tin toà (mã toà chỉ đọc, tên, phân khu, giai đoạn bán, hướng, căn đã nhập chỉ đọc), Thông số kỹ
thuật (8 ô số, 4 cột), Mô tả và tiện ích.

**Quỹ căn** — dòng tóm tắt (tổng căn, còn hàng, đã bán; thêm đã cọc khi lớn hơn 0), bộ lọc như hiện tại, bảng: Mã
căn, Toà, Loại, PN, DT thông thuỷ, Hướng, Giá (tỷ), Trạng thái bán, Phát hành. Cột Phát hành để trống với căn đã
phát hành; căn bản nháp hoặc đã lưu trữ hiện chip trạng thái đó (người dùng chốt 2026-10-09, thay cho chip cạnh mã
căn). Số đếm của dòng tóm tắt lấy từ `total` của danh sách có lọc `sale_status`, `limit=1`.

**Dự án chưa có toà nào** (người dùng chốt 2026-10-09): bảng Quỹ căn và bảng Phân khu bỏ cột Toà, màn chi tiết căn
bỏ ô Toà. Căn cứ là danh sách toà của dự án, không phải loại hình: dự án ghi loại hình biệt thự vẫn có thể có toà
condotel. Tab Toà vẫn giữ để thêm toà đầu tiên.

**Chi tiết căn (`/uform`)** — link ‹ Quỹ căn; «Căn C5Z2-14-13» kèm chip trạng thái bán; dòng phụ là phân khu, toà,
tầng, giờ sửa lần cuối. Thông tin căn (mã căn, loại sản phẩm, phân khu chỉ đọc; toà, tầng, số tầng của căn, số
phòng ngủ, hướng, trạng thái bán), Diện tích và giá (thông thuỷ, tim tường, ban công và logia với cao tầng, diện
tích đất với thấp tầng; giá bán dạng `5,95 tỷ đồng` kèm số đầy đủ ở dòng phụ; đơn giá dạng `72,28 triệu/m²`), Đặc
điểm căn, và với thấp tầng thêm thẻ Kích thước lô (mặt tiền, chiều sâu lô, đường trước nhà). Cột phải: Ảnh căn.

**Tài liệu** — giữ bộ lọc và bảng hiện tại, thêm cột Cập nhật, cột Tệp ghi loại tệp (PDF…) thay cho «có», số ký tự
có dấu chấm hàng nghìn. Nút Thêm tài liệu và cột Sửa, Xoá chỉ hiện khi đang sửa.

## Lệch so với hiện tại cần biết

- Vị trí và Mặt bằng chỉ hiện mô tả ảnh, không hiện tên tệp. Điều này lệch quyết định 2026-08-25 «luôn ưu tiên
  show tên tệp trước» ghi trong `VungMedia.tsx`. Tiến độ và Media vẫn giữ tên tệp.
- Mockup có dòng «Nạp gần nhất» trong thẻ Kiến thức cho agent; API trạng thái nạp chưa có giờ nạp nên bỏ dòng này.
- Tab Phân khu thôi chia trang: tải một lần tối đa 200 phân khu (như tab Toà tải hết toà) để xếp được theo tên.

## Backend (portal-backend)

`PhanKhuOut` thêm `unitCount: int` (số căn có `zone_code` của phân khu, đếm như `ToaOut.unitCount`), trả ở danh
sách và ở bản đọc một phân khu. Chỉ thêm trường; FE khai trường này tuỳ chọn. Test: phân khu có 2 căn trả
`unitCount = 2`, phân khu chưa có căn trả 0.

## Cách làm ở frontend

- Ô nhập trong `components/ui/Truong.tsx` (`OChu`, `OSo`, `OChon`, `OChonNhieu`) khi nhận `khoa` thì dựng bản xem:
  nhãn và giá trị dạng chữ, «—» khi trống, thay cho ô bị khoá. Các form đã truyền `khoa={!dangSua}` nên chế độ xem
  đổi ở một chỗ cho cả màn. `OSo` nhận thêm đơn vị để định dạng số và để hiện cuối ô nhập. `OMedia` khi khoá chỉ
  hiện ảnh (bấm mở `AnhLon`), không hiện nút chọn tệp.
- `NhomTruong` đổi sang kiểu tiêu đề ở quyết định 4 và nhận thêm phần nút ở cuối đường kẻ.
- `DauDuAn` dựng đầu trang mới, giữ `NhomTab`, thêm nút Sửa/Xong, giờ lưu và dải báo đang sửa. Cờ đang sửa
  (`khungSua`) dùng chung cho `/pform` và `/uform`. `CanForm` bỏ cờ riêng; với căn đang có thì bỏ thanh nút đáy,
  với căn mới thì giữ nút Tạo căn. Tạo dự án qua ô đặt tên xong thì vào thẳng chế độ sửa của dự án đó.
- Bảng Phân khu, Toà, Quỹ căn, Tài liệu và bảng bàn giao: nút thêm, sửa, xoá chỉ hiện khi đang sửa; ở chế độ xem,
  bấm hàng mở chi tiết, cuối hàng có dấu ›.
- `VungMedia` bố cục `gallery` (chỉ Vị trí, Mặt bằng dùng) đổi theo thiết kế trên. Bố cục `moc` và `luoi` (Tiến độ,
  Media) không đổi.

## Ngoài phạm vi

- Media gắn với phân khu hiện không hiện ở đâu trong portal; không làm ở đây.
- Lỗi dữ liệu fake của `aina_demo` (quy mô ghi «72498 ha», địa chỉ lặp tên xã, tỉnh, tên phân khu Z1 thiếu ngoặc):
  sửa riêng ở dữ liệu.

## Kiểm

- Test FE cho từng tab trong phạm vi và ba màn chi tiết: chế độ xem không có `input`, `select`, `textarea`; bấm Sửa
  thì có; ô số hiện đúng định dạng và đơn vị.
- Test FE: bấm ảnh cover, bản đồ, mặt bằng mở `AnhLon`; tab Tiến độ và Media không đổi (test sẵn có vẫn xanh).
- `npm run build` (dùng `tsc -b`, bắt được lỗi kiểu mà `tsc --noEmit` bỏ sót) và `npm test`.
- Backend: test `unitCount`; `make check`.
- Soát bằng mắt trên `aina_demo` ở local, so với mockup.
