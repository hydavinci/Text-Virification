"""
OCR 引擎模块 - 基于 RapidOCR v3
支持中/英/日文识别，布局分析（段落/标题/表格检测/字号估算）
"""

import numpy as np
import cv2
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# 延迟导入 RapidOCR，避免启动时下载模型
_ch_engine = None
_jp_engine = None
_en_engine = None


def _get_chinese_engine():
    """获取中英文 OCR 引擎（PP-OCRv6）"""
    global _ch_engine
    if _ch_engine is None:
        from rapidocr import RapidOCR
        _ch_engine = RapidOCR()
    return _ch_engine


def _get_japanese_engine():
    """获取日文 OCR 引擎（PP-OCRv4 japan）"""
    global _jp_engine
    if _jp_engine is None:
        from rapidocr import RapidOCR
        from rapidocr.utils.parse_parameters import (
            OCRVersion, ModelType, LangRec, LangDet
        )
        params = {
            'Det.lang_type': LangDet.CH,
            'Det.ocr_version': OCRVersion.PPOCRV4,
            'Det.model_type': ModelType.MOBILE,
            'Rec.lang_type': LangRec.JAPAN,
            'Rec.ocr_version': OCRVersion.PPOCRV4,
            'Rec.model_type': ModelType.MOBILE,
            'Cls.ocr_version': OCRVersion.PPOCRV4,
            'Cls.model_type': ModelType.MOBILE,
        }
        _jp_engine = RapidOCR(params=params)
    return _jp_engine


def _get_english_engine():
    """获取英文 OCR 引擎"""
    global _en_engine
    if _en_engine is None:
        from rapidocr import RapidOCR
        from rapidocr.utils.parse_parameters import (
            OCRVersion, ModelType, LangRec, LangDet
        )
        params = {
            'Det.lang_type': LangDet.EN,
            'Det.ocr_version': OCRVersion.PPOCRV4,
            'Det.model_type': ModelType.MOBILE,
            'Rec.lang_type': LangRec.EN,
            'Rec.ocr_version': OCRVersion.PPOCRV4,
            'Rec.model_type': ModelType.MOBILE,
            'Cls.ocr_version': OCRVersion.PPOCRV4,
            'Cls.model_type': ModelType.MOBILE,
        }
        _en_engine = RapidOCR(params=params)
    return _en_engine


def get_engine(lang: str = 'auto'):
    """根据语言选择 OCR 引擎

    Args:
        lang: 'ch' 中英文, 'japan' 日文, 'en' 英文, 'auto' 自动(中英文)
    """
    if lang == 'japan':
        return _get_japanese_engine()
    elif lang == 'en':
        return _get_english_engine()
    else:
        return _get_chinese_engine()


# ============================================================
# 数据结构
# ============================================================

@dataclass
class TextBox:
    """单个文本框"""
    box: np.ndarray          # 4x2 四点坐标
    text: str
    score: float
    x: float = 0.0           # 左边界
    y: float = 0.0           # 上边界
    x2: float = 0.0          # 右边界
    y2: float = 0.0          # 下边界
    height: float = 0.0      # 文本高度
    width: float = 0.0       # 文本宽度

    def __post_init__(self):
        xs = self.box[:, 0]
        ys = self.box[:, 1]
        self.x = float(xs.min())
        self.y = float(ys.min())
        self.x2 = float(xs.max())
        self.y2 = float(ys.max())
        self.height = self.y2 - self.y
        self.width = self.x2 - self.x


@dataclass
class DocElement:
    """文档元素（段落/标题/表格/图片）"""
    etype: str  # 'paragraph', 'heading', 'table', 'image'
    text: str = ''
    level: int = 0         # 标题级别 1-6
    font_size: float = 12  # 估算字号 (pt)
    rows: List[List[str]] = field(default_factory=list)  # 表格行
    image_data: Optional[bytes] = None
    image_ext: str = 'png'
    y: float = 0.0         # 垂直位置（用于排序）


# ============================================================
# 布局分析
# ============================================================

