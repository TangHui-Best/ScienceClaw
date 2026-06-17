# Windows 桌面版文档技能使用指南

本文面向使用 Windows 桌面安装包的最终用户，说明 DOCX、PDF、PPTX、XLSX 四类内置文档技能在本地模式下的前提条件、安装步骤和常见操作方式。

## 1. 先说明白：安装包里已经带了什么

当前桌面安装包已经内置：

- Python 运行时
- 文档技能需要的 Python 依赖
- Node.js 运行时
- 文档技能需要的 Node 模块
  - `docx`
  - `pptxgenjs`

这意味着下面这些能力通常开箱即用，不需要你额外装 Python、pip、Node、npm：

- 生成 DOCX 报告
- 生成 PPTX 演示稿
- 常规 PDF 读取、合并、拆分、生成
- 常规 XLSX 读写、格式处理

## 2. 哪些能力仍然需要你本机安装额外软件

有些能力依赖桌面软件本身，不适合直接打进主安装包，所以需要你在本机单独安装：

- `LibreOffice`
  - 用于 DOCX / PPTX 转 PDF
  - 用于 XLSX 公式重算
  - 用于部分 DOCX 工作流，例如接受修订
- `Pandoc`
  - 用于部分 DOCX 文本提取工作流
- `Tesseract OCR`
  - 用于扫描版 PDF OCR

说明：

- 主程序不会自动安装这些桌面软件。
- 如果缺少依赖，程序会直接报原始错误，不会做额外包装。

## 3. 推荐安装顺序

如果你希望把四类文档技能都用全，建议按下面顺序准备：

1. 安装 `LibreOffice`
2. 安装 `Pandoc`
3. 安装 `Tesseract OCR`
4. 重新打开桌面程序
5. 在 PowerShell 中逐条执行验证命令

## 4. LibreOffice 安装与验证

### 4.1 什么时候必须安装

以下情况建议先安装 LibreOffice：

- 需要把 DOCX 转成 PDF
- 需要把 PPTX 转成 PDF 或导出页面图片做检查
- 需要对 XLSX 执行公式重算
- 需要用 DOCX 修订接受类流程

### 4.2 官方参考页面

- 下载页：https://www.libreoffice.org/download/Windows
- Windows 安装说明：https://www.libreoffice.org/get-help/install-howto/windows/

### 4.3 安装步骤

1. 打开 LibreOffice Windows 下载页。
2. 选择 Windows 64 位版本。
3. 下载主安装程序。
4. 双击安装程序。
5. 按安装向导继续。
6. 如果没有特殊需求，直接使用默认安装即可。
7. 安装完成后，关闭当前终端窗口，再重新打开一个新的 PowerShell。

### 4.4 验证命令

```powershell
soffice --version
```

如果能看到版本号，说明安装成功。

如果提示找不到 `soffice`：

1. 先关闭并重新打开 PowerShell。
2. 仍然不行时，检查 LibreOffice 安装目录是否存在。
3. 常见目录：
   `C:\Program Files\LibreOffice\program`
4. 必要时把这个目录加入系统 `PATH`，然后重新打开桌面程序。

## 5. Pandoc 安装与验证

### 5.1 什么时候必须安装

以下情况建议先安装 Pandoc：

- 需要从现有 DOCX 中做文本提取
- 需要保留或分析部分 Word 文档结构

### 5.2 官方参考页面

- 安装说明：https://pandoc.org/installing.html

Pandoc 官方文档给出的 Windows 方式包括：

- 官方安装包
- `winget`
- `Chocolatey`

### 5.3 推荐安装方式

如果你的系统已安装 `winget`，推荐直接执行：

```powershell
winget install --source winget --exact --id JohnMacFarlane.Pandoc
```

如果你不想用 `winget`：

1. 打开 Pandoc 官方安装说明页面。
2. 进入 Windows 部分。
3. 按页面说明下载 package installer。
4. 双击安装。
5. 安装完成后重新打开 PowerShell。

### 5.4 验证命令

```powershell
pandoc --version
```

如果能看到版本信息，说明安装成功。

## 6. Tesseract OCR 安装与验证

### 6.1 什么时候必须安装

只有在下面这种场景才必须安装 Tesseract：

- 处理扫描版 PDF
- 需要 OCR 识别图片型 PDF 中的文字

普通文本型 PDF 不需要安装 Tesseract。

### 6.2 官方参考页面

- Tesseract 下载说明：https://tesseract-ocr.github.io/tessdoc/Downloads.html

