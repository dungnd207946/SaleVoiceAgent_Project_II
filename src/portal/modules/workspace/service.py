"""Nghiệp vụ tạo workspace. `slug_tenant()` là hàm THUẦN, tách khỏi phần chạm DB.

VÌ SAO `slug_tenant` PHẢI THUẦN: đầu ra của nó đi vào ba chỗ cưỡng chế cùng một
biểu thức — CHECK `tenants_id_check` (0002), `control.create_agent_role()` (0005)
và `control.dat_mat_khau_agent()` (0900). Hai hàm sau `RAISE EXCEPTION` khi không
khớp, vì tên role được ghép vào câu `CREATE ROLE`. Thuần nghĩa là cổng property
test chạy được 500 chuỗi trong vài milli-giây, không cần Docker — xem
tests/modules/workspace/test_slug.py.

BA CHỖ ĐÓ GIỜ CHẤP NHẬN `^[a-z][a-z0-9_-]{1,30}$` (migration 0911 thêm `-` cho
tenant_id import từ hệ ngoài), nhưng `slug_tenant()` VẪN CHỈ SINH
`^[a-z][a-z0-9_]{1,30}$` — nó fold mọi ký tự lạ về `_`. Đầu ra là một TẬP CON
thật sự của cái được chấp nhận, và đó là chủ ý: đường tạo workspace không nên sinh
ra hai hình dạng id cho cùng một loại tên. Property test canh biểu thức HẸP, cố
tình — nới nó theo 0911 là làm mất đúng cái nó đang canh.

VÌ SAO KHÔNG ĐẶT VÀO `core/ten_tai_nguyen.py`: file đó có luật "mọi hàm ở đây
nhận ĐÚNG `tenant_id` và không tham số nào khác", và nó suy tên tài nguyên TỪ
`tenant_id`. Hàm này đi chiều NGƯỢC (tên hiển thị -> id) và bản có tra trùng còn
cần `conn`. Đặt vào đó là phá đúng cái luật khiến file đó đáng tin.
"""

import logging
import re
import secrets
import unicodedata

import asyncpg

from portal.api import loi as loi_chung
from portal.core import nhat_ky
from portal.core.storage import kho_tep_tu_cai_dat, tien_to_tenant
from portal.core.ten_tai_nguyen import ten_khoa_truy_cap, ten_role_agent

# `enrollment` và `kb` vào đây qua MẶT TIỀN `contracts` — KHÔNG import ruột chúng
# (Luật 3). Ba tài nguyên ngoài Postgres-thuần thuộc về hai module đó: M10 sở hữu
# credential của pod, `kb` sở hữu vòng đời collection. Làm lại ở đây là hai chủ cho
# một việc.
#
# ⚠️ DẠNG IMPORT PHẢI LÀ `from ....contracts import <tên>`. Cổng
# `tests/test_module_boundaries.py` đọc AST và so đường dẫn module: dạng
# `from portal.modules.kb import contracts as kb_contracts` bị nó thấy là import
# `portal.modules.kb` (cả package) và báo VI PHẠM — đã đỏ một lần đúng như vậy.
# `xoa_kho_cua_workspace` đến qua `__getattr__` cấp module của `kb/contracts.py`;
# PEP 562 cho `from mod import name` rơi vào đó, cùng cách `ingest/chieu.py` lấy
# `dat_viec_provision`.
from portal.modules.enrollment.contracts import xoa_khoa_kho_tep_cua_tenant, xoa_role_agent_cua_tenant
from portal.modules.kb.contracts import xoa_kho_cua_workspace
from portal.modules.workspace import loi, repo
from portal.modules.workspace.contracts import (
    SuaWorkspaceIn,
    TaoWorkspaceIn,
    WorkspaceSuaRaOut,
    WorkspaceTaoRaOut,
)

log = logging.getLogger(__name__)

DAI_ID_TOI_DA = 31
"""CHECK `^[a-z][a-z0-9_]{1,30}$` cho 1 ký tự đầu + tối đa 30 ký tự sau = 31."""

DAI_ID_TOI_THIEU = 2
"""HAI, không phải một — chỗ này đã bắt được một lỗi thật lúc viết.

`^[a-z][a-z0-9_]{1,30}$` có `{1,30}` chứ không `{0,30}`: nó đòi ký tự đầu CỘNG
ít nhất một ký tự nữa. Nên một workspace tên `"A"` sinh id `"a"` — đọc thì hợp
lý, và bị CHECK `tenants_id_check` từ chối.

Lỗi đó KHÔNG nổ ở hàm này mà ở câu INSERT, và nếu đường tạo có bug khác nuốt mất
nó thì nó nổ muộn hơn nữa: ở `control.create_agent_role()` lúc cấp phát hạ tầng,
cách nguyên nhân vài ngày. Property test ở tests/modules/workspace/test_slug.py là
chỗ nó bị bắt trong 30ms.
"""

