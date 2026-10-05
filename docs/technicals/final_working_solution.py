#!/usr/bin/env python3
"""
Generate <PLTF_NAME>-Marketing.pdf from the PLATFORM_OVERVIEW.md content.

The platform display name and output filename are derived from PLTF_NAME in
conf/deploy.ini (falling back to the canonical default) so the generated
document carries the configured platform identity rather than a hardcoded one.
"""

import os
import re
import sys
from datetime import datetime
from fpdf import FPDF


def get_platform_name():
    """Read PLTF_NAME from conf/deploy.ini, falling back to the canonical
    default. Mirrors the tiny parser used across the platform's shell/py glue."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('PLTF_NAME'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return 'agentic-ai-plateform_AI_SharedGPU_Docker_Serverless'


PLATFORM_NAME = get_platform_name()
PLATFORM_SLUG = re.sub(r'[^A-Za-z0-9._-]+', '-', PLATFORM_NAME).strip('-') or 'platform'
SOURCE_DOC = 'PLATFORM_OVERVIEW.md'


class MarketingPDF(FPDF):
    def __init__(self):
        super().__init__()
        # ASCII-safe document title to avoid Unicode issues in PDF metadata.
        self.document_title = (
            f"{PLATFORM_NAME} - Marketing Document".encode('ascii', 'ignore').decode('ascii')
        )

    def header(self):
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, self.document_title, 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.cell(0, 10, f'Generated on {datetime.now().strftime("%Y-%m-%d")}', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def add_title(self, title):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(5)

    def add_subtitle(self, subtitle):
        self.set_font('Arial', 'I', 12)
        self.cell(0, 8, subtitle, 0, 1, 'L')
        self.ln(3)

    def text_block(self, text):
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 5, text)
        self.ln(3)

    def code_block(self, code):
        self.set_font('Courier', '', 10)
        self.multi_cell(0, 5, code)
        self.set_font('Arial', '', 11)
        self.ln(3)

    def table_block(self, lines):
        # Simple table rendering - just display as text for now
        for line in lines:
            self.text_block(line)

def generate_marketing_pdf():
    # Read the platform overview content (resolved next to this script).
    source_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SOURCE_DOC)
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: {SOURCE_DOC} not found at {source_path}")
        return False

    # Inject the configured platform name wherever the source uses the sentinel.
    content = content.replace('@@PLATFORM_NAME@@', PLATFORM_NAME)

    # Convert to ASCII, ignoring non-ASCII characters
    # This will strip out all Unicode characters that can't be represented in ASCII
    ascii_content = content.encode('ascii', 'ignore').decode('ascii')
    
    # Create PDF
    pdf = MarketingPDF()
    pdf.add_page()
    
    # Split content into paragraphs (separated by double newlines)
    paragraphs = ascii_content.split('\n\n')
    
    # Process each paragraph
    i = 0
    while i < len(paragraphs):
        paragraph = paragraphs[i].strip()
        if not paragraph:
            i += 1
            continue
            
        # Handle different section types
        if paragraph.startswith('# '):
            title = paragraph[2:].strip()
            # Ensure title doesn't contain Unicode characters
            ascii_title = title.encode('ascii', 'ignore').decode('ascii')
            pdf.add_title(ascii_title)
        elif paragraph.startswith('## '):
            subtitle = paragraph[3:].strip()
            # Ensure subtitle doesn't contain Unicode characters
            ascii_subtitle = subtitle.encode('ascii', 'ignore').decode('ascii')
            pdf.add_subtitle(ascii_subtitle)
        elif paragraph.startswith('### '):
            subtitle = paragraph[4:].strip()
            # Ensure subtitle doesn't contain Unicode characters
            ascii_subtitle = subtitle.encode('ascii', 'ignore').decode('ascii')
            pdf.add_subtitle(ascii_subtitle)
        elif paragraph.startswith('|') and '|' in paragraph:
            # Handle table - collect all table lines
            table_lines = []
            j = i
            while j < len(paragraphs) and (paragraphs[j].strip().startswith('|') or not paragraphs[j].strip()):
                table_lines.append(paragraphs[j].strip())
                j += 1
            if table_lines:
                pdf.table_block(table_lines)
                i = j - 1  # Skip processed lines
        elif paragraph.startswith('```'):
            # Handle code block
            code_lines = []
            j = i + 1
            while j < len(paragraphs) and not paragraphs[j].strip() == '```':
                code_lines.append(paragraphs[j].strip())
                j += 1
            if code_lines:
                code_text = '\n'.join(code_lines)
                pdf.code_block(code_text)
            i = j  # Skip to end of code block
        elif paragraph.startswith('- ') or paragraph.startswith('* '):
            # Bullet point - treat as regular text
            pdf.text_block(paragraph)
        elif paragraph.startswith('> '):
            # Blockquote - treat as regular text
            pdf.text_block(paragraph)
        else:
            # Regular paragraph
            pdf.text_block(paragraph)
        
        i += 1
    
    # Save PDF next to this script, named after the configured platform.
    output_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), f'{PLATFORM_SLUG}-Marketing.pdf'
    )
    try:
        pdf.output(output_file)
        print(f"Successfully generated {output_file}")
        return True
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = generate_marketing_pdf()
    if not success:
        sys.exit(1)