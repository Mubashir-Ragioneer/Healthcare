# services/file_ingestor.py
from fastapi import UploadFile
import aiofiles
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import requests

async def process_file(file: UploadFile) -> dict:
    content = await file.read()
    # PDF text extract
    if file.filename.lower().endswith('.pdf'):
        doc = fitz.open(stream=content, filetype='pdf')
        text = "".join(page.get_text() for page in doc)
        return {"text": text[:200]}
    # other file types...
    return {"filename": file.filename}

async def process_url(url: str) -> dict:
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    return {"title": soup.title.string if soup.title else None}