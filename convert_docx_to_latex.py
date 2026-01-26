#!/usr/bin/env python3
"""
Convert DOCX (extracted) to LaTeX format
Processes the Word document XML and generates structured LaTeX files
"""

import xml.etree.ElementTree as ET
import re
import os
from pathlib import Path

# XML namespaces
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
}

def escape_latex(text):
    """Escape special LaTeX characters"""
    if not text:
        return ""

    # First handle special LaTeX characters (except those we'll use in math mode)
    replacements = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '#': r'\#',
        '_': r'\_',
        '~': r'\textasciitilde{}',
    }

    for char, replacement in replacements.items():
        text = text.replace(char, replacement)

    # Then handle Unicode characters (some use $ for math mode)
    unicode_replacements = {
        '–': '--',           # En dash
        '—': '---',          # Em dash
        ''': "'",            # Smart single quote
        ''': "'",
        '"': '"',            # Smart double quotes
        '"': '"',
        '→': r'$\rightarrow$',  # Right arrow
        '×': r'$\times$',    # Multiplication sign
        '≥': r'$\geq$',      # Greater than or equal
        '≤': r'$\leq$',      # Less than or equal
        'ï': r'\"{i}',       # i with diaeresis
        '°': r'$^\circ$',    # Degree symbol
    }

    for char, replacement in unicode_replacements.items():
        text = text.replace(char, replacement)

    # Finally escape remaining special chars (but not $ if already in math mode)
    # We need to be careful with $ - only escape standalone ones
    # For now, escape { } ^ that weren't already escaped
    final_replacements = {
        '{': r'\{',
        '}': r'\}',
        '^': r'\textasciicircum{}',
    }

    for char, replacement in final_replacements.items():
        # Only replace if not preceded by backslash
        import re
        text = re.sub(r'(?<!\\)' + re.escape(char), replacement, text)

    return text

def get_paragraph_text(para):
    """Extract all text from a paragraph element"""
    texts = []
    for text in para.findall('.//w:t', NS):
        if text.text:
            texts.append(text.text)
    return ''.join(texts)

def is_bold(run):
    """Check if a run is bold"""
    bold = run.find('.//w:b', NS)
    return bold is not None

def is_italic(run):
    """Check if a run is italic"""
    italic = run.find('.//w:i', NS)
    return italic is not None

def get_styled_text(para):
    """Get text with LaTeX formatting applied"""
    result = []
    for run in para.findall('.//w:r', NS):
        text_elem = run.find('.//w:t', NS)
        if text_elem is not None and text_elem.text:
            text = escape_latex(text_elem.text)

            if is_bold(run) and is_italic(run):
                text = f"\\textbf{{\\textit{{{text}}}}}"
            elif is_bold(run):
                text = f"\\textbf{{{text}}}"
            elif is_italic(run):
                text = f"\\textit{{{text}}}"

            result.append(text)

    return ''.join(result)

def identify_heading_level(para):
    """Identify if paragraph is a heading and its level"""
    text = get_paragraph_text(para).strip()

    # Check for chapter
    if text.startswith('Chapter '):
        return ('chapter', text.replace('Chapter ', '').strip())

    # Check for section numbers
    section_match = re.match(r'^(\d+\.\d+\.\d+\.?\d*)\s+(.+)$', text)
    if section_match:
        num, title = section_match.groups()
        depth = num.count('.')
        if depth >= 2:
            return ('subsubsection', title)
        elif depth >= 1:
            return ('subsection', title)
        else:
            return ('section', title)

    section_match = re.match(r'^(\d+\.\d+)\s+(.+)$', text)
    if section_match:
        return ('subsection', section_match.group(2))

    section_match = re.match(r'^(\d+\.)\s+(.+)$', text)
    if section_match:
        return ('section', section_match.group(2))

    # Special sections
    if text in ['Abstract', 'Introduction', 'Background', 'Conclusion', 'References']:
        return ('section', text)

    return (None, None)

def parse_image_relationships(rels_file):
    """Parse relationships file to map rId to image filenames"""
    if not os.path.exists(rels_file):
        return {}

    tree = ET.parse(rels_file)
    root = tree.getroot()

    rel_ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    relationships = {}

    for rel in root.findall('.//r:Relationship', rel_ns):
        rel_id = rel.get('Id')
        target = rel.get('Target')
        if target and 'media/' in target:
            filename = os.path.basename(target)
            relationships[rel_id] = filename

    return relationships

def process_image(drawing, rel_map, figure_counter):
    """Process an image/drawing element and return LaTeX figure code"""
    # Try to find the image reference
    blip = drawing.find('.//a:blip', NS)
    if blip is None:
        return None

    embed_id = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
    if not embed_id or embed_id not in rel_map:
        return None

    image_file = rel_map[embed_id]

    # Try to find caption (usually in the next paragraph)
    caption = f"Figure {figure_counter}"

    latex_code = f"""\\begin{{figure}}[htbp]
  \\centering
  \\includegraphics[width=0.8\\textwidth]{{figures/{image_file}}}
  \\caption{{{caption}}}
  \\label{{fig:fig{figure_counter}}}
\\end{{figure}}
"""
    return latex_code

