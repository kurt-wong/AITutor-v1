"""
Layout Analyzer — 版面分析服务

使用 PaddleOCR PP-Structure 进行版面分析：
- 识别 text/figure/table/equation 区域
- 输出每个区域的坐标、类型、内容
"""

import logging
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LayoutRegion:
    """版面分析结果中的一个区域。"""

    region_type: str  # text, figure, table, equation
    bbox: list[int]  # [x1, y1, x2, y2]
    confidence: float = 0.0
    text: str = ""
    image: np.ndarray | None = None
    html: str = ""
    latex: str = ""
    page: int = 1

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（不含图像数据）。"""
        return {
            "region_type": self.region_type,
            "bbox": self.bbox,
            "confidence": self.confidence,
            "text": self.text,
            "html": self.html,
            "latex": self.latex,
            "page": self.page,
        }


@dataclass
class LayoutResult:
    """版面分析结果。"""

    regions: list[LayoutRegion] = field(default_factory=list)
    page_count: int = 1
    success: bool = True
    error_message: str | None = None

    @property
    def text_regions(self) -> list[LayoutRegion]:
        return [r for r in self.regions if r.region_type == "text"]

    @property
    def figure_regions(self) -> list[LayoutRegion]:
        return [r for r in self.regions if r.region_type == "figure"]

    @property
    def table_regions(self) -> list[LayoutRegion]:
        return [r for r in self.regions if r.region_type == "table"]

    @property
    def equation_regions(self) -> list[LayoutRegion]:
        return [r for r in self.regions if r.region_type == "equation"]


class LayoutAnalyzer:
    """版面分析服务。"""

    def __init__(self, show_log: bool = False):
        self._show_log = show_log
        self._engine = None

    def _get_engine(self):
        """懒加载 PP-Structure 引擎。"""
        if self._engine is None:
            try:
                from paddleocr import PPStructure
                self._engine = PPStructure(show_log=self._show_log)
                logger.info("PP-Structure engine initialized")
            except ImportError:
                raise RuntimeError("PaddleOCR not installed")
            except Exception as e:
                logger.error(f"Failed to initialize PP-Structure: {e}")
                raise
        return self._engine

    def analyze_image(self, image_path: str, page: int = 1) -> LayoutResult:
        """分析单张图片的版面。"""
        path = Path(image_path)
        if not path.exists():
            return LayoutResult(success=False, error_message=f"File not found: {image_path}")

        try:
            import cv2
            import numpy as np
            img_data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if img is None:
                return LayoutResult(success=False, error_message=f"Failed to read: {image_path}")
            return self._analyze(img, page)
        except Exception as e:
            return LayoutResult(success=False, error_message=str(e))

    def analyze_image_data(self, image_data: bytes, page: int = 1) -> LayoutResult:
        """分析图片数据的版面。"""
        try:
            import cv2
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return LayoutResult(success=False, error_message="Failed to decode image")
            return self._analyze(img, page)
        except Exception as e:
            return LayoutResult(success=False, error_message=str(e))

    def _analyze(self, img: np.ndarray, page: int = 1) -> LayoutResult:
        """执行版面分析。"""
        engine = self._get_engine()
        result = engine(img)

        regions = []
        for item in result:
            region_type = item.get("type", "text")
            bbox = item.get("bbox", [0, 0, 0, 0])
            score = item.get("score", 0.0)

            if len(bbox) == 4:
                bbox = [int(b) for b in bbox]
            else:
                bbox = [0, 0, 0, 0]

            region = LayoutRegion(
                region_type=region_type,
                bbox=bbox,
                confidence=score,
                page=page,
            )

            if region_type in ("text", "equation"):
                res = item.get("res", [])
                if res:
                    texts = []
                    for r in res:
                        if isinstance(r, dict):
                            text = r.get("text", "")
                            if text:
                                texts.append(text)
                            if region_type == "equation" and r.get("latex"):
                                region.latex = r["latex"]
                    region.text = " ".join(texts)

            elif region_type == "figure":
                region.image = item.get("img")

            elif region_type == "table":
                res = item.get("res", [])
                if res and isinstance(res, list):
                    for r in res:
                        if isinstance(r, dict) and r.get("html"):
                            region.html = r["html"]
                            break

            regions.append(region)

        logger.info(f"Layout: {len(regions)} regions "
                    f"(text={len([r for r in regions if r.region_type == 'text'])}, "
                    f"figure={len([r for r in regions if r.region_type == 'figure'])})")

        return LayoutResult(regions=regions, page_count=1)
