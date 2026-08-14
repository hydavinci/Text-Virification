"""
PDF 处理模块
- 可编辑 PDF：直接提取文字+字体信息（PyMuPDF），质量最高
- 扫描版 PDF：渲染为图片后走 OCR
- 自动判断 PDF 类型
"""

import fitz  # PyMuPDF
import numpy as np
from typing import List, Tuple, Optional
from ocr_engine import DocElement, render_pdf_page_to_image, process_image


def is_scanned_pdf(pdf_path: str, sample_pages: int = 3) -> bool:
    """判断 PDF 是否为扫描版

    判断逻辑：如果前几页几乎没有可提取文本，则认为是扫描版
    """
    doc = fitz.open(pdf_path)
    total_pages = min(sample_pages, len(doc))

    for i in range(total_pages):
        text = doc[i].get_text().strip()
        if len(text) > 50:
            doc.close()
            return False

    doc.close()
    return True


def _has_text_layer(page) -> bool:
    """检查页面是否有文本层"""
    text = page.get_text().strip()
    return len(text) > 20


def extract_editable_pdf(pdf_path: str, lang: str = 'auto') -> List[DocElement]:
    """从可编辑 PDF 直接提取结构化内容（保留字体、字号、颜色、表格、图片）

    Returns:
        List[DocElement]
    """
    doc = fitz.open(pdf_path)
    all_elements = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_elements = _extract_page_elements(page, page_num)
        all_elements.extend(page_elements)

    doc.close()
    return all_elements


def _extract_page_elements(page, page_num: int) -> List[DocElement]:
    """从单个 PDF 页面提取结构化元素"""
    elements = []

    # 获取文本块（dict 格式，包含字体信息）
    page_dict = page.get_text('dict', flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)

    # 尝试检测表格
    try:
        table_list = page.find_tables()
        tables = table_list.tables if table_list else []
    except Exception:
        tables = []

    table_rects = []
    for tbl in tables:
        try:
            # 提取表格数据
            table_data = tbl.extract()
            if table_data and any(any(str(c).strip() for c in row) for row in table_data):
                elements.append(DocElement(
                    etype='table',
                    rows=[[str(c) if c else '' for c in row] for row in table_data],
                    y=tbl.bbox.y0
                ))
                table_rects.append(fitz.Rect(tbl.bbox))
        except Exception:
            pass

    # 提取图片
    image_list = page.get_images(full=True)
    for img_info in image_list:
        try:
            xref = img_info[0]
            base_image = page.parent.extract_image(xref)
            image_bytes = base_image['image']
            ext = base_image.get('ext', 'png')

            # 获取图片在页面上的位置
            for block in page_dict.get('blocks', []):
                if block.get('type') == 1:  # image block
                    bbox = block['bbox']
                    elements.append(DocElement(
                        etype='image',
                        image_data=image_bytes,
                        image_ext=ext,
                        y=bbox[1]
                    ))
                    break
        except Exception:
            pass

    # 提取文本
    blocks = page_dict.get('blocks', [])
    text_spans = []

    for block in blocks:
        if block.get('type') != 0:  # 非文本块
            continue

        bbox = block['bbox']
        block_rect = fitz.Rect(bbox)

        # 跳过表格区域的文本
        in_table = False
        for trect in table_rects:
            if block_rect.intersects(trect):
                in_table = True
                break

        if in_table:
            continue

        for line in block.get('lines', []):
            line_bbox = line['bbox']
            line_rect = fitz.Rect(line_bbox)

            for span in line.get('spans', []):
                text = span['text'].strip()
                if not text:
                    continue

                font_size = span.get('size', 11)
                font_flags = span.get('flags', 0)
                font_name = span.get('font', '')
                color = span.get('color', 0)

                text_spans.append({
                    'text': text,
                    'font_size': font_size,
                    'font_flags': font_flags,
                    'font_name': font_name,
                    'color': color,
                    'bbox': span['bbox'],
                    'block_bbox': bbox,
                    'line_bbox': line_bbox
                })

    # 将文本 span 分组为段落和标题
    if text_spans:
        elements.extend(_group_spans_to_elements(text_spans))

    # 按 y 排序
    elements.sort(key=lambda e: e.y)

    return elements


