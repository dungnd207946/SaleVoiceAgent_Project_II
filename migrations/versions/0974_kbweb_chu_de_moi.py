"""Chủ đề mặc định: thêm «Tiềm năng tăng giá», «Thanh khoản và nhu cầu»; câu tìm bài và từ khoá mới.

Chỉ cập nhật chủ đề mặc định mà workspace CHƯA tự sửa (từ khoá + câu tìm còn đúng bản `0971`), không đè
bản người dùng đã đổi. Workspace tạo sau migration này nhận bộ mới qua trigger `tenants_tao_kbweb_mac_dinh_v2`
(tên xếp sau trigger của `0971` nên chạy sau nó). Số đóng băng ở đây, không import `portal.*`.

Revision ID: 0974_kbweb_chu_de_moi
Revises: 0973_kbweb_billing
"""

from alembic import op

revision = "0974_kbweb_chu_de_moi"
down_revision = "0973_kbweb_billing"
branch_labels = None
depends_on = None

# (code, keywords cũ, queries cũ, keywords mới, queries mới)
# fmt: off
_UPDATES = (
    ('road', ['đường', 'đại lộ', 'cao tốc', 'vành đai', 'quốc lộ', 'nút giao'], ['hạ tầng giao thông đường bộ quanh {project}', '{location} đường vành đai cao tốc tiến độ'], ['đường', 'đại lộ', 'cao tốc', 'vành đai', 'quốc lộ', 'nút giao', 'tỉnh lộ', 'mở rộng đường', 'thông xe', 'trục đường'], ['{location} đường vành đai cao tốc', '{location} mở rộng đường quốc lộ', '{project} kết nối giao thông đường bộ', '{location} nút giao tiến độ thi công']),  # noqa: E501
    ('bridge', ['cầu', 'vượt sông'], ['cầu mới gần {location} tiến độ', '{project} cầu kết nối'], ['cầu', 'vượt sông', 'thông xe', 'khởi công cầu', 'hợp long'], ['cầu mới {location}', '{location} cầu vượt sông tiến độ', '{project} cầu kết nối', '{location} khởi công cầu']),  # noqa: E501
    ('transit', ['metro', 'đường sắt đô thị', 'brt', 'xe buýt'], ['metro đường sắt đô thị {location}', 'tuyến xe buýt {location}'], ['metro', 'đường sắt đô thị', 'brt', 'xe buýt', 'ga', 'nhà ga', 'tàu điện', 'đường sắt'], ['metro đường sắt đô thị {location}', '{project} gần ga metro', 'tuyến xe buýt {location}', '{location} tuyến BRT đường sắt tiến độ']),  # noqa: E501
    ('travel_time', ['phút', 'km', 'trung tâm', 'sân bay'], ['{project} cách trung tâm bao nhiêu km', 'từ {location} đến sân bay Nội Bài mất bao lâu', 'vị trí {project} kết nối giao thông'], ['phút', 'km', 'trung tâm', 'sân bay', 'thời gian di chuyển', 'kết nối', 'khoảng cách'], ['{project} cách trung tâm bao nhiêu km', 'vị trí {project} kết nối giao thông', 'từ {location} vào trung tâm mất bao lâu', '{location} đi sân bay mất bao lâu']),  # noqa: E501
    ('education', ['trường', 'mầm non', 'tiểu học', 'thcs', 'thpt', 'đại học'], ['trường học gần {location}', 'trường quốc tế {location}'], ['trường', 'mầm non', 'tiểu học', 'thcs', 'thpt', 'đại học', 'trường quốc tế', 'liên cấp', 'học sinh'], ['trường học gần {location}', '{project} gần trường học', 'trường quốc tế {location}', 'trường mầm non tiểu học {location}']),  # noqa: E501
    ('healthcare', ['bệnh viện', 'phòng khám', 'trạm y tế'], ['bệnh viện gần {location}', 'bệnh viện đa khoa {location}'], ['bệnh viện', 'phòng khám', 'trạm y tế', 'bệnh viện quốc tế', 'cơ sở y tế', 'khám chữa bệnh'], ['bệnh viện gần {location}', '{project} gần bệnh viện', 'bệnh viện quốc tế {location}', 'phòng khám {location}']),  # noqa: E501
    ('retail', ['trung tâm thương mại', 'siêu thị', 'chợ', 'aeon', 'vincom'], ['trung tâm thương mại siêu thị gần {location}'], ['trung tâm thương mại', 'siêu thị', 'chợ', 'aeon', 'vincom', 'lotte', 'emart', 'khai trương', 'mua sắm'], ['trung tâm thương mại {location}', '{project} gần trung tâm thương mại siêu thị', 'siêu thị {location}', '{location} khai trương AEON Vincom Lotte']),  # noqa: E501
    ('leisure', ['công viên', 'hồ', 'sân golf', 'khu vui chơi'], ['công viên hồ sân golf gần {location}'], ['công viên', 'hồ', 'sân golf', 'khu vui chơi', 'hồ điều hoà', 'mảng xanh', 'vui chơi', 'giải trí'], ['công viên {location}', '{project} gần công viên hồ điều hoà', 'sân golf gần {location}', '{location} khu vui chơi giải trí']),  # noqa: E501
    ('employment', ['khu công nghiệp', 'khu công nghệ cao', 'trụ sở', 'hành chính'], ['khu công nghiệp khu công nghệ cao gần {location}'], ['khu công nghiệp', 'khu công nghệ cao', 'trụ sở', 'hành chính', 'việc làm', 'chuyên gia', 'công nhân', 'trung tâm hành chính'], ['khu công nghiệp {location}', '{location} khu công nghệ cao', '{project} gần khu công nghiệp', '{location} trung tâm hành chính mới']),  # noqa: E501
    ('zoning', ['quy hoạch', 'phân khu', 'lên quận', 'đô thị vệ tinh', 'sáp nhập'], ['quy hoạch {location} mới nhất', '{location} lên quận quy hoạch đô thị', '{project} quy hoạch 1/500'], ['quy hoạch', 'phân khu', 'lên quận', 'đô thị vệ tinh', 'sáp nhập', 'quy hoạch chung', '1/2000', '1/500', 'điều chỉnh quy hoạch'], ['quy hoạch {location} mới nhất', '{project} quy hoạch 1/500', '{location} quy hoạch phân khu', '{location} lên quận quy hoạch đô thị']),  # noqa: E501
    ('area_development', ['khởi công', 'đầu tư', 'dự án lớn', 'động lực'], ['dự án hạ tầng lớn khởi công {location}', 'hạ tầng mới quanh {project} khởi công'], ['khởi công', 'đầu tư', 'dự án lớn', 'động lực', 'trọng điểm', 'siêu dự án', 'nghìn tỷ'], ['dự án lớn khởi công {location}', '{location} dự án hạ tầng trọng điểm', '{project} hưởng lợi hạ tầng mới', '{location} siêu dự án']),  # noqa: E501
    ('nearby_projects', ['dự án', 'khu đô thị', 'chủ đầu tư'], ['dự án bất động sản gần {project}', 'dự án khu đô thị {location}'], ['dự án', 'khu đô thị', 'chủ đầu tư', 'chung cư', 'căn hộ', 'mở bán'], ['dự án bất động sản gần {project}', 'dự án khu đô thị {location}', '{location} dự án chung cư mới', '{location} dự án mở bán']),  # noqa: E501
    ('price_trend', ['giá', 'triệu/m2', 'tỷ', 'tăng giá', 'thanh khoản'], ['giá nhà đất {location} hiện nay', 'giá bán {project}', '{project} giá chuyển nhượng thứ cấp', 'giá thuê căn hộ {project}'], ['giá', 'triệu/m2', 'tỷ', 'tăng giá', 'giá thuê', 'thứ cấp', 'chênh', 'đơn giá'], ['giá bán {project}', 'giá nhà đất {location} hiện nay', '{project} giá chuyển nhượng thứ cấp', 'giá thuê căn hộ {project}']),  # noqa: E501
    ('project_news', ['mở bán', 'bàn giao', 'tiến độ', 'ra mắt', 'giải thưởng'], ['{project} tin tức mới nhất', '{project} tiến độ bàn giao', '{project} mở bán đợt mới', '{project} chủ đầu tư công bố'], ['mở bán', 'bàn giao', 'tiến độ', 'ra mắt', 'giải thưởng', 'cất nóc', 'khởi công', 'nhận nhà', 'ra hàng'], ['{project} tin tức mới nhất', '{project} tiến độ bàn giao', '{project} mở bán đợt mới', '{project} cất nóc khởi công']),  # noqa: E501
    ('onsite_amenities', ['tiện ích', 'bể bơi', 'clubhouse', 'công viên nội khu'], ['{project} tiện ích nội khu', '{project} quy mô thiết kế mặt bằng'], ['tiện ích', 'bể bơi', 'clubhouse', 'công viên nội khu', 'quy mô', 'mật độ xây dựng', 'thiết kế'], ['{project} tiện ích nội khu', '{project} quy mô thiết kế mặt bằng', '{project} bể bơi công viên nội khu', '{project} có gì']),  # noqa: E501
    ('offsite_amenities', ['tiện ích ngoại khu', 'tiện ích xung quanh', 'liên kết vùng'], ['{project} tiện ích ngoại khu', 'tiện ích xung quanh {location}'], ['tiện ích ngoại khu', 'tiện ích xung quanh', 'liên kết vùng', 'kết nối', 'lân cận', 'bán kính'], ['{project} tiện ích ngoại khu', 'tiện ích xung quanh {location}', '{project} xung quanh có gì', '{location} tiện ích liên kết vùng']),  # noqa: E501
    ('legal', ['giấy phép xây dựng', 'sổ hồng', 'pháp lý', 'phê duyệt', 'chủ trương đầu tư'], ['{project} pháp lý giấy phép xây dựng', '{project} sổ hồng cấp sổ'], ['giấy phép xây dựng', 'sổ hồng', 'pháp lý', 'phê duyệt', 'chủ trương đầu tư', 'đủ điều kiện', 'bảo lãnh', 'thế chấp', 'quyết định'], ['{project} pháp lý', '{project} giấy phép xây dựng', '{project} sổ hồng cấp sổ', '{project} đủ điều kiện mở bán']),  # noqa: E501
    ('investor', ['chủ đầu tư', 'nhà phát triển', 'năng lực', 'dự án đã bàn giao'], ['chủ đầu tư {project} là ai', '{project} chủ đầu tư các dự án đã bàn giao'], ['chủ đầu tư', 'nhà phát triển', 'năng lực', 'dự án đã bàn giao', 'tập đoàn', 'uy tín', 'năng lực tài chính'], ['chủ đầu tư {project} là ai', '{project} chủ đầu tư uy tín', '{project} chủ đầu tư các dự án đã bàn giao', '{project} chủ đầu tư năng lực tài chính']),  # noqa: E501
)

