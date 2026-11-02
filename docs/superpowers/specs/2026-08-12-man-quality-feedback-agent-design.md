# Màn Chất lượng (`/quality`) — phần CSAT: hiển thị feedback agent

**Ngày:** 2026-08-12 · **Trạng thái:** đã duyệt bố cục qua visual companion, chưa viết code.

## 0. Vì sao làm bây giờ

`src/lib/screens.ts` đã đặt sẵn màn `quality` (`path: '/quality'`, `owner: null`, `mvp: 'deferred'`, note _"Hoãn ngoài MVP — eval ⚠ · CSAT ✗. Lý do: phan-bien-prototype §19"_). Tài liệu đó (`docs/product/2026-07-28-phan-bien-prototype-va-dinh-huong-san-pham.md` §3) khuyến nghị hoãn CSAT vì **"Agent không thu feedback. Không có cơ chế đánh giá sau hội thoại"** — tiền đề chưa tồn tại.

Tiền đề đó nay đã có: backend (`odyssey-portal-backend`) đã ship `POST /api/v1/agent/feedback` (agent pod gọi bằng `Bearer api_key` sẵn có, rating 1-5 sao + comment tuỳ chọn, tenant suy từ khoá — không tin input client) và `GET /api/v1/agent/feedback` (session + `ACTIONS.CONVOS_READ`). Spec này viết đúng phần CSAT của `/quality` — phần eval (bộ kiểm thử hồi quy) VẪN hoãn, không thuộc phạm vi đây.

## 1. Vị trí trong FE

Hai chỗ:

- **`/quality`** — tổng quan: thống kê + danh sách feedback toàn workspace.
- **`/convos/$phone`** (trong `PhienKhach.tsx`) — feedback của đúng một phiên, hiện inline cạnh header phiên đó nếu có.

## 2. Backend — 3 việc nhỏ, additive, cần làm TRƯỚC khi viết FE

Cả ba đều mở rộng response/query có sẵn, không đổi hình dạng cũ, không breaking:

1. **`ops.contracts.PhienOut` thêm `phone: str | None`** — để FE suy `/convos/$phone` từ một `session_id` (hiện tại hoàn toàn thiếu, đã xác nhận query nội bộ có chọn cột này nhưng response không trả).
2. **`enrollment` — `GET /agent/feedback` thêm 2 tham số lọc tuỳ chọn**: `rating` (lặp lại, vd `?rating=1&rating=2`) và `session_id` (lọc đúng một phiên — dùng cho §7 của spec này, nhúng vào `PhienKhach.tsx`).
3. **`enrollment.contracts.FeedbackOut` thêm `customer_name: str | None` + `phone: str | None`** — lấy bằng `LEFT JOIN tenant_data.conversations c ON c.tenant_id = f.tenant_id AND c.session_id = f.session_id` trong `service.liet_ke_feedback_cua_tenant`. KHÔNG phải FK cứng (cùng lý lẽ `conversation_messages`: không gì đảm bảo hàng `conversations` luôn được ghi trước feedback). `NULL` cả hai khi không khớp ⇒ FE hiện "Khách ẩn danh".

Việc 1 và 3 cần thêm test canh cách ly tenant (JOIN không được lộ dữ liệu tenant khác) — mở rộng `test_feedback.py` đã có.

## 3. Bố cục `/quality` (đã duyệt qua mockup, xem `.superpowers/brainstorm/*/content/quality-overview-v3.html` nếu cần tham chiếu lại hình ảnh)

Một card (`rounded-xl border bg-surface`, cùng khung `Khung` của `KhachList.tsx`) gồm, từ trên xuống:

1. **Dải thống kê** — hai cột trong cùng một hàng, không kéo dài rời rạc: cột trái cố định ~220px (điểm trung bình lớn 28px + hàng sao + tổng lượt đánh giá bên dưới), cột phải là phân bố 5 sao dạng thanh ngang (mỗi thanh dài theo %, số đếm bên phải).
2. **Hàng chip lọc theo sao** — "Tất cả" + 5 chip (1★…5★), đa chọn, đẩy lên search param của route (cùng pattern `LocKhach` ở `convos.index.tsx`) — filter thật gọi `rating[]` ở API.
3. **Danh sách review dạng thẻ** (không phải bảng dày): mỗi feedback một khối — avatar chữ cái đầu tên, tên + số điện thoại ĐẦY ĐỦ (không che — xem §6) ở hàng đầu bên trái, sao + thời điểm căn phải; nhận xét ở dòng dưới (nghiêng, màu mờ nếu rỗng: "(không để lại nhận xét)"); chân khối có badge "Cần chú ý" (chỉ hiện khi rating ≤ 2) + link "Xem phiên trò chuyện →" (điều hướng kèm `session_id` — xem §4, không chỉ `phone`).
4. **Nút "Xem thêm"** cuối danh sách — gọi trang kế bằng `next_before_id` (keyset, không phải số trang).

