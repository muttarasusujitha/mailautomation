"""
PDF Processing Utility — Extract text from PDF files using PyMuPDF
"""

import io
import logging
from typing import Optional, Tuple
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_content: bytes, max_pages: int = 50) -> Tuple[str, bool]:
    """
    Extract all text from PDF content.
    
    Args:
        file_content: PDF file bytes
        max_pages: Maximum pages to extract (None for all)
        
    Returns:
        Tuple of (extracted_text, success)
    """
    if not fitz:
        return "", False
    
    try:
        pdf_document = fitz.open(stream=file_content, filetype="pdf")
        extracted_text = ""
        
        pages_to_process = min(len(pdf_document), max_pages) if max_pages else len(pdf_document)
        
        for page_num in range(pages_to_process):
            page = pdf_document[page_num]
            text = page.get_text(preserve_images=False)
            extracted_text += text + "\n"
        
        pdf_document.close()
        return extracted_text.strip(), True
        
    except Exception:
        logger.exception("PDF extraction error")
        return "", False


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Simple wrapper to extract text from PDF bytes.
    Returns empty string if extraction fails.
    """
    text, success = extract_text_from_pdf(pdf_bytes)
    return text if success else ""


def get_pdf_metadata(file_content: bytes) -> dict:
    """
    Extract metadata from PDF (page count, author, etc).
    """
    if not fitz:
        return {}
    
    try:
        pdf_document = fitz.open(stream=file_content, filetype="pdf")
        metadata = {
            "page_count": len(pdf_document),
            "title": pdf_document.metadata.get("title", ""),
            "author": pdf_document.metadata.get("author", ""),
            "subject": pdf_document.metadata.get("subject", ""),
        }
        pdf_document.close()
        return metadata
    except Exception:
        logger.exception("Metadata extraction error")
        return {}
