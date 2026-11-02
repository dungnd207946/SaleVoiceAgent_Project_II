# YÊU CẦU: Xây dựng hệ thống Multi-agent cho ứng dụng tư vấn bất động sản realtime

## Bối cảnh
Tôi cần một hệ thống multi-agent gồm 3 agent xử lý hội thoại với khách hàng bất động sản:
- **Manager Agent (MA):** điều phối trung tâm. Trả lời chitchat/câu hỏi chung và định tuyến (route) đến hai subagent.
- **Consultant Agent (CA):** tư vấn bán hàng (giới thiệu dự án, tư vấn căn hộ theo ngân sách/nhu cầu).
- **Support Agent (SA):** hỗ trợ khách hàng (kiểm tra hồ sơ, giấy phép, thủ tục).

Ứng dụng chạy realtime nên latency phải thấp.

## Vấn đề cốt lõi cần giải quyết (RẤT QUAN TRỌNG)
Kiến trúc router thông thường bị MẤT CONTEXT trong hội thoại multi-turn. Kịch bản lỗi:
khách nói "muốn mua nhà 3 tỉ cần tư vấn" → route vào CA → CA cần thêm SĐT → CA trả control
về MA để hỏi → user gửi "0901234567" → router phân loại lại tin nhắn này, thấy nó không
giống yêu cầu tư vấn nên route sai chỗ, đồng thời context "căn nhà 3 tỉ" và suy luận dở
của CA bị mất.

Hệ thống mới PHẢI khắc phục triệt để lỗi này.

## Ba nguyên tắc thiết kế bắt buộc

### 1. Shared Session State (một nguồn sự thật duy nhất)
Không agent nào được giữ context riêng trong bộ nhớ cục bộ. Tạo một đối tượng state dùng
chung cho cả 3 agent, lưu trong store nhanh (sử dụng Redis) theo session_id, được chia làm 3 loại bao gồm:
- session:{sid}:meta: dùng để lưu metadata cuộc gọi bao gồm: session_id, started_at, last_active, phone, active_agent
- session:{sid}:customer: dùng để lưu trữ hồ sơ khách hàng trong cuộc gọi bao gồm name, gender, phone, project_interest, budget, preferred_area, bedroom_count, is_noble_customer, noble_info, full_name -> Những thông tin này sẽ được nạp từ CRM khi service agent được khởi động hoặc sẽ được nạp bởi agent trong quá trình trò chuyện bởi các thông tin do agent trích xuất.
- session:{sid}:state: Toàn bộ lịch sử hội thoại (history), agent_scratchpad, summary

Trong đó một số thông tin được làm rõ sau:
- active_agent: agent đang sở hữu cuộc hội thoại (MA/CA/SA hoặc rỗng)
- agent_scratchpad: phần suy luận dở của agent, cũng lưu trong state chung
Khi handoff giữa các agent, KHÔNG có gì bị mang theo riêng nên không thể mất context.

### 2. Active-agent stickiness (định tuyến dựa trên TRẠNG THÁI, không dựa trên tin nhắn)
Mỗi lượt user gửi tin, orchestrator kiểm tra Shared State TRƯỚC KHI gọi router:
- NẾU đang có active_agent và pending_slot != rỗng → route THẲNG tin nhắn vào agent đó,
  BỎ QUA router LLM. Ghi giá trị user cung cấp vào slots và đẩy lại agent với nguyên vẹn
  slots + scratchpad.
- NẾU không có active_agent đang chờ → mới gọi MA router để phân loại intent và định tuyến.
Một khi đã vào CA hoặc SA, agent đó "sở hữu" cuộc hội thoại cho tới khi TỰ tuyên bố xong việc.

### 3. Handoff có cấu trúc, BỎ HẲN anti-pattern "fallback về MA để hỏi thêm"
Agent nào cần thông tin thì TỰ hỏi user trực tiếp và tự thu thập, tuyệt đối không trả
control về MA chỉ để đi hỏi hộ. Sau khi xử lý, agent rơi vào đúng 1 trong 2 trạng thái:
- Thiếu thông tin → GIỮ nguyên active_agent, hỏi user trực tiếp.
- Phát hiện request ngoài phạm vi → bàn giao về Agent phù hợp hoặc MA một summary có cấu trúc (không
  đẩy user về router trắng tay) → được thực hiện thông qua function switch_agent.


## Quy tắc handoff của agent
Đừng tóm tắt mỗi turn — sẽ phát sinh round-trip LLM thừa. Quy tắc:
- Trong cùng một agent (CA chạy N turn liên tiếp): giữ full history của CA, không biến đổi gì cả. Liên tục tuyệt đối, không tốn thêm gì (lịch sử lấy trong session:{sid}:state).
- Chỉ tại ranh giới handoff (CA → SA): mới sinh briefing + biến đổi tool call. Handoff là sự kiện hiếm so với số turn, nên thêm một lần gọi nhỏ ở đây gần như không ảnh hưởng latency cảm nhận. Briefing nên được cache vào state để nếu sau đó quay lại agent đó còn dùng lại.
- Chiến lược handoff:
+ Coi mỗi agent như một thread hội thoại riêng
+ khi chuyển từ agent thì load lại full thread hội thoại của nó (nếu history ngắn) + handoff summary của agent phát lệnh chuyển tiếp để thực hiện tiếp cuộc hội thoại. Nếu history dài thì thread của agent sẽ được summary lại tự động một cách bất đồng bộ trong quá trình Agent khác đặc thực hiện.
Ví dụ:
CA->SA->CA: thì khi chuyển từ SA -> CA history của CA sẽ được khôi phục lại nếu như số turn < K, nếu số turn > K thì trong quá trình SA làm việc của mình history của CA được summary bất đồng bộ và lưu vào redis, khi chuyển từ SA -> CA thì load lại summary này + handoff để tiếp tục công việc.

## Format prompt
- Trước khi bắt đầu cuộc hội thoại thì load đầy đủ các thông metadata, customer từ session
- Khi chuyển agent thì phải để phần scratchpad briefing summary vào trong prompt