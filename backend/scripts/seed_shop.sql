-- Dữ liệu mẫu cho schema `shop` (CHỈ dev). Chạy qua `make seed-shop`.
-- Một sản phẩm đầy đủ (iPhone 16 Pro Max, số liệu chép từ trang TGDĐ ngày 2026-11-02)
-- + dữ liệu tham chiếu. Gói trả góp, cửa hàng, tồn kho là SỐ GIẢ để thử agent.
SET LOCAL search_path = shop, public;

CREATE FUNCTION pg_temp.slug(t text) RETURNS text LANGUAGE sql IMMUTABLE AS
$$ SELECT trim(both '-' from regexp_replace(lower(public.unaccent(replace(replace(replace(t, '+', ' plus'), 'đ', 'd'), 'Đ', 'D'))), '[^a-z0-9]+', '-', 'g')) $$;

-- Danh mục --------------------------------------------------------------
INSERT INTO brands (slug, name, sort_order) VALUES
  ('apple','iPhone (Apple)',1), ('samsung','Samsung',2), ('oppo','OPPO',3), ('xiaomi','Xiaomi',4),
  ('motorola','Motorola',5), ('vivo','vivo',6), ('realme','realme',7), ('honor','HONOR',8),
  ('nothing','Nothing Phone',9), ('tecno','Tecno',10), ('nubia','Nubia',11), ('nokia','Nokia',12),
  ('masstel','Masstel',13), ('mobell','Mobell',14);

INSERT INTO categories (slug, name, sort_order) VALUES ('dtdd','Điện thoại',1);

INSERT INTO tags (kind, slug, name) VALUES
  ('need','choi-game','Chơi game / Cấu hình cao'),
  ('need','pin-khung','Pin khủng trên 7000 mAh'),
  ('need','chup-anh','Chụp ảnh, quay phim'),
  ('need','livestream','Livestream'),
  ('need','mong-nhe','Mỏng nhẹ'),
  ('segment','dien-thoai-ai','Điện thoại AI'),
  ('segment','ai-cao-cap','Điện thoại AI cao cấp');

-- Chính sách (tóm từ /chinh-sach-bao-hanh-san-pham và /tra-gop) ----------
INSERT INTO policies (policy_type, slug, title, summary, content_md, effective_from) VALUES
 ('return_exchange','hu-gi-doi-nay','Hư gì đổi nấy 12 tháng',
  'Hư gì đổi nấy 12 tháng tại siêu thị toàn quốc (miễn phí tháng đầu)',
  E'- Sản phẩm chính lỗi kỹ thuật: đổi sản phẩm mới cùng model, dung lượng, màu.\n- Tháng đầu tiên: miễn phí.\n- Tháng 2 đến 12: phí 10% giá trị hoá đơn mỗi tháng (tháng 2: 10%, tháng 3: 20%…).\n- Không có hàng để đổi thì áp dụng bảo hành có cam kết.',
  '2021-03-01'),
 ('warranty','bao-hanh-cam-ket-12-thang','Bảo hành có cam kết 12 tháng',
  'Bảo hành trong 15 ngày, không bảo hành lại lần 2 trong 30 ngày',
  E'- Chỉ áp dụng sản phẩm chính, không áp dụng phụ kiện đi kèm.\n- Bảo hành xong trong 15 ngày kể từ khi nhận máy lỗi.\n- Không phải bảo hành lại lần 2 trong 30 ngày kể từ lần trước.\n- Vi phạm cam kết thì khách được áp dụng đổi/hoàn tiền.\n- Từ tháng 13 chỉ còn bảo hành hãng.',
  '2021-03-01'),
 ('installment','tra-cham-cong-ty-tai-chinh','Trả chậm qua công ty tài chính',
  'Từ 18–60 tuổi, chỉ cần CCCD còn hạn, duyệt qua điện thoại',
  E'- Tuổi 18–60 (thành viên ACS đến 65).\n- Giấy tờ: CCCD còn hạn; công ty tài chính kiểm tra xong trả lại, không giữ giấy tờ.\n- Đặt online, nhân viên công ty tài chính gọi trong 2 giờ nếu đặt trước 18h.\n- Mang hồ sơ gốc ra cửa hàng nhận máy.\n- Giá theo niêm yết, nhận đủ khuyến mãi; tuỳ sản phẩm không áp dụng đồng thời trả chậm 0%.\n- Trễ hạn có phát sinh phí theo quy định từng công ty.',
  '2021-03-26');

