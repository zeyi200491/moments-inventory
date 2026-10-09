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


@pytest.mark.parametrize('contents', ['- invalid', 'database: ""', 'server: []', 'server:\n  port: 65536'])
def test_invalid_configuration_is_rejected(tmp_path, contents):
    from moments_inventory.showcase_web.config import load_showcase_settings
    config = tmp_path / 'showcase.yaml'
    config.write_text(contents, encoding='utf-8')
    with pytest.raises(ValueError):
        load_showcase_settings(config)
