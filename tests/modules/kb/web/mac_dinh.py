"""Bộ nguồn/chủ đề mặc định của nền tảng — bản dùng trong TEST.

Tenant mới được seed bằng `control.kbweb_seed_defaults` của migration `0971_kbweb_theo_tenant`
(bản ĐÓNG BĂNG, luật migration: không import `portal.*`); `tests/unit/test_kb_web_config.py`
so hai bản để chúng không lệch nhau.
Đo whitelist ngày 29/09/2026. `child_hint`: chuỗi phải có trong URL sitemap con khi sitemap
index không ghi lastmod; {y}=năm, {m}=tháng không đệm, {mm}=tháng 2 chữ số.
"""

from functools import cache

from portal.modules.kb.web.config import WebConfig, _source, _topic

# fmt: off
# (domain, name, fetch_mode, kind, rss, sitemap_index, child_hint, news_sitemaps, category_pages,
#  article_pattern, category_paths)
SOURCES: tuple[tuple, ...] = (
    ('cafef.vn', 'CafeF', 'http', 'news', ['https://cafef.vn/bat-dong-san.rss'], 'https://cafef.vn/sitemap.xml', '-{y}-{m}-', ['https://cafef.vn/google-news-sitemap.xml'], [], '', []),  # noqa: E501
    ('vnexpress.net', 'VnExpress', 'http', 'news', ['https://vnexpress.net/rss/bat-dong-san.rss'], '', '', [], [], '', []),  # noqa: E501
    ('dantri.com.vn', 'Dân trí', 'http', 'news', ['https://dantri.com.vn/rss/bat-dong-san.rss'], '', '', ['https://dantri.com.vn/google-news-sitemap.xml'], [], '', ['/bat-dong-san']),  # noqa: E501
    ('baoxaydung.vn', 'Báo Xây dựng', 'http', 'news', ['https://baoxaydung.vn/rss/bat-dong-san.rss'], 'https://baoxaydung.vn/sitemap.xml', '-{y}-{m}-', [], [], '', []),  # noqa: E501
    ('vneconomy.vn', 'VnEconomy', 'http', 'news', ['https://vneconomy.vn/dia-oc.rss'], '', '', ['https://vneconomy.vn/sitemap/google-news.xml'], [], '', []),  # noqa: E501
    ('thanhnien.vn', 'Thanh Niên', 'http', 'news', ['https://thanhnien.vn/rss/kinh-te/dia-oc.rss'], 'https://thanhnien.vn/sitemap.xml', '-{y}-{m}-', [], [], '', []),  # noqa: E501
    ('tuoitre.vn', 'Tuổi Trẻ', 'http', 'news', ['https://tuoitre.vn/rss/nha-dat.rss'], '', '', ['https://tuoitre.vn/sitemaps/latest-news.rss'], [], '', []),  # noqa: E501
    ('vietnamnet.vn', 'VietNamNet', 'http', 'news', ['https://vietnamnet.vn/bat-dong-san.rss'], '', '', ['https://vietnamnet.vn/sitemap-news.xml'], [], '', []),  # noqa: E501
    ('cafeland.vn', 'CafeLand', 'http', 'news', [], '', '', [], ['https://cafeland.vn/tin-tuc/'], '^https://cafeland\\.vn/tin-tuc/.+-\\d+\\.html$', []),  # noqa: E501
    ('batdongsan.com.vn', 'Batdongsan', 'http', 'news', [], '', '', [], ['https://wiki.batdongsan.com.vn/tin-tuc'], '^https://(wiki\\.)?batdongsan\\.com\\.vn/tin-tuc/[a-z0-9.-]+-\\d{5,}$', ['/tin-tuc/']),  # noqa: E501
    ('reatimes.vn', 'Reatimes', 'http', 'news', [], '', '', ['https://reatimes.vn/sitemaps/googlenews.ashx'], [], '', []),  # noqa: E501
    ('nhipsongkinhdoanh.vn', 'Nhịp sống kinh doanh', 'http', 'news', [], '', '', [], ['https://nhipsongkinhdoanh.vn/hashtag/bat-dong-san-191'], '^https://nhipsongkinhdoanh\\.vn/[a-z0-9-]+-\\d+\\.htm$', []),  # noqa: E501
    ('baochinhphu.vn', 'Báo Chính phủ', 'http', 'news', [], '', '', [], ['https://baochinhphu.vn/kinh-te.htm'], '^https://baochinhphu\\.vn/.+-\\d+\\.htm$', []),  # noqa: E501
    ('hanoi.gov.vn', 'Cổng thông tin Hà Nội', 'http', 'living', [], '', '', [], [], '', []),
    ('quyhoach.hanoi.vn', 'Quy hoạch Hà Nội', 'http', 'living', [], '', '', [], [], '', []),
    ('savills.com.vn', 'Savills', 'http', 'living', [], '', '', [], [], '', []),
)

