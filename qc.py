#!/usr/bin/env python3
"""
product-image-qc — AI 产品图批量质检（本地规则版）

把一个文件夹里的产品图批量过一遍基础质检，先筛掉明显翻车的，
再把时间花在人工审图 / AI 语义检查上。

检查项（全部本地运行，只依赖 Pillow）：
  1. 文件可读性 / 格式
  2. 分辨率下限（默认短边 >= 800px）
  3. 宽高比（可选：--ratio 1:1 / 3:4 / 9:16 / 16:9，或 --ratio any 关闭）
  4. 清晰度（边缘强度估算，过低判 WARN）
  5. 曝光（平均亮度过暗 / 过曝判 WARN）
  6. 背景干净程度（四角颜色一致性估算，棚拍图背景不匀判 WARN）
  7. 近似重复图（8x8 平均哈希，汉明距离 <= 5 判为重复组）

输出：report.csv（逐图明细）+ report.md（汇总）。结论分 PASS / WARN / FAIL。

注意：本地规则查不了「标签文字是否完整、Logo 是否变形」这类语义问题——
那是下一层（人工审图或 AI 打分接口，见 README 的路线图）。本工具的定位是
「先筛翻车，再人工审」的第一道筛子。

用法：
  python3 qc.py ./images
  python3 qc.py ./images --ratio 3:4 --min-side 1000 --out ./qc-out
"""

import argparse
import csv
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_ratio(text):
    if text is None or text.lower() == "any":
        return None
    w, h = text.split(":")
    return float(w) / float(h)


