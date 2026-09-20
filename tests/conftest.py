"""Global pytest fixtures and configuration."""
from pathlib import Path

from dotenv import load_dotenv

# Load .env file before running any tests
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
