"""Start the edge application from this checkout without installing a command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from smart_fridge.main import main  # noqa: E402

if __name__ == "__main__":
    main()