HAU_TO_QUA_NGAN = "_ws"
"""Đệm cho tên một ký tự. `"A"` -> `"a_ws"`.

Chọn hậu tố ngắn có nghĩa thay vì đệm `_1`: `a_1` đọc như "bản thứ nhất của a" và
sẽ đứng cạnh `a_2` do vòng tra trùng sinh ra — hai thứ khác nhau mang cùng hình
dạng. `_ws` không bao giờ nhập nhằng với hậu tố tra trùng.
"""

TEN_DU_PHONG = "workspace"
"""Dùng khi fold xong không còn ký tự `[a-z0-9]` nào (tên toàn emoji / CJK).

Trả rỗng thì câu INSERT vi phạm CHECK và người dùng nhận 500 cho một cái tên hợp
lệ với họ. Trả tên dự phòng rồi để vòng tra trùng thêm `_2` là hành vi đọc được.
"""

VERTICAL_MAC_DINH = "realestate"
"""`tenant_verticals.vertical` CHECK IN ('realestate','finance') — 0002. MVP chỉ
có bất động sản, và `ConfigPayload.pham_vi.linh_vuc` cũng là `Literal["realestate"]`.
"""

_SO_LAN_THU_HAU_TO = 50
"""Trần vòng tra trùng. `while True` ở đường tạo là một cách để một cái tên lạ
làm treo request — cùng lý do `sinh_user_id()` của M2b có trần."""


def _bo_dau(s: str) -> str:
    """Fold dấu về ASCII. `đ`/`Đ` PHẢI xử lý riêng.

    `unicodedata.normalize("NFD", "đ")` trả về đúng `"đ"` — U+0111 là một ký tự
    có gạch ngang XUYÊN QUA thân chữ, không phải `d` + dấu tổ hợp, nên không có
    gì để tách. Thiếu hai lệnh replace bên dưới thì `"Đất Xanh"` ra `"t_xanh"`:
    chữ đầu biến mất không dấu vết, và tên workspace của khách sai từ ngày đầu.
    """
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def slug_tenant(ten: str) -> str:
    """`"Sàn Đông Nam"` -> `"san_dong_nam"`. LUÔN khớp `^[a-z][a-z0-9_]{1,30}$`.

    Không nhận tham số độ dài: một chỗ gọi truyền độ dài khác là một chỗ sinh ra
    id mà CHECK từ chối, và lỗi đó nổ ở lúc cấp phát hạ tầng chứ không ở đây.
    """
    goc = re.sub(r"[^a-z0-9]+", "_", _bo_dau(ten).lower()).strip("_")
    if not goc:
        goc = TEN_DU_PHONG
    if not goc[0].isalpha():
        # `isalpha()` sau khi đã fold + lower ⇒ chỉ còn `[a-z]` là True.
        goc = f"w_{goc}"

    # Cắt TRƯỚC, đệm SAU. Đảo thứ tự thì `rstrip` sau khi cắt có thể lại làm chuỗi
    # ngắn về 1 ký tự và phép đệm đã chạy mất tác dụng.
    goc = goc[:DAI_ID_TOI_DA].rstrip("_") or TEN_DU_PHONG
    if len(goc) < DAI_ID_TOI_THIEU:
        goc = f"{goc}{HAU_TO_QUA_NGAN}"
    return goc


def _ghep_hau_to(goc: str, hau_to: str) -> str:
    """Ghép `_2` vào gốc mà TỔNG vẫn ≤ 31 — cắt gốc, không cắt hậu tố.

    Cắt hậu tố thì `..._1` và `..._2` cùng ra `..._`, và vòng tra trùng lặp vô
    ích tới hết 50 lần rồi rơi về nhánh ngẫu nhiên.
    """
    return f"{goc[: DAI_ID_TOI_DA - len(hau_to)].rstrip('_')}{hau_to}"