INSERT INTO policies (policy_type, slug, title, summary, content_md, brand_id)
SELECT 'unboxing','khui-hop-apple','Chính sách khui hộp sản phẩm Apple',
       'Sản phẩm mới, cần thanh toán trước khi mở hộp',
       'Sản phẩm Apple mới nguyên seal: khách thanh toán trước khi khui hộp kiểm tra.', id
FROM brands WHERE slug = 'apple';

INSERT INTO service_packages (code, name, service_type, duration_months, price_percent, terms_md) VALUES
 ('BH_ROI_VO','Bảo hành rơi vỡ','drop_damage',12,5,'Số liệu mẫu.'),
 ('BH_MO_RONG','Bảo hành mở rộng','extended_warranty',12,4,'Số liệu mẫu.'),
 ('BH_1_DOI_1','Bảo hành 1 đổi 1','one_to_one_exchange',12,3,'Số liệu mẫu.');

-- Trả góp (tên đối tác thật, GÓI là số mẫu) -----------------------------
INSERT INTO finance_partners (code, name, partner_type) VALUES
 ('HOME_CREDIT','Home Credit','finance_company'), ('FE_CREDIT','FE Credit','finance_company'),
 ('ACS','ACS','finance_company'), ('MAFC','Mirae Asset (MAFC)','finance_company'),
 ('MCREDIT','MCredit','finance_company'), ('CREDIT_CARD','Thẻ tín dụng (Visa, Mastercard, JCB, Amex)','credit_card');

INSERT INTO installment_plans (partner_id, name, tenor_months, interest_rate_monthly, min_down_payment_percent, required_docs)
SELECT p.id, p.name || ' 0% ' || t || ' tháng', t, 0, d, 'CCCD còn hạn'
FROM finance_partners p
CROSS JOIN (VALUES (6, 30), (12, 40)) AS x(t, d)
WHERE p.code = 'HOME_CREDIT';
INSERT INTO installment_plans (partner_id, name, tenor_months, interest_rate_monthly, min_down_payment_percent, conditions)
SELECT id, 'Trả chậm 0% qua thẻ tín dụng 6 tháng', 6, 0, 0, 'Không cần trả trước' FROM finance_partners WHERE code = 'CREDIT_CARD';
INSERT INTO installment_plan_targets (plan_id, brand_id)
SELECT ip.id, b.id FROM installment_plans ip CROSS JOIN brands b WHERE b.slug = 'apple';

