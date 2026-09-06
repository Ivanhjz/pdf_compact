#!/usr/bin/env python3
"""
compact_pdf.py — 把"一页一题、大量留白"的PDF压缩成紧凑排版。

原理（完全不依赖OCR/文字识别，纯几何裁剪+重排，公式/图形不会乱码/不会失真）：
  1. 把每一页渲染成图片，用像素分析找到内容所在的行区间（哪些行有墨迹）。
  2. 页面内部如果有"异常大"的空白间隔（比如题目和下方大片留白之间，
     或选项之间人为拉开的大间距），把这段间隔压缩到一个较小的固定值；
     正常的行间距（比如段落内的行距）保持不变，不会被误压缩。
  3. 对内容区域做裁剪时用的是矢量裁剪（PDF clip机制），不是转成图片再裁，
     所以文字、公式、线条依然保持原始的矢量清晰度。
  4. 把处理后的各题依次从上到下摆放到新页面上，排满自动换页。

用法:
    python3 compact_pdf.py input.pdf output.pdf
    python3 compact_pdf.py 输入文件夹/ 输出文件夹/      # 批量处理文件夹内所有PDF

可选参数:
    --dpi 150              检测内容的渲染分辨率
    --gap 14                不同题目之间的垂直间距（pt）
    --margin 36              输出页面的页边距（pt）
    --pagesize a4|letter     输出页面大小（默认a4）
    --white-thresh 248       判定"空白像素"的灰度阈值(0-255，越小越严格)
    --squeeze-threshold 28   页面内部超过多少pt的空白间隔会被压缩（默认28pt）
    --squeeze-target 14      被压缩后的间隔缩小到多少pt（默认14pt）
"""

import argparse
from pathlib import Path

import numpy as np
import pymupdf  # PyMuPDF


PAGE_SIZES = {
    "a4": (595, 842),
    "letter": (612, 792),
}


def get_page_blocks(
    page,
    dpi=150,
    white_thresh=248,
    min_area_px=6,
    squeeze_threshold_pt=28,
    squeeze_target_pt=14,
    outer_pad_pt=3,
):
    """分析一页内容，返回 (blocks, item_width_pt)。
    blocks: 有序列表，每项是 {'clip': fitz.Rect(原页面坐标), 'gap_after_pt': float}
            'gap_after_pt' 是本段与下一段之间、压缩后应使用的间距（最后一段为0）。
    页面完全空白时返回 ([], 0)。
    """
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    scale = 72.0 / dpi

    mask = img < white_thresh
    row_has = mask.any(axis=1)
    col_idx = np.where(mask.any(axis=0))[0]
    if not row_has.any() or col_idx.size == 0:
        return [], 0

    # 整页内容的左右边界（所有行共用，保证左对齐一致、缩放比例一致）
    x0_px, x1_px = col_idx[0], col_idx[-1]
    pad_px = max(1, int(outer_pad_pt / scale))
    x0_px = max(0, x0_px - pad_px)
    x1_px = min(img.shape[1] - 1, x1_px + pad_px)

    # 找出内容行的连续区间(run)
    runs = []
    in_run = False
    for y, v in enumerate(row_has):
        if v and not in_run:
            start = y
            in_run = True
        if not v and in_run:
            runs.append([start, y - 1])
            in_run = False
    if in_run:
        runs.append([start, len(row_has) - 1])

    if (x1_px - x0_px) * (runs[-1][1] - runs[0][0]) < min_area_px:
        return [], 0

    # 顶部/底部各留一点边距
    top_pad_px = max(1, int(outer_pad_pt / scale))
    bot_pad_px = top_pad_px
    runs[0][0] = max(0, runs[0][0] - top_pad_px)
    runs[-1][1] = min(img.shape[0] - 1, runs[-1][1] + bot_pad_px)

    blocks = []
    for i, (ry0, ry1) in enumerate(runs):
        clip = pymupdf.Rect(x0_px * scale, ry0 * scale, x1_px * scale, ry1 * scale)
        if i < len(runs) - 1:
            actual_gap_pt = (runs[i + 1][0] - ry1) * scale
            gap_after = actual_gap_pt if actual_gap_pt <= squeeze_threshold_pt else squeeze_target_pt
        else:
            gap_after = 0.0
        blocks.append({"clip": clip, "gap_after_pt": gap_after})

    item_width_pt = (x1_px - x0_px) * scale
    return blocks, item_width_pt


