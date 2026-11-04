"""Chia dataset thành train / dev / test, phân tầng theo category.

Chỉ lấy các câu đã qua đóng gói (có trong dataset/metadata.csv). Mỗi category góp
vào dev và test theo tỉ lệ số câu của nó, tối thiểu MIN_PER_CAT câu, để nhóm ít câu
không bị sót. Cố định seed nên chạy lại ra đúng cách chia cũ.

    python3 split_dataset.py                    # dev 80, test 100
    python3 split_dataset.py --dev 80 --test 150

Đầu ra: dataset/splits/omnivoice_{train,dev,test}.jsonl + split_summary.tsv
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_PER_CAT = 2


def allocate(sizes: dict[str, int], total: int, floor: int) -> dict[str, int]:
    """Chia `total` suất cho các category theo tỉ lệ, mỗi nhóm ít nhất `floor`."""
    alloc = {c: min(floor, n) for c, n in sizes.items()}
    rest = total - sum(alloc.values())
    pool = sum(sizes.values())
    quota = {c: rest * n / pool for c, n in sizes.items()}
    for c in sizes:
        alloc[c] += int(quota[c])
    left = total - sum(alloc.values())
    for c in sorted(sizes, key=lambda c: quota[c] - int(quota[c]), reverse=True)[:left]:
        alloc[c] += 1
    return alloc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=HERE / "dataset")
    ap.add_argument("--texts", type=Path, default=HERE / "texts.jsonl")
    ap.add_argument("--dev", type=int, default=80)
    ap.add_argument("--test", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    cat = {}
    for line in args.texts.open(encoding="utf-8"):
        d = json.loads(line)
        cat[d["id"]] = d.get("category", "khac")

    by_cat: dict[str, list[dict]] = defaultdict(list)
    lines = (args.dataset / "metadata.csv").read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        file_name, text, _speaker = line.split("|")
        uid = file_name.removesuffix(".wav")
        by_cat[cat[uid]].append({
            "id": uid,
            "audio_path": str(args.dataset / "raw_audio" / file_name),
            "text": text,
            "language_id": "vi",
        })

    rng = random.Random(args.seed)
    sizes = {c: len(v) for c, v in sorted(by_cat.items())}
    n_test = allocate(sizes, args.test, MIN_PER_CAT)
    n_dev = allocate({c: sizes[c] - n_test[c] for c in sizes}, args.dev, MIN_PER_CAT)

    splits: dict[str, list[dict]] = {"train": [], "dev": [], "test": []}
    rows = []
    for c in sorted(by_cat):
        items = by_cat[c]
        rng.shuffle(items)
        t, d = n_test[c], n_dev[c]
        splits["test"] += items[:t]
        splits["dev"] += items[t:t + d]
        splits["train"] += items[t + d:]
        rows.append(f"{c}\t{len(items)}\t{len(items) - t - d}\t{d}\t{t}")

    out = args.dataset / "splits"
    out.mkdir(exist_ok=True)
    for name, items in splits.items():
        rng.shuffle(items)
        with (out / f"omnivoice_{name}.jsonl").open("w", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    (out / "split_summary.tsv").write_text(
        "category\ttong\ttrain\tdev\ttest\n" + "\n".join(rows) + "\n", encoding="utf-8")

    ids = [set(x["id"] for x in v) for v in splits.values()]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2]), "trùng id giữa các tập"
    print(" ".join(f"{k}={len(v)}" for k, v in splits.items()), "->", out)


if __name__ == "__main__":
    main()
