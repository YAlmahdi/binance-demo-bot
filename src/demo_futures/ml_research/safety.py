"""Offline entrypoint guard. Instructions alone are not a sandbox."""
import os
from pathlib import Path
import sys


def offline_guard(root, *, test_mode=False):
    root = Path(root).resolve()
    protected_env = root / ".env"

    def audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind", "urllib.Request"):
            raise RuntimeError("Phase 4A prohibits all network access")
        if event == "open" and args and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0]))
            name = path.name.lower()
            secret = (name.startswith(".env") or name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))
                      or "credential" in name or name in ("secrets.json", "secrets.toml"))
            if secret and not (test_mode and name == ".env" and path.resolve() != protected_env
                               and root not in path.resolve().parents):
                raise RuntimeError("Phase 4A prohibits credential-file access")
        if not test_mode and event == "import" and args[0] in (
            "demo_futures.config", "demo_futures.client", "demo_futures.cli", "demo_futures.collector",
            "sklearn", "numpy", "scipy"):
            raise RuntimeError("Authenticated clients and ML dependencies are outside engineering scope")
    sys.addaudithook(audit)
