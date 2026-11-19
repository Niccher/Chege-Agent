"""
Legacy entrypoint adapter forwarding to modern Chege Agent package (ENG-01).
This allows existing scripts, containers, and compose setups that reference
fast-api/main.py to run the hardened, modernized Chege Agent architecture seamlessly.
"""

import sys
from pathlib import Path

# Ensure root workspace directory is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.main import app, create_app

if __name__ == "__main__":
    import uvicorn
    from backend.app.core.config import get_settings

    settings = get_settings()
    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port, reload=True)
