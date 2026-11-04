"""Kho tri thức (Qdrant) cho agent `kb_search`.

Hai luồng vào hai collection `<KB_COLLECTION_PREFIX>_documents` / `_media`:
  A. «Tài liệu tra cứu» — upload tệp → bóc chữ → chunk → nhúng (`router.py`, job `kb_file_index`).
  B. Dữ liệu DB — trigger `shop.kb_enqueue` tự xếp `kb_index`/`kb_delete`; `records.py` dựng
     văn bản (KHÔNG giá, KHÔNG tồn kho), `service.py` nhúng, sổ `shop.kb_index_state`.

Đường ra mạng: embed service (`KB_EMBED_URL`), Qdrant, kho tệp S3 — nối dây ở `deps.py`.
"""
