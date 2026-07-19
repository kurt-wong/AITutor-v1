"""
PDF to Image Converter

Converts PDF pages to images for OCR processing.
Uses pdf2image library which requires Poppler.

Installation:
    pip install pdf2image

System dependency:
    - Windows: Download Poppler from https://github.com/osber/poppler-windows/releases
    - Linux: apt-get install poppler-utils
    - macOS: brew install poppler

Usage:
    converter = PDFConverter()
    image_paths = await converter.convert_to_images("document.pdf", output_dir="/tmp")
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PDFConverter:
    """Converts PDF pages to images for OCR processing.

    Uses pdf2image library which wraps Poppler's pdftoppm utility.
    """

    def __init__(self, dpi: int = 200, format: str = "png"):
        """Initialize PDF converter.

        Args:
            dpi: Resolution for output images (higher = better quality, larger files)
            format: Output image format ('png', 'jpeg', 'tiff')
        """
        self._dpi = dpi
        self._format = format

    async def convert_to_images(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        pages: Optional[list[int]] = None,
    ) -> list[str]:
        """Convert PDF pages to images.

        Args:
            pdf_path: Path to the PDF file
            output_dir: Directory to save images (default: system temp dir)
            pages: List of page numbers to convert (1-indexed, default: all pages)

        Returns:
            List of paths to generated image files

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            RuntimeError: If pdf2image is not installed or conversion fails
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        if not pdf_path.suffix.lower() == ".pdf":
            raise ValueError(f"Not a PDF file: {pdf_path.suffix}")

        try:
            from pdf2image import convert_from_path, pdfinfo_from_path
        except ImportError:
            raise RuntimeError(
                "pdf2image not installed. Run: pip install pdf2image\n"
                "Also requires Poppler: https://github.com/osber/poppler-windows/releases"
            )

        # Create output directory
        if output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="ocr_pdf_"))

        try:
            # Get PDF info
            info = pdfinfo_from_path(str(pdf_path))
            total_pages = info.get("Pages", 1)
            logger.info(f"PDF has {total_pages} pages: {pdf_path.name}")

            # Determine which pages to convert
            if pages:
                # Validate page numbers
                valid_pages = [p for p in pages if 1 <= p <= total_pages]
                if not valid_pages:
                    raise ValueError(f"No valid pages specified (PDF has {total_pages} pages)")
            else:
                valid_pages = list(range(1, total_pages + 1))

            # Convert pages to images
            image_paths = []
            for page_num in valid_pages:
                try:
                    loop = asyncio.get_running_loop()
                    images = await loop.run_in_executor(
                        None,
                        lambda: convert_from_path(
                            str(pdf_path),
                            dpi=self._dpi,
                            first_page=page_num,
                            last_page=page_num,
                            fmt=self._format,
                            output_folder=str(out_dir),
                            output_file=f"page_{page_num:04d}",
                        ),
                    )

                    if images:
                        # pdf2image saves the file with a suffix
                        image_file = out_dir / f"page_{page_num:04d}.{self._format}"
                        if image_file.exists():
                            image_paths.append(str(image_file))
                            logger.debug(f"Converted page {page_num} -> {image_file.name}")
                        else:
                            # Try alternative naming
                            for f in out_dir.glob(f"page_{page_num:04d}*"):
                                if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".tiff"]:
                                    image_paths.append(str(f))
                                    logger.debug(f"Converted page {page_num} -> {f.name}")
                                    break

                except Exception as e:
                    logger.warning(f"Failed to convert page {page_num}: {e}")
                    continue

            logger.info(f"Converted {len(image_paths)}/{len(valid_pages)} pages from {pdf_path.name}")
            return image_paths

        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            raise RuntimeError(f"PDF conversion failed: {e}") from e

    async def get_page_count(self, pdf_path: str) -> int:
        """Get the number of pages in a PDF.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Number of pages
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            from pdf2image import pdfinfo_from_path

            info = pdfinfo_from_path(str(pdf_path))
            return info.get("Pages", 0)
        except ImportError:
            raise RuntimeError("pdf2image not installed")
        except Exception as e:
            logger.error(f"Failed to get PDF info: {e}")
            raise

    async def convert_single_page(
        self,
        pdf_path: str,
        page_num: int,
        output_path: Optional[str] = None,
    ) -> str:
        """Convert a single PDF page to an image.

        Args:
            pdf_path: Path to the PDF file
            page_num: Page number to convert (1-indexed)
            output_path: Path to save the image (default: auto-generated)

        Returns:
            Path to the generated image file
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            from pdf2image import convert_from_path
        except ImportError:
            raise RuntimeError("pdf2image not installed")

        try:
            images = convert_from_path(
                str(pdf_path),
                dpi=self._dpi,
                first_page=page_num,
                last_page=page_num,
                fmt=self._format,
            )

            if not images:
                raise RuntimeError(f"Failed to convert page {page_num}")

            # Save image
            if output_path:
                out_path = Path(output_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                out_path = Path(tempfile.mktemp(suffix=f".{self._format}"))

            images[0].save(str(out_path))
            logger.info(f"Converted page {page_num} -> {out_path.name}")

            return str(out_path)

        except Exception as e:
            logger.error(f"Failed to convert page {page_num}: {e}")
            raise