Cỡ chữ khớp quy ước đo được từ code hiện có: tên `15px`, thân/nhận xét `14px`, chữ phụ/ngày `12-13px`, nhãn uppercase `11px`.

## 4. Deep-link tới ĐÚNG phiên, không chỉ đúng khách

**Phát hiện:** `phone` (mục 2.1) chỉ đủ để tới đúng KHÁCH — một khách có thể có nhiều phiên. `PhienKhach.tsx` hiện tại chọn phiên hiển thị bằng state cục bộ khởi tạo `null`:

```ts
const [chon, setChon] = useState<string | null>(null)
const sid =
  chon !== null && dsLoc.some((p) => p.sessionId === chon) ? chon : (dsLoc[0]?.sessionId ?? null)
```

Khi `chon` là `null` (luôn đúng lúc mới vào trang — route `/convos/$phone` không có cách nào truyền `session_id` vào), `sid` rơi về `dsLoc[0]` — phiên **mới nhất** của khách (danh sách sắp giảm dần). Nếu feedback đang xem là về một phiên CŨ hơn, link "Xem phiên trò chuyện →" sẽ mở nhầm phiên mới nhất mà không báo gì.

**Sửa (chỉ FE, không đụng backend thêm):**

1. Route `convos.$phone.tsx` thêm `validateSearch` cho `session?: string` — cùng pattern `convos.index.tsx` đã dùng cho bộ lọc `LocKhach`.
2. Đọc bằng `Route.useSearch()`, truyền xuống `<PhienKhach key={phone} phone={phone} phienMoDau={session} />` (prop mới).
3. `PhienKhach` khởi tạo `useState<string | null>(phienMoDau ?? null)` thay vì hardcode `null`.
4. Logic fallback hiện có (`dsLoc.some(...) ? chon : dsLoc[0]`) **giữ nguyên, không sửa thêm** — nó đã tự xử lý đúng ca "phiên đó không có trong tab đang lọc".
5. **Quyết định ca lỗi:** nếu `session_id` từ feedback không thực sự thuộc khách đó (dữ liệu lệch — hiếm), component im lặng rơi về phiên mới nhất, giữ đúng hành vi fallback đã có. KHÔNG thêm thông báo riêng cho ca này — một trạng thái UI mới cho một ca hiếm không đáng.

Link ở `FeedbackReviewCard.tsx`: `<Link to="/convos/$phone" params={{ phone }} search={{ session: sessionId }}>`.

## 5. Cấu trúc component (FE)

Feature folder mới `src/features/quality/`:

- **`api.ts`** — `danhSachFeedback(loc: LocFeedback)`: `useQuery` gọi `GET /agent/feedback` với `rating[]`/`before_id`/`limit`. `LocFeedback` đẩy lên search param của route `quality.tsx`, cùng pattern `LocKhach`.
- **`components/FeedbackTongQuan.tsx`** — dải thống kê (mục 3.1), nhận `total`, `theoSao: Record<1|2|3|4|5, number>`, `diemTrungBinh`.

  **Quyết định:** `DanhSachFeedbackOut` (BE) thêm `theo_sao: dict[str, int]` (khoá `"1".."5"`, JSON không cho khoá int) + `diem_trung_binh: float`, tính bằng MỘT câu `GROUP BY rating` + `AVG(rating)` chạy song song với câu đếm `total` đã có trong `service.liet_ke_feedback_cua_tenant` — không thêm request, không thêm endpoint.

  **Quan trọng:** `theo_sao`/`diem_trung_binh`/`total` LUÔN tính trên TOÀN BỘ feedback của tenant, **bỏ qua filter `rating` đang áp cho `items`** — nếu không, lọc "chỉ xem 1★" sẽ làm dải thống kê chỉ còn 100% 1-sao (vô nghĩa, mất tác dụng "nhìn tổng thể"). Chỉ `items` (danh sách thẻ bên dưới) mới bị filter.

- **`components/FeedbackList.tsx`** — chip lọc + danh sách thẻ + nút "Xem thêm".
- **`components/FeedbackReviewCard.tsx`** — một khối feedback (mục 3.3).
- **`components/ui/Sao.tsx`** (dùng chung, đặt ở `components/ui/` vì tái dùng ở `PhienKhach.tsx`) — hiển thị N/5 sao bằng icon `Star` (`lucide-react`), màu theo token theme (`--color-ac`), không hardcode hex.

Route `src/routes/_app/quality.tsx` thay `<ScreenStub screen="quality" />` bằng `<FeedbackList loc={...} datLoc={...} />` (cùng pattern `convos.index.tsx` render `<KhachList>`).

