# Đăng nhập bằng Google (OAuth 2.0 / OIDC) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm đường đăng nhập thứ hai qua Google cho NobleX Portal, không đổi đường mật khẩu và không đổi mô hình phiên.

**Architecture:** Authorization Code + PKCE, redirect toàn trang. `client_secret` chỉ sống ở backend; `id_token` của Google chết ngay sau khi đọc claims. Phiên vẫn là cookie đối xứng HttpOnly lưu Redis, sinh bằng đúng `ss.tao()` mà đường mật khẩu đang dùng. Danh tính ngoài nằm ở bảng quan hệ `control.identities` khớp theo `(provider, subject)`, KHÔNG phải một cột email thứ hai trong `users`.

**Tech Stack:** Python 3.13 · FastAPI · asyncpg · Alembic · redis-py asyncio · httpx (đã là dep chính) · pytest — React 19 · TanStack Router · Vitest · MSW

**Spec:** `odyssey-portal-backend/docs/superpowers/specs/2026-08-18-dang-nhap-google-oauth-design.md`

## Global Constraints

- **Hai repo.** Task 1–6 ở `odyssey-portal-backend/`, Task 7 ở `odyssey-portal-frontend/`. Mọi đường dẫn dưới đây là tương đối từ gốc repo tương ứng.
- **KHÔNG thêm dependency nào.** `httpx` và `cryptography` đã có trong `pyproject.toml`. Không cài `pyjwt`, `google-auth`, `authlib`.
- **KHÔNG thêm cột nào vào `control.users`.** Xem spec §2.
- **Mọi endpoint phải khai `action`** — cổng 1 quét và làm CI đỏ nếu thiếu. Ba đường mới đều công khai nên khai `require(None, ly_do="…")` với lý do TƯỜNG MINH.
- **Đường trong router viết TƯƠNG ĐỐI** (`'/auth/google/start'`), tiền tố `/api/v1` do `api/app.py` gắn.
- **Mọi đường GHI bọc `conn.transaction()` ở TẦNG ROUTER**, không trong service — lối `repo.py` đã ghi ("caller quyết định giao dịch").
- **Comment và docstring viết tiếng Việt**, theo lối repo: nói VÌ SAO, không nói CÁI GÌ.
- **Chỉ một alembic head.** `tests/unit/test_alembic_mot_head.py` neo điều này.
- **Chạy test backend:** `uv run pytest <đường dẫn> -v` (cần Docker cho Postgres/Redis, trừ `tests/unit`).
- **Chạy test frontend:** `npm test -- <đường dẫn>`.
- **Typecheck frontend là `npm run build`**, KHÔNG phải `tsc --noEmit` (tsconfig kiểu solution — pass rỗng).

---

### Task 1: Migration 0108 — bảng `identities` và nới bất biến mật khẩu

**Files:**
- Create: `migrations/versions/0108_dang_nhap_google.py`
- Create: `tests/modules/auth/test_migration_google.py`

**Interfaces:**
- Consumes: head alembic hiện tại là `0935_hop_nhat_hai_head`. **Kiểm lại trước khi viết**: `grep -h 'revision = ' migrations/versions/*.py` rồi tìm revision không xuất hiện ở `down_revision` nào.
- Produces: bảng `control.identities` với `PRIMARY KEY (provider, subject)`, index `identities_user_id_idx`, unique index `identities_mot_provider_moi_user`; constraint `users_co_duong_dang_nhap_check` thay cho `users_password_theo_lifecycle_check`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/auth/test_migration_google.py`:

```python
"""Migration 0108 — bảng identities và bất biến mật khẩu đã nới.

Bốn cổng ở đây neo những thứ CHỈ DB giữ được. Cổng 4 là ngoại lệ: nó neo một
lời hứa mà CHECK không giữ nổi (phải nhìn sang bảng khác), nên test này là chỗ
DUY NHẤT giữ nó — xem spec §4.2.
"""

import asyncpg
import pytest


async def _tao_user_google(conn, user_id: str, email: str) -> None:
    """User của nhánh 3: active, KHÔNG mật khẩu."""
    await conn.execute(
        "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
        "VALUES ($1, $2, NULL, 'Người Thử', 'active')",
        user_id,
        email,
    )


async def test_cong_1_user_active_khong_mat_khau_insert_duoc(pool):
    """Chính ca mà CHECK song điều kiện của 0103 chặn. Không nới thì test này đỏ."""
    async with pool.acquire() as conn, conn.transaction():
        await _tao_user_google(conn, "u_g_cong1", "cong1@thu.vn")
        assert await conn.fetchval(
            "SELECT password_hash IS NULL FROM control.users WHERE id = 'u_g_cong1'"
        )
        raise asyncpg.exceptions.PostgresError  # rollback, không để lại rác


async def test_cong_2_pending_van_khong_duoc_co_mat_khau(pool):
    """Lời hứa ① của 0103 phải còn nguyên sau khi nới."""
    async with pool.acquire() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
                "VALUES ('u_g_cong2', 'cong2@thu.vn', 'hash-gia', 'X', 'pending')"
            )


async def test_cong_3_hai_user_khong_the_chiem_cung_mot_tai_khoan_google(pool):
    """PRIMARY KEY (provider, subject) — đây LÀ danh tính của hàng, không phải
    một UNIQUE thêm cho vui."""
    async with pool.acquire() as conn:
        try:
            await _tao_user_google(conn, "u_g_a", "a@thu.vn")
            await _tao_user_google(conn, "u_g_b", "b@thu.vn")
            await conn.execute(
                "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                "VALUES ('google', '104287', 'u_g_a', 'a@thu.vn')"
            )
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                    "VALUES ('google', '104287', 'u_g_b', 'b@thu.vn')"
                )
        finally:
            await conn.execute("DELETE FROM control.users WHERE id IN ('u_g_a', 'u_g_b')")


async def test_cong_4_mot_user_khong_gan_duoc_hai_tai_khoan_google(pool):
    async with pool.acquire() as conn:
        try:
            await _tao_user_google(conn, "u_g_c", "c@thu.vn")
            await conn.execute(
                "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                "VALUES ('google', '111', 'u_g_c', 'c@thu.vn')"
            )
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
                    "VALUES ('google', '222', 'u_g_c', 'c@thu.vn')"
                )
        finally:
            await conn.execute("DELETE FROM control.users WHERE id = 'u_g_c'")


async def test_cong_5_khong_con_hang_active_nao_khong_duong_dang_nhap(pool):
    """Lời hứa ② mà CHECK không giữ nổi (nó phải nhìn sang bảng khác — spec §4.2).

    TEST NÀY LÀ CHỖ DUY NHẤT GIỮ NÓ. Quét cả bảng chứ không kiểm một hàng: thứ
    cần chặn là rác tích lại theo thời gian, không phải một lần INSERT sai.
    """
    async with pool.acquire() as conn:
        rac = await conn.fetch(
            "SELECT u.id FROM control.users u "
            "LEFT JOIN control.identities i ON i.user_id = u.id "
            "WHERE u.lifecycle = 'active' AND u.password_hash IS NULL AND i.user_id IS NULL"
        )
    assert rac == [], f"user `active` không mật khẩu và không identity — không đường nào vào: {rac}"


async def test_cong_6_xoa_user_thi_identity_di_theo(pool):
    async with pool.acquire() as conn:
        await _tao_user_google(conn, "u_g_d", "d@thu.vn")
        await conn.execute(
            "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider) "
            "VALUES ('google', '333', 'u_g_d', 'd@thu.vn')"
        )
        await conn.execute("DELETE FROM control.users WHERE id = 'u_g_d'")
        assert await conn.fetchval("SELECT count(*) FROM control.identities WHERE subject = '333'") == 0
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/modules/auth/test_migration_google.py -v`
Expected: FAIL — `UndefinedTableError: relation "control.identities" does not exist`, và cổng 1 đỏ vì `CheckViolationError` trên `users_password_theo_lifecycle_check`.

- [ ] **Step 3: Viết migration**

Tạo `migrations/versions/0108_dang_nhap_google.py`:

```python
"""control.identities · nới bất biến mật khẩu của users

Spec: docs/superpowers/specs/2026-08-18-dang-nhap-google-oauth-design.md

HAI THỨ, MỘT MIGRATION — chúng là một thay đổi nghiệp vụ duy nhất ("người dùng
vào bằng tài khoản Google"). Tách ra thì có một trạng thái trung gian không chạy
được: bảng identities mà CHECK cũ còn nguyên nghĩa là không hàng users nào của
nhánh Google INSERT nổi.

VÌ SAO KHÔNG PHẢI MỘT CỘT `gmail` TRONG users (spec §2): `email` không phải khoá
của Google — `sub` mới là, và nó bất biến khi người dùng đổi email. Một cột email
thứ hai còn trùng lặp với `users.email` vốn đã UNIQUE; hai cột cho một sự thật là
một bug đang chờ lệch (cùng lý lẽ 0100 đã ghi khi từ chối cột `initials`).

Revision ID: 0108_dang_nhap_google
Revises: 0935_hop_nhat_hai_head
"""

from alembic import op

