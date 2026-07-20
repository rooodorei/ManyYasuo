# 批量解压工作台

用于批量解压“批量压缩工作台”生成的压缩文件。

## 功能

- 拖放或选择多个压缩文件
- 为加密压缩包设置统一解压密码
- 密码只在本次运行中使用，不会明文保存到配置文件
- 自动查找可配置前缀的标签目录
- 使用标签重命名解压后的最外层文件夹
- 只检查解压目录第 1、2 层；同一个文件名同时包含“路径”和“中文”时保留原文件夹名
- 标签前缀和保护检测词均可配置，检测词用逗号分隔且必须同时命中
- 同名目录自动追加编号，绝不覆盖已有数据
- 显示单任务和总进度，可取消整个队列

## 运行

请安装 7-Zip，并选择控制台版 `7z.exe`：

```powershell
uv sync
uv run python main.py
```

## 构建快速启动版

```powershell
uv run pyinstaller --noconfirm --clean main_fast.spec
```

生成目录为 `dist\BatchExtractorFast`，发布时必须保留其中的 `_internal` 目录。

## 构建单文件版

```powershell
uv run pyinstaller --noconfirm --clean main.spec
```

生成文件为 `dist\BatchExtractor.exe`。单文件版每次启动需要临时解包，因此比快速版慢。