def process_table(table):
    """Convert a Word table to LaTeX tabular"""
    rows = table.findall('.//w:tr', NS)
    if not rows:
        return ""

    latex_rows = []
    for row in rows:
        cells = row.findall('.//w:tc', NS)
        cell_texts = []
        for cell in cells:
            cell_text = []
            for para in cell.findall('.//w:p', NS):
                text = get_paragraph_text(para).strip()
                if text:
                    cell_text.append(escape_latex(text))
            cell_texts.append(' '.join(cell_text))
        latex_rows.append(' & '.join(cell_texts) + ' \\\\')

    num_cols = len(cells) if cells else 3
    col_spec = 'l' * num_cols

    latex_code = f"""\\begin{{table}}[htbp]
  \\centering
  \\caption{{Table}}
  \\begin{{tabular}}{{{col_spec}}}
    \\toprule
"""

    if latex_rows:
        latex_code += '    ' + latex_rows[0] + '\n'
        latex_code += '    \\midrule\n'
        for row in latex_rows[1:]:
            latex_code += '    ' + row + '\n'

    latex_code += """    \\bottomrule
  \\end{tabular}
\\end{table}
"""
    return latex_code

def process_document(doc_file, rels_file, output_dir='chapters'):
    """Main processing function"""
    tree = ET.parse(doc_file)
    root = tree.getroot()
    body = root.find('.//w:body', NS)

    if body is None:
        print("Error: Could not find document body")
        return

    # Parse image relationships
    rel_map = parse_image_relationships(rels_file)

    # Storage for different chapters
    chapters = {}
    current_chapter = None
    current_content = []
    figure_counter = 1
    in_abstract = False

    # Convert body children to list for lookahead
    body_elements = list(body)
    i = 0

    # Process all paragraphs and tables
    while i < len(body_elements):
        elem = body_elements[i]
        # Handle paragraphs
        if elem.tag == f'{{{NS["w"]}}}p':
            text = get_paragraph_text(elem).strip()

            if not text:
                # Check if there's an image
                drawing = elem.find('.//w:drawing', NS)
                if drawing is not None:
                    img_latex = process_image(drawing, rel_map, figure_counter)
                    if img_latex:
                        current_content.append(img_latex)
                        figure_counter += 1
                i += 1
                continue

            # Check for "Chapter N" pattern and look ahead for actual title
            if text.startswith('Chapter '):
                # Look ahead to next paragraph for chapter title
                chapter_num = text.replace('Chapter ', '').strip()
                chapter_title = None

                # Check next paragraph for the title
                if i + 1 < len(body_elements):
                    next_elem = body_elements[i + 1]
                    if next_elem.tag == f'{{{NS["w"]}}}p':
                        next_text = get_paragraph_text(next_elem).strip()
                        # Check if it's not a numbered section (like 1.1, 1.2)
                        if next_text and not re.match(r'^\d+\.\d+', next_text):
                            chapter_title = next_text
                            i += 1  # Skip the next paragraph since we consumed it

                # If we didn't find a title, use the chapter number
                if not chapter_title:
                    chapter_title = chapter_num

                # Save previous chapter
                if current_chapter and current_content:
                    chapters[current_chapter] = '\n'.join(current_content)

                # Start new chapter
                current_chapter = chapter_title.lower().replace(' ', '_')
                current_content = [f"\\chapter{{{escape_latex(chapter_title)}}}"]
                in_abstract = False
                i += 1
                continue

            # Check if it's Abstract
            if text == 'Abstract':
                # Save previous chapter
                if current_chapter and current_content:
                    chapters[current_chapter] = '\n'.join(current_content)

                current_chapter = 'abstract'
                current_content = []
                in_abstract = True
                i += 1
                continue

            # Check for numbered sections (1.1, 1.2, 1.1.1, etc.)
            section_match = re.match(r'^(\d+\.\d+\.\d+)\s+(.+)$', text)
            if section_match:
                title = section_match.group(2)
                current_content.append(f"\\subsection{{{escape_latex(title)}}}")
                i += 1
                continue

            section_match = re.match(r'^(\d+\.\d+)\s+(.+)$', text)
            if section_match:
                title = section_match.group(2)
                current_content.append(f"\\section{{{escape_latex(title)}}}")
                i += 1
                continue

            # Regular paragraph
            styled_text = get_styled_text(elem)
            if styled_text.strip():
                current_content.append(styled_text)
                current_content.append('')  # Add blank line

        # Handle tables
        elif elem.tag == f'{{{NS["w"]}}}tbl':
            table_latex = process_table(elem)
            if table_latex:
                current_content.append(table_latex)

        i += 1

    # Save last chapter
    if current_chapter and current_content:
        chapters[current_chapter] = '\n'.join(current_content)

    # Write chapter files
    os.makedirs(output_dir, exist_ok=True)

    for chapter_name, content in chapters.items():
        if chapter_name == 'abstract':
            filename = f'{output_dir}/abstract.tex'
        else:
            filename = f'{output_dir}/chapter_{chapter_name}.tex'

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Created: {filename}")

    return list(chapters.keys())

def main():
    doc_file = '/tmp/docx_extract/word/document.xml'
    rels_file = '/tmp/docx_extract/word/_rels/document.xml.rels'

    print("Starting conversion...")
    chapters = process_document(doc_file, rels_file)
    print(f"\nConversion complete! Created {len(chapters)} chapter files.")
    print(f"Chapters: {', '.join(chapters)}")

if __name__ == '__main__':
    main()
