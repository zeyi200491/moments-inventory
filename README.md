# 微信朋友圈 CCD 商品库

面向 Windows 使用场景的命令行工具。  
它通过 WeFlow HTTP API 抓取指定联系人朋友圈内容，识别其中的 CCD 商品信息，并导出为可直接使用的 Excel 库表与本地图片、视频素材。

## 能做什么

- 抓取指定联系人在设定时间范围内的朋友圈内容
- 识别 CCD 型号、价格、编号等关键字段
- 合并重复或连续补充发布的库存记录
- 导出 `当前在售库.xlsx` 和 `历史总库.xlsx`
- 下载并保存对应的本地图片、视频素材

## 适用场景

- 日常整理微信朋友圈 CCD 库存
- 将零散朋友圈内容沉淀成结构化库存表
- 给运营、销售或助理提供统一的 Excel 与本地媒体目录

## 运行结果

程序运行完成后，会在 `task.output_dir` 指定目录下生成：

- `当前在售库.xlsx`
- `历史总库.xlsx`
- `media/` 本地图片和视频目录

## 快速开始

### 1. 初始化环境

在项目根目录运行：

```bat
setup_windows.bat
```

它会自动完成：

- 创建 `.venv`
- 安装项目依赖
- 复制 `config/config.example.yaml` 为 `config/config.yaml`
- 复制 `config/models.example.txt` 为 `config/models.txt`

### 2. 填写配置

需要准备这三项：

- `config/config.yaml`
- `config/models.txt`
- Windows 环境变量 `WEFLOW_ACCESS_TOKEN`

重点字段：

- `weflow.base_url`：你的 WeFlow HTTP API 地址
- `targets`：要抓取的联系人
- `task.output_dir`：导出目录
- `paths.sqlite_db`：本地 SQLite 数据库路径

### 3. 一键导出

```bat
run_export.bat
```

## 配置文件来源

### `config/config.yaml`

- 来源模板：`config/config.example.yaml`
- 实际用途：运行时主配置

### `config/models.txt`

- 来源模板：`config/models.example.txt`
- 实际用途：型号关键词词库，一行一个型号

### `WEFLOW_ACCESS_TOKEN`

- 来源：你的 WeFlow API 访问凭证
- 配置方式：

```bat
setx WEFLOW_ACCESS_TOKEN "你的实际token"
```

执行后重新打开命令行窗口，再运行 `run_export.bat`。

## 命令行入口

```bash
python -m moments_inventory.cli sync
python -m moments_inventory.cli export
python -m moments_inventory.cli sync --export
```

## 开发与测试

安装后可运行：

```bash
pytest -q
```

当前发布目录测试通过。

## 目录结构

```text
src/moments_inventory/   核心实现
tests/                   测试用例
config/                  示例配置与型号词库模板
docs/                    使用文档
setup_windows.bat        首次初始化脚本
run_export.bat           日常一键导出脚本
```

## 使用说明

更完整的 Windows 使用文档见：

[docs/windows-使用说明.md](docs/windows-使用说明.md)
