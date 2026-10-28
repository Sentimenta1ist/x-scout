import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = Path(os.getenv("X_SCOUT_DATA", ROOT / "data")).expanduser().resolve()
DATA.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA / "x-scout.db"
BROWSER_PROFILE = DATA / "browser-profile"
PROFILE_MD = DATA / "profile.md"
SETTINGS_JSON = DATA / "settings.json"
# claude -p runs from an empty dir so no CLAUDE.md / project settings get pulled into the prompt.
CLAUDE_CWD = DATA / "claude-cwd"
CLAUDE_CWD.mkdir(exist_ok=True)

PORT = int(os.getenv("PORT", "8765"))
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")


def claude_bin() -> str:
    explicit = os.getenv("CLAUDE_BIN")
    if explicit:
        return str(Path(explicit).expanduser())
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local/bin/claude"
    return str(fallback)
