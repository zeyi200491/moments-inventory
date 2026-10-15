# CCD 本机配置

CCD 的仓库配置 `config/showcase.yaml` 只保留可共享的相对路径示例。本机数据库、库存表、图片和备份目录通过 `config/showcase.local.yaml` 配置；该文件已加入 `.gitignore`，不会随 Git 提交。

本地 SQLite 是库存唯一写入权威。正式运行使用正式工作树 `.worktrees/ccd-inventory-showcase` 内的本机配置，并让数据库解析到该工作树对应的 `data/showcase.db`。开发 worktree、候选恢复目录和测试库必须与正式库隔离；不要在多个工作树各自启动服务后凭相同端口或页面外观判断它们连接的是同一个数据库。Cloudflare D1 是从本地导出的只读展示快照，不参与本地配置，也不允许用云端管理页维护库存。

正式启动、Excel 导入、备份和管理员口令重置批处理会先运行 `scripts/verify_showcase_environment.py`。它根据 Git 共用目录定位正式工作树，并核对入口代码和配置文件位置、权威 SQLite、机身图片根目录、`output/ccdcpt` 样片根目录、人工库存表、备份目录及 `127.0.0.1:8899` 监听地址；任何一项不匹配都会在数据库操作前拒绝继续。请从正式工作树运行这些入口。根目录、开发工作树和恢复目录中的入口会被拒绝，不能通过把本机配置复制过去绕过检查。

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

启动、备份、导入和管理员口令重置批处理脚本遵循相同的本机优先规则，并在执行前运行正式环境门禁。升级或切换 Git 分支时，本机配置不会被仓库文件覆盖；如要迁移正式数据库或样片目录，先更新门禁实现及本说明，再在隔离副本验证，不得只改配置绕过路径保护。

路径相对配置文件所在目录解析，不依赖当前终端目录。不要将本机配置提交到 Git；不要在候选恢复服务中省略候选目录的显式配置和隔离端口。
