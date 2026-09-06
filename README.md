# compact_pdf.py

把"一页一题、大量留白"的 PDF 压缩成紧凑排版的小工具。常见场景：题库、讲义、扫描版试卷等每页只有少量内容、四周留白很多的 PDF。

A small tool that compacts PDFs with excessive whitespace (e.g. one question per page) into a dense, multi-item layout — while keeping math formulas and vector graphics fully intact.

## 特点 / Features

- **不依赖 OCR，纯几何裁剪 + 重排**：不会把公式、符号识别成文字再重建，因此数学公式、上下标、根号等内容保持原始矢量清晰度，不会乱码、不会失真。
- **智能去空白**：不仅去掉页面底部的大片留白，页面内部（比如题目和选项之间）异常大的间距也会被自动压缩，正常的行间距则保持不变。
- **支持单文件和批量处理**：可以处理单个 PDF，也可以一次性处理整个文件夹。
- **参数可调**：空白判定阈值、压缩目标间距、页边距等都可以自定义。

No OCR involved — pages are only rendered to images for whitespace *detection*; the actual content is clipped from the original vector PDF, so formulas and graphics stay crisp.

## 安装 / Installation

需要 Python 3.9 及以上版本。

```bash
pip install pymupdf numpy
```

（如果 `pip` 命令不认，可以试试 `pip3` 或 `python3 -m pip install pymupdf numpy`）

## 使用方法 / Usage

**处理单个文件：**

```bash
python3 compact_pdf.py input.pdf output.pdf
```

**批量处理整个文件夹：**

```bash
python3 compact_pdf.py 输入文件夹/ 输出文件夹/
```

## 可选参数 / Options

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--dpi` | 150 | 用于检测内容的渲染分辨率，越高检测越精细但越慢 |
| `--gap` | 14 | 不同题目之间的垂直间距（pt） |
| `--margin` | 36 | 输出页面的页边距（pt） |
| `--pagesize` | a4 | 输出页面大小，可选 `a4` 或 `letter` |
| `--white-thresh` | 248 | 判定"空白像素"的灰度阈值（0–255），越小越严格 |
| `--squeeze-threshold` | 28 | 页面内部超过多少 pt 的空白间隔会被压缩 |
| `--squeeze-target` | 14 | 被压缩后的间隔缩小到多少 pt |

示例：调整题目间距和压缩阈值

```bash
python3 compact_pdf.py input.pdf output.pdf --gap 20 --squeeze-threshold 30
```

查看完整参数说明：

```bash
python3 compact_pdf.py --help
```

## 工作原理 / How it works

1. 把每一页渲染成灰度图片，通过像素分析找到内容所在的行区间（哪些行有墨迹）。
2. 检测页面内部"异常大"的空白间隔（比如题目和下方大片留白之间），把这段间隔压缩到一个较小的固定值；正常的段内行距不受影响。
3. 对内容区域做**矢量裁剪**（PDF clip 机制，非转图片再裁剪），文字、公式、线条保持原始清晰度。
4. 把处理后的各题依次从上到下摆放到新页面上，排满自动换页。

## License

MIT