def _group_spans_to_elements(spans: List[dict]) -> List[DocElement]:
    """将文本 span 分组为段落和标题"""
    if not spans:
        return []

    # 计算平均字号
    avg_size = sum(s['font_size'] for s in spans) / len(spans)

    # 按位置排序（从上到下，从左到右）
    spans.sort(key=lambda s: (s['bbox'][1], s['bbox'][0]))

    elements = []
    current_para_texts = []
    current_para_size = avg_size
    current_para_y = 0
    current_line_bbox = None

    for i, span in enumerate(spans):
        text = span['text']
        font_size = span['font_size']
        span_bbox = span['bbox']
        line_bbox = span['line_bbox']

        # 检测标题：字号明显大于平均 + 文本较短
        is_heading = False
        heading_level = 0

        if font_size >= avg_size * 1.4 and len(text) < 80:
            if font_size >= 24:
                heading_level = 1
            elif font_size >= 18:
                heading_level = 2
            elif font_size >= 16:
                heading_level = 3
            else:
                heading_level = 4
            is_heading = True

        if is_heading:
            # 保存当前段落
            if current_para_texts:
                elements.append(DocElement(
                    etype='paragraph',
                    text='\n'.join(current_para_texts),
                    font_size=current_para_size,
                    y=current_para_y
                ))
                current_para_texts = []

            elements.append(DocElement(
                etype='heading',
                text=text,
                level=heading_level,
                font_size=font_size,
                y=span_bbox[1]
            ))
            current_line_bbox = line_bbox
            continue

        # 段落分组逻辑
        if not current_para_texts:
            current_para_texts = [text]
            current_para_size = font_size
            current_para_y = span_bbox[1]
            current_line_bbox = line_bbox
        else:
            # 判断是否新段落：
            # 1. 行间距大于行高的1.5倍 → 新段落
            # 2. 左边界明显缩进 → 新段落
            prev_bbox = current_line_bbox if current_line_bbox else spans[i-1]['bbox']

            prev_y2 = prev_bbox[3]
            curr_y0 = line_bbox[1]
            gap = curr_y0 - prev_y2
            line_height = prev_bbox[3] - prev_bbox[1]

            prev_x0 = prev_bbox[0]
            curr_x0 = line_bbox[0]

            if gap > line_height * 0.8 or abs(curr_x0 - prev_x0) > 30:
                # 新段落
                elements.append(DocElement(
                    etype='paragraph',
                    text='\n'.join(current_para_texts),
                    font_size=current_para_size,
                    y=current_para_y
                ))
                current_para_texts = [text]
                current_para_size = font_size
                current_para_y = span_bbox[1]
            else:
                # 同一段落
                # 判断是否同一行
                if (current_line_bbox and
                    abs(line_bbox[1] - current_line_bbox[1]) < 3):
                    # 同一行：直接连接
                    if current_para_texts:
                        current_para_texts[-1] += text
                    else:
                        current_para_texts = [text]
                else:
                    # 新行
                    current_para_texts.append(text)

                # 更新字号
                current_para_size = (current_para_size + font_size) / 2
                current_line_bbox = line_bbox

    # 保存最后一个段落
    if current_para_texts:
        elements.append(DocElement(
            etype='paragraph',
            text='\n'.join(current_para_texts),
            font_size=current_para_size,
            y=current_para_y
        ))

    return elements


def extract_scanned_pdf(pdf_path: str, lang: str = 'auto',
                        dpi: int = 300) -> List[DocElement]:
    """从扫描版 PDF 提取内容（渲染为图片后 OCR）"""
    doc = fitz.open(pdf_path)
    all_elements = []

    for page_num in range(len(doc)):
        # 渲染页面为图片
        image = render_pdf_page_to_image(doc, page_num, dpi)

        # OCR 处理
        page_elements = process_image(image, lang, dpi)
        all_elements.extend(page_elements)

    doc.close()
    return all_elements


def extract_mixed_pdf(pdf_path: str, lang: str = 'auto',
                      dpi: int = 300) -> List[DocElement]:
    """混合模式：每页独立判断是否有文本层

    有文本层 → 直接提取
    无文本层 → OCR
    """
    doc = fitz.open(pdf_path)
    all_elements = []

    for page_num in range(len(doc)):
        page = doc[page_num]

        if _has_text_layer(page):
            # 可编辑页
            page_elements = _extract_page_elements(page, page_num)
        else:
            # 扫描页 → OCR
            image = render_pdf_page_to_image(doc, page_num, dpi)
            page_elements = process_image(image, lang, dpi)

        all_elements.extend(page_elements)

    doc.close()
    return all_elements


def process_pdf(pdf_path: str, lang: str = 'auto',
                dpi: int = 300) -> List[DocElement]:
    """PDF 处理主函数

    自动判断 PDF 类型并选择最佳处理方式：
    - 全部可编辑 → 直接提取
    - 全部扫描版 → OCR
    - 混合 → 逐页判断

    Args:
        pdf_path: PDF 文件路径
        lang: OCR 语言 ('ch', 'japan', 'en', 'auto')
        dpi: 扫描版渲染 DPI

    Returns:
        List[DocElement]
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # 检查每页
    editable_pages = 0
    scanned_pages = 0

    for i in range(total_pages):
        if _has_text_layer(doc[i]):
            editable_pages += 1
        else:
            scanned_pages += 1

    doc.close()

    if scanned_pages == 0:
        # 全部可编辑
        return extract_editable_pdf(pdf_path, lang)
    elif editable_pages == 0:
        # 全部扫描版
        return extract_scanned_pdf(pdf_path, lang, dpi)
    else:
        # 混合模式
        return extract_mixed_pdf(pdf_path, lang, dpi)