def _boxes_from_result(result) -> List[TextBox]:
    """将 RapidOCR 结果转为 TextBox 列表"""
    if result is None or result.boxes is None or result.txts is None:
        return []

    boxes = []
    for box, txt, score in zip(result.boxes, result.txts, result.scores):
        if txt and txt.strip():
            tb = TextBox(
                box=np.array(box, dtype=np.float32),
                text=txt.strip(),
                score=float(score)
            )
            boxes.append(tb)
    return boxes


def _sort_boxes(boxes: List[TextBox]) -> List[TextBox]:
    """排序文本框：从上到下，从左到右"""
    return sorted(boxes, key=lambda b: (b.y, b.x))


def _group_into_lines(boxes: List[TextBox]) -> List[List[TextBox]]:
    """将文本框分组为行（y 坐标重叠的框属于同一行）"""
    if not boxes:
        return []

    lines = []
    current_line = [boxes[0]]
    current_y_center = (boxes[0].y + boxes[0].y2) / 2
    current_height = boxes[0].height

    for box in boxes[1:]:
        box_y_center = (box.y + box.y2) / 2
        # 如果 y 中心在当前行的上下半行高范围内，视为同一行
        if abs(box_y_center - current_y_center) < current_height * 0.6:
            current_line.append(box)
        else:
            lines.append(current_line)
            current_line = [box]
            current_y_center = box_y_center
            current_height = box.height

    lines.append(current_line)
    return lines


def _merge_line_text(line: List[TextBox]) -> Tuple[str, float, float, float, float]:
    """合并一行文本框，返回 (文本, 平均字号_px, x, y, 高度)"""
    line_sorted = sorted(line, key=lambda b: b.x)
    text = ' '.join(b.text for b in line_sorted)

    avg_height = sum(b.height for b in line_sorted) / len(line_sorted)
    x = min(b.x for b in line_sorted)
    y = min(b.y for b in line_sorted)
    x2 = max(b.x2 for b in line_sorted)
    y2 = max(b.y2 for b in line_sorted)

    # 用第一个框的文本（可能包含空格调整）
    # 对于中文，不需要空格连接；对于英文，需要空格
    first_text = line_sorted[0].text
    has_cjk = any('\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff'
                  for ch in text)
    if has_cjk:
        text = ''.join(b.text for b in line_sorted)
    else:
        text = ' '.join(b.text for b in line_sorted)

    return text, avg_height, x, y, y2 - y


def _estimate_font_pt(px_height: float, dpi: int = 300) -> float:
    """从像素高度估算 Word 字号 (pt)

    px -> pt 转换：pt = px * 72 / dpi
    然后映射到标准字号
    """
    raw_pt = px_height * 72.0 / dpi

    # 标准字号映射表
    standard_sizes = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48]
    closest = min(standard_sizes, key=lambda s: abs(s - raw_pt))
    return float(closest)


def _detect_heading(text: str, font_pt: float, avg_font_pt: float) -> int:
    """检测是否为标题，返回标题级别（0=非标题）"""
    if not text or len(text) > 100:
        return 0

    # 字号明显大于正文
    if font_pt >= avg_font_pt * 1.6:
        if font_pt >= 24:
            return 1
        elif font_pt >= 18:
            return 2
        elif font_pt >= 16:
            return 3
        else:
            return 4

    # 短文本 + 以冒号/句号结尾的可能是标题
    stripped = text.strip()
    if len(stripped) <= 30 and not stripped.endswith(('。', '，', '、', '；', '：')):
        # 纯数字编号（如 "1." "第二章"）
        if (stripped[0].isdigit() or
            any(stripped.startswith(p) for p in ['第', 'Chapter', 'CHAPTER', 'Section'])):
            if font_pt > avg_font_pt * 1.2:
                return 3

    return 0


