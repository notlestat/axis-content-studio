#!/usr/bin/env python3
"""Install this checkout's skill and a local application binding."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    codex_dir = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    parser.add_argument('--destination', type=Path, default=codex_dir / 'skills/axis-content-studio')
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    source = repository / 'skills/axis-content-studio'
    app = repository / 'content-studio'
    if not (source / 'SKILL.md').is_file() or not (app / 'studio/cli.py').is_file():
        parser.error('Run this installer from the complete Axis repository')
    destination = args.destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        parser.error(f'Destination exists; move the existing skill aside before reinstalling: {destination}')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'config.local.json'))
    (destination / 'config.local.json').write_text(json.dumps({'app_path': str(app)}, indent=2) + '\n')
    print(f'Installed skill: {destination}')
    print(f'Application: {app}')
    print('Invoke $axis-content-studio in Codex. If it is not listed yet, start a new task.')


if __name__ == '__main__':
    main()
