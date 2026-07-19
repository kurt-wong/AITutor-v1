"""
Content Extractor — 区域内容提取服务

从版面分析结果中提取结构化内容：
- text 区域 → 合并文本
- figure 区域 → 保存图片
- equation 区域 → LaTeX 公式
- table 区域 → HTML 表格
"""

import logging
import uuid
from typing import Any
from dataclasses import dataclass, field
from io import BytesIO


logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """提取的结构化内容。"""

    text: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    formulas: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "images": self.images,
            "formulas": self.formulas,
            "tables": self.tables,
        }


class ContentExtractor:
    """从版面分析结果中提取结构化内容。"""

    def __init__(self, image_bucket: str = "images"):
        self._image_bucket = image_bucket

    def extract(self, layout_result, save_images: bool = True) -> ExtractedContent:
        """从版面分析结果提取内容。"""
        content = ExtractedContent()

        # 按 bbox y 坐标排序（从上到下）
        sorted_regions = sorted(
            layout_result.regions,
            key=lambda r: r.bbox[1] if r.bbox else 0,
        )

        for region in sorted_regions:
            if region.region_type in ("text", "title"):
                if region.text:
                    content.text += region.text + "\n"

            elif region.region_type == "figure":
                if region.image is not None:
                    image_info = self._save_figure(region)
                    if image_info:
                        content.images.append(image_info)

            elif region.region_type == "equation":
                if region.latex:
                    content.formulas.append({
                        "latex": region.latex,
                        "bbox": region.bbox,
                        "text": region.text,
                    })
                elif region.text:
                    content.formulas.append({
                        "latex": "",
                        "bbox": region.bbox,
                        "text": region.text,
                    })

            elif region.region_type == "table":
                if region.html:
                    content.tables.append({
                        "html": region.html,
                        "bbox": region.bbox,
                    })

        content.text = content.text.strip()

        logger.info(
            f"Extracted: text={len(content.text)} chars, "
            f"images={len(content.images)}, "
            f"formulas={len(content.formulas)}"
        )

        return content

    def _save_figure(self, region) -> dict[str, Any] | None:
        """保存图片区域到 MinIO。"""
        try:
            import cv2

            img_id = uuid.uuid4().hex[:12]
            object_key = f"questions/figures/{img_id}.jpg"

            img = region.image
            success, encoded = cv2.imencode(".jpg", img)
            if not success:
                return None

            image_bytes = encoded.tobytes()

            try:
                from app.db.minio import upload_file
                upload_file(
                    object_name=object_key,
                    data=BytesIO(image_bytes),
                    length=len(image_bytes),
                    content_type="image/jpeg",
                    bucket=self._image_bucket,
                )
            except Exception as e:
                logger.warning(f"Failed to save figure: {e}")

            return {
                "key": object_key,
                "bbox": region.bbox,
                "size": len(image_bytes),
            }

        except Exception as e:
            logger.error(f"Failed to process figure: {e}")
            return None

    def merge_text_and_formulas(self, content: ExtractedContent) -> str:
        """将文本和公式合并为可读格式（用于 LLM 输入）。"""
        parts = []

        if content.text:
            parts.append(content.text)

        if content.formulas:
            parts.append("\n公式：")
            for i, f in enumerate(content.formulas, 1):
                latex = f.get("latex", "")
                text = f.get("text", "")
                if latex:
                    parts.append(f"  公式{i}: ${latex}$")
                elif text:
                    parts.append(f"  公式{i}: {text}")

        if content.tables:
            parts.append("\n表格：")
            for i, t in enumerate(content.tables, 1):
                parts.append(f"  表格{i}: [HTML表格]")

        return "\n".join(parts)
