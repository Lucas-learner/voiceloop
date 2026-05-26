from voiceloop.config import load_config, expand_path


def test_load_config_defaults():
    config = load_config()
    assert config.source_dir.name == "Recordings"
    assert config.data_dir.name == "data"
    assert config.repo_root.name == "voiceloop"


def test_expand_path():
    assert expand_path("~/tmp").name == "tmp"
