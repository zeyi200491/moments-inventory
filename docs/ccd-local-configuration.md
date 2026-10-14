# CCD 本机配置

CCD 的仓库配置 `config/showcase.yaml` 只保留可共享的相对路径示例。本机数据库、库存表、图片和备份目录通过 `config/showcase.local.yaml` 配置；该文件已加入 `.gitignore`，不会随 Git 提交。

## 首次设置

在项目根目录运行：

```powershell
Copy-Item config/showcase.yaml config/showcase.local.yaml
```

编辑 `config/showcase.local.yaml`，填写本机样片目录及其他需要覆盖的设置。原有配置字段不变，例如：

```yaml
sample_images_dir: E:/CCD样片目录
database: ../data/showcase.db
storage_dir: ../storage/showcase_images
manual_xlsx: ../manual/客户展示库存.xlsx
backup_dir: ../backup/showcase
server:
  host: 127.0.0.1
  port: 8899
admin:
  login_path: /admin-xingxing
customer:
  access_cookie_days: 7
```

以上是格式示例；请把样片路径换成本机实际目录。复制并编辑配置不会自动修改数据库。

## 配置优先级

1. 命令显式传入的 `--showcase-config` 路径优先级最高，适合候选恢复和隔离验证。
2. 未显式传入配置时，程序优先读取 `config/showcase.local.yaml`。
3. 本机配置不存在时，程序回退到 `config/showcase.yaml`。

启动、备份、导入和管理员口令重置批处理脚本遵循相同的本机优先规则。升级或切换 Git 分支时，本机配置不会被仓库文件覆盖；如果需要更换正式数据库或样片目录，请先备份并核对本机配置中的路径。

路径相对配置文件所在目录解析，不依赖当前终端目录。不要将本机配置提交到 Git；不要在候选恢复服务中省略候选目录的显式配置和隔离端口。
