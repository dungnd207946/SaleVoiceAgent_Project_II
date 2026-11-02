"""Ingest tri thức: làm giàu nội dung rồi đánh chỉ mục lên Qdrant.

Hai chặng. `kb_enrich` sinh caption ảnh (VLM) · mô tả video (Gemini) · bóc chữ tệp
(Docling) rồi ghi vào ĐÚNG CỘT người dùng sửa — Aurora là nguồn sự thật. `kb_index`
chạy khi người dùng bấm "Đồng bộ tri thức": chunk → embed → Qdrant.

Đường ra DUY NHẤT của module là embed service (`KB_EMBED_URL`). Chunk, point-id, payload,
prompt đều nằm trong repo này — trước 2026-08-10 chúng thuộc một `rag_service` bên
santa-models chưa bao giờ tồn tại.
"""
