#!/usr/bin/env python3
"""
compact_pdf_gui.py — 带图形界面的PDF压缩工具，可用 PyInstaller 打包成
Windows 的 .exe 或 Mac 的 .app，双击即可运行，使用者无需安装 Python 或任何库。

使用方法（开发者本机运行/调试）:
    python3 compact_pdf_gui.py

打包方法见项目 README 里的"打包成桌面程序"部分。
"""

import os
import sys
import threading
import traceback
from pathlib import Path

import numpy as np
import pymupdf  # PyMuPDF

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


PAGE_SIZES = {
    "a4": (595, 842),
    "letter": (612, 792),
}


# ---------------------------------------------------------------------------
# 核心压缩逻辑（与 compact_pdf.py 相同，未做任何修改）
# ---------------------------------------------------------------------------

def get_page_blocks(
    page,
    dpi=150,
    white_thresh=248,
    min_area_px=6,
    squeeze_threshold_pt=28,
    squeeze_target_pt=14,
    outer_pad_pt=3,
):
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    scale = 72.0 / dpi

    mask = img < white_thresh
    row_has = mask.any(axis=1)
    col_idx = np.where(mask.any(axis=0))[0]
    if not row_has.any() or col_idx.size == 0:
        return [], 0

    x0_px, x1_px = col_idx[0], col_idx[-1]
    pad_px = max(1, int(outer_pad_pt / scale))
    x0_px = max(0, x0_px - pad_px)
    x1_px = min(img.shape[1] - 1, x1_px + pad_px)

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
    log=print,
):
    src = pymupdf.open(input_path)
    src_page_count = src.page_count
    page_w, page_h = PAGE_SIZES.get(pagesize, PAGE_SIZES["a4"])
    usable_w = page_w - 2 * margin

    items = []
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

    log(f"输入页数: {src_page_count}")
    log(f"识别出内容的题目数: {len(items)}")
    if skipped:
        log(f"跳过的空白页(原页码): {skipped}")
    log(f"输出页数: {out_page_count}")
    return len(items), skipped


# ---------------------------------------------------------------------------
# 图形界面
# ---------------------------------------------------------------------------

