@echo off
setlocal
echo [已停用] 旧静态展示站发布入口不再用于 CCD 正式展示系统。
echo 当前管理数据保存在本地 SQLite；Cloudflare 仅接收只读发布快照。
echo 请按 docs\ccd-release-runbook.md 和 Cloudflare 仓库的发布手册操作。
pause
exit /b 1