# (code, label, heading, dossier, keywords, queries, position)
_NEW = (
    ('price_potential', 'Tiềm năng tăng giá', '', True, ['tiềm năng', 'tăng giá', 'sinh lời', 'động lực', 'đón sóng', 'hưởng lợi', 'thu hút đầu tư', 'fdi', 'lên quận', 'lên thành phố'], ['{location} tiềm năng tăng giá bất động sản', '{project} tiềm năng tăng giá', '{location} lên quận lên thành phố', '{location} thu hút vốn đầu tư FDI'], 18),  # noqa: E501
    ('liquidity', 'Thanh khoản và nhu cầu', '', True, ['thanh khoản', 'hấp thụ', 'bán hết', 'cháy hàng', 'giao dịch', 'nhu cầu', 'khách hàng quan tâm', 'đặt chỗ'], ['{project} bán hết tỷ lệ hấp thụ', '{project} giao dịch thanh khoản', '{location} nhu cầu mua nhà', '{location} giao dịch bất động sản sôi động'], 19),  # noqa: E501
)
# fmt: on

_DESCRIPTIONS = {
    "price_potential": "Động lực tăng giá của khu vực: hạ tầng mới, vốn đầu tư, nâng cấp đô thị.",
    "liquidity": "Tỷ lệ bán hết, lượng giao dịch và nhu cầu mua ở dự án và khu vực.",
    "price_trend": "Giá bán, giá thuê và giá thứ cấp của dự án và khu vực.",
}
_OLD_PRICE_TREND_DESC = "Giá bán, giá thứ cấp và thanh khoản của dự án và khu vực."


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _arr(items) -> str:
    return "ARRAY[" + ", ".join(_q(x) for x in items) + "]::text[]" if items else "'{}'::text[]"


