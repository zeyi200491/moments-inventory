from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / 'config' / 'showcase.yaml'


@dataclass(frozen=True)
class ShowcaseSettings:
    database: str
    storage_dir: str
    sample_images_dir: str
    manual_xlsx: str
    backup_dir: str
    host: str = '127.0.0.1'
    port: int = 8899


def load_showcase_settings(config_path: str | Path | None = None, **overrides: object) -> ShowcaseSettings:
    """集中读取展示系统配置，显式参数优先，路径以配置所在目录为基准。"""
    path = Path(config_path or DEFAULT_CONFIG_PATH).resolve()
    with path.open(encoding='utf-8-sig') as stream:
        data = yaml.safe_load(stream)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError('展示配置必须是键值映射')
    defaults = {
        'database': '../data/showcase.db',
        'storage_dir': '../storage/showcase_images',
        'sample_images_dir': '../output/ccdcpt',
        'manual_xlsx': '../manual/客户展示库存.xlsx',
        'backup_dir': '../backup/showcase',
    }
    values = {}
    for key, default in defaults.items():
        value = overrides.get(key)
        if value is None:
            value = data.get(key, default)
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError(f'展示配置路径不能为空：{key}')
        target = Path(value).expanduser()
        values[key] = str((path.parent / target).resolve())
    server = data.get('server', {})
    if not isinstance(server, dict):
        raise ValueError('server 配置必须是键值映射')
    values['host'] = overrides.get('host') if overrides.get('host') is not None else server.get('host', '127.0.0.1')
    values['port'] = int(overrides.get('port') if overrides.get('port') is not None else server.get('port', 8899))
    if not 1 <= values['port'] <= 65535:
        raise ValueError('展示服务端口必须介于 1 和 65535')
    return ShowcaseSettings(**values)