async def sinh_tenant_id(conn: asyncpg.Connection, ten: str) -> str:
    """`slug_tenant()` + tra trùng. Trùng thì `_2`.. `_50`, hết thì hậu tố ngẫu nhiên.

    Tra trùng trên `tenants.id` TOÀN CỤC, không theo org: `id` là PRIMARY KEY của
    `control.tenants`, và nó còn là tên role Postgres `agent_<id>` — hai org đặt
    trùng tên workspace vẫn phải ra hai id khác nhau. Đây là chỗ §7 của spec gốc
    nhầm: nó tưởng phải nhúng `org_id` vào id để tách hai org, nhưng hậu tố `_2`
    làm đúng việc đó mà không phá CHECK độ dài.
    """
    goc = slug_tenant(ten)
    for n in range(1, _SO_LAN_THU_HAU_TO + 1):
        ung_vien = goc if n == 1 else _ghep_hau_to(goc, f"_{n}")
        if not await repo.id_da_dung(conn, ung_vien):
            return ung_vien
    return _ghep_hau_to(goc, f"_{secrets.token_hex(3)}")


async def tao(conn: asyncpg.Connection, actor_id: str, vao: TaoWorkspaceIn) -> WorkspaceTaoRaOut:
    """Người dùng tự tạo một workspace và trở thành "Quản trị" của nó.
    Giao dịch do NGƯỜI GỌI mở (router).

    GHI `control.memberships` — ĐẢO NGƯỢC CÓ CHỦ Ý quyết định cũ. Bản trước ghi
    "KHÔNG ghi memberships" vì `org_role='owner'` + tenant cùng org đã cho đủ 13
    action mà không cần hàng nào. Nhánh owner đó bị bỏ 2026-08-15 cùng tầng tổ
    chức, nên nếu không ghi membership thì người vừa tạo workspace KHÔNG vào được
    chính nó — `doc_quyen()` sẽ trả về tập action rỗng.

    CỔNG CHỈ CÒN "CÓ PHIÊN". `org_role='owner'` là cửa cũ; sau khi mở tự đăng ký,
    ai đăng nhập được cũng tạo được workspace (spec bo-organization §2, §5.2).

    KHÔNG cấp phát hạ tầng. `CREATE ROLE` và khoá kho tệp không nằm trong giao
    dịch này, nên gộp vào đây là tạo ra trạng thái nửa vời mà rollback không dọn
    được. Workspace chưa có nhịp tim trả `provisioning`, và đó là BÌNH THƯỜNG —
    cấp phát là một hành động riêng ở `/agent/*`.
    """
    ten = vao.name.strip()

    actor = await repo.tim_actor(conn, actor_id)
    if actor is None:
        # Phiên đã xác thực tới được đây thì user luôn tồn tại, nên `None` chỉ có
        # thể là một cuộc đua với xoá user — câu trả lời đúng cho nó là "không được".
        raise loi_chung.khong_du_quyen()

    if await repo.ten_da_dung(conn, actor.id, ten):
        raise loi.ten_workspace_da_dung(ten)

    tenant_id = await sinh_tenant_id(conn, ten)
    hang = await repo.them_tenant(conn, tenant_id, ten, actor.id)
    await repo.them_vertical(conn, tenant_id, VERTICAL_MAC_DINH)
    await repo.them_membership(conn, actor.id, tenant_id, await repo.id_vai_tro_quan_tri(conn))

    # SAU CÙNG: nhật ký ghi việc ĐÃ xảy ra (xem docstring `nhat_ky.ghi`).
    await nhat_ky.ghi(
        conn,
        tenant_id,
        "workspace.tao",
        actor_id,
        {"name": ten, "created_by": actor.id, "vertical": VERTICAL_MAC_DINH},
    )

    return WorkspaceTaoRaOut(
        id=hang.id,
        name=hang.name,
        lifecycle=hang.lifecycle,
        # Trạng thái SUY RA, không phải cột lưu. Workspace mới chưa nhịp tim nào ⇒
        # `provisioning`; lifecycle suspended/closed (ý chí người vận hành) thắng.
        status=hang.lifecycle if hang.lifecycle in ("suspended", "closed") else "provisioning",
        created_at=hang.created_at,
    )


