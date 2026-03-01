import re
from unstructured.partition.pdf import partition_pdf
from langchain_core.documents import Document

def clean_text(text: str) -> str:
    """
    Cleans extracted text by removing repeated headers, fixing broken sentences,
    and removing excessive whitespace.
    """
    if not text:
        return ""
    
    # Remove repeated headers/footers (basic heuristic: lines with mostly non-alphanumeric or short lines repeating)
    # Since we are using unstructured's layout detection, we just need to clean up minor artifacts.
    
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Fix broken sentences (e.g., "This is a \n broken sentence.")
    text = re.sub(r'([a-z])-\s+([a-z])', r'\1\2', text) # merge hyphenated words at line breaks
    
    return text.strip()

def extract_layout_aware_text(file_path: str) -> list[Document]:
    """
    Extracts text from a PDF while preserving layout (reading order, columns).
    Uses unstructured's layout detection.
    """
    try:
        elements = partition_pdf(
            filename=file_path,
            strategy="hi_res",
            infer_table_structure=True
        )
    except Exception as e:
        print(f"Layout-aware extraction failed: {e}. Falling back to raw text...")
        raise
    
    paragraphs = []
    current_page = 1
    
    for element in elements:
        # Filter out headers and footers to prevent repetition
        if element.category in ["Header", "Footer"]:
            continue
            
        page_num = element.metadata.page_number if hasattr(element, "metadata") and getattr(element.metadata, "page_number", None) else current_page
        current_page = page_num
        
        text = str(element)
        cleaned_text = clean_text(text)
        
        if cleaned_text:
            paragraphs.append(Document(
                page_content=cleaned_text,
                metadata={"source": file_path, "page": page_num - 1} # 0-indexed page to match PyPDFLoader
            ))
            
    return paragraphs
