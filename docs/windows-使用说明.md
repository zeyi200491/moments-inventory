# Windows 使用说明

这份文档面向“拿到项目后直接使用”的同事或客户，重点只讲：

- 怎么配置
- 怎么运行
- 怎么导出
- 当前正式规则是什么

## 1. 这套工具做什么

工具通过 WeFlow HTTP API 抓取指定联系人的朋友圈内容，识别 CCD 商品信息，并导出为 Excel。

当前正式导出只保留“当前在售”结果，不再额外导出历史总库。

常见产物：

- `优先货源当前库.xlsx`
- `全量当前库.xlsx`
- `progress.json`
- `failed_targets.csv`
- `media/` 目录下的图片和视频（如果开启媒体下载）

## 2. 首次使用

### 第一步：初始化环境

在项目根目录运行：

```bat
setup_windows.bat
```

它会自动完成：

- 创建 `.venv`
- 安装依赖
- 生成 `config/config.yaml`
- 生成 `config/models.txt`

### 第二步：配置 `config/config.yaml`

重点字段：

说明：

- 首次初始化时，`setup_windows.bat` 会基于 `config/config.example.yaml` 生成 `config/config.yaml`
- 后续实际运行始终读取 `config/config.yaml`

#### `weflow.base_url`

WeFlow HTTP API 地址，常见是：

```yaml
weflow:
  base_url: "http://127.0.0.1:5031"
```

#### `task.download_media`

- `true`：下载图片和视频
- `false`：只导出 Excel，不下载媒体

如果你只是想快速看结果，建议先设成：

```yaml
task:
  download_media: false
```

#### `targets`

每个目标联系人支持：

- `remark_name`
- `wxid`
- `tier`

示例：

```yaml
targets:
  - remark_name: "白得一批"
    wxid: "wxid_xxx"
    tier: 1
  - remark_name: "星星"
    wxid: "wxid_yyy"
    tier: 2
```

规则：

- `tier: 1` 表示优先货源
- `tier: 2` 表示普通货源
- 在 warmup 场景下，`remark_name` 视为必填，因为当前微信桌面端自动化主要按备注名搜索联系人

#### `warmup.enabled`

- `true`：先做微信 warmup 预刷新
- `false`：不刷新，直接抓取/导出

快速测试模式建议：

```yaml
warmup:
  enabled: false
```

#### `orchestrator`

推荐使用的两种正式模式：

```yaml
orchestrator:
  enabled: true
  mode: "priority_only"
  batch_size: 25
  export_priority_after_p1: true
  export_full_after_all: true
  resume_enabled: true
  write_failed_targets: true
  priority_output_name: "优先货源当前库.xlsx"
  full_output_name: "全量当前库.xlsx"
```

说明：

- `priority_only`
  只跑 `tier=1`
- `full`
  先跑 `tier=1`，再继续跑剩余批次

### 第三步：配置 `config/models.txt`

一行一个型号关键词，例如：

```text
ixus 95
ixus 85is
sony t2
fuji f455
```

词库越全，型号识别越稳。

说明：

- 首次初始化时，`setup_windows.bat` 会基于 `config/models.example.txt` 生成 `config/models.txt`
- 后续你只需要维护 `config/models.txt`

### 第四步：配置 `WEFLOW_ACCESS_TOKEN`

在 Windows 命令行执行：

```bat
setx WEFLOW_ACCESS_TOKEN "你的实际token"
```

执行后关闭当前命令行窗口，再重新打开一个新窗口。

## 3. 正式价格规则

当前正式 Excel 的价格规则非常严格：

1. 原文里必须出现 `💰`
2. 价格只认 `💰` 前后紧邻的数字
3. 没有 `💰` 的记录，不进入正式 Excel
4. 价格 `< 99` 的记录，不进入正式 Excel

这条规则是为了避免把：

- `15新`
- `99新`
- `1400万像素`
- 编号、序列号