revision = "0108_dang_nhap_google"
down_revision = "0935_hop_nhat_hai_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ① Danh tính ngoài -------------------------------------------------
    # PRIMARY KEY (provider, subject) KHÔNG phải một UNIQUE thêm vào sau — nó LÀ
    # danh tính của hàng này, và nó là thứ duy nhất chặn hai user cùng chiếm một
    # tài khoản Google.
    #
    # `email_tai_provider` CHỈ để hiển thị và audit. KHÔNG đường nào được khớp
    # user bằng cột này: Google cho đổi email của tài khoản, nên khớp theo email
    # là để người đổi email mất sạch workspace. Cột tồn tại để trả lời "tài khoản
    # Google nào đang gắn vào đây" mà không phải gọi Google.
    #
    # UNIQUE (user_id, provider) chặn một user gắn hai tài khoản Google khác nhau
    # — nếu không, nhánh «liên kết» chạy hai lần là hai đường vào cùng một tài
    # khoản mà chỉ một cái bị thu hồi khi gỡ.
    op.execute(
        """
        CREATE TABLE control.identities (
            provider    text NOT NULL
                        CONSTRAINT identities_provider_check CHECK (provider IN ('google')),
            subject     text NOT NULL
                        CONSTRAINT identities_subject_check CHECK (subject <> ''),
            user_id     text NOT NULL REFERENCES control.users(id) ON DELETE CASCADE,
            email_tai_provider text NOT NULL
                        CONSTRAINT identities_email_lower_check
                        CHECK (email_tai_provider = lower(email_tai_provider)),
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_login_at timestamptz,
            PRIMARY KEY (provider, subject)
        )
        """
    )
    op.execute("CREATE INDEX identities_user_id_idx ON control.identities(user_id)")
    op.execute(
        "CREATE UNIQUE INDEX identities_mot_provider_moi_user ON control.identities(user_id, provider)"
    )
    # portal_api chỉ cần bốn quyền này — cùng khuôn mọi bảng control khác.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON control.identities TO portal_api")

    # --- ② Nới bất biến mật khẩu ------------------------------------------
    # CHECK cũ là SONG ĐIỀU KIỆN và giữ HAI lời hứa cùng lúc (0103 ghi rõ):
    #   ① pending mà đã có hash  -> thư mời còn sống sau khi mật khẩu đã đặt
    #   ② active  mà chưa có hash -> tài khoản đăng nhập được không cần mật khẩu
    #
    # Ràng buộc mới giữ ①. Lời hứa ② KHÔNG đặt được bằng CHECK vì nó phải nhìn
    # sang control.identities, và CHECK của Postgres không làm được điều đó.
    #
    # ⚠ ĐÂY LÀ MỘT SỰ NỚI THẬT, không phải viết lại cho gọn: sau migration này DB
    # cho phép một hàng `active` không mật khẩu và không identity — một tài khoản
    # không đường nào vào. Vô hại (không ai đăng nhập được) nhưng là rác. Lời hứa
    # ② từ nay do `tests/modules/auth/test_migration_google.py` giữ, KHÔNG do DB.
    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_password_theo_lifecycle_check")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_co_duong_dang_nhap_check
             CHECK (lifecycle <> 'pending' OR password_hash IS NULL)"""
    )


def downgrade() -> None:
    """Ngược đúng thứ tự upgrade().

    XOÁ user `active` không mật khẩu TRƯỚC khi đặt lại CHECK cũ: họ là hợp lệ
    dưới ràng buộc mới và vi phạm ràng buộc cũ, nên ALTER sẽ nổ và downgrade
    dừng giữa đường. Cùng lỗi mà 0103 đã xử ở nhánh `pending`.
    """
    op.execute("ALTER TABLE control.users DROP CONSTRAINT users_co_duong_dang_nhap_check")
    op.execute("DELETE FROM control.users WHERE lifecycle = 'active' AND password_hash IS NULL")
    op.execute(
        """ALTER TABLE control.users ADD CONSTRAINT users_password_theo_lifecycle_check
             CHECK ((lifecycle = 'pending') = (password_hash IS NULL))"""
    )
    op.execute("DROP TABLE control.identities")
```

- [ ] **Step 4: Chạy migration rồi chạy lại test**

Run: `uv run alembic upgrade head && uv run pytest tests/modules/auth/test_migration_google.py tests/unit/test_alembic_mot_head.py -v`
Expected: PASS toàn bộ (6 cổng + test một head).

- [ ] **Step 5: Kiểm downgrade chạy được**

Run: `uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: cả hai lệnh thoát mã 0, không traceback.

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/0108_dang_nhap_google.py tests/modules/auth/test_migration_google.py
git commit -m "feat(auth): bảng control.identities và nới bất biến mật khẩu của users"
```

---

### Task 2: Cấu hình Google

**Files:**
- Modify: `src/portal/core/config.py` (thêm vào lớp `Settings`, đặt ngay dưới khối `signup_enabled`)
- Create: `tests/unit/test_config_google.py`
- Modify: `deploy/odyssey-portal-backend.env.example` (nếu file tồn tại — `ls deploy/`)

**Interfaces:**
- Consumes: `Settings.public_base_url`, `Settings.environment`, `get_settings()` — đã có.
- Produces: `Settings.google_client_id: str`, `Settings.google_client_secret: str`, `Settings.google_bat() -> bool`, `Settings.google_redirect_uri() -> str`, và một phép kiểm mới trong `kiem_tra_dang_ky_mau_thuan_san_xuat()`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/test_config_google.py`:

```python
"""Cấu hình cửa Google — bật/tắt và một cấu hình production mâu thuẫn."""

import pytest

from portal.core.config import Settings


def test_rong_la_tat():
    c = Settings(google_client_id="", google_client_secret="")
    assert c.google_bat() is False


def test_du_hai_bien_la_bat():
    c = Settings(google_client_id="abc.apps.googleusercontent.com", google_client_secret="s3cret")
    assert c.google_bat() is True


def test_thieu_mot_trong_hai_van_la_tat():
    """Nửa cấu hình còn tệ hơn không cấu hình: nút hiện ra rồi đổi code thất bại
    ở bước 7, và người dùng chỉ thấy một lần redirect về /login không lý do."""
    assert Settings(google_client_id="abc", google_client_secret="").google_bat() is False
    assert Settings(google_client_id="", google_client_secret="s").google_bat() is False


def test_redirect_uri_suy_tu_public_base_url():
    c = Settings(
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="https://portal.noblex.vn",
    )
    assert c.google_redirect_uri() == "https://portal.noblex.vn/api/v1/auth/google/callback"


def test_redirect_uri_cat_dau_gach_cheo_thua():
    """Google khớp redirect_uri theo từng ký tự. `https://x/` + `/api/...` sinh
    ra một dấu gạch đôi và Google từ chối, với một thông báo không nói ra vì sao."""
    c = Settings(
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="https://portal.noblex.vn/",
    )
    assert c.google_redirect_uri() == "https://portal.noblex.vn/api/v1/auth/google/callback"


def test_production_bat_google_ma_thieu_public_base_url_thi_no():
    c = Settings(
        environment="production",
        google_client_id="abc",
        google_client_secret="s",
        public_base_url="",
        signup_enabled=False,
    )
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        c.kiem_tra_dang_ky_mau_thuan_san_xuat()


def test_production_tat_google_thi_khong_no():
    c = Settings(environment="production", google_client_id="", public_base_url="", signup_enabled=False)
    c.kiem_tra_dang_ky_mau_thuan_san_xuat()
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/unit/test_config_google.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'google_bat'`.

- [ ] **Step 3: Thêm cấu hình**

Trong `src/portal/core/config.py`, chèn ngay SAU khối `signup_enabled` và TRƯỚC `def kiem_tra_dang_ky_mau_thuan_san_xuat`:

```python
    # ─── Cửa Google (spec 2026-08-18) ────────────────────────────────────────

    google_client_id: str = ""
    """RỖNG ⇒ tắt hẳn cửa Google. Cùng lối `smtp_host`: một chuỗi rỗng là công
    tắc, không phải một cấu hình sai.

    Lấy ở Google Cloud Console → Credentials → OAuth client ID → Web application.
    Không tốn phí: đăng nhập bằng Google không phải API tính theo lượt gọi."""

    google_client_secret: str = ""
    """CHỈ sống ở backend. Nó đi cùng `code` trong lượt POST /token máy-chủ-tới-
    máy-chủ và không bao giờ đi qua trình duyệt — đó là toàn bộ lý do chọn
    Authorization Code thay vì để FE nhận id_token (spec §5)."""

    def google_bat(self) -> bool:
        """ĐÒI ĐỦ CẢ HAI BIẾN. Nửa cấu hình còn tệ hơn không cấu hình: nút hiện
        ra, người dùng bấm, rồi đổi code thất bại ở bước 7 và họ chỉ thấy một
        lần redirect về /login không lý do."""
        return bool(self.google_client_id and self.google_client_secret)

    def google_redirect_uri(self) -> str:
        """Suy từ `public_base_url`, KHÔNG một biến thứ ba — cùng lý lẽ file này
        đã ghi cho mailer: hai biến cùng phải đặt đúng thì có ngày một cái đúng
        một cái quên.

        `rstrip('/')` vì Google khớp redirect_uri theo TỪNG KÝ TỰ. Một dấu gạch
        chéo thừa ở `public_base_url` sinh ra `//api/v1/...` và Google từ chối
        với một thông báo không nói ra nguyên nhân.
        """
        return f"{self.public_base_url.rstrip('/')}/api/v1/auth/google/callback"
```

Rồi trong `kiem_tra_dang_ky_mau_thuan_san_xuat`, thay dòng `if not (self.environment == "production" and self.signup_enabled): return` bằng khối sau, và chèn phép kiểm Google TRƯỚC nó:

```python
        # Cửa Google cần `public_base_url` để dựng redirect_uri. Thiếu nó thì
        # redirect_uri thành "/api/v1/auth/google/callback" — Google từ chối, và
        # nó từ chối ở production, lúc chạy, với thông báo không nói ra vì sao.
        # Chặn ở đây thay vì để người dùng đầu tiên gặp phải.
        if self.environment == "production" and self.google_bat() and not self.public_base_url:
            raise RuntimeError(
                "GOOGLE_CLIENT_ID đã đặt ở production nhưng thiếu PUBLIC_BASE_URL — "
                "không dựng được redirect_uri. Đặt PUBLIC_BASE_URL, hoặc bỏ trống GOOGLE_CLIENT_ID."
            )

        if not (self.environment == "production" and self.signup_enabled):
            return
```

- [ ] **Step 4: Chạy test để xác nhận nó xanh**

Run: `uv run pytest tests/unit/test_config_google.py tests/unit/test_config.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Thêm biến vào `.env.example` nếu file tồn tại**

Run: `ls deploy/*.env.example 2>/dev/null`
Nếu có, thêm vào cuối:

```
# Cửa Google — RỖNG ⇒ tắt. Lấy ở Google Cloud Console → Credentials →
# OAuth client ID → Web application. Authorized redirect URI phải khớp CHÍNH XÁC
# <PUBLIC_BASE_URL>/api/v1/auth/google/callback
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

- [ ] **Step 6: Commit**

```bash
git add src/portal/core/config.py tests/unit/test_config_google.py
git commit -m "feat(config): GOOGLE_CLIENT_ID/SECRET và redirect_uri suy từ public_base_url"
```

---

### Task 3: Tầng repo — đọc/ghi `identities`

**Files:**
- Modify: `src/portal/modules/auth/repo.py` (thêm vào cuối file)
- Create: `tests/modules/auth/test_repo_identity.py`

**Interfaces:**
- Consumes: `repo.HangUser` (`id`, `email`, `password_hash`, `name`, `lifecycle`, `phone`, `job_title`), `repo.tim_user_theo_id`, `repo.tim_user_theo_email` — đã có.
- Produces:
  - `@dataclass(frozen=True, slots=True) class HangIdentity: provider: str; subject: str; user_id: str; email_tai_provider: str`
  - `async def tim_identity(conn, *, provider: str, subject: str) -> HangIdentity | None`
  - `async def ghi_identity(conn, *, provider: str, subject: str, user_id: str, email_tai_provider: str) -> None`
  - `async def cham_dang_nhap_identity(conn, *, provider: str, subject: str, email_tai_provider: str) -> None`
  - `async def tao_user_tu_google(conn, *, user_id: str, email: str, name: str) -> HangUser`
  - `async def kich_hoat_user_pending(conn, *, user_id: str) -> None`
  - `async def xoa_loi_moi_cua_user(conn, *, user_id: str) -> None`

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/auth/test_repo_identity.py`:

```python
"""Tầng repo của cửa Google. Không HTTP, không router — chỉ SQL."""

import pytest

from portal.modules.auth import repo


@pytest.fixture
async def don_sach(pool):
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u_ri_%'")


async def test_tim_identity_khong_co_tra_none(pool, don_sach):
    async with pool.acquire() as conn:
        assert await repo.tim_identity(conn, provider="google", subject="khong-ton-tai") is None


async def test_tao_user_tu_google_ra_active_khong_mat_khau(pool, don_sach):
    async with pool.acquire() as conn:
        u = await repo.tao_user_tu_google(conn, user_id="u_ri_a", email="a@thu.vn", name="Nguyễn A")
        assert u.id == "u_ri_a"
        assert u.lifecycle == "active", "khác `tao_user_tu_dang_ky` — Google đã xác thực hộp thư"
        assert u.password_hash is None


async def test_ghi_roi_tim_lai_duoc(pool, don_sach):
    async with pool.acquire() as conn:
        await repo.tao_user_tu_google(conn, user_id="u_ri_b", email="b@thu.vn", name="B")
        await repo.ghi_identity(
            conn, provider="google", subject="s-b", user_id="u_ri_b", email_tai_provider="b@thu.vn"
        )
        hang = await repo.tim_identity(conn, provider="google", subject="s-b")
        assert hang is not None
        assert hang.user_id == "u_ri_b"
        assert hang.email_tai_provider == "b@thu.vn"


async def test_cham_dang_nhap_cap_nhat_email_hien_thi(pool, don_sach):
    """Người đổi email tài khoản Google: `sub` không đổi nên vẫn là nhánh 1, và
    cột email hiển thị phải theo kịp — nếu không, audit đọc ra một email đã chết."""
    async with pool.acquire() as conn:
        await repo.tao_user_tu_google(conn, user_id="u_ri_c", email="c@thu.vn", name="C")
        await repo.ghi_identity(
            conn, provider="google", subject="s-c", user_id="u_ri_c", email_tai_provider="cu@thu.vn"
        )
        await repo.cham_dang_nhap_identity(
            conn, provider="google", subject="s-c", email_tai_provider="moi@thu.vn"
        )
        hang = await repo.tim_identity(conn, provider="google", subject="s-c")
        assert hang.email_tai_provider == "moi@thu.vn"
        assert await conn.fetchval(
            "SELECT last_login_at IS NOT NULL FROM control.identities WHERE subject = 's-c'"
        )


async def test_kich_hoat_pending_va_xoa_loi_moi(pool, don_sach):
    """Nhánh a của spec §7: người được mời vào bằng Google. Thư mời đang sống
    phải chết — một link đặt mật khẩu còn hiệu lực sau khi người ta đã vào được
    là một cửa thừa không ai theo dõi."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_ri_d', 'd@thu.vn', NULL, 'D', 'pending')"
        )
        await conn.execute(
            "INSERT INTO control.invites (token_hash, user_id, tenant_id, expires_at, created_by) "
            "VALUES ($1, 'u_ri_d', NULL, now() + interval '7 days', 'u_ri_d')",
            "d" * 64,
        )
        await repo.kich_hoat_user_pending(conn, user_id="u_ri_d")
        await repo.xoa_loi_moi_cua_user(conn, user_id="u_ri_d")

        assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_ri_d'") == "active"
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_ri_d'") == 0
```

> **Lưu ý cho người thi công:** cột của `control.invites` do 0103 + 0107 quyết định. Chạy `\d control.invites` (hoặc đọc `migrations/versions/0107_invites_tenant_id.py`) để xác nhận tên cột trước khi chạy test; nếu `tenant_id` đã đổi tên hoặc bỏ NOT NULL thì sửa câu INSERT trên cho khớp — phần còn lại của test không đổi.

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/modules/auth/test_repo_identity.py -v`
Expected: FAIL — `AttributeError: module 'portal.modules.auth.repo' has no attribute 'tim_identity'`.

