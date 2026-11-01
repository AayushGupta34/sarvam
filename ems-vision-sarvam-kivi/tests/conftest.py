"""Force offline mode so that no test can spend Sarvam credits."""
import os
import tempfile
from pathlib import Path

_scratch = Path(tempfile.mkdtemp(prefix="ems-tests-"))
os.environ["FORCE_DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{(_scratch / 'test.db').as_posix()}"
os.environ["APP_ACCESS_TOKEN"] = ""
