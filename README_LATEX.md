# LaTeX Conversion - FYP Interim Report

This directory contains the LaTeX version of `FYP_TOH_KAR_LE_Interrim_Report.docx`.

## Quick Summary

This interim report outlines the project motivation and scope, surveys related work, and documents the proposed methodology and system design. It also describes the implementation plan, preliminary progress to date, and the evaluation plan with milestones for the remaining work.

## Structure

```
fyp/
├── main.tex                          # Main LaTeX document
├── chapters/                         # Chapter files
│   ├── abstract.tex                  # Abstract
│   ├── chapter_1.tex                 # Chapter 1: Introduction
│   ├── chapter_2.tex                 # Chapter 2: Related Work
│   ├── chapter_3.tex                 # Chapter 3
│   ├── chapter_4.tex                 # Chapter 4
│   └── chapter_5.tex                 # Chapter 5
├── figures/                          # All images (68 files)
│   ├── image1.jpeg
│   ├── image2.png
│   └── ...
├── convert_docx_to_latex.py         # Conversion script (for reference)
└── README_LATEX.md                   # This file
```

## Compilation Instructions

### Prerequisites

You need a LaTeX distribution installed:

- **macOS**: Install [MacTeX](https://www.tug.org/mactex/)
  ```bash
  brew install --cask mactex
  ```

- **Linux**: Install TeX Live
  ```bash
  sudo apt-get install texlive-full   # Debian/Ubuntu
  sudo dnf install texlive-scheme-full # Fedora
  ```

- **Windows**: Install [MiKTeX](https://miktex.org/) or [TeX Live](https://www.tug.org/texlive/)

### Compiling the Document

Once LaTeX is installed, compile from the repository root:

#### Recommended (latexmk)
```bash
latexmk -pdf main.tex
```

If you use citations and `references.bib`:
```bash
latexmk -pdf -bibtex main.tex
```

#### Manual (pdflatex + bibtex)
```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

#### Alternative (xelatex)
```bash
xelatex main.tex
xelatex main.tex
```

### Expected Output

After compilation, you should get:
- `main.pdf` - The final PDF document
- `main.aux`, `main.log`, `main.toc` - Auxiliary files
- `main.lof`, `main.lot` - List of figures and tables

## Document Features

The LaTeX document includes:

- **Document class**: `report` (12pt, A4 paper)
- **Packages used**:
  - `graphicx` - Image inclusion
  - `amsmath, amssymb` - Mathematical symbols
  - `hyperref` - Hyperlinks and references
  - `booktabs` - Professional tables
  - `listings` - Code formatting
  - `float` - Better float positioning
  - `caption, subcaption` - Enhanced captions

- **Structure**:
  - Title page with NTU logo
  - Abstract
  - Table of contents
  - List of figures and tables
  - 5 chapters with proper sectioning

## Customization

### Adjusting Margins
Edit in `main.tex`:
```latex
\usepackage[margin=1in]{geometry}  % Change 1in to desired margin
```

### Figure Width
Figures are set to 80% text width by default. Edit in chapter files:
```latex
\includegraphics[width=0.8\textwidth]{figures/imageX.png}  % Change 0.8 to desired width
```

### Font Size
Change in document class declaration:
```latex
\documentclass[12pt,a4paper]{report}  % Change 12pt to 10pt or 11pt
```

## Known Issues and Notes

1. **Figure Captions**: The conversion script uses generic captions. You may want to manually update them with the actual captions from the Word document.

2. **Table Formatting**: Tables are converted with basic formatting. You may need to adjust column widths and alignment manually.

3. **Mathematical Equations**: If your document contains complex equations, verify they were converted correctly.

4. **Bibliography**: If you need citations, uncomment the bibliography section in `main.tex` and create a `references.bib` file.

5. **Special Characters**: The conversion automatically escapes LaTeX special characters (&, %, _, $, #, {, }, ~, ^).

## Troubleshooting

### "File not found" errors
- Ensure all chapter files exist in `chapters/`
- Check that image files are in `figures/`

### "Undefined control sequence"
- Make sure all required packages are installed
- Check for unescaped special characters

### Images not appearing
- Verify the `\graphicspath{{figures/}}` is correct
- Ensure image files have correct extensions (.png, .jpeg, .jpg)

### Compilation takes too long
- This is normal for documents with many images
- Use `pdflatex -interaction=batchmode main.tex` for faster compilation

## Re-running the Conversion

If you need to re-convert the Word document:

```bash
python3 convert_docx_to_latex.py
```

This will regenerate all chapter files in `chapters/`.

## Support

For LaTeX-specific questions, refer to:
- [LaTeX Wikibook](https://en.wikibooks.org/wiki/LaTeX)
- [TeX StackExchange](https://tex.stackexchange.com/)
- [Overleaf Documentation](https://www.overleaf.com/learn)

## Online Compilation

If you don't want to install LaTeX locally, you can use [Overleaf](https://www.overleaf.com/):

1. Create a new project on Overleaf
2. Upload `main.tex`, the `chapters/` folder, and the `figures/` folder
3. Compile directly in your browser
