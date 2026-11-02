"""Định giá usage — lệnh cho cron.

    python -m portal.cli.dinh_gia_usage                    # phủ lùi 48h
    python -m portal.cli.dinh_gia_usage --gio 1            # phủ lùi 1 giờ (chạy tay)
    python -m portal.cli.dinh_gia_usage --tu 2026-08-01 --den 2026-09-01
    python -m portal.cli.dinh_gia_usage --thu-kho          # diễn tập, không ghi

⚠️ LỆNH NÀY KHÔNG CÒN LÀ ĐƯỜNG CHÍNH (từ `0950`, 2026-08-21). Tiền nay được tính
trong CHÍNH câu INSERT vào `billing.usage_events` — trigger `usage_events_dinh_gia`.
Lệnh này còn lại làm LƯỚI AN TOÀN cho ba lỗ trigger không với tới: usage tới
trước khi có dòng giá phủ nó · trigger ném và bị khối `EXCEPTION` nuốt (cố ý, để
không làm vỡ câu INSERT vào sổ gốc) · dữ liệu ghi trước `0950`. Chi tiết:
`deploy/systemd/README.md`.

Nên nhịp hợp lý của nó là HẰNG ĐÊM với cửa sổ mặc định, không phải mỗi vài phút.
Cờ `--gio` giữ lại cho việc chạy tay một cửa sổ hẹp (điều tra, vá một lô vừa
lỗi) — timer 2 phút dùng nó đã bị bỏ cùng lần thêm `0950`.

Ở hệ chạy bình thường, lượt đêm nên báo con số NHỎ: trigger đã làm hết việc nên
`ON CONFLICT DO UPDATE` chỉ ghi lại đúng giá trị cũ. Con số LỚN đột ngột là dấu
hiệu trigger đang ném, không phải dấu hiệu job đang hữu ích.

VÌ SAO PHỦ LÙI 48H MẶC ĐỊNH: §5.4 hướng dẫn bên agent — đường ghi là
fire-and-forget có retry theo seq, nên lô của một phiên có thể landed muộn vài phút
tới vài giờ (vẫn mang `occurred_at` đúng lúc phát sinh). Định giá đúng cửa sổ hôm
nay là bỏ sót những dòng đó, và bỏ sót IM LẶNG.

`billing.rate_usage()` idempotent (`ON CONFLICT (event_id, metric) DO UPDATE`) nên
chạy trùng nhiều lần không nhân bản — đó là điều kiện để cửa sổ chồng lấn an toàn.

LỆNH RIÊNG, không gộp vào job khác: ops phải tắt được cái này mà giữ cái kia, và
mỗi lượt cần để lại số dòng đã xử lý để trả lời "đêm qua định giá bao nhiêu".

VÌ SAO DÙNG `migrator_url` CHỨ KHÔNG `database_url`: `rate_usage` là SECURITY
DEFINER nên role `portal_api` gọi được, nhưng job này định giá cho MỌI tenant
(`p_tenant = NULL`) — đó là thao tác cấp nền tảng, không thuộc phạm vi cách ly
của một request/tenant. Dùng DSN của `portal_api` ở đây không sai về quyền
(hàm tự vượt RLS nhờ DEFINER), nhưng job cấp nền tảng đi bằng DSN cấp nền tảng
là đúng ranh giới hơn, và tránh việc một request-scoped role phải gánh một thao
tác không hề request-scoped.

VÌ SAO Ở `portal/cli/` CHỨ KHÔNG `scripts/`: Dockerfile không COPY `scripts/` vào
image, mà cron chạy trên production. Xem docstring `portal/cli/__init__.py`.
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime, timedelta

import asyncpg

from portal.core.config import get_settings
from portal.core.db.pool import create_pool

log = logging.getLogger(__name__)

KHOANG_RE_RUN_GIO = 48
"""Cửa sổ phủ lùi mặc định. Đổi số này là đổi một quyết định nghiệp vụ."""


async def chay(
    pool: asyncpg.Pool,
    tu: date | None = None,
    den: date | None = None,
    thu_kho: bool = False,
    gio: float | None = None,
) -> int:
    """Trả số dòng `rated_usage` đã ghi/cập nhật. `tenant = NULL` ⇒ mọi tenant.

    Không tham số ⇒ cửa sổ mặc định là (bây_giờ − `KHOANG_RE_RUN_GIO` giờ) tới
    (bây_giờ + 1 phút) — biên trên nới thêm một phút để tránh bỏ sót event ghi
    đúng lúc job đang chạy. Có `tu`/`den` ⇒ dùng đúng khoảng ngày đó (00:00 UTC),
    không áp phủ lùi — dùng cho việc chạy tay một khoảng lịch sử cụ thể.
    Có `gio` ⇒ cùng khuôn cửa sổ mặc định nhưng phủ lùi `gio` giờ thay vì 48h —
    dùng khi chạy tay một cửa sổ hẹp (điều tra, vá một lô vừa lỗi).

    `tu`/`den` PHẢI đi CÙNG NHAU: cho một mình một bên rồi âm thầm rơi về cửa sổ
    48h mặc định là lấy đúng cận operator KHÔNG xin, không một lời báo — đường
    ngắn nhất để một kỳ billing bị định giá nhầm khoảng.

    `gio` LOẠI TRỪ `tu`/`den`, không phải "cái nào cũng được": hai cách khai cửa
    sổ cùng lúc thì một cái phải thắng im lặng, và operator đọc lệnh sẽ tin cái
    còn lại. Thà ném.
    """
    # Phép loại trừ đứng TRƯỚC phép ghép đôi, không phải ngược lại: với
    # `--gio 1 --tu 2026-08-01` thì CẢ HAI luật đều bị phá, và câu lỗi đúng là
    # câu nói về sai lầm gốc (trộn hai cách khai cửa sổ). Báo «--tu và --den phải
    # đi cùng nhau» ở đó là chỉ operator đi thêm `--den`, tức dẫn họ tới một lệnh
    # vẫn sai theo đúng cách vừa không nói ra.
    if gio is not None and (tu is not None or den is not None):
        raise ValueError(
            "`--gio` và `--tu/--den` loại trừ nhau: một cái khai cửa sổ phủ lùi, cái kia "
            "khai một khoảng lịch sử cụ thể. Khai cả hai thì cận nào thắng cũng là im lặng."
        )
    if (tu is None) != (den is None):
        raise ValueError(
            "`--tu` và `--den` phải đi CÙNG NHAU. Cho một mình một bên sẽ rơi về cửa sổ "
            f"{KHOANG_RE_RUN_GIO}h mặc định một cách im lặng — không phải khoảng bạn xin. "
            "Muốn phủ lùi mặc định thì bỏ CẢ HAI; muốn một khoảng cụ thể thì khai CẢ HAI."
        )
    if gio is not None and gio <= 0:
        raise ValueError(f"`--gio` phải > 0, nhận {gio} — cửa sổ rỗng thì không định giá gì.")
    if gio is not None:
        bay_gio = datetime.now(UTC)
        tu_ts = bay_gio - timedelta(hours=gio)
        den_ts = bay_gio + timedelta(minutes=1)
    elif tu is None or den is None:
        bay_gio = datetime.now(UTC)
        tu_ts = bay_gio - timedelta(hours=KHOANG_RE_RUN_GIO)
        den_ts = bay_gio + timedelta(minutes=1)
    else:
        tu_ts = datetime(tu.year, tu.month, tu.day, tzinfo=UTC)
        den_ts = datetime(den.year, den.month, den.day, tzinfo=UTC)

    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            n = await conn.fetchval("SELECT billing.rate_usage($1, $2, NULL)", tu_ts, den_ts)
            if thu_kho:
                await tx.rollback()
                log.info("THỬ KHÔ: sẽ định giá %s dòng (%s → %s)", n, tu_ts, den_ts)
                return n
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise
    log.info("đã định giá %s dòng (%s → %s)", n, tu_ts, den_ts)
    return n


def _ngay(s: str) -> date:
    return date.fromisoformat(s)


async def main_async(tu: date | None, den: date | None, thu_kho: bool, gio: float | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = get_settings()
    pool = await create_pool(c.migrator_url, min_size=1, max_size=2)
    try:
        so = await chay(pool, tu=tu, den=den, thu_kho=thu_kho, gio=gio)
    finally:
        await pool.close()
    print(f"dinh-gia-usage: {'SẼ định giá' if thu_kho else 'đã định giá'} {so} dòng")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Định giá billing.usage_events")
    ap.add_argument("--tu", type=_ngay, default=None)
    ap.add_argument("--den", type=_ngay, default=None)
    ap.add_argument(
        "--gio",
        type=float,
        default=None,
        help="phủ lùi bao nhiêu GIỜ tính từ bây giờ, cho một lượt chạy tay hẹp. "
        f"Bỏ cờ này ⇒ {KHOANG_RE_RUN_GIO}h (nhịp của job đêm). Loại trừ --tu/--den.",
    )
    ap.add_argument("--thu-kho", action="store_true")
    a = ap.parse_args()
    # Cùng THỨ TỰ với `chay()` — xem chú thích ở đó. Hai chỗ khai cùng một luật là
    # hai chỗ để lệch nhau, và lệch ở đây nghĩa là dòng lệnh nói một câu còn hàm
    # nói câu khác cho cùng một tổ hợp cờ.
    if a.gio is not None and (a.tu is not None or a.den is not None):
        ap.error("--gio loại trừ --tu/--den: khai cả hai thì cận nào thắng cũng là im lặng")
    if (a.tu is None) != (a.den is None):
        # `ap.error()` in ra usage + thông điệp rồi exit(2) — cùng khuôn lỗi
        # argparse tự sinh cho các tổ hợp cờ sai khác, không phải một traceback
        # Python trần từ `chay()`.
        ap.error("--tu và --den phải đi cùng nhau (cho một mình một bên sẽ không rõ cận còn lại là gì)")
    if a.gio is not None and a.gio <= 0:
        ap.error(f"--gio phải > 0, nhận {a.gio}")
    sys.exit(asyncio.run(main_async(a.tu, a.den, a.thu_kho, a.gio)))


if __name__ == "__main__":
    main()
