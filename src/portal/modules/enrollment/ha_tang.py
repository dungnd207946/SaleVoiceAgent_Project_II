"""Áp bí mật lên hai hệ: role Postgres và access key kho tệp.

VÌ SAO TÁCH KHỎI service.py: hai việc ở đây cần MinIO thật và quyền `CREATEROLE`.
`service.py` là nghiệp vụ và phải test được mà không dựng cả cụm. Tách ra một mặt
tiền hẹp để test tiêm được fake.

ĐÂY KHÔNG PHẢI LỚP BỌC core/storage.py — nó GỌI `chinh_sach_tien_to()` có sẵn.
Định nghĩa lại quy tắc tiền tố ở đây là tạo chủ thứ hai cho cùng một khái niệm.

VÌ SAO KHÔNG CHẠM QDRANT: vòng đời collection thuộc `modules/kb` — nay là
`kb/ops/collections.py` (`create`/`drop`, gọi qua client của rag_service và
media_service). Làm lại ở đây là hai chủ cho một việc, và import ruột module kb
vi phạm cổng ranh giới (`test_module_boundaries.py`). M10 chỉ TRAO TÊN collection.

⚠ TÊN COLLECTION ĐANG LỆCH — chưa chốt, xem MERGE-REVIEW-kb.md §A.
`core.ten_tai_nguyen.ten_collection()` trả MỘT tên (`kb_<tenant>`) và đó là tên
đi vào `manifest.toml` cho agent; nhưng module kb sau merge ghi vào HAI collection
(`<slug>_documents`, `<slug>_media`, xem `kb/clients/rag.py`+`media.py`). Agent đọc
một kho portal không ghi vào — đúng chế độ hỏng mà docstring của `ten_collection()`
cảnh báo: không có lỗi nào cả.

MỌI THAO TÁC IDEMPOTENT. Cấp phát chạm hai hệ ngoài Postgres-thuần và không thể
nằm trong một transaction; chịu được gọi lại là cách duy nhất để hỏng-giữa-chừng
không thành trạng thái nửa vời.
"""

import contextlib

import asyncpg
from minio import MinioAdmin
from minio.credentials import StaticProvider

from portal.core.config import get_settings
from portal.core.storage import chinh_sach_tien_to
from portal.core.ten_tai_nguyen import ten_khoa_truy_cap, ten_role_agent

# Mã lỗi MinIO cho "user không tồn tại" — xem `HaTang.xoa_khoa_kho_tep`.
_KHONG_CO_USER = "XMinioAdminNoSuchUser"


def lay_ha_tang() -> "HaTang":
    """Dependency FastAPI — để test tiêm được fake thay vì phải dựng MinIO.

    Ở FILE NÀY chứ không ở router.py: hai router của module (`router.py` cho admin
    nền tảng, `router_tenant.py` cho owner workspace) đều cần nó. Đặt ở router.py
    thì router_tenant phải import từ đó, và router.py lại import router_tenant để
    `include_router` — một vòng import.

    Một hàm chứ không hai: `dependency_overrides` khớp theo ĐỊNH DANH HÀM, nên hai
    bản sao giống nhau từng chữ vẫn là hai khoá khác nhau, và một lần override sẽ
    chỉ trúng một router.
    """
    return HaTang.tu_cai_dat()