- [ ] **Step 3: Thêm hàm vào repo**

Thêm vào CUỐI `src/portal/modules/auth/repo.py`:

```python
# ─── Danh tính ngoài (migration 0108) ────────────────────────────────────────
#
# Giao dịch do NGƯỜI GỌI mở, như mọi thứ khác trong file này. Nhánh 3 ghi hai
# bảng (users + identities) và cả hai phải cùng sống hoặc cùng chết — router bọc.


@dataclass(frozen=True, slots=True)
class HangIdentity:
    provider: str
    subject: str
    user_id: str
    email_tai_provider: str


async def tim_identity(conn: asyncpg.Connection, *, provider: str, subject: str) -> HangIdentity | None:
    """Đường tra CHÍNH của cửa Google — chạy TRƯỚC mọi phép tra theo email.

    Đổi thứ tự là để người dùng đổi email tài khoản Google mất sạch workspace:
    `sub` bất biến còn email thì không. Xem spec §7.
    """
    r = await conn.fetchrow(
        "SELECT provider, subject, user_id, email_tai_provider "
        "FROM control.identities WHERE provider = $1 AND subject = $2",
        provider,
        subject,
    )
    return HangIdentity(**dict(r)) if r else None


async def ghi_identity(
    conn: asyncpg.Connection, *, provider: str, subject: str, user_id: str, email_tai_provider: str
) -> None:
    """KHÔNG `ON CONFLICT DO NOTHING`: người gọi đã tra `tim_identity` và biết
    hàng chưa có. Nuốt xung đột ở đây là nuốt luôn ca «hai user cùng chiếm một
    tài khoản Google» mà PRIMARY KEY sinh ra để chặn."""
    await conn.execute(
        "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider, last_login_at) "
        "VALUES ($1, $2, $3, $4, now())",
        provider,
        subject,
        user_id,
        email_tai_provider,
    )


async def cham_dang_nhap_identity(
    conn: asyncpg.Connection, *, provider: str, subject: str, email_tai_provider: str
) -> None:
    """Cập nhật CẢ email hiển thị, không chỉ mốc thời gian: người đổi email tài
    khoản Google vẫn là nhánh 1, và nếu cột này đứng yên thì audit đọc ra một
    email đã chết."""
    await conn.execute(
        "UPDATE control.identities SET last_login_at = now(), email_tai_provider = $3 "
        "WHERE provider = $1 AND subject = $2",
        provider,
        subject,
        email_tai_provider,
    )


async def tao_user_tu_google(
    conn: asyncpg.Connection, *, user_id: str, email: str, name: str
) -> HangUser:
    """`active` NGAY, khác `tao_user_tu_dang_ky` (ra `pending` rồi chờ bấm link).

    Cái link đặt mật khẩu tồn tại để chứng minh hộp thư có thật. Google vừa
    chứng minh xong điều đó (`email_verified`), nên bắt đi lại một vòng nữa là
    thu phí một lời hứa đã được trả.
    """
    r = await conn.fetchrow(
        f"INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
        f"VALUES ($1, $2, NULL, $3, 'active') RETURNING {_COT_USER}",
        user_id,
        email,
        name,
    )
    return HangUser(**dict(r))


async def kich_hoat_user_pending(conn: asyncpg.Connection, *, user_id: str) -> None:
    """Nhánh a — người được mời vào thẳng bằng Google. `WHERE lifecycle =
    'pending'` để câu này không bao giờ hạ cấp một `suspended` thành `active`
    nếu ai đó gọi nhầm chỗ."""
    await conn.execute(
        "UPDATE control.users SET lifecycle = 'active' WHERE id = $1 AND lifecycle = 'pending'",
        user_id,
    )


async def xoa_loi_moi_cua_user(conn: asyncpg.Connection, *, user_id: str) -> None:
    """Đi CÙNG `kich_hoat_user_pending`, không tách rời. Người đã vào được rồi
    mà link đặt mật khẩu còn sống là một cửa thứ hai không ai theo dõi."""
    await conn.execute("DELETE FROM control.invites WHERE user_id = $1", user_id)
```

- [ ] **Step 4: Chạy test để xác nhận nó xanh**

Run: `uv run pytest tests/modules/auth/test_repo_identity.py -v`
Expected: PASS — 5 test.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/auth/repo.py tests/modules/auth/test_repo_identity.py
git commit -m "feat(auth): tầng repo đọc/ghi control.identities"
```

---

### Task 4: `core/auth/oauth_google.py` — chỉ nói chuyện với Google

**Files:**
- Create: `src/portal/core/auth/oauth_google.py`
- Create: `tests/unit/test_oauth_google.py`

**Interfaces:**
- Consumes: `httpx` (dep chính).
- Produces:
  - `class LoiGoogle(Exception)` với thuộc tính `ma: str` — mã đi vào `?loi=` của FE.
  - `@dataclass(frozen=True, slots=True) class ClaimsGoogle: sub: str; email: str; email_verified: bool; name: str`
  - `def sinh_verifier() -> str`
  - `def thach_thuc(verifier: str) -> str`
  - `def duong_uy_quyen(*, client_id: str, redirect_uri: str, state: str, challenge: str) -> str`
  - `async def doi_code_lay_claims(*, code, verifier, client_id, client_secret, redirect_uri, transport=None) -> ClaimsGoogle`
  - Hằng: `DIA_CHI_AUTH`, `DIA_CHI_TOKEN`

Module này KHÔNG import `portal.modules.*`, KHÔNG biết `control.users`, KHÔNG biết Redis. `tests/test_module_boundaries.py` canh chiều import.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/test_oauth_google.py`:

```python
"""Cửa Google, phần nói chuyện với Google. Không DB, không Redis, không app.

`httpx.MockTransport` thay Google — nên bộ test này chạy được ở `tests/unit`,
tức không cần Docker.
"""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from portal.core.auth import oauth_google as og

CLIENT_ID = "abc.apps.googleusercontent.com"


def _id_token(**ghi_de) -> str:
    """Dựng một id_token GIẢ: header/payload base64url, chữ ký là rác.

    Chữ ký là rác CÓ CHỦ Ý — code không verify chữ ký, và test này neo đúng điều
    đó. Xem docstring `_doc_claims` cho lý lẽ (OIDC Core §3.1.3.7).
    """
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": int(time.time()) + 600,
        "sub": "104287",
        "email": "Ai.Do@NobleX.VN",
        "email_verified": True,
        "name": "Ai Đó",
    }
    payload.update(ghi_de)

    def b64(d: dict) -> str:
        raw = json.dumps(d).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64({'alg': 'RS256'})}.{b64(payload)}.chu-ky-la-rac"


def _google(id_token: str, *, status: int = 200) -> httpx.MockTransport:
    def xu_ly(req: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": id_token, "access_token": "at"})

    return httpx.MockTransport(xu_ly)


async def _doi(id_token: str, **kw) -> og.ClaimsGoogle:
    return await og.doi_code_lay_claims(
        code="c",
        verifier="v",
        client_id=CLIENT_ID,
        client_secret="s",
        redirect_uri="https://x/api/v1/auth/google/callback",
        transport=_google(id_token, **kw),
    )


def test_thach_thuc_la_s256_cua_verifier():
    v = "abc123"
    mong = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert og.thach_thuc(v) == mong


def test_duong_uy_quyen_mang_du_tham_so_bat_buoc():
    u = og.duong_uy_quyen(
        client_id=CLIENT_ID, redirect_uri="https://x/cb", state="st", challenge="ch"
    )
    q = parse_qs(urlparse(u).query)
    assert u.startswith(og.DIA_CHI_AUTH)
    assert q["client_id"] == [CLIENT_ID]
    assert q["response_type"] == ["code"]
    assert q["scope"] == ["openid email profile"]
    assert q["state"] == ["st"]
    assert q["code_challenge"] == ["ch"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["prompt"] == ["select_account"]


async def test_doc_duoc_claims_va_chuan_hoa_email():
    c = await _doi(_id_token())
    assert c.sub == "104287"
    assert c.email == "ai.do@noblex.vn", "lower() ở biên nhập — users.email có CHECK lower"
    assert c.email_verified is True
    assert c.name == "Ai Đó"


async def test_aud_sai_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(aud="cua-ai-khac"))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_iss_sai_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(iss="https://ke-gia-mao.vn"))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_het_han_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(exp=int(time.time()) - 10))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_thieu_sub_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(sub=""))
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_google_tra_loi_thi_tu_choi():
    with pytest.raises(og.LoiGoogle) as e:
        await _doi(_id_token(), status=400)
    assert e.value.ma == "GOOGLE_TU_CHOI"


async def test_email_chua_xac_thuc_van_doc_duoc_claims():
    """Module này KHÔNG quyết định chính sách — nó chỉ đọc. Việc từ chối
    `email_verified=false` là của `dang_nhap_google.py`, nơi biết nhánh nào đang
    chạy. Trộn hai việc là để một module không có DB đi quyết định chuyện của DB."""
    c = await _doi(_id_token(email_verified=False))
    assert c.email_verified is False
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/unit/test_oauth_google.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.core.auth.oauth_google'`.

- [ ] **Step 3: Viết module**

Tạo `src/portal/core/auth/oauth_google.py`:

```python
"""Nói chuyện với Google, và CHỈ nói chuyện với Google.

Module này không biết `control.users`, không biết Redis, không biết nhánh nào
đang chạy. Nó nhận `code` và trả về claims. Chính sách («email chưa xác thực thì
sao», «user đình chỉ thì sao») nằm ở `modules/auth/dang_nhap_google.py`.

Chia vậy để test được cả hai bên mà không phải kéo nhau: bộ test của file này
chạy ở `tests/unit` với `httpx.MockTransport` và không cần Docker.

═══════════════════════════════════════════════════════════════════════════════
 VÌ SAO KHÔNG VERIFY CHỮ KÝ CỦA id_token
═══════════════════════════════════════════════════════════════════════════════
`id_token` ở đây đến TRỰC TIẾP từ Google qua TLS trong lượt POST /token dưới
đây — nó không đi qua trình duyệt, không qua tay ai. OIDC Core §3.1.3.7 miễn
verify chữ ký đúng trường hợp này: kênh đã được xác thực rồi.

ĐÂY LÀ MỘT QUYẾT ĐỊNH, KHÔNG PHẢI MỘT THIẾU SÓT. Tự viết verify RS256 là mở lại
hố `alg confusion` — đúng cái hố mà `core/auth/session.py` đã cố ý tránh khi từ
chối JWT cho phiên. Nếu ngày nào đó `id_token` được nhận từ FE (Google Identity
Services / One-Tap) thì lời miễn trừ này TAN BIẾN và verify chữ ký thành bắt
buộc — nhưng lúc đó cả kiến trúc đã khác, xem spec §5.

`aud` · `iss` · `exp` vẫn kiểm đủ: chúng chặn một token thật của Google nhưng
phát cho một ứng dụng khác, tức thứ mà TLS không nói gì về.
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlencode

import httpx

DIA_CHI_AUTH: Final = "https://accounts.google.com/o/oauth2/v2/auth"
DIA_CHI_TOKEN: Final = "https://oauth2.googleapis.com/token"
_ISS_HOP_LE: Final = frozenset({"accounts.google.com", "https://accounts.google.com"})
_HAN_GOI_GIAY: Final = 10.0


class LoiGoogle(Exception):
    """`ma` đi thẳng vào `?loi=` của FE — xem `modules/auth/router.py`.

    KHÔNG dùng `LoiPortal`: callback là điều hướng trình duyệt và trả 302, không
    trả JSON, nên envelope `{error:{code,message}}` không có chỗ để đi.
    """

    def __init__(self, ma: str) -> None:
        super().__init__(ma)
        self.ma = ma


@dataclass(frozen=True, slots=True)
class ClaimsGoogle:
    sub: str
    """Định danh BẤT BIẾN của tài khoản Google. Đây là khoá, không phải email."""
    email: str
    email_verified: bool
    name: str


def sinh_verifier() -> str:
    """43-128 ký tự theo RFC 7636. `token_urlsafe(48)` cho 64 ký tự."""
    return secrets.token_urlsafe(48)


def thach_thuc(verifier: str) -> str:
    """S256, KHÔNG `plain`. `plain` gửi thẳng verifier trong URL của trình duyệt
    và biến PKCE thành một thủ tục rỗng."""
    bam = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(bam).decode().rstrip("=")


def duong_uy_quyen(*, client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """`prompt=select_account`: buộc màn chọn tài khoản hiện MỖI lượt.

    Cố ý chịu thêm một cú bấm. Máy dùng chung mà tự đăng nhập bằng tài khoản
    Google đang mở sẵn là một bất ngờ tệ hơn nhiều so với một màn chọn.
    """
    tham_so = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{DIA_CHI_AUTH}?{urlencode(tham_so)}"


def _giai_ma_phan_than(id_token: str) -> dict[str, Any]:
    try:
        than = id_token.split(".")[1]
        # base64url không đệm '='; thêm đủ đệm trước khi giải mã.
        than += "=" * (-len(than) % 4)
        return json.loads(base64.urlsafe_b64decode(than))
    except Exception as e:  # noqa: BLE001 — mọi kiểu hỏng đều là một câu trả lời
        raise LoiGoogle("GOOGLE_TU_CHOI") from e


def _doc_claims(id_token: str, *, client_id: str) -> ClaimsGoogle:
    than = _giai_ma_phan_than(id_token)

    if than.get("iss") not in _ISS_HOP_LE:
        raise LoiGoogle("GOOGLE_TU_CHOI")
    if than.get("aud") != client_id:
        raise LoiGoogle("GOOGLE_TU_CHOI")
    if not isinstance(than.get("exp"), int) or than["exp"] <= time.time():
        raise LoiGoogle("GOOGLE_TU_CHOI")

    sub = than.get("sub") or ""
    email = than.get("email") or ""
    if not sub or not email:
        raise LoiGoogle("GOOGLE_TU_CHOI")

    return ClaimsGoogle(
        sub=sub,
        # lower() Ở ĐÂY, tại biên nhập: `users.email` có CHECK `email = lower(email)`
        # và mọi đường ghi phải chuẩn hoá trước — 0100 đã ghi lý lẽ đó.
        email=email.strip().lower(),
        email_verified=bool(than.get("email_verified")),
        name=(than.get("name") or email).strip(),
    )


async def doi_code_lay_claims(
    *,
    code: str,
    verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ClaimsGoogle:
    """Lượt máy-chủ-tới-máy-chủ DUY NHẤT của cả luồng.

    `transport` chỉ để test tiêm `MockTransport` — production truyền None. Tiêm
    qua tham số chứ không monkeypatch module: monkeypatch rò sang test khác chạy
    song song, và cái rò đó biểu hiện thành một test đỏ ở file không liên quan.
    """
    async with httpx.AsyncClient(transport=transport, timeout=_HAN_GOI_GIAY) as client:
        try:
            res = await client.post(
                DIA_CHI_TOKEN,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
        except httpx.HTTPError as e:
            raise LoiGoogle("GOOGLE_TU_CHOI") from e

    if res.status_code != 200:
        raise LoiGoogle("GOOGLE_TU_CHOI")

    id_token = res.json().get("id_token")
    if not id_token:
        raise LoiGoogle("GOOGLE_TU_CHOI")

    return _doc_claims(id_token, client_id=client_id)
```

- [ ] **Step 4: Chạy test để xác nhận nó xanh**

Run: `uv run pytest tests/unit/test_oauth_google.py -v`
Expected: PASS — 10 test.

- [ ] **Step 5: Kiểm ranh giới module còn nguyên**

Run: `uv run pytest tests/test_module_boundaries.py -v`
Expected: PASS — `core/` không được import `modules/`.

- [ ] **Step 6: Commit**

```bash
git add src/portal/core/auth/oauth_google.py tests/unit/test_oauth_google.py
git commit -m "feat(auth): core/auth/oauth_google — PKCE, đổi code, đọc claims"
```

---

### Task 5: `modules/auth/dang_nhap_google.py` — ba nhánh và ba ca biên

**Files:**
- Create: `src/portal/modules/auth/dang_nhap_google.py`
- Create: `tests/modules/auth/test_dang_nhap_google.py`

**Interfaces:**
- Consumes: `oauth_google.ClaimsGoogle`, `oauth_google.LoiGoogle`, `repo.tim_identity`, `repo.ghi_identity`, `repo.cham_dang_nhap_identity`, `repo.tao_user_tu_google`, `repo.kich_hoat_user_pending`, `repo.xoa_loi_moi_cua_user`, `repo.tim_user_theo_id`, `repo.tim_user_theo_email`, `repo.liet_ke_workspace`, `quan_tri_user.sinh_user_id`, `session.tao`, `nhat_ky.ghi_he_thong`.
- Produces: `async def dang_nhap(conn, r, *, claims: ClaimsGoogle, cho_dang_ky_moi: bool) -> tuple[str, str | None]` — trả `(session_id, tenant_id)`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/auth/test_dang_nhap_google.py`:

```python
"""Ba nhánh khớp danh tính + ba ca biên (spec §7).

Gọi THẲNG service với claims dựng tay — không dựng OAuth giả, không đi qua HTTP.
Đó là lý do `oauth_google.py` và file này là hai module: hai bộ test không phải
kéo nhau.
"""