def _body() -> str:
    updates = ",\n".join(f"({_q(c)}, {_arr(ok)}, {_arr(oq)}, {_arr(nk)}, {_arr(nq)})" for c, ok, oq, nk, nq in _UPDATES)
    news = ",\n".join(
        f"(p_tenant, {_q(c)}, {_q(lb)}, {_q(h)}, {_q(_DESCRIPTIONS[c])}, {'true' if ds else 'false'}, "
        f"{_arr(kw)}, {_arr(qs)}, 'default', {pos})"
        for c, lb, h, ds, kw, qs, pos in _NEW
    )
    return f"""
CREATE FUNCTION control.kbweb_seed_topics_v2(p_tenant text) RETURNS void
LANGUAGE plpgsql AS $kbweb$
DECLARE v_cu text := current_setting('app.tenant_id', true);
BEGIN
    PERFORM set_config('app.tenant_id', p_tenant, true);
    UPDATE tenant_data.kbweb_topics t
       SET keywords = v.nk, queries = v.nq, updated_at = now()
      FROM (VALUES
{updates}
           ) AS v(code, ok, oq, nk, nq)
     WHERE t.tenant_id = p_tenant AND t.origin = 'default' AND t.code = v.code
       AND t.keywords = v.ok AND t.queries = v.oq;
    UPDATE tenant_data.kbweb_topics
       SET description = {_q(_DESCRIPTIONS["price_trend"])}
     WHERE tenant_id = p_tenant AND origin = 'default' AND code = 'price_trend'
       AND description = {_q(_OLD_PRICE_TREND_DESC)};
    INSERT INTO tenant_data.kbweb_topics
        (tenant_id, code, label, heading, description, dossier, keywords, queries, origin, position)
    VALUES
{news}
    ON CONFLICT DO NOTHING;
    PERFORM set_config('app.tenant_id', coalesce(v_cu, ''), true);
END $kbweb$;

CREATE FUNCTION control.tao_kbweb_mac_dinh_v2() RETURNS trigger
LANGUAGE plpgsql AS $kbweb$
BEGIN
    PERFORM control.kbweb_seed_topics_v2(NEW.id);
    RETURN NULL;
END $kbweb$;

CREATE TRIGGER tenants_tao_kbweb_mac_dinh_v2 AFTER INSERT ON control.tenants
FOR EACH ROW EXECUTE FUNCTION control.tao_kbweb_mac_dinh_v2();
"""


def upgrade() -> None:
    op.execute(_body())
    op.execute("SELECT control.kbweb_seed_topics_v2(id) FROM control.tenants")


def downgrade() -> None:
    op.execute("DROP TRIGGER tenants_tao_kbweb_mac_dinh_v2 ON control.tenants")
    op.execute("DROP FUNCTION control.tao_kbweb_mac_dinh_v2()")
    op.execute("DROP FUNCTION control.kbweb_seed_topics_v2(text)")
