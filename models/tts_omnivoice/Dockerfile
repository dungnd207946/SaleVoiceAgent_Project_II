# OmniVoice-Luna-vi service — CC-BY-NC-4.0, see tts_omnivoice/README.md before
# deploying this anywhere commercial.
#
# Build context is this directory:
#   docker build tts_omnivoice
#
# Uses a plain slim base (not nvidia/cuda:*-devel) — omnivoice's own install
# instructions are a plain `pip install`, no nvcc/compiled-CUDA-kernel step.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt

COPY tts_server.py ./

EXPOSE 8016
ENV PYTHONUNBUFFERED=1

CMD ["python3", "tts_server.py"]