import pytest

from portal.core.auth import oauth_google as og
from portal.core.auth import session as ss
from portal.modules.auth import dang_nhap_google as dng
from portal.modules.auth import repo


def _claims(**ghi_de) -> og.ClaimsGoogle:
    m = {"sub": "104287", "email": "ai.do@noblex.vn", "email_verified": True, "name": "Ai Đó"}
    m.update(ghi_de)
    return og.ClaimsGoogle(**m)


@pytest.fixture
async def don_sach(pool):
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u_gg_%' OR email LIKE '%@gg.vn'")


async def _goi(conn, redis_client, claims, *, cho_dang_ky_moi=True):
    return await dng.dang_nhap(conn, redis_client, claims=claims, cho_dang_ky_moi=cho_dang_ky_moi)


async def test_nhanh_3_tao_user_moi_va_identity(pool, redis_client, don_sach):
    """Người hoàn toàn mới: 2 hàng, cùng giao dịch, 0 workspace."""
    async with pool.acquire() as conn, conn.transaction():
        sid, tenant_id = await _goi(conn, redis_client, _claims(email="moi@gg.vn"))
        assert tenant_id is None, "chưa thuộc workspace nào — FE đẩy tới màn tạo workspace"

        u = await repo.tim_user_theo_email(conn, "moi@gg.vn")
        assert u is not None
        assert u.lifecycle == "active"
        assert u.password_hash is None
        assert (await repo.tim_identity(conn, provider="google", subject="104287")).user_id == u.id

    ban_ghi = await ss.doc(redis_client, sid)
    assert ban_ghi is not None and ban_ghi.tenant_id is None


async def test_nhanh_1_lan_hai_khong_tao_them_gi(pool, redis_client, don_sach):
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="lai@gg.vn"))
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="lai@gg.vn"))
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email = 'lai@gg.vn'") == 1
        assert await conn.fetchval("SELECT count(*) FROM control.identities WHERE subject = '104287'") == 1


async def test_nhanh_1_doi_email_google_van_vao_dung_tai_khoan(pool, redis_client, don_sach):
    """Cái bẫy chính của cả tính năng. `sub` không đổi ⇒ vẫn là người cũ, dù
    email đã khác hẳn. Tra email trước thì đây thành nhánh 3 và họ mất sạch."""
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="cu@gg.vn"))
    async with pool.acquire() as conn:
        u_cu = await repo.tim_user_theo_email(conn, "cu@gg.vn")

    async with pool.acquire() as conn, conn.transaction():
        sid, _ = await _goi(conn, redis_client, _claims(email="hoan.toan.moi@gg.vn"))

    ban_ghi = await ss.doc(redis_client, sid)
    assert ban_ghi.user_id == u_cu.id, "phải là user CŨ, không phải một user thứ hai"
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email LIKE '%@gg.vn'") == 1


async def test_nhanh_2_email_trung_thi_lien_ket_khong_tao_user(pool, redis_client, don_sach):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_co_mk', 'co.mk@gg.vn', 'argon2-gia', 'Có Mật Khẩu', 'active')"
        )
    async with pool.acquire() as conn, conn.transaction():
        sid, _ = await _goi(conn, redis_client, _claims(email="co.mk@gg.vn"))

    assert (await ss.doc(redis_client, sid)).user_id == "u_gg_co_mk"
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email = 'co.mk@gg.vn'") == 1
        assert await conn.fetchval(
            "SELECT password_hash FROM control.users WHERE id = 'u_gg_co_mk'"
        ) == "argon2-gia", "liên kết KHÔNG được đụng vào mật khẩu sẵn có"


async def test_bien_a_pending_thanh_active_va_thu_moi_chet(pool, redis_client, don_sach):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_pending', 'pd@gg.vn', NULL, 'Chờ', 'pending')"
        )
        await conn.execute(
            "INSERT INTO control.invites (token_hash, user_id, tenant_id, expires_at, created_by) "
            "VALUES ($1, 'u_gg_pending', NULL, now() + interval '7 days', 'u_gg_pending')",
            "e" * 64,
        )
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="pd@gg.vn"))
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT lifecycle FROM control.users WHERE id = 'u_gg_pending'") == "active"
        assert await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_gg_pending'") == 0


async def test_bien_b_CUA_HAU_user_dinh_chi_khong_vao_duoc(pool, redis_client, don_sach):
    """TEST QUAN TRỌNG NHẤT CỦA CẢ TÍNH NĂNG.

    Đình chỉ có nghĩa "thu hồi quyền vào". Cửa mật khẩu đã chặn; cửa này mà không
    chặn thì lệnh đình chỉ chỉ còn là một dòng chữ trong DB.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_dc', 'dc@gg.vn', 'argon2-gia', 'Đình Chỉ', 'suspended')"
        )
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="dc@gg.vn"))
    assert e.value.ma == "TAI_KHOAN_DINH_CHI"
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.identities WHERE subject = '104287'") == 0


async def test_bien_b_identity_da_lien_ket_roi_bi_dinh_chi_sau_do(pool, redis_client, don_sach):
    """Đình chỉ SAU khi đã liên kết — nhánh 1 cũng phải kiểm lifecycle, không chỉ nhánh 2."""
    async with pool.acquire() as conn, conn.transaction():
        await _goi(conn, redis_client, _claims(email="sau@gg.vn"))
    async with pool.acquire() as conn:
        await conn.execute("UPDATE control.users SET lifecycle = 'suspended' WHERE email = 'sau@gg.vn'")
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="sau@gg.vn"))
    assert e.value.ma == "TAI_KHOAN_DINH_CHI"


async def test_bien_c_email_chua_xac_thuc_thi_tu_choi(pool, redis_client, don_sach):
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="chua@gg.vn", email_verified=False))
    assert e.value.ma == "EMAIL_CHUA_XAC_THUC"


async def test_tat_dang_ky_thi_nguoi_moi_bi_tu_choi_nhung_nguoi_cu_van_vao(pool, redis_client, don_sach):
    async with pool.acquire() as conn, conn.transaction():
        with pytest.raises(og.LoiGoogle) as e:
            await _goi(conn, redis_client, _claims(email="khach@gg.vn"), cho_dang_ky_moi=False)
    assert e.value.ma == "DANG_KY_DANG_TAT"

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_gg_cu', 'cu2@gg.vn', 'argon2-gia', 'Cũ', 'active')"
        )
    async with pool.acquire() as conn, conn.transaction():
        sid, _ = await _goi(conn, redis_client, _claims(email="cu2@gg.vn"), cho_dang_ky_moi=False)
    assert (await ss.doc(redis_client, sid)).user_id == "u_gg_cu"
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/modules/auth/test_dang_nhap_google.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.auth.dang_nhap_google'`.

- [ ] **Step 3: Viết module**

Tạo `src/portal/modules/auth/dang_nhap_google.py`:

```python
"""Ba nhánh khớp danh tính của cửa Google (spec §7).

Module này KHÔNG biết HTTP. Nó nhận claims đã đọc xong và quyết định: người này
là ai, có được vào không, và phiên nào được tạo.

═══════════════════════════════════════════════════════════════════════════════
 THỨ TỰ TRA CỨU LÀ BẮT BUỘC: (provider, sub) TRƯỚC, EMAIL SAU
═══════════════════════════════════════════════════════════════════════════════
`sub` là định danh bất biến của tài khoản Google; email thì Google cho đổi.

Đảo thứ tự thì người đổi email tài khoản Google rơi xuống nhánh 3 và bị tạo một
user THỨ HAI — workspace, vai trò, lịch sử của họ nằm ở user thứ nhất và không
ai hiểu vì sao. Test `test_nhanh_1_doi_email_google_van_vao_dung_tai_khoan` canh
đúng điều này.

