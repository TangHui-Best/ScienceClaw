# Windows 文档运行时分层打包设计

## 背景

当前 Windows 桌面版已经将 Electron、embedded Python、backend、task-service、builtin_skills 与 Playwright/Chromium 打进安装包，但本地模式下执行 `docx`、`pdf`、`pptx`、`xlsx` 等内置技能时，仍会遇到两类问题：

1. Python 依赖并不完整，例如 `pypdf`、`reportlab`、`pdf2image`、`pytesseract` 这类文档相关包没有全部进入桌面运行时。
2. 一部分能力并不依赖 Python 包，而是依赖外部程序或 Node 运行时，例如：
   - `LibreOffice / soffice`
   - `Pandoc`
   - `Poppler`
   - `Tesseract OCR`
   - `node.exe`
   - npm 包 `docx`、`pptxgenjs`

如果将上述所有组件全部塞入主安装包，安装体积会明显膨胀，其中最大增量来自 `LibreOffice`、`Pandoc`、`Tesseract` 与当前已存在的 `Playwright + Chromium`，不适合作为默认方案。

因此需要一个既支持完整文档处理能力、又避免主安装包继续失控增长的打包方案。

## 目标

- 主安装包继续保持桌面版“开箱即用”的核心能力：聊天、RPA、本地模式后端、已有 Python 运行时。
- 文档处理能力支持完整离线使用，但不强制所有用户在首次安装时承受完整体积。
- 对现有 Electron + embedded Python 架构做最小侵入改造。
- 为 `docx`、`pdf`、`pptx`、`xlsx` 技能建立统一的依赖发现、路径注入、缺依赖提示与修复入口。
- 支持主程序与文档运行时分开升级。

## 非目标

- 不将主安装包改造成单一的全量离线发行物。
- 不要求首次安装时默认装入所有文档运行时。
- 不在本次设计中重写文档技能的业务逻辑，只统一其运行时依赖供应方式。
- 不在本次设计中解决 Linux/macOS 桌面版分发问题。

## 核心决策

采用“双层发行”方案：

1. 主安装包
   - 保留当前 Electron 桌面应用主体。
   - 内置轻量 Python 文档依赖。
   - 提供文档运行时探测、安装、修复入口。

2. 文档运行时扩展包
   - 单独分发。
   - 安装到 `RPA_CLAW_HOME/runtime-tools/`。
   - 包含完整文档技能所需的重型运行时与 Node 环境。

不推荐的替代方案：

- 单一全量包：用户体验简单，但体积过大，升级与维护成本高。
- 首次在线下载：主包最小，但依赖网络环境，不适合离线/企业环境。

## 总体架构

### 主安装包内容

主安装包继续承载：

- Electron 主程序
- embedded Python
- backend
- task-service
- builtin_skills
- Playwright + Chromium
- 轻量 Python 文档依赖
- 文档运行时状态探测逻辑

主安装包不承载：

- LibreOffice
- Pandoc
- Poppler
- Tesseract
- Node runtime
- npm 全局模块 `docx`、`pptxgenjs`

### 文档运行时扩展包内容

扩展包承载：

- LibreOffice
- Pandoc
- Poppler
- Tesseract OCR
- Node runtime
- npm 模块 `docx`
- npm 模块 `pptxgenjs`

扩展包安装完成后，在用户目录中留下独立运行时树，而不是写入主程序 `resources/`。

## 目录布局

### 主程序目录

```text
<install-dir>/
  RpaClaw.exe
  resources/
    python/
    backend/
    task-service/
    builtin_skills/
    frontend-dist/
```

### 用户目录

```text
RPA_CLAW_HOME/
  workspace/
  data/
  logs/
  runtime-tools/
    manifest.json
    libreoffice/
    pandoc/
    poppler/
    tesseract/
    node/
      node.exe
      node_modules/
        docx/
        pptxgenjs/
```

### 原因

- 主程序升级时不覆盖重型运行时。
- 扩展包可以单独升级或修复。
- 用户数据与运行时统一在 `RPA_CLAW_HOME` 下，符合当前桌面版的本地模式数据模型。

## 依赖分层

### 第一层：主包内置轻量依赖

这些依赖应进入 `backend/requirements.txt` 并随 embedded Python 一起打包：

- `pypdf`
- `reportlab`
- `pdf2image`
- `pytesseract`

当前已经存在并继续依赖的包：

