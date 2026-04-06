# 过滤技能目录中的 __pycache__ 缓存文件

## 问题描述

当在对话界面执行技能后，Python 会在技能目录下自动生成 `__pycache__/skill.cpython-313.pyc` 等字节码缓存文件。这些文件会出现在前端的技能文件浏览器中，影响用户体验，因为它们与技能功能无关。

## 影响范围

- **后端**：`RpaClaw/backend/route/sessions.py` 的 `list_skill_files` 函数使用 `skill_dir.rglob("*")` 扫描所有文件，没有过滤逻辑
- **前端**：`RpaClaw/frontend/src/pages/SkillDetailPage.vue` 直接展示后端返回的文件列表

## 解决方案

在后端 `list_skill_files` API 中添加文件过滤逻辑，排除不应该展示给用户的文件和目录。

### 过滤规则

需要跳过的文件/目录：
- `__pycache__` 目录及其所有内容
- Python 字节码文件：`.pyc`、`.pyo`、`.pyd`
- 系统临时文件：`.DS_Store`（macOS）、`Thumbs.db`（Windows）、`desktop.ini`（Windows）
- 版本控制目录：`.git`、`.svn`
- IDE 配置目录：`.vscode`、`.idea`、`.vs`
- Git 配置文件：`.gitignore`

### 实现方式

在 `sessions.py` 中添加过滤函数：

```python
def should_skip_file(path: Path) -> bool:
    """判断是否应该跳过该文件/目录（不在技能文件列表中展示）"""
    name = path.name
    
    # 跳过 __pycache__ 目录
    if name == '__pycache__':
        return True
    
    # 跳过 Python 字节码文件
    if name.endswith(('.pyc', '.pyo', '.pyd')):
        return True
    
    # 跳过系统临时文件
    if name in {'.DS_Store', 'Thumbs.db', 'desktop.ini', '.gitignore'}:
        return True
    
    # 跳过版本控制和 IDE 目录
    if name in {'.git', '.svn', '.vscode', '.idea', '.vs'}:
        return True
    
    return False
```

在 `list_skill_files` 函数中应用过滤：

```python
for file_path in sorted(skill_dir.rglob("*")):
    # 跳过不需要展示的文件
    if should_skip_file(file_path):
        continue
    
    # 原有逻辑：添加到 items 列表
    if file_path.is_file():
        rel_path = str(file_path.relative_to(skill_dir))
        items.append({
            "name": file_path.name,
            "path": rel_path,
            "type": "file",
        })
```

### 修改文件

- `RpaClaw/backend/route/sessions.py`：添加 `should_skip_file` 函数，修改 `list_skill_files` 函数

### 前端改动

无需改动。前端会自动受益于后端的过滤逻辑。

## 测试验证

1. 执行一个技能，确认生成了 `__pycache__` 目录
2. 在前端技能详情页查看文件列表，确认 `__pycache__` 及 `.pyc` 文件不再显示
3. 确认正常的技能文件（`SKILL.md`、`skill.py` 等）仍然正常显示

## 优点

- 一次性解决，所有调用 `list_skill_files` API 的地方都受益
- 前端无需改动
- 可扩展：未来可以轻松添加更多过滤规则
- 不影响 Python 性能（字节码缓存仍然生成，只是不展示）
