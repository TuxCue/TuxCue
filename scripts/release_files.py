"""Explicit source-release selection shared by checks and source archiving."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = {'.gitignore', '.gitattributes', '.dockerignore', 'LICENSE', 'README.md',
       'TRADEMARKS.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md',
       'THIRD_PARTY_NOTICES.md', 'AGENTS.md', 'pyproject.toml',
       'requirements.lock', 'requirements-build.lock'}
DIRECTORIES = {'soundboard', 'frontend', 'packaging', 'scripts', 'tests', 'docs', '.github'}
EXCLUDED = {'__pycache__', 'node_modules', 'dist', 'input-cache', '.pytest_cache'}


def files():
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.is_file() and (str(relative) in TOP or relative.parts[0] in DIRECTORIES):
            if path.is_symlink():
                raise ValueError(f'Source release must not follow symlinks: {relative}')
            yield path
