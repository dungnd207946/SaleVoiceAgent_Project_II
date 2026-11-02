# src/portal/modules/playbook/contracts.py
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MucDemOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    ten: str
    so: int


class SoDoNutOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    soLuot: int
    daCham: int
    dat: int
    tiLeDat: float | None
    thieuDuLieu: float
    hayThieu: list[MucDemOut]
    hayPham: list[MucDemOut]
    jevSo: int
    jevKhop: float | None


class PlaybookOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    promptVersion: str
    nodes: list[dict]
    soDo: dict[str, SoDoNutOut]
    nutCu: dict[str, int]
    phienBanCu: int
    nguon: list[str]
    coDuLieu: bool
    kichBan: KichBanOut


class LuotNutItemOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    sessionId: str
    seq: int
    phone: str | None
    taoLuc: datetime
    khach: str | None
    agent: str
    dat: bool | None
    thieu: list[str]
    viPhamCam: list[str]
    thieuDuLieu: bool
    buoc: str | None
    jevNut: str | None


class LuotNutOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    luot: list[LuotNutItemOut]


class _Nghiem(BaseModel):
    """Từ chối trường lạ ở mọi tầng; strip mọi chuỗi (kể cả phần tử list) trước khi kiểm và lưu.

    `str.strip()` của Python, KHÔNG `str_strip_whitespace` của pydantic: bản Rust giữ \\x1c–\\x1f mà agent (Python)
    bỏ → BE nhận dòng agent coi là rỗng (agent từ chối cả bộ) hoặc băm lệch hash."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            return [x.strip() if isinstance(x, str) else x for x in v]
        return v


class BuocVao(_Nghiem):
    id: str
    lam: str


class NutVao(_Nghiem):
    """Một nút lớp sale — khuôn lưu `kich_ban.nut` (spec 2026-10-06 đợt 2 §3). Luật độ dài / danh sách ở `kiem.py`
    (đọc `gioiHan` của agent, không chép tay số)."""

    id: str
    ten: str
    nhom: str
    bat: bool = True
    kenh: list[str] = []
    dau_hieu: list[str]
    lam: list[str]
    tool: list[str] = []
    cam: list[str] = []
    khi_thieu: str = ""
    cau_ket: str = ""
    lan_2: str = ""
    chi_lan_2: bool = False
    nguon: str = ""
    buoc: list[BuocVao] = []


class KichBanOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    trangThai: Literal["mau", "rieng"]
    version: int
    tuTemplate: str | None
    templateVersion: str
    coTemplateMoi: bool
    roleDung: list[str]
    capNhatLuc: datetime | None
    capNhatBoi: str | None


class TemplateOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    templateVersion: str
    nodes: list[dict]
    gioiHan: dict  # luật agent xuất trong playbook.json — FE dựng form theo đây (đợt 3)


class ApDungIn(_Nghiem):
    version: int = Field(ge=0)


class LuuKichBanIn(_Nghiem):
    version: int = Field(ge=0)
    nut: list[NutVao] = Field(max_length=200)  # trần chống payload khổng lồ; luật maxNut ở kiem.py


class RoleDungIn(_Nghiem):
    version: int = Field(ge=0)
    roles: list[str] = Field(max_length=50)


PlaybookOut.model_rebuild()
