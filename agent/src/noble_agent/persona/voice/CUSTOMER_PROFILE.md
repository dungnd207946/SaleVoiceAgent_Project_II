## Hồ sơ khách hàng (đã có)

{%- if customer.name or customer.full_name %}
- Tên: {{ customer.full_name or customer.name }}
{%- endif %}
{%- if customer.gender %}
- Giới tính: {% if customer.gender == "M" %}Nam{% elif customer.gender == "F" %}Nữ{% else %}{{ customer.gender }}{% endif %}
{%- endif %}
{%- if customer.phone %}
- Điện thoại: {{ customer.phone }}
{%- endif %}
{%- if customer.is_noble_customer is not none %}
- Đã là khách Noble: {% if customer.is_noble_customer %}có{% else %}chưa{% endif %}
{%- endif %}
{%- if customer.noble_info %}
- Thông tin thêm (email/sinh nhật/ghi chú Noble): {{ customer.noble_info }}
{%- endif %}
{%- if customer.project_interest %}
- Dự án quan tâm: {{ customer.project_interest }}
{%- endif %}
{%- if customer.budget %}
- Ngân sách: {{ customer.budget }}
{%- endif %}
{%- if customer.preferred_area %}
- Diện tích/khu vực mong muốn: {{ customer.preferred_area }}
{%- endif %}
{%- if customer.bedroom_count %}
- Số phòng ngủ: {{ customer.bedroom_count }}
{%- endif %}
{%- if customer.notes %}
- Ghi chú bối cảnh: {{ customer.notes }}
{%- endif %}