class HaTang:
    def __init__(self, admin: MinioAdmin | None, bucket: str) -> None:
        self._admin = admin
        self._bucket = bucket

    @classmethod
    def tu_cai_dat(cls) -> "HaTang":
        """`admin=None` khi S3_ACCESS_KEY / S3_SECRET_KEY rỗng — kho tệp thành
        tuỳ chọn, KHÔNG phải điều kiện phát khoá.

        Vì sao kiểm Ở ĐÂY chứ không để StaticProvider tự nổ: nó ném "Access key
        must not be empty" ngay lúc FastAPI dựng dependency — một 500 câm ở tầng
        thư viện, mất nguyên một phiên truy trên production (2026-08-05) mới ra
        tới "env chép từ .env.example, hai dòng S3 để trống".

        Vì sao RỖNG-LÀ-HỢP-LỆ chứ không phải lỗi cấu hình: bản thân khoá agent
        chỉ là token + băm trong DB — nó không cần kho tệp. Bước `dat_khoa_kho_tep`
        chỉ chuẩn bị sẵn access key mà pod SẼ nhận lúc gọi `/runtime-credentials`; môi trường chưa
        dùng kho tệp qua portal (agent xác thực qua gateway, dữ liệu ở stack riêng)
        thì chặn phát khoá vì thiếu nó là quá tay. Đường bỏ qua có ghi vết —
        xem `dat_khoa_kho_tep`.
        """
        c = get_settings()
        if not c.s3_access_key or not c.s3_secret_key:
            return cls(admin=None, bucket=c.s3_bucket)
        endpoint = c.s3_endpoint_url or ""
        return cls(
            admin=MinioAdmin(
                endpoint=endpoint.removeprefix("http://").removeprefix("https://"),
                credentials=StaticProvider(c.s3_access_key, c.s3_secret_key),
                secure=endpoint.startswith("https://"),
            ),
            bucket=c.s3_bucket,
        )

    async def dat_mat_khau_role(self, conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str, mat_khau: str) -> None:
        """Tạo role nếu chưa có, đổi mật khẩu nếu đã có. Idempotent.

        Toàn bộ việc nằm trong `control.dat_mat_khau_agent()` — helper SECURITY
        DEFINER của migration 0900. Vì sao không làm ở Python: `portal_api` KHÔNG
        có CREATEROLE (cố ý), nên nó không tạo role và cũng không ALTER PASSWORD
        được. Xem docstring của helper đó để biết hai đường sai đã bị loại.

        `mat_khau` là base64url 43 ký tự từ `bi_mat.dan_xuat()`. Helper kiểm độ
        dài tối thiểu, nên một lỗi truyền chuỗi rỗng vào đây sẽ NỔ chứ không âm
        thầm đặt mật khẩu rỗng.
        """
        await conn.execute("SELECT control.dat_mat_khau_agent($1, $2)", tenant_id, mat_khau)

    def dat_khoa_kho_tep(self, tenant_id: str, secret: str) -> bool:
        """Access key + policy CHỈ mở `tenants/<id>/*`. Nếp theo seed_kho_tep.py:62.

        Trả `False` = BỎ QUA vì không có credential admin (xem `tu_cai_dat`).
        Không im lặng: caller (service.cap_phat / xoay_bi_mat) ghi cờ này vào
        nhật ký, nên "kho tệp chưa cấp" đọc được từ audit log thay vì chỉ lộ ra
        khi pod cầm credential S3 không dùng được. Hệ quả phải biết:
        `/runtime-credentials` vẫn trả bộ S3 suy dẫn, nhưng key đó CHƯA tồn tại trên MinIO — pod đọc/ghi
        kho tệp sẽ bị từ chối cho tới khi ops điền env và khoá được phát lại
        (hoặc xoay bí mật).

        Gỡ rồi thêm lại vì `user_add` trên key đã có sẽ đổi mật khẩu nhưng KHÔNG
        cập nhật policy — và một key có mật khẩu mới với policy cũ là đúng loại
        sai không có triệu chứng.
        """
        if self._admin is None:
            return False
        khoa = ten_khoa_truy_cap(tenant_id)
        with contextlib.suppress(Exception):  # chưa có key là trường hợp bình thường
            self._admin.user_remove(khoa)
        self._admin.user_add(khoa, secret)
        self._admin.policy_add(khoa, policy=chinh_sach_tien_to(tenant_id, self._bucket))
        self._admin.policy_set(khoa, user=khoa)
        return True

    async def xoa_role(self, conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str) -> bool:
        """Xoá role Postgres của pod. `False` = chưa từng cấp phát, không phải lỗi.

        Cặp đối xứng của `dat_mat_khau_role`, và cùng lý do phải đi qua một helper
        SQL: `portal_api` KHÔNG có `CREATEROLE` nên nó không `DROP ROLE` được.
        `control.xoa_role_agent()` là `SECURITY DEFINER` (migration `0936`) và tự
        chặn hai đường lạm dụng — xem docstring migration đó.

        GỌI SAU KHI hàng `control.tenants` đã bị xoá: hàm SQL cố ý KHÔNG đòi tenant
        còn tồn tại, khác `create_agent_role`.
        """
        return bool(await conn.fetchval("SELECT control.xoa_role_agent($1)", tenant_id))

    def xoa_khoa_kho_tep(self, tenant_id: str) -> bool:
        """Gỡ access key MinIO của pod. `False` = KHÔNG CÓ GÌ ĐỂ GỠ.

        Cặp đối xứng của `dat_khoa_kho_tep`, và `user_remove` gỡ luôn policy gắn vào
        key nên không cần `policy_remove` thứ hai — chính sách đặt bằng
        `policy_set(user=...)`, nó là một liên kết chứ không phải đối tượng sống độc lập.

        HAI ca trả `False`, cả hai đều BÌNH THƯỜNG:
          · không có credential admin (`S3_ACCESS_KEY` rỗng — xem `tu_cai_dat`)
          · **key chưa từng tồn tại.** Access key chỉ ra đời ở `service.cap_phat`,
            tức khi workspace được cấp phát một pod — mà phần lớn workspace thì
            không. Đây là đường THƯỜNG của mọi lượt xoá, không phải ngoại lệ.

        ⚠️ ĐÃ TỪNG ĐỂ 404 NÉM RA NGOÀI, VÀ NÓ SAI THEO HƯỚNG NGUY HIỂM NHẤT: mọi
        lượt xoá workspace ghi một dòng `ERROR` nói "credential có thể còn sống",
        cho một credential chưa bao giờ tồn tại. Một cảnh báo kêu ở mọi lượt bình
        thường là cảnh báo người trực học cách bỏ qua — rồi đúng lúc nó kêu thật thì
        không ai đọc. Đo được trên stack thật, xem
        `test_don_ha_tang_khong_bao_loi_khi_chua_tung_cap_phat`.

        MỌI LỖI KHÁC VẪN NÉM. Đó là chỗ phân biệt thật: "không có key" là không sao,
        còn "MinIO từ chối / không với tới được" nghĩa là credential của workspace
        vừa xoá CÓ THỂ vẫn mở được kho tệp, và người gọi phải kêu to.

        Bắt theo MÃ LỖI trong thông điệp (`XMinioAdminNoSuchUser`) vì `MinioAdmin`
        ném `MinioAdminException` chung cho mọi mã HTTP, không có lớp con nào để
        `except` theo kiểu. Nếu SDK về sau khai lớp riêng thì đổi sang nó.
        """
        if self._admin is None:
            return False
        try:
            self._admin.user_remove(ten_khoa_truy_cap(tenant_id))
        except Exception as e:
            if _KHONG_CO_USER in str(e):
                return False
            raise
        return True

    async def thieu_gi(self, conn: asyncpg.Connection | asyncpg.Pool, tenant_id: str) -> str:
        """Chuỗi rỗng = cấp phát đủ. Ngược lại liệt kê thứ thiếu, để lỗi
        NOT_PROVISIONED nói được thiếu cái gì thay vì chỉ nói "chưa xong"."""
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", ten_role_agent(tenant_id)):
            return "role Postgres"
        return ""
