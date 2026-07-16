import sys
from pathlib import Path

# Make repo-root packages (agents/, infra/, shared/) importable regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
