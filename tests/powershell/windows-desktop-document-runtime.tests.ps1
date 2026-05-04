$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Run-Test {
    param(
        [string]$Name,
        [scriptblock]$Script
    )

    try {
        & $Script
        Write-Host "PASS $Name"
    }
    catch {
        Write-Host "FAIL $Name"
        throw
    }
}

$RootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BuildPython = Join-Path $RootDir "build\python\python.exe"
$BuildNode = Join-Path $RootDir "build\node\node.exe"
$BuildNodeModules = Join-Path $RootDir "build\node\node_modules"
$DocxValidator = Join-Path $RootDir "build\staging\builtin_skills\docx\scripts\office\validate.py"
$TempDocx = Join-Path $RootDir "build\test-office-import.docx"
$BuiltinSkillDocxPy = Join-Path $RootDir "build\staging\builtin_skills\docx\scripts\office\validate.py"
$BackendMainPyc = Join-Path $RootDir "build\staging\backend\main.pyc"
$BackendMainPy = Join-Path $RootDir "build\staging\backend\main.py"

Run-Test "bundled node runtime exposes required document modules" {
    Assert-True (Test-Path $BuildNode) "Bundled node runtime not found"
    Assert-True (Test-Path $BuildNodeModules) "Bundled node_modules not found"

    $previousNodePath = $env:NODE_PATH
    try {
        $env:NODE_PATH = $BuildNodeModules
        $output = & $BuildNode -e "require('docx'); require('pptxgenjs'); require('adm-zip'); console.log('ok')" 2>&1
        Assert-True ($LASTEXITCODE -eq 0) "Bundled node modules probe failed: $output"
        Assert-True (($output | Out-String).Contains("ok")) "Bundled node modules probe did not print ok"
    }
    finally {
        $env:NODE_PATH = $previousNodePath
    }
}

Run-Test "staging keeps builtin_skills as source while backend remains compiled" {
    Assert-True (Test-Path $BuiltinSkillDocxPy) "builtin_skills should keep .py source files in staging"
    Assert-True (Test-Path $BackendMainPyc) "backend should still be compiled to .pyc"
    Assert-True (-not (Test-Path $BackendMainPy)) "backend source .py should be removed from staging"
}

Run-Test "source office validator runs from staged builtin_skills layout" {
    Assert-True (Test-Path $BuildPython) "Bundled python runtime not found"
    Assert-True (Test-Path $DocxValidator) "Staged docx validator source not found"

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $tempDir = Join-Path $RootDir "build\test-office-import-tmp"
    if (Test-Path $tempDir) {
        Remove-Item -Recurse -Force $tempDir
    }
    New-Item -ItemType Directory -Path (Join-Path $tempDir "_rels") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $tempDir "word") -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $tempDir "[Content_Types].xml"), "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'></Types>")
    [System.IO.File]::WriteAllText((Join-Path $tempDir "_rels\.rels"), "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'></Relationships>")
    [System.IO.File]::WriteAllText((Join-Path $tempDir "word\document.xml"), "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body/></w:document>")

    if (Test-Path $TempDocx) {
        Remove-Item -Force $TempDocx
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory($tempDir, $TempDocx)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $BuildPython $DocxValidator $TempDocx 2>&1
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    $outputText = $output | Out-String

    Assert-True (-not $outputText.Contains("ModuleNotFoundError")) "Staged source validator should not fail with ModuleNotFoundError: $outputText"
    Assert-True (-not $outputText.Contains("No module named 'validators'")) "Staged source validator should resolve local validators package: $outputText"
}

Write-Host "All windows desktop document runtime tests passed"
