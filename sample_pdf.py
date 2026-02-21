"""Generate a sample PDF for testing the PDF QA Bot."""
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except ImportError:
    print("Installing reportlab...")
    import subprocess
    subprocess.check_call(["pip", "install", "reportlab"])
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

def create_sample_pdf():
    output_path = "sample_document.pdf"
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter

    # Title
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, height - 72, "Sample Document for PDF QA Bot")
    c.setFont("Helvetica", 12)

    # Content
    lines = [
        "Introduction",
        "This is a sample PDF document created for testing the PDF QA Bot.",
        "You can upload this file and ask questions about its contents.",
        "",
        "Key Features of PDF QA Bot:",
        "1. Upload any PDF document",
        "2. Ask questions in natural language",
        "3. Get answers based on the document content",
        "4. Summarize the entire document",
        "5. Conversation history maintains context across questions",
        "",
        "How to Use:",
        "Upload this PDF, wait for processing, then ask questions like:",
        '- "What is this document about?"',
        '- "What are the key features?"',
        '- "How do I use the PDF QA Bot?"',
        "",
        "Technical Details:",
        "The bot uses RAG (Retrieval Augmented Generation) to find relevant",
        "text from your PDF and generates answers using a language model.",
    ]
    y = height - 100
    for line in lines:
        c.drawString(72, y, line[:90])
        y -= 16

    c.save()
    print(f"Created {output_path}")
    return output_path

if __name__ == "__main__":
    create_sample_pdf()