async def sua(conn: asyncpg.Connection, actor_id: str, tenant_id: str, vao: SuaWorkspaceIn) -> WorkspaceSuaRaOut:
    """Đổi tên workspace. Giao dịch do NGƯỜI GỌI mở (router).

    KHÔNG sinh lại `tenant_id` từ tên mới. Đó là cám dỗ thật — `sinh_tenant_id()`
    ngay trên đã làm đúng việc đó cho đường tạo — và nó sai ở đây theo cách không
    có lỗi nào: mã cũ vẫn là tên role Postgres `agent_<id>`, vẫn là tiền tố
    `tenants/<id>/` trên kho tệp, vẫn là collection `kb_<id>`. Đổi một cột trong
    `control.tenants` thì ba kho kia không đi theo, và workspace mất dữ liệu của
    chính nó mà không có gì đỏ lên.

    `vao.name` ĐÃ được `strip()` ở `SuaWorkspaceIn` — không strip lại ở đây; hai
    chỗ chuẩn hoá là hai chỗ để chúng lệch nhau.
    """
    hang = await repo.doc_tenant(conn, tenant_id)
    if hang is None:
        # Router đã đối chiếu `tenant_id` với `Principal.tenant_id`, nên tới được
        # đây mà không có hàng nghĩa là workspace bị xoá cứng giữa hai câu — một
        # cuộc đua, không phải đường thường.
        raise loi_chung.khong_du_quyen()

    # TRA THEO `hang.created_by`, KHÔNG THEO `actor_id`. Xem docstring
    # `repo.HangTenant.created_by` — đây là chỗ duy nhất phân biệt được hai vế đó.
    if await repo.ten_da_dung(conn, hang.created_by, vao.name, tru_id=tenant_id):
        raise loi.ten_workspace_da_dung(vao.name)

    moi = await repo.doi_ten(conn, tenant_id, vao.name)

    await nhat_ky.ghi(conn, tenant_id, "workspace.doi_ten", actor_id, {"tu": hang.name, "sang": moi.name})

    return WorkspaceSuaRaOut(id=moi.id, name=moi.name)


async def xoa(conn: asyncpg.Connection, actor_id: str, tenant_id: str) -> str:
    """XOÁ CỨNG workspace. Giao dịch do NGƯỜI GỌI mở (router).

    Một câu `DELETE FROM control.tenants` cuốn theo 17 bảng `tenant_data` và ~14
    bảng `control` qua FK `ON DELETE CASCADE` — xem `repo.xoa_han`.

    ⚠️ **BA THỨ NGOÀI GIAO DỊCH NÀY KHÔNG BỊ CUỐN THEO** (collection Qdrant · tiền
    tố `tenants/<id>/` trên kho tệp · role Postgres `agent_<id>`). Chúng là việc của
    `don_ha_tang_ngoai`, gọi SAU commit. Thứ tự đó là một quyết định, không phải sự
    tiện tay: nửa-hỏng theo chiều này để lại **tài nguyên mồ côi** (dọn tay được, và
    không ai bị hại vì workspace đã biến mất thật); đảo lại — dọn hạ tầng trước rồi
    `DELETE` hỏng — để lại một **workspace ĐANG SỐNG mà kho tri thức và tệp đã bị
    xoá**, tức mất dữ liệu của người không xin xoá. `kb/ops/collections.drop()` đã
    ghi đúng thứ tự này trong docstring của nó từ trước.

    ⚠️ **NHẬT KÝ DÙNG `ghi_he_thong`, KHÔNG `ghi`.** `control.audit_log.tenant_id` là
    FK cascade tới bảng vừa xoá, nên một dòng có tenant sẽ bị xoá bởi CHÍNH câu lệnh
    nó đang ghi lại — xoá xong là không còn bằng chứng workspace từng tồn tại, cũng
    không còn ai xoá nó. Ghi kèm `name` vì sau khi hàng biến mất thì không còn chỗ
    nào tra id → tên, và "ai xoá workspace TÊN GÌ" mới là câu người ta mở nhật ký ra
    để hỏi.

    ⚠️ **ID ĐƯỢC TÁI SỬ DỤNG.** `sinh_tenant_id()` tra trùng trên `control.tenants`;
    hàng đã xoá thì id đó rảnh cho workspace sau. Đó là lý do `don_ha_tang_ngoai`
    thất bại phải KÊU TO thay vì im lặng: một collection `abc_documents` mồ côi sẽ
    được workspace `abc` của khách KHÁC thừa hưởng.

    CHẶN WORKSPACE CUỐI CÙNG — xem `loi.workspace_cuoi_cung`. Đọc trước khi xoá,
    trong cùng giao dịch, và trả về luôn id đó cho router dời con trỏ phiên.
    """
    ke_tiep = await repo.workspace_dau_tien_con_lai(conn, actor_id, tenant_id)
    if ke_tiep is None:
        raise loi.workspace_cuoi_cung()

    hang = await repo.doc_tenant(conn, tenant_id)
    if hang is None:
        # Router đã đối chiếu với `Principal.tenant_id`, nên tới được đây mà không có
        # hàng là một cuộc đua với chính đường xoá này ở tab khác.
        raise loi_chung.khong_du_quyen()

    if await repo.xoa_han(conn, tenant_id):
        await nhat_ky.ghi_he_thong(
            conn,
            "workspace.xoa",
            actor_id,
            {"id": hang.id, "name": hang.name, "created_by": hang.created_by},
        )
    # `False` = tab khác vừa xoá xong. Luỹ đẳng: vẫn 204, vẫn chuyển phiên, nhưng
    # KHÔNG ghi dòng nhật ký thứ hai cho một hành động đã xảy ra một lần.

    return ke_tiep


