Quản lý quy trình chuyển tiếp khách tới chuyên viên.

action:
  check_state → kiểm tra đã có tên và số điện thoại khách chưa, và có đang trong giờ làm việc không
  transfer → thực hiện chuyển tiếp (cần reason, department, priority)

department: CVTV, CSKH, Kỹ thuật, Pháp lý, Quản lý KD, Kế toán, Bàn giao, Thủ tục
priority: normal, high, urgent

LUÔN gọi check_state trước để biết cần hỏi thêm thông tin gì.
LUÔN nói lý do chuyển cho khách nghe trước khi gọi transfer.