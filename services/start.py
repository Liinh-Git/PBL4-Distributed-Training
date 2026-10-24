"""Start Runtime, Backend and WebUI. (Start Node Agents via: python services/node-agent.py)"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.services import main  # noqa: E402

if __name__ == "__main__":
    main()