-- Từ điển tính năng (đúng chữ trên bảng thông số TGDĐ) ------------------
INSERT INTO features (feature_group, name, slug, is_filterable)
SELECT g, n, pg_temp.slug(n), n IN ('Sạc không dây','Chỉnh ảnh AI')
FROM (VALUES
 ('rear_camera','Ban đêm (Night Mode)'),('rear_camera','Bộ lọc màu'),('rear_camera','Chân dung đêm'),
 ('rear_camera','Chế độ hành động (Action Mode)'),('rear_camera','Chống rung quang học (OIS)'),
 ('rear_camera','Chụp ảnh liên tục'),('rear_camera','Cinematic'),('rear_camera','Deep Fusion'),
 ('rear_camera','Dolby Vision HDR'),('rear_camera','Góc siêu rộng (Ultrawide)'),('rear_camera','Live Photos'),
 ('rear_camera','Photonic Engine'),('rear_camera','Quay chậm (Slow Motion)'),('rear_camera','Quay video ProRes'),
 ('rear_camera','Quay video định dạng Log'),('rear_camera','Siêu cận (Macro)'),('rear_camera','Siêu độ phân giải'),
 ('rear_camera','Smart HDR 5'),('rear_camera','Trôi nhanh thời gian (Time Lapse)'),('rear_camera','Xóa phông'),
 ('rear_camera','Zoom kỹ thuật số'),('rear_camera','Zoom quang học'),('rear_camera','Điều khiển camera (Camera Control)'),
 ('rear_camera','Ảnh Raw'),
 ('rear_video','2.8K 60fps'),('rear_video','4K 2160p@24fps'),('rear_video','4K 2160p@25fps'),('rear_video','4K 2160p@30fps'),
 ('rear_video','4K 2160p@60fps'),('rear_video','4K 2160p@100fps'),('rear_video','4K 2160p@120fps'),
 ('rear_video','FullHD 1080p@25fps'),('rear_video','FullHD 1080p@30fps'),('rear_video','FullHD 1080p@60fps'),
 ('rear_video','FullHD 1080p@120fps'),('rear_video','FullHD 1080p@240fps'),('rear_video','HD 720p@30fps'),
 ('front_camera','Bộ lọc màu'),('front_camera','Chống rung'),('front_camera','Chụp đêm'),('front_camera','Chụp ảnh Raw'),
 ('front_camera','Chụp ảnh liên tục'),('front_camera','Cinematic'),('front_camera','Deep Fusion'),('front_camera','Live Photos'),
 ('front_camera','Photonic Engine'),('front_camera','Quay chậm (Slow Motion)'),('front_camera','Quay video 4K'),
 ('front_camera','Quay video Full HD'),('front_camera','Quay video ProRes'),('front_camera','Quay video định dạng Log'),
 ('front_camera','Retina Flash'),('front_camera','Smart HDR 5'),('front_camera','Trôi nhanh thời gian (Time Lapse)'),
 ('front_camera','Xóa phông'),
 ('battery_tech','Sạc không dây'),('battery_tech','Sạc không dây MagSafe'),('battery_tech','Sạc ngược qua cáp'),
 ('battery_tech','Sạc pin nhanh'),('battery_tech','Tiết kiệm pin'),
 ('special','Apple Pay'),('special','Chạm 2 lần sáng màn hình'),('special','Công nghệ âm thanh Dolby Digital'),
 ('special','Công nghệ HLG'),('special','Công nghệ hình ảnh Dolby Vision'),('special','Công nghệ âm thanh Dolby Digital Plus'),
 ('special','DCI-P3'),('special','HDR10'),('special','HDR10+'),('special','Loa kép'),
 ('special','Màn hình luôn hiển thị AOD'),('special','Phát hiện va chạm (Crash Detection)'),('special','Âm thanh Dolby Atmos'),
 ('ai','Chỉnh ảnh AI'),
 ('wifi','Wi-Fi 7'),('wifi','Wi-Fi MIMO'),
 ('connectivity_other','NFC'),
 ('video_format','HEVC'),('video_format','MP4'),
 ('audio_format','AAC'),('audio_format','APAC'),('audio_format','Apple Lossless'),('audio_format','FLAC'),('audio_format','MP3')
) AS f(g, n);

-- iPhone 16 Pro Max ------------------------------------------------------
INSERT INTO series (brand_id, slug, name) SELECT id, 'iphone-16-series', 'iPhone 16 series' FROM brands WHERE slug = 'apple';

INSERT INTO products (category_id, brand_id, series_id, slug, name, phone_type, release_date, short_description,
                      in_box, warranty_months, warranty_note, status, is_featured, rating_avg, rating_count, sold_count)
SELECT c.id, b.id, s.id, 'iphone-16-pro-max', 'iPhone 16 Pro Max', 'smartphone', '2024-09-01',
       'Chip A18 Pro, màn hình 6.9" 120Hz, camera 48MP với nút Camera Control, khung Titan.',
       'Hộp, Sách hướng dẫn, Cáp, Cây lấy sim', 12,
       'Bảo hành chính hãng Điện thoại 1 năm tại các trung tâm bảo hành hãng',
       'selling', true, 4.9, 229, 312500
