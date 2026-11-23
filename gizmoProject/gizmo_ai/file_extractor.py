"""
GIZMO File Text Extractor
=========================
Extracts raw text from uploaded student answer files.
Supports: PDF, DOCX, PPTX, TXT, images (via pytesseract OCR)

All extractors degrade gracefully if a library is not installed.
"""

from __future__ import annotations
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def extract_text(file_path: str) -> str:
    """
    Main entry point. Given a path to an uploaded file, return its text content.
    Returns empty string if extraction fails or format is unsupported.
    """
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return ""

    ext = os.path.splitext(file_path)[1].lower()

    extractors = {
        '.pdf':  _extract_pdf,
        '.docx': _extract_docx,
        '.doc':  _extract_docx,
        '.pptx': _extract_pptx,
        '.txt':  _extract_txt,
        '.md':   _extract_txt,
        '.rtf':  _extract_txt,
        '.png':  _extract_image,
        '.jpg':  _extract_image,
        '.jpeg': _extract_image,
        '.bmp':  _extract_image,
        '.tiff': _extract_image,
        '.tif':  _extract_image,
        '.webp': _extract_image,
    }

    extractor = extractors.get(ext)
    if extractor is None:
        logger.warning(f"Unsupported file type: {ext}. Returning empty string.")
        return ""

    try:
        text = extractor(file_path)
        text = _clean_extracted(text)
        logger.info(f"Extracted {len(text)} chars from {ext} file.")
        return text
    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {e}")
        return ""


def _clean_extracted(text: str) -> str:
    """Remove excessive whitespace and null bytes from extracted text."""
    if not text:
        return ""
    import re
    text = text.replace('\x00', '')               # null bytes
    text = re.sub(r'\n{3,}', '\n\n', text)        # triple+ newlines → double
    text = re.sub(r'[ \t]{2,}', ' ', text)        # multiple spaces → single
    return text.strip()


def _extract_pdf(path: str) -> str:
    """Extract text from PDF using pdfminer (preferred) or pypdf2 fallback."""
    # Try pdfminer first (best for text-based PDFs)
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        text = pdfminer_extract(path)
        if text and text.strip():
            return text
    except ImportError:
        logger.debug("pdfminer not installed, trying pypdf.")
    except Exception as e:
        logger.warning(f"pdfminer failed: {e}")

    # Try pypdf (formerly PyPDF2)
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
        text = "\n".join(pages)
        if text.strip():
            return text
    except ImportError:
        logger.debug("pypdf not installed.")
    except Exception as e:
        logger.warning(f"pypdf failed: {e}")

    # If both fail and it might be a scanned PDF, try OCR
    return _extract_scanned_pdf(path)


def _extract_scanned_pdf(path: str) -> str:
    """Convert scanned PDF pages to images then OCR them."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(path, dpi=200)
        texts = []
        for img in images:
            t = pytesseract.image_to_string(img, lang='eng')
            if t.strip():
                texts.append(t)
        return "\n".join(texts)
    except ImportError:
        logger.debug("pdf2image or pytesseract not installed — cannot OCR scanned PDF.")
    except Exception as e:
        logger.warning(f"OCR PDF failed: {e}")
    return ""


def _extract_docx(path: str) -> str:
    """Extract text from .docx files."""
    try:
        from docx import Document
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except ImportError:
        logger.debug("python-docx not installed.")
    except Exception as e:
        logger.warning(f"DOCX extraction failed: {e}")
    return ""


def _extract_pptx(path: str) -> str:
    """Extract text from .pptx files (notes + slide text)."""
    try:
        from pptx import Presentation
        prs = Presentation(path)
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, 'text') and shape.text.strip():
                    texts.append(shape.text)
            # Slide notes
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text
                if notes.strip():
                    texts.append(notes)
        return "\n".join(texts)
    except ImportError:
        logger.debug("python-pptx not installed.")
    except Exception as e:
        logger.warning(f"PPTX extraction failed: {e}")
    return ""


def _extract_txt(path: str) -> str:
    """Read plain text files."""
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"TXT extraction failed ({enc}): {e}")
            break
    return ""


def _extract_image(path: str) -> str:
    """Extract text from images using Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path)
        # Convert to greyscale for better OCR accuracy
        img = img.convert('L')
        text = pytesseract.image_to_string(img, lang='eng', config='--psm 6')
        return text
    except ImportError:
        logger.debug("pytesseract or Pillow not installed — cannot OCR image.")
    except Exception as e:
        logger.warning(f"Image OCR failed: {e}")
    return ""


def get_word_count(text: str) -> int:
    """Count words in text."""
    if not text:
        return 0
    import re
    words = re.findall(r'\b\w+\b', text)
    return len(words)