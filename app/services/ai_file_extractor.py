import io
from fastapi import UploadFile
from pypdf import PdfReader
from docx import Document

class FileExtractor:
    """Extrahiert Text aus hochgeladenen Dokumenten (.pdf, .docx, .txt)"""
    
    @staticmethod
    async def extract_text(file: UploadFile) -> str:
        content = await file.read()
        filename = file.filename.lower()
        
        if filename.endswith(".pdf"):
            return FileExtractor._extract_pdf(content)
        elif filename.endswith(".docx"):
            return FileExtractor._extract_docx(content)
        elif filename.endswith(".txt"):
            return content.decode("utf-8", errors="replace")
        else:
            raise ValueError(f"Nicht unterstütztes Dateiformat: {filename}")
            
    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        pdf_reader = PdfReader(io.BytesIO(content))
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
        
    @staticmethod
    def _extract_docx(content: bytes) -> str:
        doc = Document(io.BytesIO(content))
        return "\n".join([paragraph.text for paragraph in doc.paragraphs]).strip()
