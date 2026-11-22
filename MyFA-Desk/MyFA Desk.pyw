# Double-click to start MyFA Desk. It runs in the background (no terminal window)
# and opens your dashboard in the browser. Use Quit in the dashboard's top bar to stop it.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app  # noqa: E402

app.main()
