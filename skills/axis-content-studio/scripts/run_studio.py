#!/usr/bin/env python3
"""Locate Axis and delegate to its own Python environment."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def is_app(path: Path) -> bool:
    return (path / 'studio/cli.py').is_file() and (path / 'pyproject.toml').is_file()


def locate_app() -> Path:
    explicit = os.environ.get('AXIS_STUDIO_APP')
    if explicit:
        app = Path(explicit).expanduser().resolve()
        if not is_app(app):
            raise ValueError('AXIS_STUDIO_APP must point to the content-studio application directory')
        return app
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for parent in (start, *start.parents):
            for candidate in (parent / 'content-studio', parent):
                if is_app(candidate):
                    return candidate.resolve()
    binding = Path(__file__).resolve().parents[1] / 'config.local.json'
    if binding.exists():
        app = Path(json.loads(binding.read_text())['app_path']).expanduser().resolve()
        if is_app(app):
            return app
    raise ValueError('Axis application not found. Clone the repository, install its dependencies, then set AXIS_STUDIO_APP to its content-studio directory. See the repository README.')


def main() -> int:
    try:
        app = locate_app()
        python = app / '.venv/bin/python'
        if sys.argv[1:] == ['--locate']:
            print(json.dumps({'app': str(app), 'readme': str(app / 'README.md'), 'python': str(python), 'environment_installed': python.exists()}, indent=2))
            return 0
        if not python.exists():
            raise ValueError(f'Python environment is missing. Follow {app.parent / "README.md"} to install it.')
        # Preserve cwd for relative input paths. Import the resolved application
        # before any unrelated studio package in the current directory.
        code = 'import sys; app=sys.argv.pop(1); sys.path.insert(0,app); from studio.cli import main; sys.exit(main())'
        return subprocess.call([str(python), '-c', code, str(app), *sys.argv[1:]])
    except (ValueError, KeyError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
