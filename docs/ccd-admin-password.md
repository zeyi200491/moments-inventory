# CCD 管理员口令维护

正常启动使用 `start_showcase_server.bat`。启动过程只初始化数据库结构，不修改已有管理员口令。

需要更换口令时，运行 `reset_showcase_admin_password.bat`，按提示输入两次新口令。输入不会显示在终端；更换成功后，所有已有管理员会话都会失效，需要用新口令重新登录。

管理员批量操作历史及其逐商品撤销快照保留 90 天。超过保留期的操作会在管理员读取操作历史时分批清理，之后无法撤销；这项清理只删除历史记录，不会更改商品现值。

命令行方式：

```powershell
python -m moments_inventory.cli showcase-admin-password-reset --showcase-config config/showcase.local.yaml
```

重置命令和服务启动都使用同一个本机配置。首次配置请按 `docs/ccd-local-configuration.md` 操作。不要把口令作为命令行参数传入。