def _detect_tables(image: np.ndarray) -> List[Dict]:
    """使用 OpenCV 检测表格线，返回表格区域列表"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape

    # 二值化
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 15, 10
    )

    # 检测水平线
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 30, 10), 1))
    horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)

    # 检测垂直线
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 30, 10)))
    vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)

    # 合并线条
    table_mask = cv2.add(horizontal, vertical)

    # 查找表格轮廓
    contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    tables = []
    for contour in contours:
        x, y, w_c, h_c = cv2.boundingRect(contour)
        # 过滤太小的区域
        if w_c < 50 or h_c < 30:
            continue
        tables.append({
            'x': x, 'y': y, 'w': w_c, 'h': h_c,
            'x2': x + w_c, 'y2': y + h_c
        })

    return tables


def _boxes_in_region(boxes: List[TextBox], region: Dict) -> List[TextBox]:
    """获取位于指定区域内的文本框"""
    return [b for b in boxes
            if b.x >= region['x'] - 5 and b.x2 <= region['x2'] + 5
            and b.y >= region['y'] - 5 and b.y2 <= region['y2'] + 5]


def _extract_table_cells(boxes: List[TextBox], region: Dict, image: np.ndarray) -> List[List[str]]:
    """从表格区域提取单元格文本"""
    table_boxes = _boxes_in_region(boxes, region)
    if not table_boxes:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    region_img = gray[int(region['y']):int(region['y2']),
                      int(region['x']):int(region['x2'])]

    if region_img.size == 0 or region_img.shape[0] < 5 or region_img.shape[1] < 5:
        return _fallback_table_rows(table_boxes)

    thresh = cv2.adaptiveThreshold(
        region_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 15, 10
    )

    h_r, w_r = region_img.shape
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w_r // 20, 5), 1))
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h_r // 20, 5)))

    horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horiz_kernel, iterations=1)
    vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vert_kernel, iterations=1)

    grid = cv2.add(horizontal, vertical)
    grid = cv2.dilate(grid, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(grid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    cells = []
    for contour in contours:
        cx, cy, cw, ch = cv2.boundingRect(contour)
        if cw < 10 or ch < 10:
            continue
        abs_x = cx + region['x']
        abs_y = cy + region['y']
        cells.append({
            'x': abs_x, 'y': abs_y, 'x2': abs_x + cw, 'y2': abs_y + ch
        })

    if not cells:
        return _fallback_table_rows(table_boxes)

    cells.sort(key=lambda c: (c['y'], c['x']))

    # 分组为行
    rows = []
    current_row = [cells[0]]
    current_y = cells[0]['y'] + cells[0]['y2']
    current_h = cells[0]['y2'] - cells[0]['y']

    for cell in cells[1:]:
        cell_y_center = (cell['y'] + cell['y2']) / 2
        row_y_center = current_y / len(current_row)
        if abs(cell_y_center - row_y_center) < current_h * 0.5:
            current_row.append(cell)
        else:
            rows.append(current_row)
            current_row = [cell]
            current_y = cell['y'] + cell['y2']
            current_h = cell['y2'] - cell['y']

    rows.append(current_row)

    # 将文本框映射到单元格
    table_data = []
    for row_cells in rows:
        row_cells.sort(key=lambda c: c['x'])
        row_text = []
        for cell in row_cells:
            cell_text = []
            for b in table_boxes:
                bcx = (b.x + b.x2) / 2
                bcy = (b.y + b.y2) / 2
                if (cell['x'] <= bcx <= cell['x2'] and
                    cell['y'] <= bcy <= cell['y2']):
                    cell_text.append(b.text)
            row_text.append(' '.join(cell_text) if cell_text else '')
        table_data.append(row_text)

    return table_data


def _fallback_table_rows(table_boxes: List[TextBox]) -> List[List[str]]:
    """无法检测网格线时的表格行回退方案"""
    lines = _group_into_lines(table_boxes)
    rows = []
    for line in lines:
        line_sorted = sorted(line, key=lambda b: b.x)
        row_text = [b.text for b in line_sorted]
        rows.append(row_text)
    return rows


def _detect_image_regions(image: np.ndarray, text_boxes: List[TextBox]) -> List[Dict]:
    """检测图片区域（基于内容：寻找有实际图像内容的非文本区域）"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape

    # 方法：寻找有实际内容的区域（非纯白/纯黑的大块区域）
    # 阈值化：将非背景像素标记出来
    # 背景通常是白色（>230）或黑色（<25）
    content_mask = np.ones((h, w), dtype=np.uint8) * 255  # 先标记全部为内容
    content_mask[gray > 230] = 0  # 去掉白色背景
    content_mask[gray < 25] = 0  # 去掉黑色背景

    # 去掉文本区域
    text_mask = np.zeros((h, w), dtype=np.uint8)
    for b in text_boxes:
        pts = np.array(b.box, dtype=np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(text_mask, [pts], 255)
    # 膨胀文本区域
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    text_mask = cv2.dilate(text_mask, kernel, iterations=2)
    # 从内容中去除文本
    content_mask = cv2.bitwise_and(content_mask, cv2.bitwise_not(text_mask))

    # 查找内容区域轮廓
    contours, _ = cv2.findContours(content_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    image_regions = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cw * ch
        # 过滤太小的区域
        if cw < 50 or ch < 50 or area < 3000:
            continue
        # 检查区域内实际内容像素密度
        region_content = content_mask[y:y+ch, x:x+cw]
        content_ratio = np.count_nonzero(region_content) / region_content.size
        # 内容像素占比太低（< 5%），可能是噪声
        if content_ratio < 0.05:
            continue

        image_regions.append({
            'x': x, 'y': y, 'w': cw, 'h': ch,
            'x2': x + cw, 'y2': y + ch
        })

    return image_regions


# ============================================================
# 主处理函数
# ============================================================

def _detect_dpi(image_input) -> int:
    """从图片元数据检测 DPI，无法检测时返回 72（屏幕分辨率）"""
    try:
        from PIL import Image
        if isinstance(image_input, str):
            img = Image.open(image_input)
        elif isinstance(image_input, np.ndarray):
            return 72  # numpy 数组没有 DPI 信息
        else:
            return 72

        dpi = img.info.get('dpi', (72, 72))
        if isinstance(dpi, (tuple, list)) and len(dpi) >= 1:
            d = dpi[0]
            if d and d > 0:
                return int(d)
        return 72
    except Exception:
        return 72


def process_image(image_input, lang: str = 'auto', dpi: int = None) -> List[DocElement]:
    """处理图片，返回结构化文档元素列表

    Args:
        image_input: 图片路径(str)或 numpy 数组
        lang: 'ch' 中英文, 'japan' 日文, 'en' 英文, 'auto' 自动
        dpi: 用于字号估算的 DPI（None 时自动检测）

    Returns:
        List[DocElement]
    """
    engine = get_engine(lang)

    # 检测 DPI（用于字号估算）
    if dpi is None:
        dpi = _detect_dpi(image_input)

    # 执行 OCR
    result = engine(image_input)

    # 提取文本框
    boxes = _boxes_from_result(result)
    if not boxes:
        return []

    # 加载图片用于表格检测
    if isinstance(image_input, str):
        image = cv2.imread(image_input)
    elif isinstance(image_input, np.ndarray):
        image = image_input.copy()
    else:
        image = None

    # 排序文本框
    boxes = _sort_boxes(boxes)

    # 检测表格区域
    table_regions = []
    if image is not None:
        table_regions = _detect_tables(image)

    # 检测图片区域
    image_regions = []
    if image is not None:
        image_regions = _detect_image_regions(image, boxes)

    # 将属于表格的文本框提取出来
    table_boxes_used = set()
    table_elements = []
    for region in table_regions:
        table_boxes = _boxes_in_region(boxes, region)
        if len(table_boxes) < 2:
            continue

        table_data = _extract_table_cells(boxes, region, image)
        if table_data and any(any(cell for cell in row) for row in table_data):
            table_elements.append(DocElement(
                etype='table',
                rows=table_data,
                y=region['y']
            ))
            for b in table_boxes:
                table_boxes_used.add(id(b))

    # 剩余的文本框用于段落和标题
    text_boxes = [b for b in boxes if id(b) not in table_boxes_used]

    # 分组为行
    lines = _group_into_lines(text_boxes)

    # 合并行文本并估算字号
    line_info = []
    for line in lines:
        text, px_height, x, y, height = _merge_line_text(line)
        font_pt = _estimate_font_pt(px_height, dpi)
        line_info.append({
            'text': text,
            'font_pt': font_pt,
            'px_height': px_height,
            'x': x,
            'y': y,
            'height': height
        })

    # 计算平均字号（用于标题检测）
    if line_info:
        avg_pt = sum(l['font_pt'] for l in line_info) / len(line_info)
    else:
        avg_pt = 12

    # 将行分组为段落和标题
    elements = []

    # 先插入表格元素（按 y 排序）
    for te in table_elements:
        elements.append(te)

    # 再插入图片元素
    if image is not None:
        from PIL import Image
        import io as _io
        for region in image_regions:
            x, y = int(region['x']), int(region['y'])
            x2, y2 = int(region['x2']), int(region['y2'])
            if x2 > x and y2 > y and x2 <= image.shape[1] and y2 <= image.shape[0]:
                crop = image[y:y2, x:x2]
                if crop.size > 0:
                    pil_img = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                    buf = _io.BytesIO()
                    pil_img.save(buf, format='PNG')
                    elements.append(DocElement(
                        etype='image',
                        image_data=buf.getvalue(),
                        image_ext='png',
                        y=float(y)
                    ))

    # 处理文本行
    current_para_text = []
    current_para_font = avg_pt
    current_para_y = 0
    current_heading_level = 0

    for info in line_info:
        heading_level = _detect_heading(info['text'], info['font_pt'], avg_pt)

        if heading_level > 0:
            # 先保存当前段落
            if current_para_text:
                elements.append(DocElement(
                    etype='paragraph',
                    text='\n'.join(current_para_text),
                    font_size=current_para_font,
                    y=current_para_y
                ))
                current_para_text = []

            # 添加标题
            elements.append(DocElement(
                etype='heading',
                text=info['text'],
                level=heading_level,
                font_size=info['font_pt'],
                y=info['y']
            ))
            current_heading_level = heading_level
        else:
            # 段落检测：如果行间距与字号接近，视为同一段落
            if not current_para_text:
                current_para_text = [info['text']]
                current_para_font = info['font_pt']
                current_para_y = info['y']
                current_heading_level = 0
            else:
                # 判断是否属于当前段落
                prev_info = line_info[line_info.index(info) - 1]
                gap = info['y'] - (prev_info['y'] + prev_info['height'])

                if gap < info['height'] * 1.5:
                    # 同一段落
                    current_para_text.append(info['text'])
                    # 更新字号为平均值
                    current_para_font = (current_para_font + info['font_pt']) / 2
                else:
                    # 新段落
                    elements.append(DocElement(
                        etype='paragraph',
                        text='\n'.join(current_para_text),
                        font_size=current_para_font,
                        y=current_para_y
                    ))
                    current_para_text = [info['text']]
                    current_para_font = info['font_pt']
                    current_para_y = info['y']

    # 保存最后一个段落
    if current_para_text:
        elements.append(DocElement(
            etype='paragraph',
            text='\n'.join(current_para_text),
            font_size=current_para_font,
            y=current_para_y
        ))

    # 按 y 坐标排序所有元素
    elements.sort(key=lambda e: e.y)

    return elements


def process_image_file(image_path: str, lang: str = 'auto', dpi: int = None) -> List[DocElement]:
    """处理图片文件"""
    return process_image(image_path, lang, dpi)


def render_pdf_page_to_image(pdf_doc, page_num: int, dpi: int = 300) -> np.ndarray:
    """将 PDF 页面渲染为图片"""
    import fitz
    page = pdf_doc[page_num]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    # 转为 numpy 数组
    import io as _io
    from PIL import Image
    img = Image.open(_io.BytesIO(img_data))
    return np.array(img)
