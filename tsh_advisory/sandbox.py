"""Anonymous demo storage: opaque session namespaces, bounded inactivity, no live provider."""
import os
import gc
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

TTL_SECONDS = 3600
_TOKEN = re.compile(r'^[0-9a-f]{32}$')

def enabled():
    return (Path(__file__).resolve().parents[1] / '.public-sandbox').is_file() or os.getenv('BIO_ADVISORY_PUBLIC_DEMO', '').lower() in ('1', 'true', 'yes')

def base():
    return Path(os.getenv('BIO_ADVISORY_DEMO_ROOT', str(Path(tempfile.gettempdir()) / 'bio-advisory-public-demo')))

def session_path(token):
    if not _TOKEN.fullmatch(token):
        raise ValueError('Invalid demo session.')
    root = base().resolve()
    path = root / token
    if path.is_symlink():
        raise ValueError('Invalid demo storage.')
    return path

def create_session():
    token = uuid.uuid4().hex
    path = session_path(token)
    path.mkdir(parents=True, exist_ok=False)
    (path / '.public-demo').touch()
    touch(token)
    return token

def touch(token):
    path = session_path(token)
    if not (path / '.public-demo').is_file():
        raise ValueError('Demo expired. Reset to start again.')
    (path / '.activity').touch()

def remove_session(token):
    path = session_path(token)
    if path.exists() and (path / '.public-demo').is_file():
        # SQLite context managers commit but older store connections may await GC.
        gc.collect()
        shutil.rmtree(path)

def cleanup(now=None):
    current = time.time() if now is None else now
    root = base()
    if not root.exists():
        return
    for path in root.iterdir():
        if not _TOKEN.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
            continue
        marker = path / '.activity'
        try:
            if marker.is_file() and current - marker.stat().st_mtime > TTL_SECONDS:
                remove_session(path.name)
        except FileNotFoundError:
            pass

def start_janitor():
    def sweep():
        while True:
            try:
                cleanup()
            except OSError:
                pass
            time.sleep(60)
    threading.Thread(target=sweep, name='demo-inactivity-cleanup', daemon=True).start()

def forbid_live(store):
    if enabled() or (store.root / '.public-demo').is_file():
        raise ValueError('Public sandbox: paid model calls and live research are disabled.')
