"""Fixture module kb: fake embed/Qdrant/S3 cắm vào `deps` + dữ liệu sản phẩm mẫu."""

from dataclasses import dataclass

import asyncpg
import pytest

import portal.modules.kb.jobs  # noqa: F401 — đăng ký handler cho run_once
from portal.modules.kb import deps
from tests.modules.kb.fakes import FakeEmbed, FakeObjects, FakeStore

GIA_NIEM_YET = 34_990_000
GIA_BAN = 33_490_000


@dataclass
class Fakes:
    embed: FakeEmbed
    store: FakeStore
    objects: FakeObjects


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    f = Fakes(FakeEmbed(), FakeStore(), FakeObjects())
    monkeypatch.setattr(deps, "embed_client", lambda objects: f.embed)
    monkeypatch.setattr(deps, "qdrant_store", lambda: f.store)
    monkeypatch.setattr(deps, "object_store", lambda: f.objects)
    return f


async def seed_product(pool: asyncpg.Pool, *, status: str = "selling") -> int:
    """iPhone mẫu đủ thông số, tính năng đa trị, màu, 2 cấu hình RAM/ROM có GIÁ, nhãn."""
    async with pool.acquire() as c, c.transaction():
        cat = await c.fetchval("INSERT INTO shop.categories (slug, name) VALUES ('dtdd', 'Điện thoại') RETURNING id")
        brand = await c.fetchval("INSERT INTO shop.brands (slug, name) VALUES ('apple', 'iPhone (Apple)') RETURNING id")
        pid = await c.fetchval(
            """INSERT INTO shop.products (category_id, brand_id, slug, name, phone_type, status, release_date,
                                          short_description, highlights_md, in_box, warranty_months, warranty_note)
               VALUES ($1, $2, 'iphone-16-pro-max', 'iPhone 16 Pro Max', 'smartphone', $3, '2024-09-01',
                       'Flagship 2024 của Apple.', '- Khung titan\n- Nút Camera Control',
                       'Hộp, Cáp USB-C, Cây lấy sim', 12, 'Bảo hành chính hãng 1 năm')
               RETURNING id""",
            cat,
            brand,
            status,
        )
        await c.execute(
            """INSERT INTO shop.phone_specs (product_id, os_name, os_version, chipset, cpu_speed_text,
                   rear_camera_text, front_camera_text, display_tech, display_resolution_text,
                   screen_size_inch, refresh_rate_hz, battery_text, max_charge_w, charger_included,
                   ip_rating, network_gen, sim_text, has_nfc, material_text, weight_g,
                   length_mm, width_mm, thickness_mm)
               VALUES ($1, 'iOS', 'iOS 18', 'Apple A18 Pro 6 nhân', '4.05 GHz',
                   'Chính 48 MP & Phụ 48 MP, 12 MP', '12 MP', 'OLED', 'Super Retina XDR (1320 x 2868 Pixels)',
                   6.90, 120, '33 giờ', 20, false,
                   'IP68', '5G', '1 Nano SIM & 1 eSIM', true, 'Khung Titan & Mặt lưng kính cường lực', 227,
                   163.0, 77.6, 8.25)""",
            pid,
        )
        f1 = await c.fetchval(
            "INSERT INTO shop.features (feature_group, name, slug) "
            "VALUES ('rear_camera', 'Chống rung quang học (OIS)', 'ois') RETURNING id"
        )
        f2 = await c.fetchval(
            "INSERT INTO shop.features (feature_group, name, slug) VALUES ('wifi', 'Wi-Fi 7', 'wifi-7') RETURNING id"
        )
        await c.execute("INSERT INTO shop.product_features VALUES ($1, $2), ($1, $3)", pid, f1, f2)
        color = await c.fetchval(
            "INSERT INTO shop.product_colors (product_id, name) VALUES ($1, 'Titan sa mạc') RETURNING id", pid
        )
        await c.execute(
            """INSERT INTO shop.product_variants (product_id, color_id, sku, ram_gb, storage_gb,
                                                  list_price_vnd, sale_price_vnd)
               VALUES ($1, $2, 'IP16PM-256', 8, 256, $3, $4), ($1, $2, 'IP16PM-1T', 8, 1024, $3 + 10000000, NULL)""",
            pid,
            color,
            GIA_NIEM_YET,
            GIA_BAN,
        )
        tag = await c.fetchval(
            "INSERT INTO shop.tags (kind, slug, name) VALUES ('need', 'chup-anh', 'Chụp ảnh đẹp') RETURNING id"
        )
        await c.execute("INSERT INTO shop.product_tags VALUES ($1, $2)", pid, tag)
    return pid
