"""VOC 数据集准备：解压原始 zip → 转成 YOLO 格式。

为什么不直接用 ultralytics 自带的自动转换：
    1. 它内部的 safe_download 走 github.com，在本机代理环境下会报
       SSLCertVerificationError（这个坑已经在 DEVLOG 里记过一笔）
    2. 自动转换的 train/val 划分是它写死的，我讲不清楚也不敢改
    自己写一遍之后，划分规则、跳过规则全在我手里，出问题能一行行调。

产出目录（相对 data/VOC/）：
    images/train/  ← VOC2007 trainval(5011) + VOC2012 trainval(11540) = 16551
    images/val/    ← VOC2007 test(4952)
    labels/train/  labels/val/

用法：
    python training/prepare_dataset.py            # 解压 + 转换
    python training/prepare_dataset.py --skip-extract   # 已解压，只转换
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOC_DIR = ROOT / "data" / "VOC"
ZIP_DIR = VOC_DIR / "images"          # 下载时先落在 images/ 下
DEVKIT = VOC_DIR / "VOCdevkit"

# ultralytics 的 VOC.yaml 用的是这套类别顺序，不能改顺序，改了标签就全错
CLASSES = [
    "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat",
    "chair", "cow", "diningtable", "dog", "horse", "motorbike", "person",
    "pottedplant", "sheep", "sofa", "train", "tvmonitor",
]
CLASS_INDEX = {name: i for i, name in enumerate(CLASSES)}

# (年份, ImageSets 里的集合名, 输出到哪个 split)
SPLITS = [
    ("VOC2007", "trainval", "train"),
    ("VOC2012", "trainval", "train"),
    ("VOC2007", "test", "val"),
]

ZIPS = [
    "VOCtrainval_06-Nov-2007.zip",
    "VOCtest_06-Nov-2007.zip",
    "VOCtrainval_11-May-2012.zip",
]


def extract() -> None:
    """解压三个 zip。已解出 VOCdevkit 就跳过，避免重复劳动。"""
    if DEVKIT.is_dir():
        print(f"[跳过] {DEVKIT} 已存在")
        return

    for name in ZIPS:
        path = ZIP_DIR / name
        if not path.is_file():
            print(f"[错误] 缺少 {path}，先跑下载命令", file=sys.stderr)
            sys.exit(1)
        print(f"[解压] {name} ({path.stat().st_size / 1e6:.0f} MB) ...")
        with zipfile.ZipFile(path) as zf:
            zf.extractall(VOC_DIR)
        print(f"[完成] {name}")


def _parse_annotation(xml_path: Path) -> tuple[int, int, list[tuple[int, float, float, float, float]]]:
    """解析一个 VOC XML，返回 (宽, 高, [(类别id, cx, cy, w, h), ...])。

    difficult=1 的目标按 VOC 官方评估惯例跳过——那些是严重遮挡、
    人眼都难辨的框，拿来训练只会教坏模型。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    size = root.find("size")
    if size is None:
        raise ValueError(f"{xml_path} 缺少 size 字段")
    img_w = int(size.findtext("width", "0"))
    img_h = int(size.findtext("height", "0"))
    if img_w <= 0 or img_h <= 0:
        raise ValueError(f"{xml_path} 尺寸非法: {img_w}x{img_h}")

    objects: list[tuple[int, float, float, float, float]] = []
    for obj in root.findall("object"):
        name = obj.findtext("name", "").strip()
        if name not in CLASS_INDEX:
            continue
        if obj.findtext("difficult", "0").strip() == "1":
            continue

        box = obj.find("bndbox")
        if box is None:
            continue
        try:
            xmin = float(box.findtext("xmin", "0"))
            ymin = float(box.findtext("ymin", "0"))
            xmax = float(box.findtext("xmax", "0"))
            ymax = float(box.findtext("ymax", "0"))
        except ValueError:
            continue

        # 夹到图像范围内，VOC 里偶尔有越界标注
        xmin, xmax = max(0.0, xmin), min(float(img_w), xmax)
        ymin, ymax = max(0.0, ymin), min(float(img_h), ymax)
        if xmax <= xmin or ymax <= ymin:
            continue

        # VOC 用 xmin/ymin/xmax/ymax，YOLO 用归一化的中心点+宽高
        cx = ((xmin + xmax) / 2) / img_w
        cy = ((ymin + ymax) / 2) / img_h
        bw = (xmax - xmin) / img_w
        bh = (ymax - ymin) / img_h

        # 数值合法性兜底，脏数据不能污染训练集
        if not all(0.0 <= v <= 1.0 for v in (cx, cy, bw, bh)):
            continue
        objects.append((CLASS_INDEX[name], cx, cy, bw, bh))

    return img_w, img_h, objects


def convert_split(year: str, image_set: str, out_split: str) -> tuple[int, int]:
    """把一个 (年份, 集合) 转成 YOLO 格式的 images/ labels/。

    图片用**硬链接**，复制不了就退成 copy。
    16551 张原图约 2GB，硬链接能省掉一倍磁盘和几分钟 IO。
    """
    src_root = DEVKIT / year
    list_file = src_root / "ImageSets" / "Main" / f"{image_set}.txt"
    if not list_file.is_file():
        print(f"[警告] 找不到 {list_file}，跳过", file=sys.stderr)
        return 0, 0

    names = [n.strip() for n in list_file.read_text().splitlines() if n.strip()]
    img_out = VOC_DIR / "images" / out_split
    lbl_out = VOC_DIR / "labels" / out_split
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    for stem in names:
        src_img = src_root / "JPEGImages" / f"{stem}.jpg"
        src_xml = src_root / "Annotations" / f"{stem}.xml"
        if not src_img.is_file() or not src_xml.is_file():
            skipped += 1
            continue

        try:
            _, _, objects = _parse_annotation(src_xml)
        except Exception as exc:  # noqa: BLE001
            print(f"[警告] 解析失败 {src_xml.name}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        dst_img = img_out / f"{year}_{stem}.jpg"  # 加年份前缀，07/12 有重名
        if not dst_img.exists():
            try:
                dst_img.hardlink_to(src_img)
            except OSError:
                shutil.copy2(src_img, dst_img)

        lines = [f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}" for cid, cx, cy, bw, bh in objects]
        (lbl_out / f"{year}_{stem}.txt").write_text("\n".join(lines), encoding="utf-8")
        written += 1

    print(f"[转换] {year}/{image_set} -> {out_split}: {written} 张，跳过 {skipped} 张")
    return written, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="准备 VOC 数据集")
    parser.add_argument("--skip-extract", action="store_true", help="跳过解压，只做转换")
    args = parser.parse_args()

    if not args.skip_extract:
        extract()

    total = 0
    for year, image_set, out_split in SPLITS:
        n, _ = convert_split(year, image_set, out_split)
        total += n

    # 统计一下，确认划分对得上官方数字
    for split in ("train", "val"):
        n_img = len(list((VOC_DIR / "images" / split).glob("*.jpg")))
        n_lbl = len(list((VOC_DIR / "labels" / split).glob("*.txt")))
        print(f"[统计] {split}: {n_img} 图 / {n_lbl} 标签")

    print(f"\n完成，共 {total} 张。数据集在 {VOC_DIR}")


if __name__ == "__main__":
    main()
