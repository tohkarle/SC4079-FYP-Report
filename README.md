# LaTeX Conversion - FYP Interim Report

This directory contains the LaTeX version of `FYP_TOH_KAR_LE_Interrim_Report.docx`.

## Quick Summary

This interim report outlines the project motivation and scope, surveys related work, and documents the proposed methodology and system design. It also describes the implementation plan, preliminary progress to date, and the evaluation plan with milestones for the remaining work.

## Structure

```
fyp/
├── fyp_report.tex                    # Main LaTeX document
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
└── README.md                         # This file
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
latexmk -pdf fyp_report.tex
```

If you use citations and `references.bib`:
```bash
latexmk -pdf -bibtex fyp_report.tex
```

#### Manual (pdflatex + bibtex)
```bash
pdflatex fyp_report.tex
bibtex fyp_report
pdflatex fyp_report.tex
pdflatex fyp_report.tex
```

#### Alternative (xelatex)
```bash
xelatex fyp_report.tex
xelatex fyp_report.tex
```

### Expected Output

After compilation, you should get:
- `fyp_report.pdf` - The final PDF document
- `fyp_report.aux`, `fyp_report.log`, `fyp_report.toc` - Auxiliary files
- `fyp_report.lof`, `fyp_report.lot` - List of figures and tables

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
- Use `pdflatex -interaction=batchmode fyp_report.tex` for faster compilation

## Support

For LaTeX-specific questions, refer to:
- [LaTeX Wikibook](https://en.wikibooks.org/wiki/LaTeX)
- [TeX StackExchange](https://tex.stackexchange.com/)
- [Overleaf Documentation](https://www.overleaf.com/learn)

## Online Compilation

If you don't want to install LaTeX locally, you can use [Overleaf](https://www.overleaf.com/):

1. Create a new project on Overleaf
2. Upload `fyp_report.tex`, the `chapters/` folder, and the `figures/` folder
3. Compile directly in your browser
