# Standalone STT service — sherpa-onnx Zipformer (CPU). Self-contained: no
# dependency on any agent image. Model is bind-mounted (see compose).
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    sherpa-onnx \
    huggingface_hub \
    numpy \
    "websockets>=12"

COPY stt_server.py /app/stt_server.py
# bpe.vocab của santa-stt (export từ bpe.model của lần finetune) — cho hotword
# dạng word-level. Server tự đối chiếu số dòng với tokens.txt lúc boot; model
# khác vocab thì tính năng word-level tự tắt (xem _bpe_vocab_for).
COPY bpe.vocab /app/bpe.vocab
# Danh sách hotword nền (brand NobleX) đi kèm image — KHÔNG để trong /models:
# thư mục đó do container ghi (root), runner CI pull vào sẽ Permission denied.
# Bật bằng STT_HOTWORDS_FILE=/app/hotwords.txt; muốn sửa nóng không rebuild thì
# bind-mount file khác và trỏ env vào đó.
COPY hotwords.txt /app/hotwords.txt

EXPOSE 8012
ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/stt_server.py"]
