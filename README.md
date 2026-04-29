# 微信朋友圈 CCD 商品库

这是一个面向 Windows 使用者的命令行工具，用来通过 WeFlow HTTP API 抓取朋友圈内容，识别 CCD 商品信息，并导出：

- 当前在售 Excel
- 历史总库 Excel
- 对应的本地图片和视频

## 快速开始

1. 运行 `setup_windows.bat`
2. 按文档填写 `config/config.yaml`
3. 按文档填写 `config/models.txt`
4. 配置系统环境变量 `WEFLOW_ACCESS_TOKEN`
5. 运行 `run_export.bat`

详细说明见 [docs/windows-使用说明.md](docs/windows-使用说明.md)。

## 命令行入口

```bash
python -m moments_inventory.cli sync
python -m moments_inventory.cli export
python -m moments_inventory.cli sync --export
```