FROM categories c, brands b, series s
WHERE c.slug = 'dtdd' AND b.slug = 'apple' AND s.slug = 'iphone-16-series';

INSERT INTO product_tags (product_id, tag_id)
SELECT p.id, t.id FROM products p, tags t
WHERE p.slug = 'iphone-16-pro-max' AND t.slug IN ('chup-anh','choi-game','ai-cao-cap');

INSERT INTO product_colors (product_id, name, sort_order)
SELECT p.id, c, o FROM products p,
  (VALUES ('Titan sa mạc',1),('Titan đen',2),('Titan trắng',3),('Titan tự nhiên',4)) AS x(c, o)
WHERE p.slug = 'iphone-16-pro-max';

-- Giá: 256GB theo trang chi tiết (niêm yết 33.990.000, bán 31.590.000); 512GB/1TB theo bảng giá trong bài viết.
INSERT INTO product_variants (product_id, color_id, sku, ram_gb, storage_gb, storage_available_gb,
                              list_price_vnd, sale_price_vnd, sale_status, is_default, sort_order)
SELECT p.id, pc.id,
       'IP16PM-' || v.rom || '-' || upper(pg_temp.slug(pc.name)),
       8, v.gb, v.avail, v.list, v.sale,
       CASE WHEN pc.name = 'Titan đen' AND v.gb = 256 THEN 'out_of_stock' ELSE 'in_stock' END,
       pc.name = 'Titan sa mạc' AND v.gb = 256,
       v.gb::int / 256 * 10 + pc.sort_order
FROM products p
JOIN product_colors pc ON pc.product_id = p.id
CROSS JOIN (VALUES ('256', 256, 241, 33990000, 31590000),
                   ('512', 512, NULL, 40990000, NULL),
                   ('1TB', 1024, NULL, 46990000, NULL)) AS v(rom, gb, avail, list, sale)
WHERE p.slug = 'iphone-16-pro-max';

INSERT INTO phone_specs (product_id, os_name, os_version, chipset, cpu_cores, cpu_speed_text, gpu,
  memory_card_text, supports_memory_card, contacts_limit_text,
  rear_camera_text, rear_camera_main_mp, rear_camera_count, rear_flash, front_camera_text, front_camera_mp,
  display_tech, display_resolution_text, resolution_class, screen_size_inch, refresh_rate_hz, peak_brightness_nits, screen_glass,
  battery_text, battery_type, max_charge_w, charger_included,
  security_text, has_face_3d, ip_rating, recorder_text, radio_text, has_flashlight,
  network_gen, sim_text, sim_slots, has_esim, bluetooth_version, charging_port, headphone_jack, has_nfc,
  design_text, material_text, weight_g, thickness_mm, length_mm, width_mm)
SELECT id, 'iOS', 'iOS 18', 'Apple A18 Pro 6 nhân', 6, 'Hãng không công bố', 'Apple GPU 6 nhân',
  'Không', false, 'Không giới hạn',
  'Chính 48 MP & Phụ 48 MP, 12 MP', 48, 3, true, '12 MP', 12,
  'OLED', 'Super Retina XDR (1320 x 2868 Pixels)', 'Retina', 6.9, 120, 2000, 'Kính cường lực Ceramic Shield',
  '33 giờ', 'Li-Ion', 20, false,
  'Mở khoá khuôn mặt Face ID', true, 'IP68', 'Ghi âm mặc định', 'Không', false,
  '5G', '1 Nano SIM & 1 eSIM', 1, true, 'v5.3', 'Type-C', 'Type-C', true,
  'Nguyên khối', 'Khung Titan & Mặt lưng kính cường lực', 227, 8.25, 163, 77.6
FROM products WHERE slug = 'iphone-16-pro-max';

