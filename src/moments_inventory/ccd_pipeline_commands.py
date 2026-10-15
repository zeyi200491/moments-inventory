from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import json
import re
import shutil
import subprocess
import tomllib
from typing import Callable, Sequence

from moments_inventory.showcase_web.config import load_showcase_settings


class PipelinePreflightError(RuntimeError):
    """执行 CCD 流程前发现环境或目标不符合要求。"""


class PipelineCommandError(RuntimeError):
    """外部命令失败或在超时后结果未知。"""

    def __init__(self, message: str, *, unknown: bool = False):
        super().__init__(message)
        self.unknown = unknown


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PreflightResult:
    project_root: Path
    cloud_repo: Path
    showcase_config: Path
    database: Path
    storage_dir: Path
    sample_images_dir: Path
    manual_xlsx: Path
    backup_dir: Path
    cloud_config: Path
    database_name: str
    bucket_name: str
    environment_fingerprint: str
    target_fingerprint: str
    admin_url: str = "http://127.0.0.1:8899/admin-xingxing"


def _safe_output(value: str, environment: dict[str, str] | None = None) -> str:
    result = value[-12000:]
    for key, secret in (environment or os.environ).items():
        if secret and any(part in key.casefold() for part in ("password", "token", "secret", "cookie", "authorization")):
            result = result.replace(secret, "[已脱敏]")
    result = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[已脱敏]", result)
    return result