误识别成价格。

例如：

- `319💰宾得s55` -> 价格 `319`
- `💰460 编号H1916` -> 价格 `460`
- `15新 宾得s55` -> 不进入正式 Excel

## 4. 推荐运行方式

### 方式 A：不 warmup 的快速导出

适合：

- 先验证分层模式是否正常
- 先看 Excel
- 不想等待微信自动化

配置建议：

```yaml
warmup:
  enabled: false

task:
  download_media: false
```

运行：

```bash
python -m moments_inventory.cli orchestrated-run --mode priority_only
```

输出：

- `优先货源当前库.xlsx`

### 方式 B：第一阶段优先货源

适合：

- 先刷最重要的 25 人
- 先出一份优先货源表

配置建议：

```yaml
warmup:
  enabled: true

task:
  download_media: false
```

运行：

```bat
run_warmup_and_export.bat
```

或者：

```bash
python -m moments_inventory.cli orchestrated-run --mode priority_only
```

### 方式 C：全量模式

适合：

- 先跑 `tier=1`
- 再继续批量跑 `tier=2`
- 最后出全量表

运行：

```bash
python -m moments_inventory.cli orchestrated-run --mode full
```

输出：

- `优先货源当前库.xlsx`
- `全量当前库.xlsx`
- `progress.json`
- `failed_targets.csv`

如果中途断了，可以继续：

```bash
python -m moments_inventory.cli orchestrated-run --mode full --resume
```

## 5. warmup 说明

当前 warmup 是 Windows 微信桌面端 UI 自动化。

现阶段已经重点做过这几类优化：

- 25 人按 `5×5` 分段执行
- 每个联系人结束后做状态校验
- 如果恢复失败，会走强制恢复
- 单个联系人失败后会记录并跳过，不直接把整批带崩
- 重点提升“打开朋友圈小窗”的命中率

但它仍然有边界：

- 依赖微信桌面端界面结构
- 受窗口大小、DPI、版本影响
- 不能承诺 100% 绝对命中

运行 warmup 前，微信先停在通讯录或聊天列表，再开始执行脚本。

如果你只是要快速出表，优先建议：

- `warmup.enabled: false`
- `task.download_media: false`

## 6. 常用脚本

项目根目录下提供：

- `setup_windows.bat`
- `run_export.bat`
- `run_warmup_and_export.bat`
- `run_batched_warmup_and_export.bat`
- `run_ai_kefu_workbench.bat`

说明：

- `run_export.bat`
  适合普通导出
- `run_warmup_and_export.bat`
  适合先 warmup 再导出
- `run_batched_warmup_and_export.bat`
  适合大量联系人按批 warmup + 导出

## 7. 常见问题

### 提示找不到 `.venv\Scripts\python.exe`

先执行：

```bat
setup_windows.bat
```

### 提示没有 `config/config.yaml`

先执行：

```bat
setup_windows.bat
```

### 提示没有 `WEFLOW_ACCESS_TOKEN`

执行：

```bat
setx WEFLOW_ACCESS_TOKEN "你的实际token"
```

然后重新打开命令行。

### warmup 成功率不稳定

优先确认：

- 微信在当前桌面
- 微信窗口可见
- 不要停在搜一搜页
- 不要让其他窗口遮挡

如果只是为了快速出表，建议先关闭 warmup。

### Excel 里没有商品数据

优先检查：

1. 联系人抓取结果里是否真的有朋友圈内容
2. 原文里是否包含 `💰`
3. 价格是否 `>= 99`
4. 型号词库是否覆盖你的实际商品型号

## 8. 交付建议

如果你要把这套工具交给别人，建议一起交付：

- 项目目录
- `config/config.yaml`
- `config/models.txt`
- WeFlow 地址
- WeFlow token 的配置方式

这样接手的人通常只需要：

1. 执行 `setup_windows.bat`
2. 核对配置
3. 运行对应脚本

就能直接开始导出。
