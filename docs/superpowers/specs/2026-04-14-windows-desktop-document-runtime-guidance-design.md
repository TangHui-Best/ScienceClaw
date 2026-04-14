# Windows Desktop Document Runtime Guidance Design

**Date:** 2026-04-14  
**Status:** Approved  
**Target:** Windows desktop local-mode packaging

## Goal

Keep the desktop installer self-contained for all Python and Node-based document skill logic, while removing the separate offline document runtime plugin path entirely.

## Decisions

### 1. What ships in the main installer

The Windows desktop installer includes:

- embedded Python runtime
- backend Python dependencies required by builtin document skills
- embedded Node.js runtime
- Node modules required by builtin document skills:
  - `docx`
  - `pptxgenjs`

This keeps the packaged app able to execute the document skills that only depend on Python libraries or Node modules already used by the builtin scripts.

### 2. What does not ship in the installer

The installer does not bundle heavyweight desktop applications that are typically installed through their own installers or system packages, including:

- `LibreOffice`
- `Pandoc`
- `Tesseract OCR`

These tools remain external prerequisites when a specific builtin skill workflow depends on them.

### 3. User experience model

The application runtime stays decoupled from any plugin or post-install package.

- no runtime plugin zip
- no plugin installer or uninstaller
- no extra `runtime-tools/` directory
- no application-side plugin management

When an external tool is missing, the program keeps the current behavior and surfaces the original command failure as-is.

### 4. Documentation model

End-user setup guidance for Windows local mode lives in a dedicated Chinese document instead of inside builtin skill `SKILL.md` files.

- add a standalone user guide under `docs/`
- keep builtin skill `SKILL.md` focused on technical and agent-facing usage
- keep `electron-app/README.md` as a short entry point that links to the Chinese guide

## Impacted Areas

- `build-windows.ps1`
  - must prepare Python dependencies and bundled Node runtime/modules
- `electron-app/package.json`
  - must package the bundled Node runtime as app resources
- `electron-app/src/runtime.ts`
  - must expose bundled `node` and `NODE_PATH` to backend processes
- user guide doc
  - a standalone Chinese guide must describe Windows local-mode prerequisites clearly
- builtin skill docs
  - remove user-facing prerequisite guidance that was temporarily added there
- obsolete plugin assets
  - plugin build/test/docs must be removed to avoid conflicting guidance

## User Guide Coverage

The dedicated Chinese user guide only targets Windows desktop local mode. It does not need to document sandbox-mode setup.

### DOCX

- bundled: Python runtime, backend Python deps, Node runtime, `docx`
- external:
  - `Pandoc` for some extraction workflows
  - `LibreOffice` for `.doc` conversion, PDF conversion, accepting tracked changes

### PDF

- bundled: Python PDF libraries, `pypdfium2`, `pytesseract`
- external:
  - `Tesseract OCR` for OCR command execution
- optional:
  - `pdftotext` from Poppler for better academic two-column extraction

### PPTX

- bundled: Python runtime, `markitdown[pptx]`, Node runtime, `pptxgenjs`
- external:
  - `LibreOffice` for PPTX-to-PDF conversion and image QA workflow

### XLSX

- bundled: Python spreadsheet libraries such as `openpyxl`
- external:
  - `LibreOffice` for formula recalculation through `scripts/recalc.py`

## Verification

Implementation is complete when:

1. the plugin build path is absent from the repository
2. the desktop runtime test still passes with bundled Node support
3. repo searches no longer present the obsolete plugin flow as the recommended solution
4. the dedicated Chinese user guide covers the new local prerequisite model
5. builtin skill docs no longer contain user-facing desktop prerequisite sections
