"""Community Cloud entry point: always anonymous synthetic-only sandbox."""
import os
import runpy
from pathlib import Path

os.environ['BIO_ADVISORY_PUBLIC_DEMO'] = 'true'
runpy.run_path(str(Path(__file__).parent / 'tsh_advisory' / 'app.py'), run_name='__main__')
