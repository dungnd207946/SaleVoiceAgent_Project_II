-- =====================================================================
-- DB bán lẻ điện thoại (kiểu TGDĐ) — schema `shop`, KHÔNG chia tenant.
-- Migration gốc 0001_shop. Thiết kế: docs/superpowers/specs/2026-11-02-phone-shop-db-design.md
-- Giá CHUNG toàn hệ thống (không theo khu vực). Đơn hàng/admin: làm sau.
-- Postgres >= 15 (dùng NULLS NOT DISTINCT). Dev đang chạy 18.
-- Quy ước: id bigint identity · tiền VND kiểu bigint · enum = text + CHECK
-- (dễ thêm giá trị hơn kiểu ENUM) · created_at/updated_at timestamptz.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE SCHEMA IF NOT EXISTS shop;
SET LOCAL search_path = shop, public;

CREATE FUNCTION shop.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- ---------------------------------------------------------------------
-- 1. DANH MỤC: hãng · ngành hàng · dòng máy
-- ---------------------------------------------------------------------
CREATE TABLE brands (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug        text NOT NULL UNIQUE,                 -- 'apple', 'samsung'
  name        text NOT NULL UNIQUE,                 -- 'iPhone (Apple)', 'Samsung'
  country     text,
  logo_url    text,
  description text,
  sort_order  int  NOT NULL DEFAULT 0,
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE categories (                          -- cây ngành hàng: điện thoại, phụ kiện > ốp lưng, sạc...
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  parent_id   bigint REFERENCES categories(id) ON DELETE RESTRICT,
  slug        text NOT NULL UNIQUE,                 -- 'dtdd', 'phu-kien', 'op-lung'
  name        text NOT NULL,
  sort_order  int  NOT NULL DEFAULT 0,
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (parent_id IS DISTINCT FROM id)
);

CREATE TABLE series (                              -- 'iPhone 16 series', 'Galaxy S25'
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  brand_id    bigint NOT NULL REFERENCES brands(id) ON DELETE RESTRICT,
  slug        text NOT NULL UNIQUE,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (brand_id, name)
);

-- ---------------------------------------------------------------------
-- 2. SẢN PHẨM (model) → MÀU → BIẾN THỂ/SKU (RAM·ROM·màu·tình trạng, có giá)
-- ---------------------------------------------------------------------
CREATE TABLE products (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  category_id       bigint NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
  brand_id          bigint NOT NULL REFERENCES brands(id)     ON DELETE RESTRICT,
  series_id         bigint REFERENCES series(id) ON DELETE SET NULL,
  slug              text NOT NULL UNIQUE,           -- 'iphone-16-pro-max'
  name              text NOT NULL,                  -- 'iPhone 16 Pro Max'
  model_code        text,                           -- mã hãng, vd 'SM-S938B'
  phone_type        text CHECK (phone_type IN ('smartphone','foldable','feature_phone')),  -- NULL nếu không phải điện thoại
  release_date      date,                           -- 'Thời điểm ra mắt: 09/2024' → 2024-09-01
  short_description text,
  highlights_md     text,                           -- vài gạch đầu dòng nổi bật
  in_box            text,                           -- 'Hộp, Sách hướng dẫn, Cáp, Cây lấy sim'
  warranty_months   smallint NOT NULL DEFAULT 12 CHECK (warranty_months >= 0),
  warranty_note     text,                           -- 'Bảo hành chính hãng 1 năm tại TTBH hãng'
  status            text NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','coming_soon','selling','discontinued')),
  is_featured       boolean NOT NULL DEFAULT false,
  -- số liệu tổng hợp (cache, cập nhật bằng job/trigger từ reviews & orders)
  rating_avg        numeric(2,1) CHECK (rating_avg BETWEEN 0 AND 5),
  rating_count      int NOT NULL DEFAULT 0 CHECK (rating_count >= 0),
  sold_count        int NOT NULL DEFAULT 0 CHECK (sold_count >= 0),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX products_brand_idx    ON products (brand_id);
CREATE INDEX products_category_idx ON products (category_id);
CREATE INDEX products_name_trgm    ON products USING gin (lower(name) gin_trgm_ops);

CREATE TABLE product_colors (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id  bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name        text NOT NULL,                        -- 'Titan sa mạc'
  hex_code    text CHECK (hex_code ~ '^#[0-9A-Fa-f]{6}$'),
  sort_order  int NOT NULL DEFAULT 0,
  UNIQUE (product_id, name),
  UNIQUE (product_id, id)                           -- cho FK ghép từ variants/media
);

CREATE TABLE product_variants (                    -- 1 dòng = 1 SKU có giá & tồn kho
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id            bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  color_id              bigint,
  sku                   text NOT NULL UNIQUE,
  ram_gb                numeric(6,3) CHECK (ram_gb > 0),          -- máy phổ thông có thể 0.048 (48 MB)
  storage_gb            numeric(8,3) CHECK (storage_gb > 0),      -- 1 TB = 1024
  storage_available_gb  numeric(8,3) CHECK (storage_available_gb > 0),  -- 'Dung lượng khả dụng khoảng 241'
  condition             text NOT NULL DEFAULT 'new'
                        CHECK (condition IN ('new','used','refurbished')),  -- 'Máy cũ giá tốt'
  condition_note        text,                                     -- máy cũ: 'trầy nhẹ, pin 89%'
  list_price_vnd        bigint NOT NULL CHECK (list_price_vnd > 0),         -- giá niêm yết (gạch ngang)
  sale_price_vnd        bigint CHECK (sale_price_vnd > 0),                  -- giá bán; NULL = bằng niêm yết
  sale_status           text NOT NULL DEFAULT 'in_stock'
                        CHECK (sale_status IN ('in_stock','out_of_stock','pre_order','coming_soon','discontinued')),
  is_default            boolean NOT NULL DEFAULT false,           -- biến thể hiện mặc định trên thẻ SP
  sort_order            int NOT NULL DEFAULT 0,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (product_id, color_id) REFERENCES product_colors (product_id, id),
  CHECK (sale_price_vnd IS NULL OR sale_price_vnd <= list_price_vnd),
  CHECK (storage_available_gb IS NULL OR storage_available_gb <= storage_gb)
);
-- máy mới: mỗi cấu hình×màu chỉ 1 SKU; máy cũ thì mỗi máy có thể là 1 SKU riêng
CREATE UNIQUE INDEX product_variants_new_uq ON product_variants
  (product_id, color_id, ram_gb, storage_gb) NULLS NOT DISTINCT WHERE condition = 'new';
CREATE UNIQUE INDEX product_variants_one_default ON product_variants (product_id) WHERE is_default;
CREATE INDEX product_variants_price_idx ON product_variants (coalesce(sale_price_vnd, list_price_vnd));

CREATE TABLE price_history (                       -- tự ghi bằng trigger khi đổi giá
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  variant_id      bigint NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
  list_price_vnd  bigint NOT NULL,
  sale_price_vnd  bigint,
  changed_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX price_history_variant_idx ON price_history (variant_id, changed_at DESC);

CREATE FUNCTION shop.log_price_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT'
     OR NEW.list_price_vnd IS DISTINCT FROM OLD.list_price_vnd
     OR NEW.sale_price_vnd IS DISTINCT FROM OLD.sale_price_vnd THEN
    INSERT INTO shop.price_history (variant_id, list_price_vnd, sale_price_vnd)
    VALUES (NEW.id, NEW.list_price_vnd, NEW.sale_price_vnd);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER product_variants_price_log AFTER INSERT OR UPDATE ON product_variants
  FOR EACH ROW EXECUTE FUNCTION shop.log_price_change();

-- ---------------------------------------------------------------------
-- 3. THÔNG SỐ KỸ THUẬT
--   phone_specs: trường ĐƠN TRỊ, 1-1 với products, cột có kiểu để lọc/so sánh;
--                cột *_text giữ nguyên văn hiển thị như bảng thông số TGDĐ.
--   features + product_features: trường ĐA TRỊ (tính năng camera, chế độ quay,
--                công nghệ pin, tính năng đặc biệt, Wi-Fi, GPS, định dạng nhạc/phim...).
--   RAM/ROM nằm ở product_variants vì đổi theo phiên bản.
-- ---------------------------------------------------------------------
CREATE TABLE phone_specs (
  product_id             bigint PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
  -- Cấu hình & Bộ nhớ
  os_name                text CHECK (os_name IN ('iOS','Android','HarmonyOS','Khác')),
  os_version             text,                      -- 'iOS 18', 'Android 15'
  chipset                text,                      -- 'Apple A18 Pro 6 nhân'
  cpu_cores              smallint CHECK (cpu_cores > 0),
  cpu_speed_text         text,                      -- '3.2 GHz' | 'Hãng không công bố'
  gpu                    text,
  memory_card_text       text,                      -- 'Không' | 'MicroSD, tối đa 1 TB'
  supports_memory_card   boolean,
  contacts_limit_text    text,                      -- 'Không giới hạn'
  -- Camera
  rear_camera_text       text,                      -- 'Chính 48 MP & Phụ 48 MP, 12 MP'
  rear_camera_main_mp    numeric(5,1),
  rear_camera_count      smallint CHECK (rear_camera_count >= 0),
  rear_flash             boolean,
  front_camera_text      text,
  front_camera_mp        numeric(5,1),
  -- Màn hình
  display_tech           text,                      -- 'OLED', 'Dynamic AMOLED 2X'
  display_resolution_text text,                     -- 'Super Retina XDR (1320 x 2868 Pixels)'
  resolution_class       text CHECK (resolution_class IN
                           ('QQVGA','QVGA','HD+','Full HD+','1.5K','1.5K+','2K+','QXGA+','Retina')),
  screen_size_inch       numeric(4,2) CHECK (screen_size_inch > 0),          -- máy gập: màn trong
  cover_screen_size_inch numeric(4,2) CHECK (cover_screen_size_inch > 0),    -- máy gập: màn ngoài
  refresh_rate_hz        smallint CHECK (refresh_rate_hz > 0),
  peak_brightness_nits   int CHECK (peak_brightness_nits > 0),
  screen_glass           text,                      -- 'Kính cường lực Ceramic Shield'
  -- Pin & Sạc
  battery_mah            int CHECK (battery_mah > 0),        -- Apple không công bố → NULL
  battery_text           text,                      -- '33 giờ' | '5000 mAh'
  battery_type           text,                      -- 'Li-Ion'
  max_charge_w           numeric(5,1) CHECK (max_charge_w > 0),
  charger_included       boolean,
  -- Tiện ích
  security_text          text,                      -- 'Mở khoá khuôn mặt Face ID'
  has_face_3d            boolean,                   -- lọc 'Bảo mật khuôn mặt 3D'
  ip_rating              text,                      -- 'IP68'
  recorder_text          text,
  radio_text             text,
  has_flashlight         boolean,
  -- Kết nối
  network_gen            text CHECK (network_gen IN ('2G','3G','4G','5G')),
  has_5g                 boolean GENERATED ALWAYS AS (network_gen = '5G') STORED,
  sim_text               text,                      -- '1 Nano SIM & 1 eSIM'
  sim_slots              smallint CHECK (sim_slots >= 0),
  has_esim               boolean,
  bluetooth_version      text,                      -- 'v5.3'
  charging_port          text,                      -- 'Type-C', 'Lightning'
  headphone_jack         text,                      -- 'Type-C', '3.5 mm'
  has_nfc                boolean,
  -- Thiết kế & Chất liệu
  design_text            text,                      -- 'Nguyên khối'
  material_text          text,                      -- 'Khung Titan & Mặt lưng kính cường lực'
  weight_g               numeric(6,1) CHECK (weight_g > 0),
  thickness_mm           numeric(5,2) CHECK (thickness_mm > 0),
  length_mm              numeric(6,2) CHECK (length_mm > 0),
  width_mm               numeric(6,2) CHECK (width_mm > 0),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE features (                            -- từ điển giá trị đa trị
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  feature_group text NOT NULL CHECK (feature_group IN (
                  'rear_camera','front_camera','rear_video','front_video','battery_tech',
                  'special','ai','wifi','gps','connectivity_other','video_format','audio_format')),
  name          text NOT NULL,                      -- 'Chống rung quang học (OIS)', 'Wi-Fi 7', 'Sạc không dây MagSafe'
  slug          text NOT NULL,
  is_filterable boolean NOT NULL DEFAULT false,     -- hiện ở bộ lọc (vd 'Sạc không dây', 'Chỉnh ảnh AI')
  sort_order    int NOT NULL DEFAULT 0,
  UNIQUE (feature_group, name),
  UNIQUE (feature_group, slug)
);

CREATE TABLE product_features (
  product_id  bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  feature_id  bigint NOT NULL REFERENCES features(id) ON DELETE RESTRICT,
  PRIMARY KEY (product_id, feature_id)
);
CREATE INDEX product_features_feature_idx ON product_features (feature_id);

-- ---------------------------------------------------------------------
-- 4. NHU CẦU / NHÃN (bộ lọc 'Nhu cầu', 'Điện thoại AI'...)
-- ---------------------------------------------------------------------
CREATE TABLE tags (
  id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind  text NOT NULL CHECK (kind IN ('need','segment','badge')),
        -- need: chơi game, chụp ảnh, pin khủng, livestream, mỏng nhẹ
        -- segment: điện thoại AI, cao cấp, sinh viên ; badge: 'Mới', 'Độc quyền'
  slug  text NOT NULL UNIQUE,
  name  text NOT NULL,
  UNIQUE (kind, name)
);

CREATE TABLE product_tags (
  product_id bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  tag_id     bigint NOT NULL REFERENCES tags(id)     ON DELETE CASCADE,
  PRIMARY KEY (product_id, tag_id)
);

-- ---------------------------------------------------------------------
-- 5. MEDIA · BÀI VIẾT · FAQ · SẢN PHẨM LIÊN QUAN
-- ---------------------------------------------------------------------
CREATE TABLE product_media (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id  bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  color_id    bigint,                               -- ảnh theo màu; NULL = ảnh chung
  media_type  text NOT NULL CHECK (media_type IN ('image','video','image_360','thumbnail')),
  url         text NOT NULL,
  alt_text    text,
  sort_order  int NOT NULL DEFAULT 0,
  FOREIGN KEY (product_id, color_id) REFERENCES product_colors (product_id, id) ON DELETE CASCADE
);
CREATE INDEX product_media_product_idx ON product_media (product_id, sort_order);

CREATE TABLE articles (                            -- bài đánh giá/giới thiệu dài
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind          text NOT NULL CHECK (kind IN ('overview','review','news','buying_guide')),
  slug          text NOT NULL UNIQUE,
  title         text NOT NULL,
  content_md    text NOT NULL,
  published_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE article_products (
  article_id  bigint NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  product_id  bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  PRIMARY KEY (article_id, product_id)
);

CREATE TABLE faqs (                                -- 'Câu hỏi thường gặp trước khi mua'
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id  bigint REFERENCES products(id) ON DELETE CASCADE,   -- NULL = FAQ chung
  question    text NOT NULL,
  answer      text NOT NULL,
  sort_order  int NOT NULL DEFAULT 0
);

CREATE TABLE product_relations (
  product_id          bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  related_product_id  bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  relation_type       text NOT NULL CHECK (relation_type IN
                        ('accessory','bought_together','similar','newer_model','older_model')),
  sort_order          int NOT NULL DEFAULT 0,
  PRIMARY KEY (product_id, related_product_id, relation_type),
  CHECK (product_id <> related_product_id)
);

-- ---------------------------------------------------------------------
-- 6. CHÍNH SÁCH · GÓI DỊCH VỤ BẢO HÀNH
-- ---------------------------------------------------------------------
CREATE TABLE policies (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  policy_type     text NOT NULL CHECK (policy_type IN (
                    'warranty','return_exchange','installment','delivery','payment',
                    'unboxing','trade_in','privacy','other')),
  slug            text NOT NULL UNIQUE,
  title           text NOT NULL,                    -- 'Hư gì đổi nấy 12 tháng'
  summary         text,                             -- 1 dòng hiện ở mục 'cam kết' trang SP
  content_md      text NOT NULL,
  brand_id        bigint REFERENCES brands(id)     ON DELETE CASCADE,  -- NULL = mọi hãng
  category_id     bigint REFERENCES categories(id) ON DELETE CASCADE,  -- NULL = mọi ngành hàng
  effective_from  date NOT NULL DEFAULT current_date,
  effective_to    date,
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE service_packages (                    -- bán thêm: BH rơi vỡ, BH mở rộng, 1 đổi 1
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               text NOT NULL UNIQUE,
  name               text NOT NULL,
  service_type       text NOT NULL CHECK (service_type IN
                       ('extended_warranty','drop_damage','one_to_one_exchange','insurance','other')),
  duration_months    smallint NOT NULL CHECK (duration_months > 0),
  price_vnd          bigint CHECK (price_vnd >= 0),
  price_percent      numeric(5,2) CHECK (price_percent > 0 AND price_percent <= 100),  -- % giá máy
  min_product_price_vnd bigint,
  max_product_price_vnd bigint,
  brand_id           bigint REFERENCES brands(id)     ON DELETE CASCADE,
  category_id        bigint REFERENCES categories(id) ON DELETE CASCADE,
  terms_md           text,
  is_active          boolean NOT NULL DEFAULT true,
  CHECK (num_nonnulls(price_vnd, price_percent) = 1)
);

-- ---------------------------------------------------------------------
-- 7. KHUYẾN MÃI ('Chọn 1 trong các quà', giảm giá, phiếu mua hàng, ưu đãi thanh toán, thu cũ đổi mới)
-- ---------------------------------------------------------------------
CREATE TABLE promotions (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code               text UNIQUE,
  name               text NOT NULL,                 -- 'Giảm giá 2.400.000₫'
  description        text,
  promo_type         text NOT NULL CHECK (promo_type IN (
                       'discount_amount','discount_percent','voucher','gift_product',
                       'payment_discount','trade_in_bonus','bundle_discount','other')),
  discount_vnd       bigint CHECK (discount_vnd > 0),
  discount_percent   numeric(5,2) CHECK (discount_percent > 0 AND discount_percent <= 100),
  max_discount_vnd   bigint CHECK (max_discount_vnd > 0),
  voucher_value_vnd  bigint CHECK (voucher_value_vnd > 0),   -- 'Phiếu mua hàng Apple Watch trị giá 1.000.000đ'
  voucher_scope      text,                          -- áp dụng phiếu cho gì
  gift_product_id    bigint REFERENCES products(id) ON DELETE SET NULL,
  payment_method     text,                          -- ưu đãi qua VNPAY/thẻ ngân hàng X
  choice_group       text,                          -- cùng giá trị = khách chọn 1 trong nhóm
  is_stackable       boolean NOT NULL DEFAULT true,
  excludes_installment_0 boolean NOT NULL DEFAULT false,  -- 'không áp dụng đồng thời trả chậm 0%'
  channel            text NOT NULL DEFAULT 'all' CHECK (channel IN ('all','online','store')),
  priority           int NOT NULL DEFAULT 0,
  terms              text,
  starts_at          timestamptz NOT NULL,
  ends_at            timestamptz,                   -- 'áp dụng đến 23:59 | 30/11'
  is_active          boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR ends_at > starts_at),
  CHECK (promo_type <> 'discount_amount'  OR discount_vnd IS NOT NULL),
  CHECK (promo_type <> 'discount_percent' OR discount_percent IS NOT NULL),
  CHECK (promo_type <> 'voucher'          OR voucher_value_vnd IS NOT NULL),
  CHECK (promo_type <> 'gift_product'     OR gift_product_id IS NOT NULL)
);

CREATE TABLE promotion_targets (                   -- KM áp cho SP / SKU / hãng / ngành hàng
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  promotion_id bigint NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
  product_id   bigint REFERENCES products(id)          ON DELETE CASCADE,
  variant_id   bigint REFERENCES product_variants(id)  ON DELETE CASCADE,
  brand_id     bigint REFERENCES brands(id)            ON DELETE CASCADE,
  category_id  bigint REFERENCES categories(id)        ON DELETE CASCADE,
  CHECK (num_nonnulls(product_id, variant_id, brand_id, category_id) = 1)
);
CREATE INDEX promotion_targets_promo_idx ON promotion_targets (promotion_id);

-- ---------------------------------------------------------------------
-- 8. TRẢ CHẬM / TRẢ GÓP (công ty tài chính, thẻ tín dụng)
-- ---------------------------------------------------------------------
CREATE TABLE finance_partners (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code          text NOT NULL UNIQUE,               -- 'HOME_CREDIT', 'FE_CREDIT', 'ACS', 'MAFC', 'MCREDIT', 'VISA'
  name          text NOT NULL,
  partner_type  text NOT NULL CHECK (partner_type IN ('finance_company','credit_card','bnpl')),
  hotline       text,
  late_fee_note text,
  is_active     boolean NOT NULL DEFAULT true
);

CREATE TABLE installment_plans (                   -- 1 dòng = 1 gói: đối tác × kỳ hạn × lãi × trả trước
  id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  partner_id               bigint NOT NULL REFERENCES finance_partners(id) ON DELETE RESTRICT,
  name                     text NOT NULL,           -- 'Trả chậm 0% qua Home Credit 6 tháng'
  tenor_months             smallint NOT NULL CHECK (tenor_months > 0),
  interest_rate_monthly    numeric(5,3) NOT NULL DEFAULT 0 CHECK (interest_rate_monthly >= 0),  -- % / tháng
  min_down_payment_percent numeric(5,2) NOT NULL DEFAULT 0 CHECK (min_down_payment_percent BETWEEN 0 AND 100),
  fixed_fee_vnd            bigint NOT NULL DEFAULT 0 CHECK (fixed_fee_vnd >= 0),   -- phí hồ sơ/bảo hiểm khoản vay
  min_price_vnd            bigint,
  max_price_vnd            bigint,
  min_age                  smallint DEFAULT 18,
  max_age                  smallint DEFAULT 60,
  required_docs            text,                    -- 'CCCD còn hạn'
  conditions               text,
  starts_at                timestamptz NOT NULL DEFAULT now(),
  ends_at                  timestamptz,
  is_active                boolean NOT NULL DEFAULT true,
  CHECK (ends_at IS NULL OR ends_at > starts_at)
);

CREATE TABLE installment_plan_targets (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  plan_id     bigint NOT NULL REFERENCES installment_plans(id) ON DELETE CASCADE,
  product_id  bigint REFERENCES products(id)         ON DELETE CASCADE,
  variant_id  bigint REFERENCES product_variants(id) ON DELETE CASCADE,
  brand_id    bigint REFERENCES brands(id)           ON DELETE CASCADE,
  category_id bigint REFERENCES categories(id)       ON DELETE CASCADE,
  CHECK (num_nonnulls(product_id, variant_id, brand_id, category_id) = 1)
);
CREATE INDEX installment_plan_targets_plan_idx ON installment_plan_targets (plan_id);

-- ---------------------------------------------------------------------
-- 9. CỬA HÀNG & TỒN KHO
-- ---------------------------------------------------------------------
CREATE TABLE provinces (                           -- 2 cấp hành chính: tỉnh/thành → phường/xã
  code  text PRIMARY KEY,
  name  text NOT NULL UNIQUE
);

CREATE TABLE stores (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code           text NOT NULL UNIQUE,
  name           text NOT NULL,
  store_type     text NOT NULL DEFAULT 'store' CHECK (store_type IN ('store','warehouse')),  -- kho online = warehouse
  address        text NOT NULL,
  ward           text,
  province_code  text NOT NULL REFERENCES provinces(code),
  latitude       numeric(9,6),
  longitude      numeric(9,6),
  phone          text,
  open_time      time,
  close_time     time,
  is_active      boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stores_province_idx ON stores (province_code);

CREATE TABLE inventory (
  store_id      bigint NOT NULL REFERENCES stores(id)           ON DELETE CASCADE,
  variant_id    bigint NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
  quantity      int NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  reserved_qty  int NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (store_id, variant_id),
  CHECK (reserved_qty <= quantity)
);
CREATE INDEX inventory_variant_idx ON inventory (variant_id);

-- ---------------------------------------------------------------------
-- 10. KHÁCH HÀNG · ĐÁNH GIÁ · HỎI ĐÁP · GIỮ HÀNG/HẸN (agent ghi vào)
-- ---------------------------------------------------------------------
CREATE TABLE customers (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  phone              text UNIQUE,
  full_name          text,
  email              text,
  province_code      text REFERENCES provinces(code),
  budget_min_vnd     bigint CHECK (budget_min_vnd >= 0),
  budget_max_vnd     bigint CHECK (budget_max_vnd >= 0),
  preferred_brand_id bigint REFERENCES brands(id) ON DELETE SET NULL,
  needs              text,                          -- agent tóm tắt: 'chơi game, pin trâu'
  notes              text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (budget_max_vnd IS NULL OR budget_min_vnd IS NULL OR budget_max_vnd >= budget_min_vnd)
);

CREATE TABLE product_reviews (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id            bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  variant_id            bigint REFERENCES product_variants(id) ON DELETE SET NULL,
  customer_id           bigint REFERENCES customers(id) ON DELETE SET NULL,
  author_name           text NOT NULL,
  rating                smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
  content               text,
  is_verified_purchase  boolean NOT NULL DEFAULT false,   -- 'Đã mua tại ĐMX'
  helpful_count         int NOT NULL DEFAULT 0 CHECK (helpful_count >= 0),
  status                text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','hidden')),
  staff_reply           text,                       -- 'Bộ phận bảo hành đã liên hệ hỗ trợ...'
  replied_at            timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX product_reviews_product_idx ON product_reviews (product_id, created_at DESC);

CREATE TABLE product_questions (                   -- mục 'Hỏi đáp'
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id   bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  customer_id  bigint REFERENCES customers(id) ON DELETE SET NULL,
  author_name  text NOT NULL,
  question     text NOT NULL,
  answer       text,
  answered_at  timestamptz,
  status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','hidden')),
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reservations (                        -- giữ hàng tại cửa hàng / hẹn tư vấn trả góp / gọi lại
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id       bigint NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  reservation_type  text NOT NULL CHECK (reservation_type IN ('hold_stock','store_visit','installment_consult','callback')),
  variant_id        bigint REFERENCES product_variants(id) ON DELETE SET NULL,
  store_id          bigint REFERENCES stores(id) ON DELETE SET NULL,
  quantity          smallint NOT NULL DEFAULT 1 CHECK (quantity > 0),
  scheduled_at      timestamptz,
  expires_at        timestamptz,
  status            text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','confirmed','completed','cancelled','expired')),
  channel           text NOT NULL DEFAULT 'chat' CHECK (channel IN ('voice','chat','web','store')),
  note              text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (reservation_type <> 'hold_stock' OR (variant_id IS NOT NULL AND store_id IS NOT NULL))
);
CREATE INDEX reservations_customer_idx ON reservations (customer_id, created_at DESC);

-- ---------------------------------------------------------------------
-- 11. HÀNG ĐỢI JOB (worker: index Qdrant, bóc chữ tài liệu...) — core/jobs.py
-- ---------------------------------------------------------------------
CREATE TABLE jobs (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind          text NOT NULL,
  actor         text NOT NULL DEFAULT 'system',
  payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
  state         text NOT NULL DEFAULT 'queued'
                CHECK (state IN ('queued','running','success','failed')),
  attempts      int NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  count         int NOT NULL DEFAULT 0,
  message       text,
  run_after     timestamptz NOT NULL DEFAULT now(),
  started_at    timestamptz,
  heartbeat_at  timestamptz,
  finished_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_queued_idx ON jobs (kind, id) WHERE state = 'queued';
CREATE INDEX jobs_running_idx ON jobs (kind) WHERE state = 'running';
-- Chống trùng: đã có việc y hệt đang chờ thì không xếp thêm (sửa liên tiếp 10 lần = 1 lượt index).
-- KHÔNG unique: retry/thu hồi/trả việc đưa job về 'queued' và sẽ đụng khoá với bản đang chờ.
-- Hai giao dịch song song lọt một bản trùng là vô hại — handler bỏ qua khi content_hash không đổi.
CREATE INDEX jobs_dedup_queued ON jobs (kind, payload) WHERE state = 'queued';

-- ---------------------------------------------------------------------
-- 12. KHO TRI THỨC (Qdrant) — modules/kb
-- ---------------------------------------------------------------------
CREATE TABLE kb_files (                            -- «Tài liệu tra cứu»: tệp upload → bóc chữ → nhúng
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  file_name      text NOT NULL,
  s3_key         text NOT NULL UNIQUE,
  size_bytes     bigint NOT NULL CHECK (size_bytes > 0),
  file_type      text NOT NULL CHECK (file_type IN ('pdf','docx','xlsx','md')),
  product_id     bigint REFERENCES products(id) ON DELETE SET NULL,   -- tài liệu riêng của 1 máy (HDSD...)
  brand_id       bigint REFERENCES brands(id)   ON DELETE SET NULL,   -- hoặc của 1 hãng
  state          text NOT NULL DEFAULT 'processing' CHECK (state IN ('processing','ready','error')),
  chunk_count    int NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
  error_message  text,
  uploaded_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE kb_index_state (                      -- sổ index của dữ liệu DB (không gồm kb_files — bảng đó tự giữ state)
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity        text NOT NULL CHECK (entity IN ('product','policy','article','faq','service_package','product_media')),
  record_id     bigint NOT NULL,
  target        text NOT NULL CHECK (target IN ('documents','media')),
  state         text NOT NULL CHECK (state IN ('indexed','skipped','error','deleted')),
  content_hash  text,
  points        int NOT NULL DEFAULT 0,
  error         text,
  indexed_at    timestamptz,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (entity, record_id, target)
);

-- Xếp job nếu chưa có bản y hệt đang chờ. Trả id job mới, NULL nếu đã có.
CREATE FUNCTION shop.enqueue_once(p_kind text, p_actor text, p_payload jsonb, p_delay_sec float8 DEFAULT 0)
RETURNS bigint LANGUAGE sql AS $$
  INSERT INTO shop.jobs (kind, actor, payload, run_after)
  SELECT p_kind, p_actor, p_payload, now() + make_interval(secs => p_delay_sec)
  WHERE NOT EXISTS (SELECT 1 FROM shop.jobs WHERE state = 'queued' AND kind = p_kind AND payload = p_payload)
  RETURNING id
$$;

-- Mọi thay đổi ở bảng nguồn tự xếp job index — code CRUD không thể quên báo KB.
-- TG_ARGV[0] = entity; TG_ARGV[1] = cột chứa id của entity (vd bảng con phone_specs → 'product_id').
CREATE FUNCTION shop.kb_enqueue() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  r      jsonb := to_jsonb(CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END);
  rid    bigint := (r ->> TG_ARGV[1])::bigint;
  kind   text := CASE WHEN TG_OP = 'DELETE' AND TG_ARGV[1] = 'id' THEN 'kb_delete' ELSE 'kb_index' END;
BEGIN
  IF rid IS NOT NULL THEN
    PERFORM shop.enqueue_once(kind, 'trigger', jsonb_build_object('entity', TG_ARGV[0], 'id', rid));
  END IF;
  -- UPDATE đổi khoá cha (vd media chuyển sang sản phẩm khác) ⇒ index lại cả bên cũ.
  IF TG_OP = 'UPDATE' AND TG_ARGV[1] <> 'id' AND (to_jsonb(OLD) ->> TG_ARGV[1]) IS DISTINCT FROM (r ->> TG_ARGV[1]) THEN
    PERFORM shop.enqueue_once('kb_index', 'trigger',
                              jsonb_build_object('entity', TG_ARGV[0], 'id', (to_jsonb(OLD) ->> TG_ARGV[1])::bigint));
  END IF;
  RETURN NULL;
END $$;

-- Đổi TÊN hãng/ngành hàng/dòng máy ⇒ index lại mọi sản phẩm thuộc nó (tên nằm trong text + payload).
-- TG_ARGV[0] = cột khoá ngoại trên products ('brand_id' | 'category_id' | 'series_id').
CREATE FUNCTION shop.kb_enqueue_products_of() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.name IS DISTINCT FROM OLD.name THEN
    EXECUTE format(
      'SELECT shop.enqueue_once(''kb_index'', ''trigger'', jsonb_build_object(''entity'', ''product'', ''id'', p.id))
         FROM shop.products p WHERE p.%I = $1', TG_ARGV[0])
    USING NEW.id;
  END IF;
  RETURN NULL;
END $$;

CREATE TRIGGER kb_brands_rename     AFTER UPDATE OF name ON brands     FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue_products_of('brand_id');
CREATE TRIGGER kb_categories_rename AFTER UPDATE OF name ON categories FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue_products_of('category_id');
CREATE TRIGGER kb_series_rename     AFTER UPDATE OF name ON series     FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue_products_of('series_id');

CREATE TRIGGER kb_products         AFTER INSERT OR UPDATE OR DELETE ON products         FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product', 'id');
CREATE TRIGGER kb_phone_specs      AFTER INSERT OR UPDATE OR DELETE ON phone_specs      FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product', 'product_id');
CREATE TRIGGER kb_product_variants AFTER INSERT OR UPDATE OR DELETE ON product_variants FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product', 'product_id');
CREATE TRIGGER kb_product_colors   AFTER INSERT OR UPDATE OR DELETE ON product_colors   FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product', 'product_id');
CREATE TRIGGER kb_product_features AFTER INSERT OR UPDATE OR DELETE ON product_features FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product', 'product_id');
CREATE TRIGGER kb_product_tags     AFTER INSERT OR UPDATE OR DELETE ON product_tags     FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product', 'product_id');
CREATE TRIGGER kb_faqs             AFTER INSERT OR UPDATE OR DELETE ON faqs             FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('faq', 'id');
CREATE TRIGGER kb_policies         AFTER INSERT OR UPDATE OR DELETE ON policies         FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('policy', 'id');
CREATE TRIGGER kb_articles         AFTER INSERT OR UPDATE OR DELETE ON articles         FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('article', 'id');
CREATE TRIGGER kb_article_products AFTER INSERT OR UPDATE OR DELETE ON article_products FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('article', 'article_id');
CREATE TRIGGER kb_service_packages AFTER INSERT OR UPDATE OR DELETE ON service_packages FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('service_package', 'id');
CREATE TRIGGER kb_product_media    AFTER INSERT OR UPDATE OR DELETE ON product_media    FOR EACH ROW EXECUTE FUNCTION shop.kb_enqueue('product_media', 'id');

-- updated_at triggers
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['brands','categories','products','product_variants','phone_specs','articles',
                           'policies','promotions','stores','inventory','customers','reservations']
  LOOP
    EXECUTE format('CREATE TRIGGER %I_touch BEFORE UPDATE ON shop.%I FOR EACH ROW EXECUTE FUNCTION shop.touch_updated_at()', t, t);
  END LOOP;
END $$;

-- =====================================================================
-- 12. VIEW CHO AGENT (text-to-SQL đọc view phẳng, không đọc bảng)
-- =====================================================================
CREATE VIEW agent_products_v AS
SELECT
  v.id                                         AS variant_id,
  p.id                                         AS product_id,
  v.sku,
  p.name                                       AS product_name,
  p.name
    || coalesce(' ' || nullif(trim(to_char(v.ram_gb, 'FM999990.###')), '') || 'GB', '')
    || coalesce('/' || CASE WHEN v.storage_gb >= 1024 THEN trim(to_char(v.storage_gb / 1024, 'FM9990.##')) || 'TB'
                             ELSE trim(to_char(v.storage_gb, 'FM999990.###')) || 'GB' END, '')
    || coalesce(' ' || c.name, '')            AS variant_name,
  b.name                                       AS brand,
  cat.name                                     AS category,
  s.name                                       AS series,
  p.phone_type,
  c.name                                       AS color,
  v.ram_gb, v.storage_gb, v.condition,
  v.list_price_vnd,
  coalesce(v.sale_price_vnd, v.list_price_vnd) AS price_vnd,
  round(100.0 * (v.list_price_vnd - coalesce(v.sale_price_vnd, v.list_price_vnd)) / v.list_price_vnd)::int
                                               AS discount_percent,
  v.sale_status,
  coalesce(stk.qty_available, 0)               AS qty_available,
  sp.os_name, sp.os_version, sp.chipset,
  sp.screen_size_inch, sp.display_tech, sp.resolution_class, sp.refresh_rate_hz,
  sp.rear_camera_main_mp, sp.front_camera_mp,
  sp.battery_mah, sp.battery_text, sp.max_charge_w,
  sp.has_5g, sp.has_nfc, sp.has_esim, sp.has_face_3d, sp.ip_rating,
  sp.weight_g, sp.thickness_mm,
  p.release_date, p.warranty_months,
  p.rating_avg, p.rating_count, p.sold_count,
  tg.tags,
  EXISTS (SELECT 1 FROM installment_plans ip JOIN installment_plan_targets t ON t.plan_id = ip.id
          WHERE ip.is_active AND ip.interest_rate_monthly = 0
            AND now() >= ip.starts_at AND (ip.ends_at IS NULL OR now() < ip.ends_at)
            AND (t.variant_id = v.id OR t.product_id = p.id OR t.brand_id = p.brand_id OR t.category_id = p.category_id))
                                               AS has_installment_0,
  lower(unaccent(p.name || ' ' || b.name || ' ' || coalesce(c.name, '') || ' ' || coalesce(sp.chipset, '')))
                                               AS search_text
FROM product_variants v
JOIN products   p   ON p.id = v.product_id
JOIN brands     b   ON b.id = p.brand_id
JOIN categories cat ON cat.id = p.category_id
LEFT JOIN series         s  ON s.id = p.series_id
LEFT JOIN product_colors c  ON c.id = v.color_id
LEFT JOIN phone_specs    sp ON sp.product_id = p.id
LEFT JOIN LATERAL (SELECT sum(i.quantity - i.reserved_qty) AS qty_available
                   FROM inventory i WHERE i.variant_id = v.id) stk ON true
LEFT JOIN LATERAL (SELECT string_agg(t.name, ', ' ORDER BY t.name) AS tags
                   FROM product_tags pt JOIN tags t ON t.id = pt.tag_id WHERE pt.product_id = p.id) tg ON true
WHERE p.status IN ('selling','coming_soon');

COMMENT ON VIEW agent_products_v IS 'Mỗi dòng 1 SKU đang bán/sắp bán. Giá VND. Lọc tên bằng search_text ILIKE (đã bỏ dấu, chữ thường).';
COMMENT ON COLUMN agent_products_v.price_vnd        IS 'Giá bán hiện tại (sau giảm trực tiếp, CHƯA trừ quà/voucher)';
COMMENT ON COLUMN agent_products_v.discount_percent IS '% giảm so với giá niêm yết';
COMMENT ON COLUMN agent_products_v.qty_available    IS 'Tổng tồn khả dụng mọi cửa hàng (đã trừ hàng đang giữ)';
COMMENT ON COLUMN agent_products_v.battery_mah      IS 'NULL với iPhone (Apple không công bố) — dùng battery_text';
COMMENT ON COLUMN agent_products_v.tags             IS 'Nhu cầu/nhãn, vd: Chơi game, Chụp ảnh, Pin khủng';

CREATE VIEW agent_promotions_v AS
SELECT pr.id AS promotion_id, pr.name, pr.promo_type, pr.discount_vnd, pr.discount_percent,
       pr.voucher_value_vnd, gp.name AS gift_product, pr.payment_method, pr.choice_group,
       pr.excludes_installment_0, pr.channel, pr.starts_at, pr.ends_at,
       t.product_id, t.variant_id, b.name AS brand, cat.name AS category
FROM promotions pr
JOIN promotion_targets t ON t.promotion_id = pr.id
LEFT JOIN products   gp  ON gp.id  = pr.gift_product_id
LEFT JOIN brands     b   ON b.id   = t.brand_id
LEFT JOIN categories cat ON cat.id = t.category_id
WHERE pr.is_active AND now() >= pr.starts_at AND (pr.ends_at IS NULL OR now() < pr.ends_at);

COMMENT ON VIEW agent_promotions_v IS 'KM đang chạy. Một KM áp cho đúng 1 trong: product_id | variant_id | brand | category. Cùng choice_group = khách chọn 1.';

CREATE VIEW agent_stock_v AS
SELECT i.variant_id, st.id AS store_id, st.name AS store_name, st.address, st.ward,
       pv.name AS province, st.phone, st.open_time, st.close_time,
       i.quantity - i.reserved_qty AS qty_available
FROM inventory i
JOIN stores st   ON st.id = i.store_id AND st.is_active AND st.store_type = 'store'
JOIN provinces pv ON pv.code = st.province_code
WHERE i.quantity > i.reserved_qty;

COMMENT ON VIEW agent_stock_v IS 'Tồn kho còn bán được theo cửa hàng. Nối agent_products_v qua variant_id.';
