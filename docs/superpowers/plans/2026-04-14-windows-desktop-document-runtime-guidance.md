# Windows Desktop Document Runtime Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Python and Node document runtimes bundled in the desktop installer, remove the abandoned offline plugin path, and move Windows local-mode end-user dependency instructions into a dedicated Chinese guide instead of builtin skill docs.

**Architecture:** Reuse the existing desktop packaging flow for Python and Node assets. Remove the parallel plugin packaging path so there is only one supported build story. Put Windows local-mode end-user setup in a standalone Chinese guide, while keeping builtin skill docs focused on technical usage plus only the minimum environment-neutral corrections.

**Tech Stack:** PowerShell, Electron Builder, Node.js, embedded Python, markdown skill docs

---

### Task 1: Preserve the main-installer runtime path

**Files:**
- Modify: `build-windows.ps1`
- Modify: `electron-app/package.json`
- Modify: `electron-app/src/runtime.ts`
- Modify: `electron-app/test/runtime.test.js`

- [ ] Confirm the build script downloads Node, installs `docx` and `pptxgenjs`, and stages the runtime under `build/node`.
- [ ] Confirm Electron Builder packages `build/node` into `resources/node`.
- [ ] Confirm backend environment wiring prepends bundled `node` to `PATH` and sets `NODE_PATH`.
- [ ] Verify the runtime test covers the bundled Node path and `NODE_PATH`.

### Task 2: Remove obsolete plugin packaging

**Files:**
- Delete: `build-windows-document-runtime.ps1`
- Delete: `packaging/windows-document-runtime/common.ps1`
- Delete: `packaging/windows-document-runtime/install.ps1`
- Delete: `packaging/windows-document-runtime/README.md`
- Delete: `packaging/windows-document-runtime/sources.ps1`
- Delete: `packaging/windows-document-runtime/uninstall.ps1`
- Delete: `tests/powershell/document-runtime-plugin.tests.ps1`
- Delete: `docs/superpowers/specs/2026-04-13-windows-document-runtime-packaging-design.md`
- Delete: `docs/superpowers/specs/2026-04-14-windows-offline-document-runtime-plugin-design.md`
- Delete: `docs/superpowers/plans/2026-04-14-windows-offline-document-runtime-plugin.md`

- [ ] Remove the abandoned plugin build script and packaging directory.
- [ ] Remove the obsolete PowerShell plugin tests.
- [ ] Remove the obsolete plugin design and plan docs.

### Task 3: Add dedicated Chinese user guide and restore skill docs

**Files:**
- Create: `docs/windows-desktop-document-skills-guide.zh-CN.md`
- Modify: `RpaClaw/backend/builtin_skills/docx/SKILL.md`
- Modify: `RpaClaw/backend/builtin_skills/pdf/SKILL.md`
- Modify: `RpaClaw/backend/builtin_skills/pptx/SKILL.md`
- Modify: `RpaClaw/backend/builtin_skills/xlsx/SKILL.md`
- Modify: `electron-app/README.md`

- [ ] Add a standalone Chinese user guide for Windows desktop local-mode document skill prerequisites and usage.
- [ ] Cover bundled runtimes, external tools, install steps, verification commands, and common operations for DOCX, PDF, PPTX, and XLSX.
- [ ] Replace the temporary user-facing prerequisite sections inside builtin skill docs with neutral technical wording.
- [ ] Keep technical corrections such as the `pypdfium2` image-rendering workflow where they improve the builtin skills themselves.
- [ ] Keep the app error model unchanged and only document the prerequisites.

### Task 4: Verify and clean references

**Files:**
- Verify: `electron-app/test/runtime.test.js`
- Search: repository-wide stale plugin references

- [ ] Run `node test/runtime.test.js` from `electron-app` after rebuilding TypeScript.
- [ ] Search the repo for `build-windows-document-runtime`, `windows-document-runtime`, and `runtime-tools` references and confirm only historical or unrelated references remain.
- [ ] Remove any untracked plugin build artifacts created by the abandoned flow if they are still present in `build/`.