async def don_ha_tang_ngoai(pool: asyncpg.Pool, tenant_id: str) -> dict[str, object]:
    """Dọn BỐN tài nguyên mà `ON DELETE CASCADE` không với tới. Gọi SAU commit.

    KHÔNG NÉM. BỐN bước độc lập (role Postgres · access key kho tệp · collection
    Qdrant · tiền tố tệp), mỗi bước một `try`: hỏng ở Qdrant không được ngăn kho tệp
    được dọn, và một 404 của MinIO không được che kết quả của ba bước kia. Mỗi nhánh
    lỗi ghi `error` với ĐÚNG TÊN tài nguyên còn lại — đó là thứ ops cần để dọn tay,
    và một thông điệp "cái này và/hoặc cái kia" thì không dùng được.

    `False` trong báo cáo nghĩa là KHÔNG CÓ GÌ ĐỂ DỌN, không phải thất bại. Thất bại
    luôn xuất hiện thành một khoá `loi_*`.

    VÌ SAO KHÔNG NÉM: workspace đã biến mất thật rồi (giao dịch đã commit). Trả 500
    lúc này là mời người dùng bấm Xoá lần nữa, mà lần nữa sẽ 403 vì hàng không còn —
    họ kết luận là xoá thất bại trong khi nó đã thành công. Đúng của người dùng và
    đúng của ops là hai câu trả lời khác nhau ở đây, và nhật ký là chỗ dành cho ops.

    MỞ KẾT NỐI RIÊNG: giao dịch của lời gọi đã đóng, và bước xoá role là một câu SQL.
    """
    bao_cao: dict[str, object] = {}

    # BỐN BƯỚC, BỐN `try` RIÊNG. Gộp lại là để một hệ hỏng che kết quả của ba hệ
    # kia — đã đo được: MinIO trả 404 trong khi role Postgres đã xoá xong, mà thông
    # điệp gộp chỉ nói được "role và/hoặc access key".
    try:
        async with pool.acquire() as conn:
            bao_cao["role"] = await xoa_role_agent_cua_tenant(conn, tenant_id)
    except Exception as e:  # noqa: BLE001 — mọi lỗi ở đây chỉ là "chưa dọn được", không đổi kết quả xoá
        bao_cao["loi_role"] = str(e)
        log.error(
            "xoá workspace %s: KHÔNG xoá được role Postgres %s — mật khẩu của pod cũ "
            "vẫn đăng nhập được, và một workspace trùng id sau này sẽ gặp role đã tồn tại: %s",
            tenant_id,
            ten_role_agent(tenant_id),
            e,
        )

    try:
        bao_cao["khoa_kho_tep"] = xoa_khoa_kho_tep_cua_tenant(tenant_id)
    except Exception as e:  # noqa: BLE001
        bao_cao["loi_khoa_kho_tep"] = str(e)
        log.error(
            "xoá workspace %s: KHÔNG gỡ được access key %s trên kho tệp — credential "
            "của workspace vừa xoá có thể vẫn mở được dữ liệu: %s",
            tenant_id,
            ten_khoa_truy_cap(tenant_id),
            e,
        )

    try:
        bao_cao["collection"] = await xoa_kho_cua_workspace(tenant_id)
    except Exception as e:  # noqa: BLE001
        bao_cao["loi_collection"] = str(e)
        log.error(
            "xoá workspace %s: KHÔNG dọn được collection Qdrant — id này có thể được "
            "cấp lại cho workspace khác, và nó sẽ thừa hưởng kho cũ: %s",
            tenant_id,
            e,
        )

    tien_to = tien_to_tenant(tenant_id)
    try:
        bao_cao["tep_da_xoa"] = await kho_tep_tu_cai_dat().xoa_tien_to(tien_to)
    except Exception as e:  # noqa: BLE001
        bao_cao["loi_kho_tep"] = str(e)
        log.error(
            "xoá workspace %s: KHÔNG dọn được kho tệp dưới %s — cùng rủi ro thừa hưởng như collection: %s",
            tenant_id,
            tien_to,
            e,
        )

    return bao_cao