- `openpyxl`
- `lxml`
- `defusedxml`
- `Pillow`
- `pandas`
- `pdfplumber`
- `markitdown`

这层依赖的目标是保证：

- `pdf` 基础读写能力
- `pdf` 报告生成能力
- `xlsx` 基础编辑能力
- office XML pack/unpack/validate 能力

### 第二层：扩展包中的重型运行时

这些依赖不进入主安装包，而进入扩展包：

- `LibreOffice`
- `Pandoc`
- `Poppler`
- `Tesseract OCR`
- `Node runtime`
- `docx`
- `pptxgenjs`

### 第三层：能力降级

当扩展包未安装时，系统不报底层异常给用户，而是显式降级：

- 缺 `LibreOffice`
  - 禁用 DOCX/PPTX 转 PDF
  - 禁用 XLSX 公式重算
  - 禁用部分 DOCX 修订处理
- 缺 `Pandoc`
  - 禁用高质量 DOCX 文本提取
- 缺 `Poppler`
  - 禁用 PDF 转图片
- 缺 `Tesseract`
  - 禁用 OCR
- 缺 `Node/docx/pptxgenjs`
  - 禁用 DOCX/PPTX 模板生成

## 技能能力映射

### docx

依赖：

- 主包：`lxml`、`defusedxml`
- 扩展包：`node + docx`、`pandoc`、`LibreOffice`

能力：

- 基础 unpack/pack/validate：主包即可
- 报告模板生成：需要 `node + docx`
- `.doc`/`.docx` 转换与导出 PDF：需要 `LibreOffice`
- 文本提取：优先 `Pandoc`

### pptx

依赖：

- 主包：`lxml`、`defusedxml`
- 扩展包：`node + pptxgenjs`、`LibreOffice`

能力：

- 基础 unpack/pack/validate：主包即可
- 报告模板生成：需要 `node + pptxgenjs`
- 导出 PDF：需要 `LibreOffice`

### xlsx

依赖：

- 主包：`openpyxl`
- 扩展包：`LibreOffice`

能力：

- 基础读写与样式：主包即可
- 公式重算：需要 `LibreOffice`

### pdf

依赖：

- 主包：`pypdf`、`reportlab`、`pdf2image`、`pytesseract`
- 扩展包：`Poppler`、`Tesseract`

能力：

- 基础合并、拆分、表单读写：主包即可
- 报告生成：主包即可
- 转图片：需要 `Poppler`
- OCR：需要 `Tesseract`

## 运行时路径协议

Electron 在启动 backend / task-service 时，统一注入以下环境变量：

- `RPA_CLAW_HOME`
- `RPA_CLAW_RUNTIME_TOOLS_DIR`
- `SOFFICE_BIN`
- `PANDOC_BIN`
- `POPPLER_BIN`
- `TESSERACT_BIN`
- `NODE_BIN`
- `NODE_PATH`

### 查找优先级

所有文档相关脚本统一按以下顺序查找依赖：

1. 显式环境变量
2. `RPA_CLAW_HOME/runtime-tools/...` 默认路径
3. 系统 `PATH`

禁止每个脚本自行分散实现不同查找逻辑，否则后续扩展包维护会继续失控。

## 后端改造

新增统一运行时解析模块，例如：

```text
backend/runtime_tools.py
```

职责：

- 解析 `RPA_CLAW_HOME/runtime-tools/manifest.json`
- 校验可执行文件存在性
- 组装运行时状态对象
- 生成供脚本消费的环境变量
- 输出结构化缺依赖错误

建议暴露：

- `get_runtime_tools_status()`
- `resolve_soffice_bin()`
- `resolve_pandoc_bin()`
- `resolve_poppler_bin()`
- `resolve_tesseract_bin()`
- `resolve_node_bin()`
- `build_document_runtime_env()`

所有 `docx/pptx/xlsx/pdf` 相关脚本统一改为：

- 优先读取显式环境变量
- 避免硬编码 `"soffice"`、`"pandoc"`、`"node"` 等裸命令

## Electron 改造

### ProcessManager

在构建 backend env 时增加：

- `RPA_CLAW_RUNTIME_TOOLS_DIR`
- 各类二进制显式路径
- 将 `runtime-tools` 下所需目录 prepend 到 `PATH`

### 设置页

新增“文档运行时”设置区块，展示：

- 安装状态
- 版本
- 组件完整性
- 修复入口

展示内容示例：