Đây cũng là lý do thiết kế cần bảng `control.identities` chứ không phải một cột
`gmail` trong `users` — xem spec §2.
"""

import asyncpg
from redis.asyncio import Redis

from portal.core import nhat_ky
from portal.core.auth import session as ss
from portal.core.auth.oauth_google import ClaimsGoogle, LoiGoogle
from portal.modules.auth import quan_tri_user, repo

_PROVIDER = "google"


async def dang_nhap(
    conn: asyncpg.Connection, r: Redis, *, claims: ClaimsGoogle, cho_dang_ky_moi: bool
) -> tuple[str, str | None]:
    """Trả `(session_id, tenant_id)`. Người gọi mở giao dịch VÀ đặt cookie.

    `cho_dang_ky_moi` là `signup_enabled` truyền xuống — chặn nhánh 3 mà KHÔNG
    chặn nhánh 1/2: tắt đăng ký nghĩa là "thôi nhận người mới", không phải "khoá
    cửa những người đang dùng".
    """
    # ── ca c: email chưa xác thực ────────────────────────────────────────────
    # Chặn TRƯỚC mọi thứ. Toàn bộ quyết định «tự liên kết» (spec Q1) đứng trên
    # đúng claim này — không có nó thì nhánh 2 là một đường chiếm tài khoản bằng
    # cách khai một email bất kỳ.
    if not claims.email_verified:
        raise LoiGoogle("EMAIL_CHUA_XAC_THUC")

    hang = await repo.tim_identity(conn, provider=_PROVIDER, subject=claims.sub)

    if hang is not None:
        # ── NHÁNH 1 — đã liên kết. ~99% lượt đăng nhập. ──────────────────────
        u = await repo.tim_user_theo_id(conn, hang.user_id)
        if u is None:
            # ON DELETE CASCADE làm ca này bất khả thi. Nếu vẫn xảy ra thì DB đã
            # sai chứ không phải người dùng — từ chối, đừng đoán.
            raise LoiGoogle("GOOGLE_TU_CHOI")
        _kiem_vao_duoc(u)
        await repo.cham_dang_nhap_identity(
            conn, provider=_PROVIDER, subject=claims.sub, email_tai_provider=claims.email
        )
        return await _mo_phien(conn, r, u, "user.dang_nhap_google")

    u = await repo.tim_user_theo_email(conn, claims.email)

    if u is not None:
        # ── NHÁNH 2 — email trùng, tự liên kết (spec Q1) ─────────────────────
        # KHÔNG đụng vào `password_hash`: người này vẫn đăng nhập bằng mật khẩu
        # được, cửa Google chỉ là đường thứ hai.
        _kiem_vao_duoc(u)
        if u.lifecycle == "pending":
            # ── ca a — được mời, chưa đặt mật khẩu, vào thẳng bằng Google ────
            # Hai câu đi CÙNG NHAU. Kích hoạt mà không xoá thư mời là để lại một
            # link đặt mật khẩu còn sống cho một tài khoản đã vào được — một cửa
            # thứ hai không ai theo dõi.
            await repo.kich_hoat_user_pending(conn, user_id=u.id)
            await repo.xoa_loi_moi_cua_user(conn, user_id=u.id)
        await repo.ghi_identity(
            conn,
            provider=_PROVIDER,
            subject=claims.sub,
            user_id=u.id,
            email_tai_provider=claims.email,
        )
        await nhat_ky.ghi_he_thong(conn, "user.lien_ket_google", u.id, {"email": claims.email})
        u = await repo.tim_user_theo_id(conn, u.id)  # đọc lại: lifecycle có thể vừa đổi
        return await _mo_phien(conn, r, u, "user.dang_nhap_google")

    # ── NHÁNH 3 — người hoàn toàn mới ────────────────────────────────────────
    if not cho_dang_ky_moi:
        raise LoiGoogle("DANG_KY_DANG_TAT")

    user_id = await quan_tri_user.sinh_user_id(conn, claims.email)
    u = await repo.tao_user_tu_google(conn, user_id=user_id, email=claims.email, name=claims.name)
    await repo.ghi_identity(
        conn,
        provider=_PROVIDER,
        subject=claims.sub,
        user_id=u.id,
        email_tai_provider=claims.email,
    )
    await nhat_ky.ghi_he_thong(conn, "user.dang_ky_google", u.id, {"email": claims.email})
    return await _mo_phien(conn, r, u, "user.dang_nhap_google")


def _kiem_vao_duoc(u: repo.HangUser) -> None:
    """Ca b — CỬA HẬU.

    Cửa mật khẩu đã chặn `suspended` (`service.dang_nhap`). Cửa này mà không chặn
    thì: admin đình chỉ người vừa nghỉ việc, mật khẩu hết tác dụng, và họ bấm nút
    Google vẫn vào được — lệnh đình chỉ thành vô nghĩa mà không ai nhìn thấy.

    Repo đã vấp đúng loại lỗi này một lần ở `thanh_vien.py` (user `suspended` rơi
    chung nhánh "đã có tài khoản" và ĐƯỢC cấp membership).

    NÓI THẲNG, không gộp vào `sai_dang_nhap()`: lý lẽ chống dò email không áp
    được ở đây. Muốn thử email X qua cửa này thì phải đăng nhập được vào tài
    khoản Google của X — đã là chủ hộp thư rồi, không còn gì để rò. Và "Email
    hoặc mật khẩu không đúng" là câu vô nghĩa với người không gõ mật khẩu nào.
    """
    if u.lifecycle == "suspended":
        raise LoiGoogle("TAI_KHOAN_DINH_CHI")


async def _mo_phien(
    conn: asyncpg.Connection, r: Redis, u: repo.HangUser, hanh_dong: str
) -> tuple[str, str | None]:
    """DÙNG LẠI `ss.tao()` của đường mật khẩu, không viết bản thứ hai.

    Hai đường vào phải sinh ra CÙNG một loại phiên. Lệch nhau ở đây nghĩa là
    `logout`, thu hồi phiên, và TTL trượt chỉ đúng cho một nửa số người dùng.

    KHÔNG dựng `SessionOut` ở đây: callback trả 302, không trả JSON — FE gọi
    `/me` như mọi lần tải trang khác.
    """
    ws = await repo.liet_ke_workspace(conn, u.id)
    tenant_id = ws[0].id if ws else None
    session_id = await ss.tao(r, user_id=u.id, tenant_id=tenant_id)
    await nhat_ky.ghi_he_thong(conn, hanh_dong, u.id, {"email": u.email})
    return session_id, tenant_id
```

- [ ] **Step 4: Chạy test để xác nhận nó xanh**

Run: `uv run pytest tests/modules/auth/test_dang_nhap_google.py -v`
Expected: PASS — 9 test.

- [ ] **Step 5: Commit**

```bash
git add src/portal/modules/auth/dang_nhap_google.py tests/modules/auth/test_dang_nhap_google.py
git commit -m "feat(auth): ba nhánh khớp danh tính Google và ba ca biên"
```

---

### Task 6: Ba endpoint

**Files:**
- Modify: `src/portal/modules/auth/router.py` (thêm vào cuối, trước khối "hai đường CÔNG KHAI của thư mời" hoặc sau nó — chỗ nào cũng được, miễn cùng file)
- Create: `tests/modules/auth/test_cong_google.py`

**Interfaces:**
- Consumes: `oauth_google.*` (Task 4), `dang_nhap_google.dang_nhap` (Task 5), `Settings.google_bat()` / `google_redirect_uri()` (Task 2), `_dat_cookie` / `_secure()` / `lay_pool` / `lay_redis` / `require` — đã có trong router.
- Produces: `GET /auth/providers` · `GET /auth/google/start` · `GET /auth/google/callback`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/modules/auth/test_cong_google.py`:

```python
"""Ba đường HTTP của cửa Google.

Google được thay bằng `MockTransport` tiêm qua `monkeypatch` vào hàm module —
đây là chỗ DUY NHẤT trong bộ test dùng monkeypatch cho việc này, vì router
không có tham số `transport` để tiêm qua (và không nên có: một tham số chỉ
dành cho test nằm trên đường production là một cửa).
"""

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from portal.core.auth import oauth_google as og

CLIENT_ID = "abc.apps.googleusercontent.com"


@pytest.fixture(autouse=True)
def bat_google(monkeypatch):
    """`get_settings()` dựng một `Settings()` MỚI mỗi lần gọi (KHÔNG lru_cache),
    nên `monkeypatch.setenv` là đủ — không có `cache_clear()` nào để gọi. Cũng
    chính là lý do router đọc cấu hình mỗi lần thay vì giữ một biến module."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.thu.vn")


@pytest.fixture
async def don_sach(pool):
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.users WHERE email LIKE '%@cong.vn'")


def _claims_gia(monkeypatch, **ghi_de):
    """Thay `doi_code_lay_claims` — bước ⑦⑧ là lượt duy nhất đi ra ngoài."""
    m = {"sub": "104287", "email": "ai.do@cong.vn", "email_verified": True, "name": "Ai Đó"}
    m.update(ghi_de)

    async def gia(**_kw):
        return og.ClaimsGoogle(**m)

    monkeypatch.setattr("portal.modules.auth.router.oauth_google.doi_code_lay_claims", gia)


async def test_providers_bao_google_dang_bat(app_client: httpx.AsyncClient):
    r = await app_client.get("/api/v1/auth/providers")
    assert r.status_code == 200
    assert r.json() == {"google": True}


async def test_providers_bao_tat_khi_thieu_cau_hinh(app_client: httpx.AsyncClient, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    r = await app_client.get("/api/v1/auth/providers")
    assert r.json() == {"google": False}


async def test_providers_khong_lo_client_id(app_client: httpx.AsyncClient):
    """Đường công khai CHỈ trả tên nhà cung cấp. Mỗi trường thêm vào là một thứ
    nói cho người chưa đăng nhập biết về hệ thống."""
    r = await app_client.get("/api/v1/auth/providers")
    assert set(r.json()) == {"google"}
    assert CLIENT_ID not in r.text


async def test_start_307_sang_google_va_cat_state(app_client: httpx.AsyncClient, redis_client):
    r = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 307
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == [CLIENT_ID]
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["https://portal.thu.vn/api/v1/auth/google/callback"]
    assert await redis_client.get(f"oauth:state:{q['state'][0]}") is not None


async def test_start_404_khi_tinh_nang_tat(app_client: httpx.AsyncClient, monkeypatch):
    """PHÉP CHẶN nằm ở đây, không ở /auth/providers — cái kia chỉ để FE khỏi vẽ
    một nút chết."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    r = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert r.status_code == 403, "FEATURE_DISABLED — xem api/loi.py::tinh_nang_dang_tat"


async def test_callback_dat_cookie_va_ve_tao_workspace(
    app_client: httpx.AsyncClient, redis_client, monkeypatch, don_sach
):
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    r = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/tao-workspace", "user mới có 0 workspace"
    assert "odyssey_session=" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]

    me = await app_client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ai.do@cong.vn"


async def test_callback_state_dung_lai_lan_hai_thi_hong(
    app_client: httpx.AsyncClient, monkeypatch, don_sach
):
    """GETDEL — một lần dùng. Hai lệnh GET rồi DEL rời nhau là một cửa sổ replay."""
    _claims_gia(monkeypatch)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]

    await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    r2 = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False
    )
    assert r2.status_code == 302
    assert r2.headers["location"] == "/login?loi=STATE_HET_HAN"


async def test_callback_state_bia_dat_thi_hong(app_client: httpx.AsyncClient):
    r = await app_client.get(
        "/api/v1/auth/google/callback?code=c&state=toi-tu-bia-ra", follow_redirects=False
    )
    assert r.headers["location"] == "/login?loi=STATE_HET_HAN"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")


async def test_callback_google_tu_choi_thi_ve_login_co_ma(
    app_client: httpx.AsyncClient, monkeypatch
):
    async def no(**_kw):
        raise og.LoiGoogle("GOOGLE_TU_CHOI")

    monkeypatch.setattr("portal.modules.auth.router.oauth_google.doi_code_lay_claims", no)
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
    r = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False
    )
    assert r.headers["location"] == "/login?loi=GOOGLE_TU_CHOI"


async def test_CUA_HAU_user_dinh_chi_khong_vao_duoc_bang_google(
    app_client: httpx.AsyncClient, pool, monkeypatch, don_sach
):
    """CỔNG QUAN TRỌNG NHẤT. Xem `dang_nhap_google._kiem_vao_duoc`."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
            "VALUES ('u_cg_dc', 'dc@cong.vn', 'argon2-gia', 'Đình Chỉ', 'suspended')"
        )
    _claims_gia(monkeypatch, email="dc@cong.vn")
    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
    r = await app_client.get(
        f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False
    )
    assert r.headers["location"] == "/login?loi=TAI_KHOAN_DINH_CHI"
    assert "odyssey_session=" not in r.headers.get("set-cookie", "")
    assert (await app_client.get("/api/v1/me")).status_code == 401


