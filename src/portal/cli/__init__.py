"""Lệnh một-lần chạy trong image production. KHÔNG phải `scripts/`.

VÌ SAO KHÔNG NẰM Ở `scripts/`: Dockerfile không COPY `scripts/` vào image — tầng
runtime chỉ có venv, và `portal` được cài thành wheel (`--no-editable`). Một lệnh
devops phải chạy trên production BUỘC phải sống trong package, không thì
`python -m` không tìm thấy nó.

Ranh giới: `scripts/` là dev — seed dữ liệu mẫu, agent giả, sinh contract; mọi
thứ ở đó chạy trên máy dev với `uv run`. `portal/cli/` là những lệnh có mặt trong
image và chạy được trên Aurora.
"""
