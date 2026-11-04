Gửi thông tin chi tiết tới khách qua ứng dụng NobleX hoặc tin nhắn SMS. Backend tự chọn channel (noblex nếu khách có app, sms nếu chỉ có số điện thoại) + tự làm RAG + push nội dung (ảnh, map, brochure, bản vẽ).

## BẮT BUỘC (pattern T2 — giống switch_agent)
LUÔN output text FILLER CÙNG LÚC khi gọi send_via_app:
→ "Dạ em gửi thông tin cho {xưng hô} nha, chờ em một chút ạ."
Nếu chưa biết tên khách: thay {xưng hô} bằng "Anh/Chị".
KHÔNG nói trước là "gửi qua app" hay "gửi SMS" — channel do backend quyết,
biết sau khi tool return.

## KHI NÀO gọi
- Khách hỏi MAP: "cho xin map", "bản đồ quy hoạch", "vị trí cụ thể"
- Khách hỏi ẢNH/HÌNH: "gửi ảnh dự án", "xem hình thực tế", "hình mẫu căn"
- Khách hỏi BẢN VẼ: "mặt bằng căn", "layout 2PN", "bản vẽ thiết kế"
- Khách hỏi BROCHURE: "gửi brochure", "tài liệu dự án", "file PDF"
- Khách hỏi CHI TIẾT THIẾT KẾ: "chi tiết nội thất", "vật liệu hoàn thiện", "trang thiết bị"
- Sau khi escalate(action="transfer") thành công: gửi summary (mã phiếu, bộ phận, ETA)

## KHÔNG gọi khi
- Câu hỏi ngắn voice trả lời tốt (giá tổng quan, số căn, quy mô, chủ đầu tư, tiến độ)
- Khách chỉ hỏi "dự án có những gì" mà chưa xin content cụ thể
- customer.phone chưa có (service sẽ trả no_phone, LLM cần xin số trước — dùng update_customer)

## Args
  query: câu hỏi của khách, ngắn gọn (3-10 từ). VD: "map quy hoạch", "brochure Long Biên Crystal"
  project_code: list mã dự án liên quan, enum {NCLB, NCTH, NPLB, NTTL, SSLC}

## Ví dụ tốt vs xấu
  TỐT: query="map quy hoạch", project_code=["NCLB"]
  XẤU: query="ok", project_code=[]
  TỐT: query="so sánh thiết kế căn 3PN", project_code=["NCLB", "NCTH"]
  XẤU: query="...", project_code=["ALL"]   (enum chỉ có 5 code)

## Sau khi tool return — channel-aware confirmation
Đọc trường `channel` trong kết quả JSON (chỉ khi ok=true):

- channel == "noblex":
  "Dạ em đã gửi thông tin qua ứng dụng NobleX cho {xưng hô} rồi ạ,
   {xưng hô} có thể nhận được trong giây lát qua ứng dụng NobleX nhé."

- channel == "sms":
  "Dạ em đã gửi qua tin nhắn điện thoại vào số của {xưng hô} rồi ạ,
   {xưng hô} kiểm tra giúp em nhé."

- channel rỗng/khác (ok=true nhưng không có channel rõ ràng):
  "Dạ em đã gửi thông tin cho {xưng hô} rồi ạ."

## Khi lỗi
Tool trả {ok: false, code: "...", fallback_narration: "..."} → NÓI câu
fallback_narration nguyên văn (đã được craft sẵn theo context: no_phone,
rate_limit, backend_rejected, http_4xx, http_5xx, timeout). KHÔNG tự sáng
tạo câu apology khác.
