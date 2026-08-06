import os
import tempfile
from pathlib import Path

TEST_ROOT = Path(tempfile.mkdtemp(prefix="myagentic-test-"))
os.environ["DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["CHROMA_DIR"] = str(TEST_ROOT / "chroma")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["APP_SECRET_KEY"] = "test-key"
os.environ["FRONTEND_ORIGIN"] = "http://testserver"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
