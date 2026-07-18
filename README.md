# 批量压缩工作台

基于 CustomTkinter 和 7-Zip 的 Windows 批量压缩工具。

主要功能：

- 拖放或选择多个文件夹，自动排序并校验连续编号
- 为文件夹添加自定义标签，并支持配置标签目录前缀
- 批量 7z 压缩、密码加密和文件名加密
- 显示单任务与队列总进度
- 暂停、继续或取消整个压缩队列
- 保存命名、加密与性能配置

## 运行源码

请先安装 [7-Zip](https://www.7-zip.org/)，然后执行：

```powershell
uv sync
uv run python main.py
```

建议在软件中选择控制台版 `7z.exe`，使用 `7zG.exe` 时无法稳定读取压缩进度。

## 构建单文件 EXE

```powershell
uv run pyinstaller --noconfirm --clean main.spec
```

生成文件位于 `dist\BatchCompressor.exe`。单文件版本启动时会临时解包界面和拖放组件，因此首次启动可能略慢。

## 构建快速启动版

```powershell
uv run pyinstaller --noconfirm --clean main_fast.spec
```

生成目录为 `dist\BatchCompressorFast`。发布时保留整个目录，用户只需运行其中的 `BatchCompressor.exe`；其余依赖统一放在 `_internal` 目录中。该版本无需每次临时解包，启动明显更快。