注意：

- Tesseract 官方文档说明，较新的 Windows 版本目前没有官方 Windows 安装器。
- 官方文档在 Windows 部分明确指向 `UB Mannheim` 提供的安装包。

### 6.3 安装步骤

1. 打开 Tesseract 官方下载说明页面。
2. 找到 `Binaries for Windows`。
3. 按官方页面给出的 `UB Mannheim` 链接下载安装包。
4. 双击安装。
5. 安装完成后，重新打开 PowerShell。

### 6.4 验证命令

```powershell
tesseract --version
```

如果能看到版本号，说明 OCR 引擎已经可用。

如果你还需要中文 OCR，可以继续检查语言包：

```powershell
tesseract --list-langs
```

常见中文语言包名称：

- `chi_sim`
- `chi_tra`

## 7. 各技能分别怎么用

## 7.1 DOCX 技能

### 直接可用

以下能力通常不需要额外安装桌面软件：

- 生成新的 DOCX 报告
- 基于模板生成 Word 文档
- 一般性的 DOCX 结构处理

### 额外前提

- 读取部分现有 DOCX 内容：建议安装 `Pandoc`
- DOC / DOCX 转 PDF、接受修订：需要安装 `LibreOffice`

### 推荐操作顺序

1. 只生成 DOCX：直接使用即可。
2. 要读取现有 Word 文档内容：先确认 `pandoc --version` 正常。
3. 要做转换或接受修订：先确认 `soffice --version` 正常。

## 7.2 PDF 技能

### 直接可用

以下能力通常不需要额外安装桌面软件：

- 读取普通文本型 PDF
- 合并 PDF
- 拆分 PDF
- 旋转 PDF
- 生成 PDF 报告

### 额外前提

- 扫描版 PDF OCR：需要安装 `Tesseract OCR`
- 学术论文高质量双栏提取：可选安装 `pdftotext` 所在工具链

### 推荐操作顺序

1. 先判断 PDF 是否是扫描件。
2. 如果是扫描件，先确认 `tesseract --version` 正常。
3. 如果是普通文本型 PDF，通常可直接使用。

## 7.3 PPTX 技能

### 直接可用

以下能力通常不需要额外安装桌面软件：

- 生成新的 PPTX 演示稿
- 读取 PPTX 文本内容
- 常规结构化演示文稿生成

### 额外前提

- PPTX 转 PDF：需要 `LibreOffice`
- 导出页面图片做视觉检查：需要先有 `LibreOffice`

### 推荐操作顺序

1. 只生成或读取 PPTX：直接使用。
2. 需要转 PDF 或图片校验：先确认 `soffice --version` 正常。

## 7.4 XLSX 技能

### 直接可用

以下能力通常不需要额外安装桌面软件：

- 创建 XLSX
- 修改单元格、样式、工作表
- 写入公式
- 读取和导出表格数据

### 额外前提

- 如果你要让公式真正完成重算，需要 `LibreOffice`

### 推荐操作顺序

1. 普通读写：直接使用。
2. 涉及公式并要求结果值正确：先确认 `soffice --version` 正常，再执行相关流程。

## 8. 常见问题

### 8.1 为什么主安装包不直接把这些软件都带上

因为这类软件通常体积较大，且很多是独立安装程序，不适合直接作为主程序内置运行时的一部分打包。

当前方案是：

- 主程序内置 Python 和 Node 相关运行时
- 桌面软件由用户按需安装
- 缺依赖时直接返回原始报错

### 8.2 我已经装了软件，还是提示命令找不到

按下面顺序排查：

1. 关闭并重新打开 PowerShell
2. 关闭并重新打开桌面程序
3. 在 PowerShell 中执行：

```powershell
Get-Command soffice
Get-Command pandoc
Get-Command tesseract
```

4. 如果 `Get-Command` 找不到，通常说明程序目录没有进入 `PATH`
5. 把对应安装目录加入系统 `PATH` 后重新打开程序

### 8.3 我只需要常规文档生成，是不是可以什么都不装

大多数情况下可以。

如果你的需求是：

- 生成 DOCX
- 生成 PPTX
- 处理普通文本型 PDF
- 创建和修改 XLSX

通常直接使用桌面安装包即可。

### 8.4 哪些场景最容易因为缺依赖失败

最常见的是下面几类：

- DOCX 读取时缺 `pandoc`
- DOCX / PPTX / XLSX 转换时缺 `LibreOffice`
- 扫描版 PDF OCR 时缺 `Tesseract`