- 已安装
- 缺失 LibreOffice
- 版本过旧，需要升级
- 运行时清单损坏，需要修复

### 首次运行体验

主包安装后不强制安装扩展包。

文档扩展包安装入口：

1. 安装向导勾选“安装文档处理支持”
2. 设置页点击“安装/修复文档运行时”

## 扩展包安装行为

扩展包安装器职责：

- 解压/安装全部文档运行时到 `RPA_CLAW_HOME/runtime-tools/`
- 安装 npm 模块到 `node/node_modules`
- 生成 `manifest.json`
- 写入版本与路径信息

### manifest 示例

```json
{
  "version": "2026.04",
  "installed": true,
  "components": {
    "libreoffice": true,
    "pandoc": true,
    "poppler": true,
    "tesseract": true,
    "node": true,
    "docx": true,
    "pptxgenjs": true
  },
  "paths": {
    "soffice": "C:/Users/Alice/RpaClaw/runtime-tools/libreoffice/program/soffice.exe",
    "pandoc": "C:/Users/Alice/RpaClaw/runtime-tools/pandoc/pandoc.exe",
    "pdftoppm": "C:/Users/Alice/RpaClaw/runtime-tools/poppler/bin/pdftoppm.exe",
    "tesseract": "C:/Users/Alice/RpaClaw/runtime-tools/tesseract/tesseract.exe",
    "node": "C:/Users/Alice/RpaClaw/runtime-tools/node/node.exe"
  }
}
```

## 错误模型

后端不要将底层 `ModuleNotFoundError`、`FileNotFoundError`、`WinError 2` 直接暴露给用户。

统一转成业务错误：

- `DOCUMENT_RUNTIME_MISSING: libreoffice`
- `DOCUMENT_RUNTIME_MISSING: pandoc`
- `DOCUMENT_RUNTIME_MISSING: poppler`
- `DOCUMENT_RUNTIME_MISSING: tesseract`
- `DOCUMENT_RUNTIME_MISSING: node-docx`
- `DOCUMENT_RUNTIME_BROKEN: manifest`

前端根据错误码展示：

- 缺哪个组件
- 哪些技能受影响
- 修复按钮

## 构建流程

### 主包构建

保留现有 `build-windows.ps1` 主流程，并新增：

- 安装轻量 Python 文档依赖
- 拷贝文档运行时状态管理前端资源

不在主构建中加入：

- LibreOffice
- Pandoc
- Poppler
- Tesseract
- Node runtime

### 扩展包构建

新增独立脚本，例如：

```text
build-windows-document-runtime.ps1
```

职责：

- 下载或收集各运行时安装产物
- 组装 `runtime-tools/`
- 安装 npm 模块 `docx`、`pptxgenjs`
- 生成 `manifest.json`
- 打包为独立安装器或自解压包

## 版本与升级策略

主包与扩展包允许独立升级，但需要兼容性约束：

- 主包读取 `manifest.version`
- 如果版本低于最低要求，提示用户升级扩展包
- 扩展包升级不能覆盖用户数据目录中的非运行时内容

## 验证策略

### 主包无扩展场景

验证：

- 聊天、RPA、本地执行正常
- 设置页正确显示文档运行时未安装
- 调用文档技能时报结构化缺依赖错误，而不是 Python 栈追踪

### 安装扩展后

验证：

- `docx` 模板生成可用
- `pptx` 模板生成可用
- `xlsx` 公式重算可用
- `pdf` 转图片可用
- `pdf` OCR 可用
- `docx/pptx` 导出 PDF 可用

### 升级场景

验证：

- 升级主包不破坏已安装扩展
- 升级扩展不破坏用户目录
- 清单损坏时能提示修复

## 风险与取舍

- 文档扩展包仍然会比较大，尤其是 `LibreOffice`。
- 但该体积从“所有用户首次安装必须承担”变成“需要文档能力的用户按需安装”。
- 引入单独扩展包后，发布、签名、版本管理会变得稍复杂。
- 这是可接受代价，因为它显著降低了主包体积压力，并保持完整离线能力。

## 结论

采用“主安装包 + 文档运行时扩展包”的分层打包方案。

主包继续保持当前桌面版核心能力，文档完整能力通过可选扩展包离线提供。所有文档技能统一通过 `RPA_CLAW_HOME/runtime-tools/` 与显式环境变量发现运行时，并通过结构化错误向前端暴露缺依赖状态。
