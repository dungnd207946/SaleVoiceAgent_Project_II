# Embed service — nhà máy vector: e5-large (dense) + BM25 sparse + SigLIP2
# image/text tower. Stateless. GPU-enabled for Ampere (RTX 3070 Ti) — see
# docker-compose.yml's `gpu` profile.
#
# Build context là REPO ROOT (không phải ./embed) vì image cần `pyproject.toml`:
#   docker build -f embed/Dockerfile .
FROM python:3.11-slim

WORKDIR /app

# No CPU-only torch index here — default PyPI index ships a CUDA-enabled wheel
# on Linux (~2.5GB). Host needs an NVIDIA driver + nvidia-container-toolkit for
# the container to see the GPU at runtime.

# Dep TRƯỚC source: layer này chỉ vỡ khi pyproject.toml đổi, nên sửa code không kéo lại
# transformers/sentence-transformers. Stub package để `packages.find` có thứ để tìm.
COPY pyproject.toml ./
RUN mkdir -p embed && touch embed/__init__.py \
    && pip install --no-cache-dir setuptools ".[embed]"

COPY embed/ ./embed/

# Ghi bản thật lên stub. `--no-build-isolation` là chỗ quan trọng: mặc định PEP 517 dựng
# venv tạm và TẢI setuptools từ PyPI ở MỌI lần build, kể cả khi dep đã cache — riêng nó
# tốn ~30s mỗi lượt deploy. setuptools đã cài ở layer trên.
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

EXPOSE 8013
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "embed.server:app", "--host", "0.0.0.0", "--port", "8013"]