class CompactPdfApp:
    def __init__(self, root):
        self.root = root
        root.title("PDF 紧凑排版工具")
        root.geometry("560x420")
        root.resizable(False, False)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.mode = tk.StringVar(value="file")  # file 或 folder

        pad = {"padx": 12, "pady": 6}

        # 模式选择
        mode_frame = tk.Frame(root)
        mode_frame.pack(fill="x", **pad)
        tk.Label(mode_frame, text="处理模式：").pack(side="left")
        tk.Radiobutton(mode_frame, text="单个文件", variable=self.mode, value="file",
                        command=self.reset_paths).pack(side="left")
        tk.Radiobutton(mode_frame, text="整个文件夹（批量）", variable=self.mode, value="folder",
                        command=self.reset_paths).pack(side="left")

        # 输入选择
        in_frame = tk.Frame(root)
        in_frame.pack(fill="x", **pad)
        tk.Label(in_frame, text="输入：").pack(side="left")
        tk.Entry(in_frame, textvariable=self.input_path, width=45).pack(side="left", padx=6)
        tk.Button(in_frame, text="选择...", command=self.choose_input).pack(side="left")

        # 输出选择
        out_frame = tk.Frame(root)
        out_frame.pack(fill="x", **pad)
        tk.Label(out_frame, text="输出：").pack(side="left")
        tk.Entry(out_frame, textvariable=self.output_path, width=45).pack(side="left", padx=6)
        tk.Button(out_frame, text="选择...", command=self.choose_output).pack(side="left")

        # 参数区（可选，默认值已经适合大多数情况）
        param_frame = tk.LabelFrame(root, text="高级参数（一般无需修改）")
        param_frame.pack(fill="x", padx=12, pady=10)

        self.gap = tk.StringVar(value="14")
        self.squeeze_threshold = tk.StringVar(value="28")
        self.squeeze_target = tk.StringVar(value="14")
        self.pagesize = tk.StringVar(value="a4")

        row1 = tk.Frame(param_frame)
        row1.pack(fill="x", pady=4)
        tk.Label(row1, text="题目间距 gap:").pack(side="left")
        tk.Entry(row1, textvariable=self.gap, width=6).pack(side="left", padx=4)
        tk.Label(row1, text="页面大小:").pack(side="left", padx=(12, 0))
        ttk.Combobox(row1, textvariable=self.pagesize, values=["a4", "letter"],
                     width=6, state="readonly").pack(side="left", padx=4)

        row2 = tk.Frame(param_frame)
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="压缩阈值 squeeze-threshold:").pack(side="left")
        tk.Entry(row2, textvariable=self.squeeze_threshold, width=6).pack(side="left", padx=4)
        tk.Label(row2, text="压缩目标 squeeze-target:").pack(side="left", padx=(12, 0))
        tk.Entry(row2, textvariable=self.squeeze_target, width=6).pack(side="left", padx=4)

        # 运行按钮
        self.run_btn = tk.Button(root, text="开始压缩", command=self.run_clicked,
                                  bg="#2d6cdf", fg="white", height=2)
        self.run_btn.pack(fill="x", padx=12, pady=8)

        # 日志区
        self.log_text = tk.Text(root, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def reset_paths(self):
        self.input_path.set("")
        self.output_path.set("")

    def choose_input(self):
        if self.mode.get() == "file":
            path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        else:
            path = filedialog.askdirectory()
        if path:
            self.input_path.set(path)

    def choose_output(self):
        if self.mode.get() == "file":
            path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                                 filetypes=[("PDF files", "*.pdf")])
        else:
            path = filedialog.askdirectory()
        if path:
            self.output_path.set(path)

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(msg) + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def run_clicked(self):
        in_path = self.input_path.get().strip()
        out_path = self.output_path.get().strip()
        if not in_path or not out_path:
            messagebox.showwarning("提示", "请先选择输入和输出路径")
            return

        try:
            gap = float(self.gap.get())
            squeeze_threshold = float(self.squeeze_threshold.get())
            squeeze_target = float(self.squeeze_target.get())
        except ValueError:
            messagebox.showerror("参数错误", "间距/阈值参数必须是数字")
            return

        self.run_btn.config(state="disabled", text="处理中...")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        kwargs = dict(
            gap=gap, pagesize=self.pagesize.get(),
            squeeze_threshold=squeeze_threshold, squeeze_target=squeeze_target,
        )

        thread = threading.Thread(target=self.do_run, args=(in_path, out_path, kwargs), daemon=True)
        thread.start()

    def do_run(self, in_path, out_path, kwargs):
        try:
            if self.mode.get() == "folder":
                in_dir = Path(in_path)
                out_dir = Path(out_path)
                out_dir.mkdir(parents=True, exist_ok=True)
                pdf_files = sorted(in_dir.glob("*.pdf"))
                if not pdf_files:
                    self.log(f"文件夹 {in_dir} 下没有找到PDF文件")
                else:
                    self.log(f"共找到 {len(pdf_files)} 个PDF，开始批量处理...")
                    for f in pdf_files:
                        out_file = out_dir / f.name
                        self.log(f"\n处理: {f.name}")
                        compact_pdf(str(f), str(out_file), log=self.log, **kwargs)
            else:
                compact_pdf(in_path, out_path, log=self.log, **kwargs)
            self.log("\n✅ 全部完成！")
            messagebox.showinfo("完成", "处理完成！")
        except Exception as e:
            self.log("\n❌ 出错了：\n" + traceback.format_exc())
            messagebox.showerror("出错了", str(e))
        finally:
            self.run_btn.config(state="normal", text="开始压缩")


def main():
    root = tk.Tk()
    app = CompactPdfApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