# (code, label, heading, dossier, keywords, queries)
TOPICS: tuple[tuple, ...] = (
    ('road', 'Đường bộ', 'Hạ tầng giao thông – Đường bộ', True, ['đường', 'đại lộ', 'cao tốc', 'vành đai', 'quốc lộ', 'nút giao', 'tỉnh lộ', 'mở rộng đường', 'thông xe', 'trục đường'], ['{location} đường vành đai cao tốc', '{location} mở rộng đường quốc lộ', '{project} kết nối giao thông đường bộ', '{location} nút giao tiến độ thi công']),  # noqa: E501
    ('bridge', 'Cầu và vượt sông', 'Hạ tầng giao thông – Cầu', True, ['cầu', 'vượt sông', 'thông xe', 'khởi công cầu', 'hợp long'], ['cầu mới {location}', '{location} cầu vượt sông tiến độ', '{project} cầu kết nối', '{location} khởi công cầu']),  # noqa: E501
    ('transit', 'Giao thông công cộng', 'Hạ tầng giao thông – Giao thông công cộng', True, ['metro', 'đường sắt đô thị', 'brt', 'xe buýt', 'ga', 'nhà ga', 'tàu điện', 'đường sắt'], ['metro đường sắt đô thị {location}', '{project} gần ga metro', 'tuyến xe buýt {location}', '{location} tuyến BRT đường sắt tiến độ']),  # noqa: E501
    ('travel_time', 'Thời gian di chuyển', 'Vị trí và thời gian di chuyển', True, ['phút', 'km', 'trung tâm', 'sân bay', 'thời gian di chuyển', 'kết nối', 'khoảng cách'], ['{project} cách trung tâm bao nhiêu km', 'vị trí {project} kết nối giao thông', 'từ {location} vào trung tâm mất bao lâu', '{location} đi sân bay mất bao lâu']),  # noqa: E501
    ('education', 'Giáo dục', 'Tiện ích – Giáo dục', True, ['trường', 'mầm non', 'tiểu học', 'thcs', 'thpt', 'đại học', 'trường quốc tế', 'liên cấp', 'học sinh'], ['trường học gần {location}', '{project} gần trường học', 'trường quốc tế {location}', 'trường mầm non tiểu học {location}']),  # noqa: E501
    ('healthcare', 'Y tế', 'Tiện ích – Y tế', True, ['bệnh viện', 'phòng khám', 'trạm y tế', 'bệnh viện quốc tế', 'cơ sở y tế', 'khám chữa bệnh'], ['bệnh viện gần {location}', '{project} gần bệnh viện', 'bệnh viện quốc tế {location}', 'phòng khám {location}']),  # noqa: E501
    ('retail', 'Thương mại', 'Tiện ích – Thương mại', True, ['trung tâm thương mại', 'siêu thị', 'chợ', 'aeon', 'vincom', 'lotte', 'emart', 'khai trương', 'mua sắm'], ['trung tâm thương mại {location}', '{project} gần trung tâm thương mại siêu thị', 'siêu thị {location}', '{location} khai trương AEON Vincom Lotte']),  # noqa: E501
    ('leisure', 'Cảnh quan và giải trí', 'Tiện ích – Cảnh quan và giải trí', True, ['công viên', 'hồ', 'sân golf', 'khu vui chơi', 'hồ điều hoà', 'mảng xanh', 'vui chơi', 'giải trí'], ['công viên {location}', '{project} gần công viên hồ điều hoà', 'sân golf gần {location}', '{location} khu vui chơi giải trí']),  # noqa: E501
    ('employment', 'Việc làm và hành chính', '', True, ['khu công nghiệp', 'khu công nghệ cao', 'trụ sở', 'hành chính', 'việc làm', 'chuyên gia', 'công nhân', 'trung tâm hành chính'], ['khu công nghiệp {location}', '{location} khu công nghệ cao', '{project} gần khu công nghiệp', '{location} trung tâm hành chính mới']),  # noqa: E501
    ('zoning', 'Quy hoạch', '', True, ['quy hoạch', 'phân khu', 'lên quận', 'đô thị vệ tinh', 'sáp nhập', 'quy hoạch chung', '1/2000', '1/500', 'điều chỉnh quy hoạch'], ['quy hoạch {location} mới nhất', '{project} quy hoạch 1/500', '{location} quy hoạch phân khu', '{location} lên quận quy hoạch đô thị']),  # noqa: E501
    ('area_development', 'Dự án lớn trong khu vực', '', True, ['khởi công', 'đầu tư', 'dự án lớn', 'động lực', 'trọng điểm', 'siêu dự án', 'nghìn tỷ'], ['dự án lớn khởi công {location}', '{location} dự án hạ tầng trọng điểm', '{project} hưởng lợi hạ tầng mới', '{location} siêu dự án']),  # noqa: E501
    ('nearby_projects', 'Dự án lân cận', '', False, ['dự án', 'khu đô thị', 'chủ đầu tư', 'chung cư', 'căn hộ', 'mở bán'], ['dự án bất động sản gần {project}', 'dự án khu đô thị {location}', '{location} dự án chung cư mới', '{location} dự án mở bán']),  # noqa: E501
    ('price_trend', 'Mặt bằng giá', '', True, ['giá', 'triệu/m2', 'tỷ', 'tăng giá', 'giá thuê', 'thứ cấp', 'chênh', 'đơn giá'], ['giá bán {project}', 'giá nhà đất {location} hiện nay', '{project} giá chuyển nhượng thứ cấp', 'giá thuê căn hộ {project}']),  # noqa: E501
    ('project_news', 'Tin về dự án', 'Tin về dự án và tiến độ', True, ['mở bán', 'bàn giao', 'tiến độ', 'ra mắt', 'giải thưởng', 'cất nóc', 'khởi công', 'nhận nhà', 'ra hàng'], ['{project} tin tức mới nhất', '{project} tiến độ bàn giao', '{project} mở bán đợt mới', '{project} cất nóc khởi công']),  # noqa: E501
    ('onsite_amenities', 'Tiện ích nội khu', '', True, ['tiện ích', 'bể bơi', 'clubhouse', 'công viên nội khu', 'quy mô', 'mật độ xây dựng', 'thiết kế'], ['{project} tiện ích nội khu', '{project} quy mô thiết kế mặt bằng', '{project} bể bơi công viên nội khu', '{project} có gì']),  # noqa: E501
    ('offsite_amenities', 'Tiện ích ngoại khu', '', True, ['tiện ích ngoại khu', 'tiện ích xung quanh', 'liên kết vùng', 'kết nối', 'lân cận', 'bán kính'], ['{project} tiện ích ngoại khu', 'tiện ích xung quanh {location}', '{project} xung quanh có gì', '{location} tiện ích liên kết vùng']),  # noqa: E501
    ('legal', 'Pháp lý dự án', 'Pháp lý', True, ['giấy phép xây dựng', 'sổ hồng', 'pháp lý', 'phê duyệt', 'chủ trương đầu tư', 'đủ điều kiện', 'bảo lãnh', 'thế chấp', 'quyết định'], ['{project} pháp lý', '{project} giấy phép xây dựng', '{project} sổ hồng cấp sổ', '{project} đủ điều kiện mở bán']),  # noqa: E501
    ('investor', 'Chủ đầu tư', '', True, ['chủ đầu tư', 'nhà phát triển', 'năng lực', 'dự án đã bàn giao', 'tập đoàn', 'uy tín', 'năng lực tài chính'], ['chủ đầu tư {project} là ai', '{project} chủ đầu tư uy tín', '{project} chủ đầu tư các dự án đã bàn giao', '{project} chủ đầu tư năng lực tài chính']),  # noqa: E501
    ('price_potential', 'Tiềm năng tăng giá', '', True, ['tiềm năng', 'tăng giá', 'sinh lời', 'động lực', 'đón sóng', 'hưởng lợi', 'thu hút đầu tư', 'fdi', 'lên quận', 'lên thành phố'], ['{location} tiềm năng tăng giá bất động sản', '{project} tiềm năng tăng giá', '{location} lên quận lên thành phố', '{location} thu hút vốn đầu tư FDI']),  # noqa: E501
    ('liquidity', 'Thanh khoản và nhu cầu', '', True, ['thanh khoản', 'hấp thụ', 'bán hết', 'cháy hàng', 'giao dịch', 'nhu cầu', 'khách hàng quan tâm', 'đặt chỗ'], ['{project} bán hết tỷ lệ hấp thụ', '{project} giao dịch thanh khoản', '{location} nhu cầu mua nhà', '{location} giao dịch bất động sản sôi động']),  # noqa: E501
)
# fmt: on