**`src/lib/screens.ts` — không phải "thêm màn mới".** Mục `quality` đã tồn tại (`inNav: true`, route đã có), nên KHÔNG cần 4 bước "Thêm một màn MỚI" của README/CLAUDE.md (screens.ts/nav.ts/nav-registry.ts/route đều đã sẵn). Chỉ cần sửa `note` (bỏ phần "CSAT ✗", giữ phần "eval ⚠" vì phần đó vẫn hoãn) và kiểm `tests/nav-registry.test.ts` xem có assertion nào đếm số màn "hoãn" cứng theo con số — nếu có, cập nhật theo đúng còn 1 lý do hoãn (eval) thay vì 2 (eval + CSAT). Trường `mvp` giữ `'deferred'` hay đổi `'full'` — quyết định lúc viết plan sau khi đọc đúng test đó, vì cờ này áp cho CẢ màn `/quality`, không tách được theo từng phần nội dung.

## 6. Tên/số điện thoại — KHÔNG che

Mockup minh hoạ che một phần ("Trần Văn A***", "090***4567") để gợi cảm giác "review Shopee" lúc dựng bố cục, nhưng **quyết định cuối: hiện ĐẦY ĐỦ**, không che — đây là công cụ nội bộ cho nhân viên vận hành xem dữ liệu khách hàng CỦA CHÍNH họ (không phải hiện công khai giữa những người lạ như Shopee), và `KhachRow.tsx`/`PhienKhach.tsx` (màn Hội thoại) đã hiện đầy đủ tên/sđt từ trước — che ở đây tạo ra một ngoại lệ khó hiểu, và cản đúng việc người vận hành cần làm với feedback "Cần chú ý": gọi lại khách. Tham chiếu Shopee chỉ áp dụng cho BỐ CỤC khối (avatar/tên/sao/ngày/nhận xét), không áp dụng cho việc che thông tin.

## 7. `PhienKhach.tsx` — feedback của một phiên

Gọi `GET /agent/feedback?session_id=...&limit=1`. Có thì hiện một dòng nhỏ (component `Sao.tsx` + comment rút gọn) cạnh header phiên. Không có thì không hiện gì — khác `/quality` (nơi trạng thái rỗng của TOÀN danh sách cần nói ra), ở đây thiếu feedback của MỘT phiên riêng lẻ là bình thường, không phải lỗi.

## 8. Kiểm thử

- **Backend**: mở rộng `test_feedback.py` (JOIN đúng `customer_name`/`phone`, kể cả khi `conversations` chưa có hàng khớp → NULL; filter `rating`/`session_id`; `PhienOut.phone` không lộ sang tenant khác).
- **Frontend**: repo chưa có Playwright (ghi rõ trong CLAUDE.md, mục "Cái CHƯA có") — không viết E2E. Dựa vào MSW mock cho `useQuery` nếu có sẵn quy ước test component; xác nhận lại lúc viết plan. Thêm test cho `convos.$phone.tsx`: mở kèm `?session=X` phải chọn đúng phiên X, không phải phiên mới nhất.

## 9. Ngoài phạm vi

- Phần "eval" (bộ kiểm thử hồi quy) của màn `/quality` — vẫn hoãn.
- Voice feedback (thu CSAT qua thoại) — tài liệu gốc đã nói khó, không giải quyết ở đây; feedback hiện chỉ tới từ agent pod gọi API, không phân biệt kênh chat/voice ở tầng lưu trữ.
- Xuất/export danh sách feedback (CSV...) — không ai yêu cầu, không thêm.

## 10. ⚠️ Thứ tự deploy — FE phụ thuộc backend CHƯA lên nhánh chính

Ba việc backend ở §2 (`customer_name`/`phone` trên feedback qua LEFT JOIN · filter `rating`/`session_id` ở `GET /agent/feedback` · `phone` trên `PhienOut`) sống trên một nhánh của `odyssey-portal-backend` **chưa push/merge** tính tới ngày viết dòng này (2026-08-12) — FE ở đây đã code xong phần đọc các field đó nhưng chưa xác nhận được nhánh backend đã lên `main`.

**Nếu FE deploy trước:** phần lớn màn xuống cấp AN TOÀN — thiếu `customer_name`/`phone` thì `chuanHoaFeedback` coi là `null` (hiện "Khách ẩn danh", ẩn nút "Xem phiên trò chuyện →"); thiếu filter `rating`/`session_id` ở backend thì query param bị bỏ qua, `/quality` chỉ mất tác dụng lọc, không lỗi. **NGOẠI LỆ DUY NHẤT, và nó SAI THẦM LẶNG:** nếu backend chưa nhận `session_id`, `feedbackCuaPhien()` (gọi `GET /agent/feedback?session_id=...&limit=1`) sẽ nhận về feedback MỚI NHẤT của cả tenant bất kể tham số đó — và `PhienKhach.tsx` gắn nó vào header của MỌI phiên đang xem, tức hiện đúng một sao/comment nhưng gắn nhầm cho hội thoại khác, không có lỗi/cảnh báo nào trên màn để nhận ra.

Kết luận: merge backend nhánh đó **trước** khi bật `/quality`/hiện feedback trên `/convos/$phone` ở production; nếu buộc phải đi trước, tắt tạm phần hiện feedback trong `PhienKhach.tsx` cho tới khi xác nhận `session_id` đã lọc đúng ở backend.