INSERT INTO product_features (product_id, feature_id)
SELECT p.id, f.id FROM products p CROSS JOIN features f
WHERE p.slug = 'iphone-16-pro-max' AND f.feature_group <> 'ai';  -- từ điển hiện chỉ chứa tính năng của máy này

INSERT INTO faqs (product_id, question, answer, sort_order)
SELECT id, q, a, o FROM products,
 (VALUES ('iPhone 16 Pro Max sạc nhanh bao nhiêu W?', 'Sạc có dây 20W, sạc không dây MagSafe 25W khi dùng bộ sạc phù hợp.', 1),
         ('iPhone 16 Pro Max hỗ trợ mấy SIM?', 'Một Nano SIM vật lý và một eSIM.', 2),
         ('iPhone 16 Pro Max có mấy màu?', 'Bốn màu: Titan sa mạc, Titan đen, Titan trắng, Titan tự nhiên.', 3),
         ('iPhone 16 Pro Max dùng chip gì?', 'Chip Apple A18 Pro trên tiến trình 3 nm.', 4)) AS x(q, a, o)
WHERE slug = 'iphone-16-pro-max';

-- Khuyến mãi "Chọn 1 trong các quà", hạn 23:59 30/11 -----------------------
INSERT INTO promotions (name, promo_type, discount_vnd, voucher_value_vnd, voucher_scope, choice_group, starts_at, ends_at)
VALUES
 ('Giảm giá 2.400.000₫','discount_amount',2400000,NULL,NULL,'ip16pm-qua','2026-11-01 00:00+07','2026-11-30 23:59+07'),
 ('Phiếu mua hàng Phụ kiện, Đồng hồ trị giá 2.900.000đ','voucher',NULL,2900000,'Phụ kiện, Đồng hồ','ip16pm-qua','2026-11-01 00:00+07','2026-11-30 23:59+07'),
 ('Phiếu mua hàng Apple Watch trị giá 1.000.000đ','voucher',NULL,1000000,'Apple Watch (trừ S12, SE3 và Ultra 4)',NULL,'2026-11-01 00:00+07','2026-11-30 23:59+07'),
 ('Phiếu mua hàng Macbook trị giá 1.000.000đ','voucher',NULL,1000000,'Macbook Air, Macbook Pro',NULL,'2026-11-01 00:00+07','2026-11-30 23:59+07'),
 ('Phiếu mua hàng AirPods trị giá 300.000đ','voucher',NULL,300000,'AirPods',NULL,'2026-11-01 00:00+07','2026-11-30 23:59+07');
INSERT INTO promotions (name, promo_type, discount_vnd, starts_at, terms)
VALUES ('Thu cũ đổi mới: giảm thêm đến 2.000.000đ','trade_in_bonus',2000000,'2026-11-01 00:00+07','Áp dụng tuỳ model máy cũ.');
INSERT INTO promotion_targets (promotion_id, product_id)
SELECT pr.id, p.id FROM promotions pr, products p WHERE p.slug = 'iphone-16-pro-max';

-- Cửa hàng & tồn kho (SỐ GIẢ) --------------------------------------------
INSERT INTO provinces (code, name) VALUES ('01','Hà Nội'), ('79','Hồ Chí Minh'), ('48','Đà Nẵng');
INSERT INTO stores (code, name, store_type, address, ward, province_code, phone, open_time, close_time) VALUES
 ('KHO-ONLINE','Kho online','warehouse','Kho tổng','—','79',NULL,NULL,NULL),
 ('HCM-001','Cửa hàng mẫu Quận 1','store','1 Đường Mẫu','Phường Sài Gòn','79','0280000001','08:00','22:00'),
 ('HN-001','Cửa hàng mẫu Hoàn Kiếm','store','2 Phố Mẫu','Phường Hoàn Kiếm','01','0240000001','08:00','22:00');
INSERT INTO inventory (store_id, variant_id, quantity)
SELECT s.id, v.id, (v.id * 7 + s.id * 3) % 6
FROM stores s CROSS JOIN product_variants v
WHERE v.sale_status = 'in_stock';