def ahash(img, size=8):
    """8x8 average hash -> 64-bit int"""
    g = img.convert("L").resize((size, size), Image.LANCZOS)
    px = list(g.getdata())
    avg = sum(px) / len(px)
    bits = 0
    for i, p in enumerate(px):
        if p > avg:
            bits |= 1 << i
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def corner_deviation(img):
    """四角小块的平均色最大偏差：粗估背景是否均匀干净。"""
    w, h = img.size
    pw, ph = max(4, w // 20), max(4, h // 20)
    corners = [
        (0, 0, pw, ph),
        (w - pw, 0, w, ph),
        (0, h - ph, pw, h),
     	(w - pw, h - ph, w, h),
    ]
    means = []
    for box in corners:
        patch = img.crop(box).convert("RGB")
        stat = ImageStat.Stat(patch)
        means.append(stat.mean)
    dev = 0.0
    for i in range(len(means)):
        for j in range(i + 1, len(means)):
            d = max(abs(means[i][c] - means[j][c]) for c in range(3))
            dev = max(dev, d)
    return dev


def check_image(path, min_side, target_ratio, ratio_tol=0.03):
    row = {
        "file": str(path),
        "format": "",
        "width": "",
        "height": "",
        "size_kb": round(path.stat().st_size / 1024, 1),
        "sharpness": "",
        "brightness": "",
        "bg_deviation": "",
        "issues": [],
        "verdict": "PASS",
    }
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:  # unreadable / corrupt
        row["issues"].append(f"unreadable: {e}")
        row["verdict"] = "FAIL"
        return row, None

    row["format"] = img.format or path.suffix.lstrip(".").upper()
    row["width"], row["height"] = img.size
    short_side = min(img.size)

    if short_side < min_side:
        row["issues"].append(f"resolution: short side {short_side}px < {min_side}px")
        row["verdict"] = "FAIL"

    if target_ratio is not None:
        actual = img.size[0] / img.size[1]
        if abs(actual - target_ratio) / target_ratio > ratio_tol:
            row["issues"].append(
                f"ratio: {img.size[0]}x{img.size[1]} != target {target_ratio:.3f} (tol {ratio_tol:.0%})"
            )
            if row["verdict"] != "FAIL":
                row["verdict"] = "WARN"

    g = img.convert("L")
    # sharpness: mean edge strength on a downscaled copy (fast + stable)
    small = g.resize((min(512, g.size[0]), min(512, g.size[1])), Image.LANCZOS) \
        if max(g.size) > 512 else g
    edges = small.filter(ImageFilter.FIND_EDGES)
    sharp = ImageStat.Stat(edges).mean[0]
    row["sharpness"] = round(sharp, 2)
    if sharp < 4.0:
        row["issues"].append(f"sharpness low: {sharp:.2f} (possible blur)")
        if row["verdict"] == "PASS":
            row["verdict"] = "WARN"

    bright = ImageStat.Stat(g).mean[0]
    row["brightness"] = round(bright, 1)
    if bright < 40:
        row["issues"].append(f"too dark: mean brightness {bright:.0f}")
        if row["verdict"] == "PASS":
            row["verdict"] = "WARN"
    elif bright > 235:
        row["issues"].append(f"overexposed: mean brightness {bright:.0f}")
        if row["verdict"] == "PASS":
            row["verdict"] = "WARN"

    dev = corner_deviation(img)
    row["bg_deviation"] = round(dev, 1)
    if dev > 45:
        row["issues"].append(f"background uneven: corner deviation {dev:.0f}")
        if row["verdict"] == "PASS":
            row["verdict"] = "WARN"

    return row, ahash(img)


def main():
    ap = argparse.ArgumentParser(description="AI 产品图批量质检（本地规则版）")
    ap.add_argument("folder", help="要检查的图片文件夹（递归）")
    ap.add_argument("--min-side", type=int, default=800, help="短边分辨率下限 px（默认 800）")
    ap.add_argument("--ratio", default="any",
                    help="目标宽高比，如 1:1 / 3:4 / 9:16 / 16:9；any=不查（默认）")
    ap.add_argument("--out", default="qc-out", help="报告输出目录（默认 ./qc-out）")
    args = ap.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"error: {folder} is not a folder", file=sys.stderr)
        return 1

    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUPPORTED)
    if not files:
        print(f"no images found in {folder}", file=sys.stderr)
        return 1

    target_ratio = parse_ratio(args.ratio)
    rows, hashes = [], {}
    for p in files:
        row, h = check_image(p, args.min_side, target_ratio)
        rows.append(row)
        if h is not None:
            hashes[p] = h

    # near-duplicate detection
    plist = list(hashes.keys())
    for i in range(len(plist)):
        for j in range(i + 1, len(plist)):
            if hamming(hashes[plist[i]], hashes[plist[j]]) <= 5:
                for p in (plist[i], plist[j]):
                    r = next(r for r in rows if r["file"] == str(p))
                    note = f"near-duplicate of {plist[j].name if p == plist[i] else plist[i].name}"
                    if note not in r["issues"]:
                        r["issues"].append(note)
                    if r["verdict"] == "PASS":
                        r["verdict"] = "WARN"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "format", "width", "height", "size_kb", "sharpness",
                    "brightness", "bg_deviation", "verdict", "issues"])
        for r in rows:
            w.writerow([r["file"], r["format"], r["width"], r["height"], r["size_kb"],
                        r["sharpness"], r["brightness"], r["bg_deviation"],
                        r["verdict"], "; ".join(r["issues"])])

    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in rows:
        counts[r["verdict"]] += 1

    md_path = out / "report.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# 产品图批量质检报告\n\n")
        f.write(f"- 检查总数：{len(rows)}\n")
        f.write(f"- PASS：{counts['PASS']} ｜ WARN：{counts['WARN']} ｜ FAIL：{counts['FAIL']}\n\n")
        for verdict in ("FAIL", "WARN", "PASS"):
            group = [r for r in rows if r["verdict"] == verdict]
            if not group:
                continue
            f.write(f"## {verdict}（{len(group)}）\n\n")
            for r in group:
                name = Path(r["file"]).name
                issues = "；".join(r["issues"]) if r["issues"] else "—"
                f.write(f"- `{name}` — {issues}\n")
            f.write("\n")
        f.write("> 本报告由本地规则生成：查不了标签文字/Logo 等语义问题，WARN/FAIL 之后仍需人工审图。\n")

    print(f"checked {len(rows)} images: PASS {counts['PASS']} / WARN {counts['WARN']} / FAIL {counts['FAIL']}")
    print(f"reports -> {csv_path} , {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
