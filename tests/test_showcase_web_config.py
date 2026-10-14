from pathlib import Path

import pytest


def test_config_paths_stay_relative_to_config_directory(tmp_path, monkeypatch):
    from moments_inventory.showcase_web.config import load_showcase_settings
    directory = tmp_path / 'config'
    directory.mkdir()
    config = directory / 'showcase.yaml'
    config.write_text('database: ../data/showcase.db\nsample_images_dir: ../real_samples\nserver:\n  port: 9010\nadmin:\n  login_path: /manager\ncustomer:\n  access_cookie_days: 3\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    settings = load_showcase_settings(config)
    assert settings.database == str((tmp_path / 'data/showcase.db').resolve())
    assert settings.sample_images_dir == str((tmp_path / 'real_samples').resolve())
    assert settings.port == 9010
    assert settings.admin_login_path == '/manager'
    assert settings.customer_access_cookie_days == 3
    overrides = load_showcase_settings(config, database='override.db', port=8890)
    assert overrides.database == str(directory / 'override.db')
    assert overrides.port == 8890


@pytest.mark.parametrize('contents', ['admin:\n  login_path: relative', 'customer:\n  access_cookie_days: 0', 'customer:\n  access_cookie_days: 366'])
def test_invalid_admin_path_and_customer_session_length_are_rejected(tmp_path, contents):
    from moments_inventory.showcase_web.config import load_showcase_settings
    config = tmp_path / 'showcase.yaml'
    config.write_text(contents, encoding='utf-8')
    with pytest.raises(ValueError):
        load_showcase_settings(config)


def test_missing_config_is_not_silently_ignored(tmp_path):
    from moments_inventory.showcase_web.config import load_showcase_settings
    with pytest.raises(FileNotFoundError):
        load_showcase_settings(tmp_path / 'missing.yaml')


def test_default_config_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    from moments_inventory.showcase_web.config import DEFAULT_CONFIG_PATH, load_showcase_settings
    expected = load_showcase_settings()
    monkeypatch.chdir(tmp_path)
    actual = load_showcase_settings()
    assert actual == expected
    assert actual.database == str((DEFAULT_CONFIG_PATH.parent / '../data/showcase.db').resolve())


def test_local_config_is_preferred_for_implicit_load(tmp_path, monkeypatch):
    from moments_inventory.showcase_web import config as showcase_config

    shared_config = tmp_path / 'config' / 'showcase.yaml'
    local_config = tmp_path / 'config' / 'showcase.local.yaml'
    shared_config.parent.mkdir()
    shared_config.write_text('database: ../data/shared.db\n', encoding='utf-8')
    local_config.write_text('database: ../data/local.db\n', encoding='utf-8')
    monkeypatch.setattr(showcase_config, 'DEFAULT_CONFIG_PATH', shared_config)
    monkeypatch.setattr(showcase_config, 'LOCAL_CONFIG_PATH', local_config)

    settings = showcase_config.load_showcase_settings()

    assert settings.database == str((tmp_path / 'data/local.db').resolve())


def test_shared_config_is_fallback_when_local_config_is_absent(tmp_path, monkeypatch):
    from moments_inventory.showcase_web import config as showcase_config

    shared_config = tmp_path / 'config' / 'showcase.yaml'
    local_config = tmp_path / 'config' / 'showcase.local.yaml'
    shared_config.parent.mkdir()
    shared_config.write_text('database: ../data/shared.db\n', encoding='utf-8')
    monkeypatch.setattr(showcase_config, 'DEFAULT_CONFIG_PATH', shared_config)
    monkeypatch.setattr(showcase_config, 'LOCAL_CONFIG_PATH', local_config)

    settings = showcase_config.load_showcase_settings()

    assert settings.database == str((tmp_path / 'data/shared.db').resolve())


def test_explicit_config_path_takes_precedence_over_local_override(tmp_path, monkeypatch):
    from moments_inventory.showcase_web import config as showcase_config

    shared_config = tmp_path / 'config' / 'showcase.yaml'
    local_config = tmp_path / 'config' / 'showcase.local.yaml'
    shared_config.parent.mkdir()
    shared_config.write_text('database: ../data/shared.db\n', encoding='utf-8')
    local_config.write_text('database: ../data/local.db\n', encoding='utf-8')
    monkeypatch.setattr(showcase_config, 'DEFAULT_CONFIG_PATH', shared_config)
    monkeypatch.setattr(showcase_config, 'LOCAL_CONFIG_PATH', local_config)

    settings = showcase_config.load_showcase_settings(shared_config)

    assert settings.database == str((tmp_path / 'data/shared.db').resolve())


def test_repository_showcase_config_uses_portable_sample_path():
    import yaml
    from moments_inventory.showcase_web.config import DEFAULT_CONFIG_PATH

    settings = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding='utf-8'))

    assert not Path(settings['sample_images_dir']).is_absolute()


@pytest.mark.parametrize('contents', ['- invalid', 'database: ""', 'server: []', 'server:\n  port: 65536'])
def test_invalid_configuration_is_rejected(tmp_path, contents):
    from moments_inventory.showcase_web.config import load_showcase_settings
    config = tmp_path / 'showcase.yaml'
    config.write_text(contents, encoding='utf-8')
    with pytest.raises(ValueError):
        load_showcase_settings(config)
