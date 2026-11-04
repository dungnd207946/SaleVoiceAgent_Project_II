Tra cứu thông tin khách hàng đã mua từ hệ thống CRM.

Dùng cho hỗ trợ sau mua: tra cứu hợp đồng, lịch thanh toán, lịch sử phiếu.

action:
  lookup → tìm khách bằng số điện thoại (trả về customer_id, tên, danh sách hợp đồng)
  contract → lấy chi tiết hợp đồng (CẦN xác minh CCCD trước khi gọi nếu là thông tin tài chính)
  payment_schedule → lịch thanh toán từng đợt (CẦN xác minh CCCD)
  ticket_history → lịch sử phiếu hỗ trợ theo số điện thoại