def compact_pdf(
    input_path,
    output_path,
    dpi=150,
    gap=14,
    margin=36,
    pagesize="a4",
    white_thresh=248,
    squeeze_threshold=28,
    squeeze_target=14,
    max_scale=1.0,
):
    src = pymupdf.open(input_path)
    src_page_count = src.page_count
    page_w, page_h = PAGE_SIZES.get(pagesize, PAGE_SIZES["a4"])
    usable_w = page_w - 2 * margin

    items = []  # (src_page_index, blocks, item_width_pt, item_height_pt)
    skipped = []
    for i, page in enumerate(src):
        blocks, w = get_page_blocks(
            page, dpi=dpi, white_thresh=white_thresh,
            squeeze_threshold_pt=squeeze_threshold, squeeze_target_pt=squeeze_target,
        )
        if not blocks:
            skipped.append(i + 1)
            continue
        h = sum(b["clip"].height for b in blocks) + sum(b["gap_after_pt"] for b in blocks)
        items.append((i, blocks, w, h))

    out = pymupdf.open()
    cur_page = None
    cur_y = margin

    for src_index, blocks, item_w, item_h in items:
        scale = min(usable_w / item_w, max_scale) if max_scale else usable_w / item_w
        dst_h_total = item_h * scale

        if cur_page is None or cur_y + dst_h_total > page_h - margin:
            cur_page = out.new_page(width=page_w, height=page_h)
            cur_y = margin

        y = cur_y
        for b in blocks:
            clip = b["clip"]
            dst_h = clip.height * scale
            dst_w = clip.width * scale
            dst_rect = pymupdf.Rect(margin, y, margin + dst_w, y + dst_h)
            cur_page.show_pdf_page(dst_rect, src, src_index, clip=clip)
            y += dst_h + b["gap_after_pt"] * scale

        cur_y += dst_h_total + gap

    if out.page_count == 0:
        out.new_page(width=page_w, height=page_h)

    out_page_count = out.page_count
    out.save(output_path, garbage=4, deflate=True)
    out.close()
    src.close()

    print(f"输入页数: {src_page_count}")
    print(f"识别出内容的题目数: {len(items)}")
    if skipped:
        print(f"跳过的空白页(原页码): {skipped}")
    print(f"输出页数: {out_page_count}")
    return len(items), skipped


def main():
    ap = argparse.ArgumentParser(description="将一页一题、大量留白的PDF压缩为紧凑排版")
    ap.add_argument("input", help="输入PDF文件路径，或包含多个PDF的文件夹路径（批量模式）")
    ap.add_argument("output", help="输出PDF文件路径，或输出文件夹路径（批量模式）")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--gap", type=float, default=14)
    ap.add_argument("--margin", type=float, default=36)
    ap.add_argument("--pagesize", choices=["a4", "letter"], default="a4")
    ap.add_argument("--white-thresh", type=int, default=248)
    ap.add_argument("--squeeze-threshold", type=float, default=28)
    ap.add_argument("--squeeze-target", type=float, default=14)
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    kwargs = dict(
        dpi=args.dpi, gap=args.gap, margin=args.margin,
        pagesize=args.pagesize, white_thresh=args.white_thresh,
        squeeze_threshold=args.squeeze_threshold, squeeze_target=args.squeeze_target,
    )

    if in_path.is_dir():
        out_path.mkdir(parents=True, exist_ok=True)
        pdf_files = sorted(in_path.glob("*.pdf"))
        if not pdf_files:
            print(f"文件夹 {in_path} 下没有找到PDF文件")
            return
        print(f"共找到 {len(pdf_files)} 个PDF，开始批量处理...")
        for f in pdf_files:
            out_file = out_path / f.name
            print(f"\n处理: {f.name}")
            compact_pdf(str(f), str(out_file), **kwargs)
    else:
        compact_pdf(str(in_path), str(out_path), **kwargs)


if __name__ == "__main__":
    main()
