"""Guard and provenance for explicitly approved, inactive development fitting."""
import os
from pathlib import Path
import sys
import json
import importlib.metadata
from .dataset import file_hash
from .config import canonical


def guard(root, *, test_mode=False):
    root = Path(root).resolve()
    def audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind", "urllib.Request"):
            raise PermissionError("Development research prohibits network access")
        if event == "open" and args and isinstance(args[0], (str, bytes)):
            p = Path(os.fsdecode(args[0])); name = p.name.lower()
            secret = (name.startswith(".env") or name.endswith((".key", ".pem", ".p12", ".pfx", ".keystore"))
                      or "credential" in name or name in ("secrets.json", "secrets.toml"))
            dummy = test_mode and name == ".env" and root not in p.resolve().parents
            if secret and not dummy:
                raise PermissionError("Credential files are forbidden")
        if not test_mode and event == "import" and args[0] in (
                "demo_futures.config", "demo_futures.client", "demo_futures.cli", "demo_futures.collector",
                "demo_futures.public_history"):
            raise PermissionError("Exchange clients are forbidden")
    sys.addaudithook(audit)


def environment(root):
    expected = json.loads((Path(root)/"research/dependencies/environment.json").read_text())
    actual = {n: importlib.metadata.version(n) for n in expected["packages"]}
    if actual != expected["packages"] or sys.version.split()[0] != expected["python"]:
        raise RuntimeError("Use the exact pinned research environment")
    if Path(sys.prefix).resolve() != Path(expected["environment"]).resolve():
        raise RuntimeError("Fitting requires the separate research environment")
    return {"python": expected["python"], "packages": actual, "thread_limit": 1}


def write_version(directory, files):
    """New immutable, plain-text version. Never write a deployment pointer or pickle."""
    directory = Path(directory)
    if any(Path(n).name != n or not n.endswith((".json", ".csv", ".md")) for n in files):
        raise ValueError("Only plain safe research artifact names are permitted")
    if directory.exists():
        raise FileExistsError("An experiment version cannot be overwritten or automatically refitted")
    directory.mkdir(parents=True)
    for name, content in sorted(files.items()):
        with (directory/name).open("x", encoding="utf-8", newline="") as f:
            f.write(content)
    manifest = {"stage": "DEVELOPMENT_FOLDS_ONLY", "execution_enabled": False,
                "selection_validation": "LOCKED", "final": "LOCKED", "risk_evidence": "NOT CLEARED",
                "files_sha256": {n: file_hash(directory/n) for n in sorted(files)}}
    (directory/"manifest.json").write_text(canonical(manifest)+"\n", encoding="utf-8")
    return manifest