# Mô tả hiện ở màn «Dữ liệu ngoài» (cột Mô tả của bảng Chủ đề).
TOPIC_DESCRIPTIONS: dict[str, str] = {
    "road": "Đường, cao tốc, vành đai và nút giao kết nối dự án.",
    "bridge": "Cầu và tuyến vượt sông gần dự án, tiến độ xây dựng.",
    "transit": "Metro, đường sắt đô thị, BRT và xe buýt quanh khu vực.",
    "travel_time": "Khoảng cách và thời gian di chuyển tới trung tâm, sân bay.",
    "education": "Trường mầm non, phổ thông, đại học và trường quốc tế gần dự án.",
    "healthcare": "Bệnh viện, phòng khám quanh khu vực.",
    "retail": "Trung tâm thương mại, siêu thị và chợ gần dự án.",
    "leisure": "Công viên, hồ, sân golf và khu vui chơi gần dự án.",
    "employment": "Khu công nghiệp, khu công nghệ cao và trụ sở hành chính lân cận.",
    "zoning": "Quy hoạch phân khu, lên quận, đô thị vệ tinh của khu vực.",
    "area_development": "Dự án hạ tầng và đầu tư lớn đang triển khai trong khu vực.",
    "nearby_projects": "Các dự án bất động sản khác gần dự án.",
    "price_trend": "Giá bán, giá thuê và giá thứ cấp của dự án và khu vực.",
    "project_news": "Tin mở bán, tiến độ, bàn giao và giải thưởng của dự án.",
    "onsite_amenities": "Tiện ích nội khu, quy mô và thiết kế của dự án.",
    "offsite_amenities": "Tiện ích xung quanh dự án và liên kết vùng.",
    "legal": "Giấy phép, chủ trương đầu tư, sổ hồng và tình trạng pháp lý.",
    "investor": "Chủ đầu tư, năng lực và các dự án đã bàn giao.",
    "price_potential": "Động lực tăng giá của khu vực: hạ tầng mới, vốn đầu tư, nâng cấp đô thị.",
    "liquidity": "Tỷ lệ bán hết, lượng giao dịch và nhu cầu mua ở dự án và khu vực.",
}


@cache
def defaults() -> WebConfig:
    return WebConfig(sources=tuple(_source(*s) for s in SOURCES), topics=tuple(_topic(*t) for t in TOPICS))