def run_command(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | Path,
    timeout: float = 3600,
    runner: Callable = subprocess.run,
    environment: dict[str, str] | None = None,
) -> CommandResult:
    command = [os.fspath(argument) for argument in argv]
    if not command or not command[0]:
        raise PipelineCommandError("外部命令参数为空")
    try:
        completed = runner(
            command,
            cwd=os.fspath(cwd),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipelineCommandError("外部命令超时，执行结果未知", unknown=True) from exc
    except OSError as exc:
        raise PipelineCommandError("外部命令无法启动") from exc
    result = CommandResult(
        returncode=int(completed.returncode),
        stdout=_safe_output(str(completed.stdout or ""), environment),
        stderr=_safe_output(str(completed.stderr or ""), environment),
    )
    if result.returncode:
        raise PipelineCommandError(
            f"外部命令退出码为 {result.returncode}：{result.stderr or result.stdout or '无诊断输出'}"
        )
    return result


def _git_value(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip() or "empty"


def _files_fingerprint(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.resolve()).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _cloud_target(config: Path) -> tuple[str, str]:
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
        d1 = data["d1_databases"]
        r2 = data["r2_buckets"]
        databases = [item for item in d1 if item.get("binding") == "DB"]
        buckets = [item for item in r2 if item.get("binding") == "IMAGES"]
        if len(databases) != 1 or len(buckets) != 1:
            raise ValueError
        database = str(databases[0]["database_name"])
        bucket = str(buckets[0]["bucket_name"])
        if not database or not bucket:
            raise ValueError
        return database, bucket
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise PipelinePreflightError("Cloudflare 配置中 DB/IMAGES 目标无效或不唯一") from exc


def validate_preflight(
    project_root: str | Path,
    cloud_repo: str | Path,
    *,
    config_path: str | Path | None = None,
    cloud_config_path: str | Path | None = None,
    require_tools: bool = True,
    command_probe: Callable[[Sequence[str]], object] | None = None,
    environment_verifier: Callable[..., dict[str, str]] | None = None,
) -> PreflightResult:
    root = Path(project_root).resolve()
    cloud = Path(cloud_repo).resolve()
    if not str(cloud_repo).strip():
        raise PipelinePreflightError("必须显式指定 Cloudflare 仓库路径")
    required_local = (
        root / "run_full_mode.bat",
        root / "src" / "moments_inventory" / "showcase_web",
        root / "pyproject.toml",
    )
    if not all(path.exists() for path in required_local):
        raise PipelinePreflightError("当前目录不是 CCD 展示网页项目根目录")
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            local_project = tomllib.load(stream)
        if local_project.get("project", {}).get("name") != "moments-inventory":
            raise ValueError
    except (OSError, ValueError, tomllib.TOMLDecodeError, AttributeError) as exc:
        raise PipelinePreflightError("本地项目标识不匹配 moments-inventory") from exc
    selected_config = Path(config_path).resolve() if config_path else None
    if selected_config is None:
        local_config = root / "config" / "showcase.local.yaml"
        selected_config = local_config if local_config.is_file() else root / "config" / "showcase.yaml"
    if not selected_config.is_file():
        raise PipelinePreflightError("CCD 展示配置不存在")
    if environment_verifier is None:
        try:
            from scripts.verify_showcase_environment import verify_showcase_config

            environment_verifier = verify_showcase_config
        except ImportError as exc:
            raise PipelinePreflightError("无法加载 CCD 正式工作树环境门禁") from exc
    try:
        verified_environment = environment_verifier(selected_config, entrypoint_root=root)
        settings = load_showcase_settings(selected_config)
    except Exception as exc:
        raise PipelinePreflightError("CCD 正式工作树或展示配置门禁拒绝本次运行") from exc
    database = Path(settings.database).resolve()
    storage = Path(settings.storage_dir).resolve()
    sample_images = Path(settings.sample_images_dir).resolve()
    manual_xlsx = Path(settings.manual_xlsx).resolve()
    backup = Path(settings.backup_dir).resolve()
    if not database.is_file() or not database.name.casefold().endswith(".db"):
        raise PipelinePreflightError("配置指向的 CCD SQLite 数据库不存在或路径类型错误")
    if not storage.is_dir() or not sample_images.is_dir():
        raise PipelinePreflightError("配置声明的商品图片或样片目录不存在")
    cloud_markers = (
        cloud / "package.json",
        cloud / "scripts" / "export-local-showcase.py",
        cloud / "scripts" / "sync-cloudflare.mjs",
        cloud / "scripts" / "verify-deploy-config.mjs",
    )
    if not cloud.is_dir() or not all(path.is_file() for path in cloud_markers):
        raise PipelinePreflightError("Cloudflare 仓库缺少必需的配置或同步脚本")
    try:
        cloud_package = json.loads((cloud / "package.json").read_text(encoding="utf-8"))
        if cloud_package.get("name") != "xingxing-ccd-showcase":
            raise ValueError
    except (OSError, ValueError, json.JSONDecodeError, AttributeError) as exc:
        raise PipelinePreflightError("Cloudflare 项目标识不匹配 CCD 展示网页仓库") from exc
    local_git_root = _git_value(root, "rev-parse", "--show-toplevel")
    cloud_git_root = _git_value(cloud, "rev-parse", "--show-toplevel")
    if (local_git_root == "unavailable" or cloud_git_root == "unavailable"
            or Path(local_git_root).resolve() != root
            or Path(cloud_git_root).resolve() != cloud):
        raise PipelinePreflightError("本地 CCD 项目和 Cloudflare 路径必须分别是各自仓库的 Git 根目录")
    cloud_config = Path(cloud_config_path).resolve() if cloud_config_path else cloud / "wrangler.toml"
    if not cloud_config.is_file() or not cloud_config.is_relative_to(cloud):
        raise PipelinePreflightError("Cloudflare 配置必须是指定仓库内的文件")
    database_name, bucket_name = _cloud_target(cloud_config)
    output = root / "output" / "ccd-pipeline" / "runs"
    try:
        output.mkdir(parents=True, exist_ok=True)
        probe_path = output / ".write-check"
        probe_path.write_text("ok", encoding="ascii")
        probe_path.unlink()
    except OSError as exc:
        raise PipelinePreflightError("CCD 流程状态目录不可写") from exc
    if require_tools:
        names = ("node",)
        missing = [name for name in names if shutil.which(name) is None]
        if missing:
            raise PipelinePreflightError("缺少所需命令：" + ", ".join(missing))
        if command_probe is not None:
            command_probe(names)
    environment = "|".join((
        str(root), str(database), str(verified_environment.get("environment_id", "")),
        _git_value(root, "rev-parse", "HEAD"),
        _files_fingerprint([selected_config, root / "run_full_mode.bat"]),
    ))
    target = "|".join((
        str(cloud), _git_value(cloud, "rev-parse", "HEAD"), str(cloud_config), database_name, bucket_name,
        _files_fingerprint([
            cloud_config,
            cloud / "scripts" / "export-local-showcase.py",
            cloud / "scripts" / "sync-cloudflare.mjs",
            cloud / "scripts" / "verify-deploy-config.mjs",
        ]),
    ))

    return PreflightResult(
        project_root=root,
        cloud_repo=cloud,
        showcase_config=selected_config,
        database=database,
        storage_dir=storage,
        sample_images_dir=sample_images,
        manual_xlsx=manual_xlsx,
        backup_dir=backup,
        cloud_config=cloud_config,
        database_name=database_name,
        bucket_name=bucket_name,
        environment_fingerprint=hashlib.sha256(environment.encode()).hexdigest(),
        target_fingerprint=hashlib.sha256(target.encode()).hexdigest(),
        admin_url=(
            f"http://{'127.0.0.1' if settings.host in {'0.0.0.0', '::'} else settings.host}:"
            f"{settings.port}{settings.admin_login_path}"
        ),
    )
