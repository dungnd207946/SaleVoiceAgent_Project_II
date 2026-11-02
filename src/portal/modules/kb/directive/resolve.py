"""Row + VerticalSpec → TextDirective. Hàm thuần, test không cần DB."""

import unicodedata

from portal.modules.kb import settings
from portal.modules.kb.contracts import ChildBlockSpec, ChunkSpec, EntitySpec, TextDirective, VerticalSpec


def _khong_dau(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _tieu_de(ten: str, nhan: str) -> str:
    """«Phân khu MIYABI»; tên đã mở đầu bằng nhãn («Tòa P1») thì giữ nguyên."""
    return ten if _khong_dau(ten).startswith(_khong_dau(nhan)) else f"{nhan} {ten}"


def _gia_tri(row: dict, col: str, block: ChildBlockSpec) -> str:
    value = row.get(col)
    if value is None or not str(value).strip():
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return block.value_labels.get(col, {}).get(str(value), str(value))


def _than(row: dict, block: ChildBlockSpec) -> list[str]:
    """Dòng tóm tắt (trường có nhãn), rồi mỗi trường `line_fields` một dòng, rồi đoạn văn không nhãn."""
    gon = [
        f"{block.field_labels[c]}: {v}"
        for c in block.fields
        if c in block.field_labels and c not in block.line_fields and (v := _gia_tri(row, c, block))
    ]
    dong = [" · ".join(gon)] if gon else []
    dong += [f"{block.field_labels[c]}: {v}" for c in block.line_fields if (v := _gia_tri(row, c, block))]
    dong += [v for c in block.fields if c not in block.field_labels and (v := _gia_tri(row, c, block))]
    return dong


def _ten(row: dict, block: ChildBlockSpec) -> str:
    return str(row.get(block.name_col) or "").strip()


def _danh_sach(rows: list[dict], block: ChildBlockSpec) -> str:
    ten = list(dict.fromkeys(t for r in rows if (t := _ten(r, block))))
    return f"Gồm {len(ten)} {block.subsection.lower()}: {', '.join(ten)}." if ten else ""


def child_block_text(rows: list[dict], block: ChildBlockSpec, orphans: list[dict] | None = None) -> str:
    """Bảng con → `## <section>` › `### <subsection>` (dòng «Gồm N …»), mỗi hàng có thông tin một
    mục `####`, cấp con (`block.child`) thành `#####` ngay dưới hàng cha.

    Sâu hai cấp là chủ ý: chunker cho các mục cùng cha gộp với nhau, nên khối này phải nằm dưới
    `###` thì mới không bị gộp vào đuôi các mục trường của dự án. Hàng chỉ có tên KHÔNG thành
    tiêu đề riêng (chunker bỏ tiêu đề không có thân) — tên luôn nằm ở dòng «Gồm N …». Tiêu đề toà
    mang cả tên phân khu vì embed chỉ gắn cấp tiêu đề cuối vào đoạn.
    """
    orphans = orphans or []
    tong = _danh_sach(rows, block)
    if not tong and not orphans:
        return ""
    out = [f"## {block.section}", f"### {block.subsection}"]
    if tong:
        out.append(tong)
    seen: set[str] = set()
    for row in rows:
        ten = _ten(row, block)
        if not ten:
            continue
        con = row.get("children") or []
        than = _than(row, block)
        if block.child is not None and (ds := _danh_sach(con, block.child)):
            than.append(ds)
        if not than:
            continue
        muc = [f"#### {_tieu_de(ten, block.subsection)}", *than]
        if block.child is not None:
            for c in con:
                if (tc := _than(c, block.child)) and (cten := _ten(c, block.child)):
                    tieu_de = f"{_tieu_de(cten, block.child.subsection)} — {block.subsection.lower()} {ten}"
                    muc += ["", f"##### {tieu_de}", *tc]
        khoi = "\n".join(muc)
        if khoi in seen:
            continue
        seen.add(khoi)
        out += ["", khoi]
    if orphans and block.child is not None:
        out += ["", f"#### {block.orphan_heading}", _danh_sach(orphans, block.child)]
        for c in orphans:
            if (tc := _than(c, block.child)) and (cten := _ten(c, block.child)):
                out += ["", f"##### {_tieu_de(cten, block.child.subsection)}", *tc]
    return "\n".join(out)


def build_text(row: dict, spec: EntitySpec) -> str:
    """Ghép field thành MARKDOWN CÓ TIÊU ĐỀ, mỗi field một `##`.

    Thứ tự cố định vì content_hash tính trên chuỗi này. Bỏ field rỗng nhưng giữ số 0.

    VÌ SAO PHẢI CÓ TIÊU ĐỀ (2026-08-14): chunker cắt theo cấp tiêu đề. Ghép field thành
    `khu vực: X\\nchủ đầu tư: Y` như trước cho ra một khối phẳng không có chỗ nào để bám,
    nên chunker chỉ còn cách cắt theo độ dài — đúng thứ vừa bỏ. Với `##` mỗi field, một dự
    án ngắn vẫn ra một chunk (11 quick-fact ngắn được gói chung, xem `chunker._goi_cung_cha`)
    còn dự án có tổng quan dài thì tổng quan tách ra riêng và mang đúng `section_path`.

    `noi_dung_da_markdown` (documents.body) đi đường khác: chữ bóc từ docx/xlsx đã có `#`
    của chính nó, bọc thêm một cấp sẽ làm tiêu đề của tài liệu thành anh em với tiêu đề ta
    chèn. Nối thẳng, không thêm gì.
    """
    phan: list[str] = []
    for name in spec.fields:
        value = row.get(name)
        if name in spec.formatters and value is not None:
            value = spec.formatters[name](value)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if spec.noi_dung_da_markdown:
            phan.append(str(value))
        else:
            phan.append(f"## {spec.field_labels.get(name, name)}\n{value}")
    if spec.child_block is not None:
        khoi = child_block_text(list(row.get("children") or []), spec.child_block, row.get("orphan_children"))
        if khoi:
            phan.append(khoi)
    return "\n\n".join(phan)


def build_section(anchor_name: str, row: dict, spec: EntitySpec) -> str:
    """Đuôi breadcrumb — tên hàng (tên phân khu, tiêu đề tài liệu) nếu spec khai cột đó."""
    if spec.section_col is None:
        return anchor_name
    tail = row.get(spec.section_col) or ""
    return f"{anchor_name} > {tail}" if tail else anchor_name


def chunk_root(row: dict, spec: EntitySpec) -> tuple[str, ...]:
    """Đường dẫn tổ tiên KHÔNG có mặt trong text — xem `chunker.split(root=...)`.

    Tên phân khu và tiêu đề tài liệu vào đây thay vì prepend một dòng `#` vào nội dung:
    với tài liệu thì nội dung đã mang `#` của chính nó, và với phân khu thì thêm một dòng
    tiêu đề vào text là thêm một dòng phải nhúng ở MỌI chunk của nó.
    """
    if spec.section_col is None:
        return ()
    tail = row.get(spec.section_col) or ""
    return (str(tail),) if str(tail).strip() else ()


def _ten_hien(row: dict) -> str:
    """Tên tệp hiện cho khách: cột thật nếu có, không thì tiêu đề đã bỏ tiền tố loại."""
    from portal.modules.kb.contracts import split_title

    ten = str(row.get("file_name") or "")
    if ten:
        return ten
    tieu_de = str(row.get("title") or "")
    return split_title(tieu_de)[1] if tieu_de else ""


def resolve_text(
    *,
    workspace_slug: str,
    row: dict,
    anchor_name: str,
    spec: EntitySpec,
    source_file_url: str | None = None,
    extract_profile: str | None = None,
) -> TextDirective:
    return TextDirective(
        workspace_slug=workspace_slug,
        record_id=int(row["id"]),
        doc_type=spec.doc_type_from(row) if spec.doc_type_from else spec.doc_type,
        anchor_code=str(row[spec.anchor_col]),
        anchor_name=anchor_name,
        section=build_section(anchor_name, row, spec),
        text=build_text(row, spec),
        chunk=ChunkSpec(
            max_chars=settings.CHUNK_MAX_CHARS,
            overlap=settings.CHUNK_OVERLAP,
            min_chars=settings.CHUNK_MIN_CHARS,
        ),
        chunk_root=chunk_root(row, spec),
        source_file_url=source_file_url,
        extract_profile=extract_profile,
        entity=spec.table,
        status=str(row.get("status") or ""),
        anchor_status=str(row.get("anchor_status") or ""),
        updated_at=row.get("updated_at"),
        file_url=str(row.get("file_url") or "") or None,
        file_name=_ten_hien(row) or None,
        thumb_url=str(row.get("thumb_url") or "") or None,
    )


def source_for(vertical: VerticalSpec, entity: str, doc_type: str = "") -> EntitySpec:
    """Tra spec theo tên bảng; `doc_type` chỉ dùng để phân giải khi một bảng khai
    nhiều spec. Hôm nay `real_estate` không còn trường hợp đó (`projects` đã gộp về
    một spec), nên mọi caller gọi được với `doc_type=""`.

    ⚠ `doc_type` ở đây là ĐỊNH DANH SPEC (`tai_lieu`), KHÔNG phải doc_type của point:
    với `documents`, loại thật đến từ `spec.doc_type_from(row)`.
    """
    candidates = [s for s in vertical.embed_sources if s.table == entity]
    if not candidates:
        raise ValueError(f"{entity!r} không phải nguồn embed của {vertical.key!r}")
    if len(candidates) == 1:
        return candidates[0]
    for s in candidates:
        if s.doc_type == doc_type:
            return s
    raise ValueError(f"{entity!r} có {len(candidates)} nguồn — phải nói rõ doc_type, nhận {doc_type!r}")
