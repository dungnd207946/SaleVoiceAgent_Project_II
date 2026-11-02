Lấy thông tin tài chính dự án từ database: bảng giá, thanh toán, vay, ưu đãi, phí.

Dùng khi khách hỏi giá cụ thể, chính sách thanh toán, lãi suất vay, ưu đãi đang có, hoặc phí bảo trì.
PHẢI có project_code trước khi gọi. Nếu khách chưa nói dự án → hỏi trước.

info_type:
  pricing → bảng giá theo loại căn
  payment_plans → chính sách thanh toán, mốc thanh toán
  loan_policies → ngân hàng đối tác, lãi suất, tỷ lệ vay
  promotions → ưu đãi đang còn hiệu lực
  fees → phí bảo trì, phí dịch vụ, VAT, phí giữ chỗ