async def test_callback_that_bai_khong_de_lai_hang_nao(
    app_client: httpx.AsyncClient, pool, monkeypatch, don_sach
):
    """Phép kiểm giao dịch: bỏ `conn.transaction()` ở router thì test này đỏ."""
    _claims_gia(monkeypatch, email="ro.ri@cong.vn")

    # Nổ ở `ghi_identity`, tức SAU khi `tao_user_tu_google` đã chèn hàng users.
    # Đó là điều kiện để test này có nghĩa: nổ TRƯỚC khi tạo gì thì bảng rỗng dù
    # có giao dịch hay không, và test xanh mà chẳng chứng minh điều gì.
    async def no_sau_khi_tao_user(*a, **kw):
        raise RuntimeError("vỡ giữa chừng")

    r0 = await app_client.get("/api/v1/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r0.headers["location"]).query)["state"][0]
    monkeypatch.setattr("portal.modules.auth.dang_nhap_google.repo.ghi_identity", no_sau_khi_tao_user)
    with pytest.raises(RuntimeError):
        await app_client.get(f"/api/v1/auth/google/callback?code=c&state={state}", follow_redirects=False)
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.users WHERE email = 'ro.ri@cong.vn'") == 0
```

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `uv run pytest tests/modules/auth/test_cong_google.py -v`
Expected: FAIL — 404 trên `/api/v1/auth/providers` (route chưa tồn tại).

- [ ] **Step 3: Thêm ba endpoint**

Thêm vào phần import ở đầu `src/portal/modules/auth/router.py`:

```python
import secrets

from fastapi.responses import RedirectResponse

from portal.core.auth import oauth_google
from portal.modules.auth import dang_nhap_google
```

Rồi thêm vào CUỐI file:

```python
# --- ba đường CÔNG KHAI của cửa Google (spec 2026-08-18) ---------------------
#
# Cả ba là GET. `/auth/google/callback` là GET vì Google điều hướng trình duyệt
# tới nó — ta không chọn được method.

_TIEN_TO_STATE = "oauth:state:"
_HAN_STATE_GIAY = 300


def _cau_hinh_google():
    """Đọc cấu hình MỖI lần, như `_secure()`. Trả `Settings` hoặc ném 403.

    `tinh_nang_dang_tat` trả 403 chứ không 404, và lý lẽ của nó (`api/loi.py`)
    áp đúng ở đây: cửa CÓ tồn tại và sẽ bật lại khi cấu hình đủ. 404 làm FE kết
    luận sai rằng đường đã bị gỡ và đi tìm đường thay thế.
    """
    from portal.core.config import get_settings

    c = get_settings()
    if not c.google_bat():
        raise loi.tinh_nang_dang_tat("đăng nhập bằng Google")
    return c


def _ve_login(ma: str) -> RedirectResponse:
    """Callback là điều hướng trình duyệt nên KHÔNG trả JSON được — envelope
    `{error:{code,message}}` không có chỗ để đi. FE đọc `?loi=` và hiện tại chỗ.

    302 chứ không 307: đây là kết thúc một luồng GET, không phải một lệnh phải
    giữ nguyên method.
    """
    return RedirectResponse(f"/login?loi={ma}", status_code=302)


@ROUTER.get("/auth/providers")
async def nha_cung_cap(
    _: None = require(None, ly_do="màn đăng nhập chưa có phiên nào để đòi"),
) -> dict[str, bool]:
    """CHỈ trả tên nhà cung cấp. Không `client_id`, không URL, không gì khác —
    mỗi trường thêm vào là một thứ nói cho người chưa đăng nhập biết về hệ thống.

    Tồn tại vì FE không có đường nào khác biết tính năng bật hay tắt: `/config/*`
    là agent config và đòi phiên, `/me` cũng vậy. KHÔNG dùng biến build-time của
    Vite thay cho đường này — cờ thật nằm ở `.env` của backend, và một bản FE
    build sẵn đem sang môi trường khác sẽ nói sai.

    ⚠ Đây KHÔNG phải phép chặn. Phép chặn nằm ở `/auth/google/start`.
    """
    from portal.core.config import get_settings

    return {"google": get_settings().google_bat()}


@ROUTER.get("/auth/google/start")
async def bat_dau_google(
    _: None = require(None, ly_do="chính đường này bắt đầu việc tạo phiên — đòi phiên là vòng tròn"),
    r: Redis = Depends(lay_redis),
) -> RedirectResponse:
    """Sinh `state` + `code_verifier`, cất Redis 5 phút, đẩy sang Google.

    Redis chứ không Postgres: dữ liệu này sống 5 phút và chết hẳn. Một bảng cho
    nó là một bảng phải có job dọn rác.
    """
    c = _cau_hinh_google()
    state = secrets.token_urlsafe(32)
    verifier = oauth_google.sinh_verifier()
    await r.set(f"{_TIEN_TO_STATE}{state}", verifier, ex=_HAN_STATE_GIAY)
    return RedirectResponse(
        oauth_google.duong_uy_quyen(
            client_id=c.google_client_id,
            redirect_uri=c.google_redirect_uri(),
            state=state,
            challenge=oauth_google.thach_thuc(verifier),
        ),
        status_code=307,
    )


@ROUTER.get("/auth/google/callback")
async def tro_ve_tu_google(
    res: Response,
    code: str = "",
    state: str = "",
    _: None = require(None, ly_do="chính đường này tạo ra phiên đầu tiên — đòi phiên là vòng tròn"),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> RedirectResponse:
    """Điểm hạ cánh của luồng. Mọi lỗi thành `302 /login?loi=<MA>`.

    `code`/`state` khai mặc định `""` chứ không bắt buộc: Google trả về đây cả
    khi người dùng bấm «Huỷ» (không có `code`), và một 422 của FastAPI ở đúng
    lúc đó là một trang lỗi JSON đập vào mặt người vừa đổi ý.
    """
    c = _cau_hinh_google()

    # GETDEL — dùng MỘT LẦN, atomic. `GET` rồi `DEL` là hai lệnh rời nhau, và
    # khoảng giữa chúng là một cửa sổ replay. Đây là toàn bộ phần chống CSRF của
    # luồng: không có state hợp lệ thì callback này không làm gì cả.
    verifier = await r.getdel(f"{_TIEN_TO_STATE}{state}") if state else None
    if verifier is None:
        return _ve_login("STATE_HET_HAN")
    if not code:
        return _ve_login("GOOGLE_TU_CHOI")

    if isinstance(verifier, bytes):
        verifier = verifier.decode()

    try:
        claims = await oauth_google.doi_code_lay_claims(
            code=code,
            verifier=verifier,
            client_id=c.google_client_id,
            client_secret=c.google_client_secret,
            redirect_uri=c.google_redirect_uri(),
        )
        async with pool.acquire() as conn, conn.transaction():
            session_id, tenant_id = await dang_nhap_google.dang_nhap(
                conn, r, claims=claims, cho_dang_ky_moi=c.signup_enabled
            )
    except oauth_google.LoiGoogle as e:
        return _ve_login(e.ma)

    # `_dat_cookie` CỦA CHÍNH FILE NÀY, không một bản thứ hai: `_secure()` lệch
    # nhau một cờ là đăng nhập chạy còn đăng xuất hỏng — xem `_xoa_cookie`.
    ve = RedirectResponse("/dashboard" if tenant_id else "/tao-workspace", status_code=302)
    _dat_cookie(ve, session_id)
    return ve
```

> **Lưu ý:** `_dat_cookie(res, ...)` hiện nhận `Response`. `RedirectResponse` là một `Response`, nên truyền thẳng object trả về vào nó là đúng. Tham số `res: Response` của handler không dùng tới ở nhánh thành công — nếu linter phàn nàn thì bỏ nó khỏi chữ ký.

- [ ] **Step 4: Chạy test để xác nhận nó xanh**

Run: `uv run pytest tests/modules/auth/test_cong_google.py -v`
Expected: PASS — 11 test.

- [ ] **Step 5: Chạy toàn bộ test module auth để chắc không vỡ gì**

Run: `uv run pytest tests/modules/auth tests/unit -v`
Expected: PASS toàn bộ. Đặc biệt `test_co_dong_cong.py` (cổng 1 — mọi endpoint khai action) phải xanh.

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/auth/router.py tests/modules/auth/test_cong_google.py
git commit -m "feat(auth): GET /auth/providers, /auth/google/start và /auth/google/callback"
```

---

### Task 7: Frontend — nút Google và màn lỗi

**Repo:** `odyssey-portal-frontend/`

**Files:**
- Modify: `src/features/auth/api.ts` (thêm `layNhaCungCap`)
- Create: `src/features/auth/components/NutGoogle.tsx`
- Modify: `src/features/auth/components/LoginForm.tsx` (thêm nút + **sửa docstring**)
- Modify: `src/features/auth/components/DangKyForm.tsx` (thêm nút)
- Modify: `src/routes/login.tsx` (đọc `?loi=`)
- Modify: `src/lib/msw/handlers.ts` (handler cho `/api/v1/auth/providers`)
- Create: `tests/nut-google.test.tsx`

**Interfaces:**
- Consumes: `goi<T>` từ `features/auth/api.ts`; `GET /api/v1/auth/providers → {google: boolean}` (Task 6).
- Produces: `export function layNhaCungCap(): Promise<{google: boolean}>`; `export function NutGoogle(): JSX.Element | null`; `LoginForm` nhận prop tuỳ chọn `loiBanDau?: string`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/nut-google.test.tsx` — bộ test FE nằm PHẲNG trong `tests/`, tên kebab-case (theo `tests/login.test.tsx`, `tests/dang-ky.test.tsx`):

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { NutGoogle } from '@/features/auth/components/NutGoogle'
import { server } from '../vitest.setup'

describe('NutGoogle', () => {
  it('vẽ một thẻ <a> thật, không phải <button>', async () => {
    render(<NutGoogle />)
    const a = await screen.findByRole('link', { name: /Google/i })
    // Phải là <a href> — OAuth cần trình duyệt RỜI KHỎI trang. Một <button> +
    // fetch sẽ đâm vào CORS của Google và không bao giờ chạy.
    expect(a).toHaveAttribute('href', '/api/v1/auth/google/start')
  })

  it('không vẽ gì khi backend báo tính năng tắt', async () => {
    server.use(
      http.get('/api/v1/auth/providers', () => HttpResponse.json({ google: false })),
    )
    const { container } = render(<NutGoogle />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('không vẽ gì trong lúc đang hỏi backend', () => {
    // Vẽ chỗ trống rồi nhét nút vào sau là để một nút nhảy ra dưới ngón tay
    // người đang bấm «Đăng nhập».
    const { container } = render(<NutGoogle />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

> **BẮT BUỘC làm TRƯỚC khi chạy test này:** `vitest.setup.ts` đặt `onUnhandledRequest: 'error'`, nên một request không có handler mặc định là LỖI, không phải một fetch trả undefined. Thêm handler vào `src/lib/msw/handlers.ts` ngay bây giờ (đây là hạ tầng test, không phải code sản phẩm), cạnh các handler auth khác:
>
> ```ts
>   http.get('/api/v1/auth/providers', () => HttpResponse.json({ google: true })),
> ```
>
> Bước 8 bên dưới nhắc lại việc này — đã làm ở đây thì bỏ qua nó.

- [ ] **Step 2: Chạy test để xác nhận nó đỏ**

Run: `npm test -- tests/nut-google.test.tsx`
Expected: FAIL — không resolve được `@/features/auth/components/NutGoogle`.

- [ ] **Step 3: Thêm seam API**

Trong `src/features/auth/api.ts`, thêm cạnh `dangNhap`:

```ts
/**
 * CÔNG KHAI — màn đăng nhập chưa có phiên nào để gửi.
 *
 * FE không có đường nào khác biết cửa Google bật hay tắt: cờ thật nằm ở `.env`
 * của backend. KHÔNG thay bằng một biến build-time của Vite — một bản build sẵn
 * đem sang môi trường khác sẽ nói sai.
 */
export function layNhaCungCap(): Promise<{ google: boolean }> {
  return goi<{ google: boolean }>('/api/v1/auth/providers')
}
```

- [ ] **Step 4: Viết `NutGoogle.tsx`**

Tạo `src/features/auth/components/NutGoogle.tsx`:

```tsx
/**
 * Nút «Tiếp tục với Google». Dùng chung cho màn đăng nhập và màn đăng ký —
 * backend không phân biệt hai đường (nhánh 3 của `dang_nhap_google.py` tự lo
 * việc tạo tài khoản mới).
 *
 * ⚠ THẺ <a href> THẬT, KHÔNG PHẢI onClick + fetch. OAuth cần trình duyệt RỜI
 * KHỎI trang; `fetch` sẽ đâm vào CORS của accounts.google.com và không bao giờ
 * chạy. Dùng <a> còn cho middle-click / mở tab mới hoạt động miễn phí.
 *
 * KHÔNG vẽ gì trong lúc đang hỏi backend: một nút nhảy ra dưới ngón tay người
 * đang bấm «Đăng nhập» là một cú bấm nhầm.
 */
import { useQuery } from '@tanstack/react-query'

import { layNhaCungCap } from '../api'

export function NutGoogle() {
  const { data } = useQuery({
    queryKey: ['auth', 'providers'],
    queryFn: layNhaCungCap,
    staleTime: Infinity,
  })

  if (!data?.google) return null

  return (
    <>
      <div className="flex items-center gap-3 text-[11px] text-muted-2">
        <span className="h-px flex-1 bg-border" />
        hoặc
        <span className="h-px flex-1 bg-border" />
      </div>
      <a
        href="/api/v1/auth/google/start"
        className="flex items-center justify-center gap-2 rounded-lg border border-border-field px-4 py-2 text-sm font-medium text-fg hover:bg-n2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ac"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M23.04 12.26c0-.82-.07-1.6-.21-2.36H12v4.47h6.19a5.3 5.3 0 0 1-2.3 3.47v2.89h3.72c2.18-2 3.43-4.96 3.43-8.47z" />
          <path fill="#34A853" d="M12 24c3.1 0 5.7-1.03 7.6-2.79l-3.72-2.89c-1.03.69-2.35 1.1-3.88 1.1-2.98 0-5.5-2.01-6.4-4.72H1.75v2.98A11.5 11.5 0 0 0 12 24z" />
          <path fill="#FBBC05" d="M5.6 14.7a6.9 6.9 0 0 1 0-4.42V7.3H1.75a11.5 11.5 0 0 0 0 10.38L5.6 14.7z" />
          <path fill="#EA4335" d="M12 4.75c1.68 0 3.19.58 4.38 1.72l3.29-3.29C17.7 1.3 15.1 0 12 0 7.5 0 3.62 2.56 1.75 6.3L5.6 9.28C6.5 6.57 9.02 4.75 12 4.75z" />
        </svg>
        Tiếp tục với Google
      </a>
    </>
  )
}
```

> **Lưu ý:** tên class Tailwind ở trên theo token của `styles/theme.css` (`bg-border`, `text-muted-2`, `border-border-field`, `outline-ac`). Mở `LoginForm.tsx` và **chép đúng lối class của nút «Đăng nhập» hiện có** thay vì dùng nguyên khối trên nếu chúng lệch nhau — hình dạng nút phải khớp màn, không phải khớp plan này.

- [ ] **Step 5: Chạy test để xác nhận nó xanh**

Run: `npm test -- tests/nut-google.test.tsx`
Expected: PASS — 3 test.

- [ ] **Step 6: Cắm nút vào hai form và sửa docstring**

Trong `src/features/auth/components/LoginForm.tsx`:

1. Thêm `import { NutGoogle } from './NutGoogle'`.
2. Đặt `<NutGoogle />` ngay SAU nút «Đăng nhập», TRƯỚC dòng «Chưa có tài khoản?».
3. **Sửa docstring** — thay đoạn đang ghi *"KHÔNG có nút Google/Apple/SSO và KHÔNG có «Quên mật khẩu?»: seam auth chỉ có `dangNhap(email, matKhau)`. Vẽ chúng ra là hứa tính năng không tồn tại…"* bằng:

```
 * CÓ nút Google từ 2026-08-18 (spec dang-nhap-google-oauth) — nó là một <a href>
 * thật sang `/api/v1/auth/google/start`, không phải một lời hứa suông: seam có
 * `layNhaCungCap()` và nút TỰ ẨN khi backend báo tính năng tắt.
 *
 * VẪN KHÔNG có «Quên mật khẩu?» và KHÔNG có Apple/SSO: chưa có đường nào ở
 * backend, và một link chết là thứ người dùng bấm đúng vào lúc bí nhất.
```

Trong `src/features/auth/components/DangKyForm.tsx`: thêm cùng import và đặt `<NutGoogle />` sau nút gửi. Không cần seam riêng — nhánh 3 ở backend tự tạo tài khoản.

- [ ] **Step 7: Đọc `?loi=` ở route đăng nhập**

Trong `src/routes/login.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { LoginForm } from '@/features/auth/components/LoginForm'

/**
 * NGOÀI `_app` — cố ý. `_app` là layout của mọi màn SAU đăng nhập và nó bọc
 * <SessionProvider>; màn này phải render được khi chưa có phiên.
 *
 * `?loi=` là đường lỗi CỦA CỬA GOOGLE: callback là điều hướng trình duyệt nên
 * nó không trả JSON được, và envelope `{error:{code,message}}` không có chỗ để
 * đi. Xem `modules/auth/router.py::_ve_login`.
 */
const NHAN_LOI: Record<string, string> = {
  STATE_HET_HAN: 'Phiên đăng nhập Google đã quá hạn. Bấm lại nút để thử lần nữa.',
  GOOGLE_TU_CHOI: 'Google không hoàn tất được lần đăng nhập này. Thử lại, hoặc dùng email và mật khẩu.',
  EMAIL_CHUA_XAC_THUC: 'Tài khoản Google này chưa xác thực email. Xác thực ở Google rồi quay lại.',
  TAI_KHOAN_DINH_CHI: 'Tài khoản của bạn đã bị đình chỉ. Liên hệ quản trị viên của tổ chức để được mở lại.',
  DANG_KY_DANG_TAT: 'Portal đang tạm ngừng nhận tài khoản mới.',
}

export const Route = createFileRoute('/login')({
  validateSearch: (s: Record<string, unknown>) => ({ loi: typeof s.loi === 'string' ? s.loi : undefined }),
  component: ManDangNhap,
})

function ManDangNhap() {
  const { loi } = Route.useSearch()
  // Mã lạ -> không hiện gì. Một mã ta không biết nghĩa là backend đã đi trước FE
  // một bản deploy; hiện mã thô ra màn đăng nhập không giúp ai cả.
  return <LoginForm loiBanDau={loi ? NHAN_LOI[loi] : undefined} />
}
```

Rồi trong `LoginForm.tsx`, nhận prop và hiện nó ở đúng chỗ lỗi hiện tại:

```tsx
export function LoginForm({ loiBanDau }: { loiBanDau?: string } = {}) {
  // …giữ nguyên state hiện có…
  // Ở chỗ render lỗi: hiện `loi` như cũ, và nếu chưa có `loi` thì hiện `loiBanDau`.
}
```

- [ ] **Step 8: Thêm handler MSW**

Trong `src/lib/msw/handlers.ts`, thêm cạnh các handler auth khác:

```ts
  http.get('/api/v1/auth/providers', () => HttpResponse.json({ google: true })),
```

- [ ] **Step 9: Chạy toàn bộ test và typecheck**

Run: `npm test && npm run build`
Expected: test PASS toàn bộ, build không lỗi TypeScript.

⚠ `tsc --noEmit` KHÔNG dùng được ở repo này (tsconfig kiểu solution — pass rỗng). Dùng `npm run build`.

- [ ] **Step 10: Commit**

```bash
git add src/features/auth src/routes/login.tsx src/lib/msw/handlers.ts tests/nut-google.test.tsx
git commit -m "feat(auth): nút đăng nhập Google và màn lỗi ?loi= ở /login"
```

---

## Kiểm tra cuối (sau Task 7)

- [ ] **Backend:** `make check` (lint + toàn bộ test) — PASS.
- [ ] **Frontend:** `npm test && npm run build` — PASS.
- [ ] **Thủ công, chạy thật:** đặt `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` thật vào `.env`, khai redirect URI `http://localhost:<cổng>/api/v1/auth/google/callback` trong Google Cloud Console, rồi đi hết bốn ca:
  1. Tài khoản Google chưa từng dùng → vào màn tạo workspace.
  2. Đăng xuất, bấm lại → vào thẳng dashboard, KHÔNG tạo user thứ hai.
  3. Tạo một user có mật khẩu trùng email Google → bấm nút → liên kết, mật khẩu cũ vẫn dùng được.
  4. `UPDATE control.users SET lifecycle='suspended'` → bấm nút → về `/login?loi=TAI_KHOAN_DINH_CHI`, không có cookie.
- [ ] **Việc ngoài code:** chuyển OAuth consent screen từ *Testing* sang *In production* trước khi mở cho người dùng thật — để ở Testing thì chỉ 100 tài khoản khai sẵn đăng nhập được, và nó chỉ lộ ra khi người thứ 101 thử.
