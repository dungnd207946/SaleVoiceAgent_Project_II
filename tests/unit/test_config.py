"""Test Settings — chạy được không cần Docker, nhờ đó `make test-unit` luôn thật."""

from pathlib import Path

from portal.core.config import Settings, to_alembic_url

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_EXAMPLE = BACKEND_ROOT / ".env.example"


# 5442, KHÔNG phải 5433. Cổng mặc định của postgres và của mấy project khác trên
# cùng máy dev đều đã có chủ (5433 = icr-postgres, đang chạy) — xem
# ../docs/dev-ports.md. Hai test này neo con số lại: default là thứ chạy khi chưa
# ai có `.env`, nên default trỏ sai cổng là default trỏ vào DB của người khác.
#
# `_env_file=None` BẮT BUỘC: hai test này đo HẰNG SỐ TRONG CODE, không đo môi
# trường của người đang lập trình. `Settings()` trần đọc `.env`, nên trên máy có
# `.env` (dev này đặt 5444) chúng đỏ vì một cấu hình local hợp lệ, còn trên CI —
# nơi không có `.env` — chúng xanh. Tức một cổng không thể đỏ ở đúng chỗ nó cần
# đỏ, và xanh ở chỗ nó không đo được gì.
def test_dsn_runtime_mac_dinh_tro_cong_5442():
    assert Settings(_env_file=None).database_url == "postgresql://portal_api:apidev@localhost:5442/portal"


def test_dsn_migrator_mac_dinh_tro_cong_5442():
    assert Settings(_env_file=None).migrator_url == "postgresql://portal_migrator:dev@localhost:5442/portal"


def test_default_runtime_khong_bao_gio_la_portal_migrator():
    """CANH LỖ HỔNG, KHÔNG PHẢI CANH CHÍNH TẢ.

    `portal_migrator` là owner của mọi schema, và ở container dev/test nó là bootstrap
    superuser. Superuser/owner đi xuyên RLS **bất kể FORCE**, nên một tiến trình runtime
    nối bằng nó chạy hoàn toàn NGOÀI cách ly: một job handler quên WHERE đọc và GHI
    xuyên mọi tenant, im lặng, không có lỗi nào.

    Đúng chuyện đó đã từng là mặc định: `database_url` trỏ `portal_migrator` và
    `portal/worker/__main__.py` nối bằng nó, nên `make worker` chạy mọi handler ở chế
    độ không cách ly. deploy/README.md §2 ghi luật "không tiến trình nào nối bằng
    portal_migrator" như một ràng buộc runbook không test được — với DEFAULT CỦA CHÍNH
    REPO thì nó test được, và đây là test đó.
    """
    assert "portal_migrator" not in Settings().database_url


def test_env_example_khong_dat_runtime_dsn_thanh_portal_migrator():
    """Cùng lý do như trên, cho file mà người mới copy thành `.env` đầu tiên.

    Một default an toàn trong code mà `.env.example` vẫn dạy sai thì lỗ hổng chỉ dịch
    chỗ: ai cũng `cp .env.example .env` rồi chạy.
    """
    dong = [
        ln.strip()
        for ln in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("DATABASE_URL=")
    ]
    assert dong, ".env.example không còn dòng DATABASE_URL= — spec §8.3 yêu cầu có cả hai DSN"
    for ln in dong:
        assert "portal_migrator" not in ln, f"{ln} — DSN runtime trong .env.example đang trỏ role owner"


def test_env_example_co_ca_hai_dsn():
    """Spec §8.3: `.env.example` có mẫu CẢ HAI DSN. Trước bản này nó chỉ có một."""
    noi_dung = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "DATABASE_URL=" in noi_dung
    assert "MIGRATOR_URL=" in noi_dung


def test_alembic_url_suy_tu_migrator_khong_phai_runtime():
    """Alembic phải chạy bằng credential DDL, không phải credential runtime.

    Trước bản này `alembic_url` chỉ là `database_url` đổi driver — một credential cho
    hai việc, nên đặt đúng cho việc này là hỏng việc kia.
    """
    s = Settings(
        database_url="postgresql://portal_api:x@h:5432/db",
        migrator_url="postgresql://portal_migrator:y@h:5432/db",
    )
    assert s.alembic_url == "postgresql+psycopg://portal_migrator:y@h:5432/db"


def test_to_alembic_url_chi_doi_tien_to_dau_tien():
    got = to_alembic_url("postgresql://u:p@h/db?opt=postgresql://x")
    assert got == "postgresql+psycopg://u:p@h/db?opt=postgresql://x"


def test_bien_moi_truong_de_duoc_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://a:b@c:1/d")
    monkeypatch.setenv("MIGRATOR_URL", "postgresql://e:f@g:2/h")
    s = Settings()
    assert s.database_url == "postgresql://a:b@c:1/d"
    assert s.migrator_url == "postgresql://e:f@g:2/h"
