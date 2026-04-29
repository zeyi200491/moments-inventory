# Windows 使用说明

这份文档给“拿到项目后直接使用”的同事或客户看。  
首次配置完成后，后面只需要运行 `run_export.bat`。

## 1. 这个工具做什么

工具会通过 WeFlow 的 HTTP API 抓取指定联系人的朋友圈内容，识别其中的 CCD 商品信息，然后导出到你配置的输出目录中，主要产物包括：

- `当前在售库.xlsx`
- `历史总库.xlsx`
- `media/` 目录下的本地图片和视频

## 2. 首次使用步骤

### 第一步：运行初始化脚本

在项目根目录运行：

```bat
setup_windows.bat
```

它会自动完成这些事情：

- 创建 `.venv` 虚拟环境
- 安装项目依赖
- 如果 `config/config.yaml` 不存在，就从 `config/config.example.yaml` 复制一份
- 如果 `config/models.txt` 不存在，就从 `config/models.example.txt` 复制一份

### 第二步：填写 `config/config.yaml`

`config/config.yaml` 不是手动新建的，它来自项目自带的示例配置：

- 示例文件：`config/config.example.yaml`
- 实际使用文件：`config/config.yaml`

通常在你运行完 `setup_windows.bat` 之后，`config/config.yaml` 已经自动生成好了，你只需要编辑它。

重点需要确认这些字段：

#### `weflow.base_url`

这是 WeFlow HTTP API 的地址。

常见情况：

- 如果 WeFlow 跑在你自己的电脑上，通常是 `http://127.0.0.1:5030` 或 `http://127.0.0.1:5031`
- 如果 WeFlow 是别人部署给你用的，就让对方提供完整地址

#### `targets`

这里填写你要抓取的联系人。

建议优先填 `wxid`，更稳定；如果你没有 `wxid`，也可以只填 `remark_name`，程序会尝试按备注名匹配联系人。

示例：

```yaml
targets:
  - remark_name: "张三库存号"
    wxid: "wxid_123"
  - remark_name: "李四"
    wxid: ""
```

#### `task.output_dir`

这是导出目录，例如：

```yaml
task:
  output_dir: "./output"
```

脚本运行成功后，Excel、图片和视频都会出现在这个目录里。

#### `paths.sqlite_db`

这是本地 SQLite 数据库路径，一般保持默认即可。

## 3. `config/models.txt` 从哪里来，怎么填

这个文件是“型号关键词词库”。

项目中有两份相关文件：

- 实际使用文件：`config/models.txt`
- 示例文件：`config/models.example.txt`

如果你已经运行过 `setup_windows.bat`：

- `config/models.txt` 已存在：直接编辑它
- `config/models.txt` 不存在：脚本会自动从 `config/models.example.txt` 复制

填写规则很简单：一行一个型号关键词，例如：

```text
ixus 95
ixus 85is
sony t2
fuji f455
```

这些关键词通常来自：

- 你平时实际售卖的 CCD 型号清单
- 你历史朋友圈文案中经常出现的型号名
- 现有库存表中的型号列

词库越完整，识别准确率越高。

## 4. `WEFLOW_ACCESS_TOKEN` 从哪里来，怎么配置

项目默认不把 token 写进仓库文件，而是要求你在 Windows 里配置系统环境变量：

- 变量名：`WEFLOW_ACCESS_TOKEN`

### 这个 token 从哪里来

它本质上就是 WeFlow HTTP API 的访问凭证。

常见来源：

- 如果 WeFlow 是你自己部署的：去 WeFlow 的启动配置、环境变量、后台配置页面或部署说明里找 `access token`
- 如果 WeFlow 是别人部署给你用的：直接向对方索取 API token

可以把它理解成“访问 WeFlow 接口的密码”。

### 在 Windows 里怎么配置

最简单的方式是在命令行执行：

```bat
setx WEFLOW_ACCESS_TOKEN "你的实际token"
```

执行完成后：

1. 关闭当前命令行窗口
2. 重新打开一个新的命令行窗口
3. 再运行 `run_export.bat`

也可以用图形界面配置：

1. 打开“编辑系统环境变量”
2. 进入“环境变量”
3. 新建用户变量
4. 变量名填 `WEFLOW_ACCESS_TOKEN`
5. 变量值填你的实际 token

## 5. 日常怎么运行

配置完成后，平时只需要运行：

```bat
run_export.bat
```

它会自动执行：

```bash
python -m moments_inventory.cli sync --export
```

运行完成后，你会得到：

- Excel 文件
- 本地图片
- 本地视频

它们都在 `config/config.yaml` 里 `task.output_dir` 指定的目录下。

## 6. 常见问题

### 提示找不到 `.venv\Scripts\python.exe`

说明你还没做初始化。先运行：

```bat
setup_windows.bat
```

### 提示没有 `config/config.yaml`

说明配置文件还没准备好。先运行：

```bat
setup_windows.bat
```

然后编辑 `config/config.yaml`。

### 提示没有 `WEFLOW_ACCESS_TOKEN`

说明系统环境变量还没配置。执行：

```bat
setx WEFLOW_ACCESS_TOKEN "你的实际token"
```

然后重新打开命令行窗口。

### 运行成功了，但没有导出想要的数据

重点检查：

- `targets` 里的联系人是否填对
- `weflow.base_url` 是否指向正确的 WeFlow 服务
- `config/models.txt` 是否覆盖了你实际售卖的型号

## 7. 推荐交付方式

如果你要把这个项目交给别人，建议一起提供：

- 整个项目目录
- 正确的 `config/config.yaml` 示例
- 正确的 `config/models.txt` 词库
- WeFlow 地址
- WeFlow token 获取方式，或者直接提供 token

这样对方只需要：

1. 跑一次 `setup_windows.bat`
2. 核对配置
3. 运行 `run_export.bat`

就能直接拿到 Excel、图片和视频。
