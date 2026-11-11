import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("COPILOT_LLM", "off")
COPILOT = Path(os.getenv("ONCALL_COPILOT_REPO", ROOT.parent / "oncall-copilot-v2"))
if (COPILOT / "src").exists():
    sys.path.insert(0, str(COPILOT / "src"))
