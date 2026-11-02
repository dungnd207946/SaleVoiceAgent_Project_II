Chuyển xử lý sang agent AI chuyên biệt khác (nội bộ). Khách hàng KHÔNG biết có nhiều AI agent — đây là chuyển ẨN.

## TUYỆT ĐỐI KHÔNG NÓI KHI GỌI switch_agent
- "chuyển cuộc gọi" — NGHIÊM CẤM
- "chuyển sang chuyên viên tư vấn" — NGHIÊM CẤM
- "chuyển sang bộ phận" — NGHIÊM CẤM
- "em đã chuyển cuộc gọi của {Xưng hô}" — NGHIÊM CẤM
Các cụm từ "chuyển chuyên viên" CHỈ dùng khi gọi escalate(action="transfer") — chuyển NGƯỜI THẬT.

## CÂU NÓI ĐÚNG (output CÙNG LÚC với switch_agent)
→ consultant: "Dạ để em tìm hiểu thông tin [dự án/giá/đặt lịch] cho {xưng hô} ạ."
→ support:    "Dạ em sẽ kiểm tra thông tin [hợp đồng/bảo hành] cho {xưng hô} ạ."
→ router:     "Dạ, {xưng hô} còn cần em hỗ trợ gì nữa không ạ?"
Nếu chưa biết tên khách, thay {xưng hô} bằng "Quý Khách".

## KHÔNG GỌI switch_agent khi
- target == agent hiện tại (VD: consultant gọi switch_agent("consultant") = TỰ GỌI CHÍNH MÌNH → KHÔNG ĐƯỢC)
- Bạn đã xử lý được câu hỏi trực tiếp bằng tool khác (noble_search, get_project_financial, crm_lookup...)

## Phân biệt switch_agent vs escalate
- switch_agent = chuyển giữa AI agents (ẨN, khách không biết)
- escalate(action="transfer") = chuyển sang NGƯỜI THẬT (NÓI RÕ cho khách)

## Cách dùng
  agent_id: "consultant" | "support" | "router"
  query: tóm tắt nhu cầu khách (bao gồm: tên KH nếu biết, dự án, yêu cầu cụ thể, context)

## Ví dụ query tốt vs xấu
  TỐT: "Anh Cường hỏi căn 3PN dưới 10 tỷ tại NCLB, mua để ở"
  XẤU: "hỏi giá"
  TỐT: "KH đã mua tại NCTH, hỏi tiến độ bàn giao, lo lắng bị trễ"
  XẤU: "hỗ trợ sau mua"
