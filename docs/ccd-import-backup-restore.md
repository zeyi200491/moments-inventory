# CCD 库存导入与备份恢复

本说明仅用于 CCD 展示系统。正式数据库、机身图片、样片目录由 CCD 配置指定；所有配置相对路径以配置文件所在目录解析。常规本机操作优先使用 Git 忽略的 `config/showcase.local.yaml`；未创建时回退到仓库示例配置 `config/showcase.yaml`。首次配置请按 `docs/ccd-local-configuration.md` 操作。不同工作目录下运行时传入配置绝对路径。

## 导入预览与确认

默认命令只校验及预览，不写入商品。首次空数据库会初始化表结构。

```powershell
python -m moments_inventory.cli showcase-db-import --showcase-config config/showcase.local.yaml --preview-file import-preview.json
python -m moments_inventory.cli showcase-db-import --showcase-config config/showcase.local.yaml --commit-preview import-preview.json
```

预览文件保存来源记录、文件 SHA-256、目标数据库及行版本。确认提交复用该快照；预览后有人改价或新增相关商品时拒绝冲突，重新生成预览。预览文件含运营内容，应只保存在本机，不上传或提交 Git。

明确全量导入时必须声明范围与完整性：

```powershell
python -m moments_inventory.cli showcase-db-import --showcase-config config/showcase.local.yaml --mode full --scope default --complete --preview-file import-preview.json
```

默认增量只改出现的商品。全量只对同一 scope 判断缺失，缺失标记 `review_state=missing`，保留既有展示状态。减少超过 30% 会拒绝；复核数据确实完整后才显式调整 `--max-missing-fraction`（0～1）。空全量、缺表头、重复 ID、无效价格均拒绝。来源范围不可共用同一个商品 ID。

人工覆盖优先于来源；当前来源范围和模式下，连续重复提交相同文件会复用最新成功批次。若其间提交过其他来源快照，再提交旧文件会作为新的来源回归重新应用，恢复可用状态并记录新批次。`--yes` 可直接校验并提交，适用于已明确确认的批处理。`import_showcase_excel.bat` 使用该模式保持原有正式导入操作。

## 一致快照

```powershell
python -m moments_inventory.cli showcase-db-backup --showcase-config config/showcase.local.yaml
```

备份使用 SQLite backup API，包含已提交的 WAL 数据；不直接复制线上数据库文件。数据库快照中的封面、机身/人工样片、共享型号样片及图库引用被汇总去重，复制对应文件并记录 SHA-256、大小、引用值及记录数。媒体复制前后再次校验，文件缺失或复制期间改变会报错。

只有含 `manifest.json` 的目录是完整备份。失败目录可能保留数据库及部分媒体用于诊断，不能恢复。备份仅收集数据库实际引用媒体，不复制全部历史孤立文件。已有 12 GB 基线无需为测试再次复制。

当前沿用手动快照流程，尚未承诺固定的保留期限、RPO 或 RTO，也不应把单次快照视为已经演练的灾难恢复能力。管理者应按现有操作在关键导入、批量改价和发布前创建快照，并由人工保留已知可恢复的快照；恢复演练继续使用独立目录，不能覆盖正式库。

## 恢复到全新目录

```powershell
python -m moments_inventory.cli showcase-db-restore --snapshot "备份目录/某次快照" --destination "E:/CCD恢复验证/新目录"
```

恢复目标必须不存在，工具不会覆盖线上数据。先验证数据库及全部媒体哈希、`integrity_check`、引用清单和记录数，再写入新目录。标准 `storage/showcase_images/` 和 `sample-images/` 路径保持原结构；历史绝对路径及其他相对路径会复制到恢复目录并改写引用，避免继续读取线上文件。

成功后生成 `config/showcase.yaml` 和 `restore-report.json`。恢复目录自包含；启动恢复副本时使用它的配置并显式选择不同端口，例如 `--port 8900`。工具不自动启动服务、不替换正式数据库。

验收测试使用临时 SQLite 与几字节图片，覆盖 WAL、共享样片、缺失文件、损坏文件拒绝、引用校验及拒绝覆盖已有目录：

```powershell
python -m pytest tests/test_showcase_web_backup.py tests/test_cli_showcase_web.py tests/test_showcase_web_import_reconciliation.py -q
```
