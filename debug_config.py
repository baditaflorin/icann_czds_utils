
from czds_utils.config import Config
import tempfile
import os
from pathlib import Path

env_content = """
CZDS_USERNAME=test_user
CZDS_PASSWORD=test_password_123
CZDS_API_BASE_URL=https://test-api.example.com
DATABASE_PATH=./test.db
LOG_LEVEL=DEBUG
"""

with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
    tmp.write(env_content)
    tmp_path = tmp.name

print(f"Created temp env file: {tmp_path}")

try:
    c = Config(env_file=tmp_path)
    print("Config loaded successfully!")
    print(f"DATABASE_TIMEOUT: {c.DATABASE_TIMEOUT} (type: {type(c.DATABASE_TIMEOUT)})")
except Exception as e:
    print(f"Config failed: {e}")
finally:
    os.unlink(tmp_path)
