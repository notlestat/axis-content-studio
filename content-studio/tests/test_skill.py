import importlib.util
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest
from studio.storage import Studio

REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / 'skills/axis-content-studio/scripts/run_studio.py'
INSTALLER = REPOSITORY / 'tools/install-skill.py'


def run_script(path, *args, cwd, env=None):
    return subprocess.run([sys.executable, str(path), *map(str, args)], cwd=cwd,
                          env=env, capture_output=True, text=True)


def test_installed_skill_finds_app_from_unrelated_folder(tmp_path):
    destination = tmp_path / 'skills/axis-content-studio'
    result = run_script(INSTALLER, '--destination', destination, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    env = {k: v for k, v in os.environ.items() if k != 'AXIS_STUDIO_APP'}
    installed = destination / 'scripts/run_studio.py'
    result = run_script(installed, '--locate', cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)['app']) == REPOSITORY / 'content-studio'
    result = run_script(installed, '--version', cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '0.1.0'
    # Reinstalling cannot overwrite an operator-edited skill.
    (destination / 'SKILL.md').write_text('Operator notes')
    result = run_script(INSTALLER, '--destination', destination, cwd=tmp_path)
    assert result.returncode != 0
    assert (destination / 'SKILL.md').read_text() == 'Operator notes'


def test_invalid_explicit_binding_fails_without_falling_back(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('axis_skill_launcher', LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('AXIS_STUDIO_APP', str(tmp_path / 'missing'))
    with pytest.raises(ValueError, match='AXIS_STUDIO_APP'):
        module.locate_app()


def test_launcher_preserves_relative_source_paths_and_exit_codes(tmp_path):
    store = Studio(tmp_path / 'client-store')
    store.create_client('Local client')
    project = store.create_project('local-client', 'Episode')
    original = tmp_path / 'relative recording.wav'
    with wave.open(str(original), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b'\x00\x00' * 16000)
    env = {**os.environ, 'AXIS_STUDIO_APP': str(REPOSITORY / 'content-studio')}
    result = run_script(LAUNCHER, '--root', store.root, 'ingest', 'local-client',
                        'episode', '--file', original.name, cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    item = project.read('sources.json')[0]
    assert project.file(item['path']).read_bytes() == original.read_bytes()
    result = run_script(LAUNCHER, '--root', store.root, 'client', 'validate',
                        'does-not-exist', cwd=tmp_path, env=env)
    assert result.returncode == 1
