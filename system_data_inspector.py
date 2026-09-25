"""
macOS System Data Inspector
Scans filesystem locations responsible for "System Data" disk usage.
Run with: python system_data_inspector.py
Requires: pip install PySide6 matplotlib
"""

import os
import re
import sys
import subprocess
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependency bootstrap — runs before any third-party imports
# ---------------------------------------------------------------------------

def _check_and_install_dependencies():
    """Check for required packages and offer to install if missing."""
    import importlib.util

    REQUIRED = {
        "PySide6": "PySide6>=6.4.0",
        "matplotlib": "matplotlib>=3.6.0",
    }

    missing = [pkg for pkg, _ in REQUIRED.items() if importlib.util.find_spec(pkg) is None]

    if not missing:
        return

    print("\n" + "=" * 58)
    print("  Missing required packages:")
    for pkg in missing:
        print(f"    • {pkg}")
    print("=" * 58)

    req_file = Path(__file__).parent / "requirements.txt"
    install_cmd = (
        f"{sys.executable} -m pip install -r {req_file}"
        if req_file.exists()
        else f"{sys.executable} -m pip install " + " ".join(REQUIRED[p] for p in missing)
    )

    answer = input("\nInstall them now? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted. Install manually with:\n  pip install PySide6 matplotlib")
        sys.exit(1)

    print("\nInstalling…")
    result = subprocess.run(install_cmd, shell=True)
    if result.returncode != 0:
        print("\nInstallation failed. Try manually:\n  pip install PySide6 matplotlib")
        sys.exit(1)

    print("\nInstallation complete — restarting…\n")
    os.execv(sys.executable, [sys.executable] + sys.argv)


_check_and_install_dependencies()

# ---------------------------------------------------------------------------
# Standard + third-party imports (safe after bootstrap)
# ---------------------------------------------------------------------------

import csv
import json
import plistlib
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QProgressBar, QLabel, QSlider, QCheckBox, QTableView,
    QLineEdit, QListWidget,
    QHeaderView, QAbstractItemView, QMenu, QMessageBox, QSizePolicy,
    QScrollArea, QGroupBox, QFrame, QDialog,
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    QTimer,
)
from PySide6.QtGui import QColor, QPalette, QFont, QAction, QBrush

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATEGORY_COLORS = {
    "Cache":       "#E07B39",
    "App Support": "#4A90D9",
    "Log":         "#7ED321",
    "iOS Backup":  "#D0021B",
    "Snapshot":    "#9B59B6",
    "Trash":       "#95A5A6",
    "Container":   "#F39C12",
    "Developer":   "#1ABC9C",
}

CLEANUP_ADVICE = {
    "docker": {
        "risk": "safe",
        "what": "Docker virtual machine disk image and container data. The sparse disk image can claim hundreds of GBs while only occupying a fraction on disk.",
        "steps": [
            "If Docker is installed: open Terminal and run →  docker system prune -a --volumes",
            "If Docker is NOT installed: delete ~/Library/Containers/com.docker.docker via Finder (terminal rm is blocked by macOS)",
            "Also remove: ~/Library/Application Support/Docker Desktop  and  ~/.docker",
        ],
    },
    "xcode": {
        "risk": "safe",
        "what": "Xcode build artifacts including DerivedData, archives, and device support files.",
        "steps": [
            "In Xcode: Settings → Locations → click the arrow next to Derived Data → delete the folder",
            "Or delete directly in terminal:  rm -rf ~/Library/Developer/Xcode/DerivedData",
            "Remove unused simulators:  xcrun simctl delete unavailable",
            "Remove old device support in Xcode → Settings → Platforms",
        ],
    },
    "pip": {
        "risk": "safe",
        "what": "Python pip package download cache. Packages are re-downloaded if needed.",
        "steps": [
            "Run in Terminal:  pip cache purge",
            "Or delete directly:  rm -rf ~/Library/Caches/pip",
        ],
    },
    "homebrew": {
        "risk": "safe",
        "what": "Homebrew cached bottle downloads. Old versions pile up after upgrades.",
        "steps": [
            "Run in Terminal:  brew cleanup",
            "Aggressive cleanup (remove all):  brew cleanup --prune=all",
        ],
    },
    "spotify": {
        "risk": "safe",
        "what": "Spotify local song cache for offline/faster playback.",
        "steps": [
            "In Spotify: Settings → Storage → Clear Cache",
            "Or delete directly:  rm -rf ~/Library/Caches/com.spotify.client",
        ],
    },
    "google": {
        "risk": "caution",
        "what": "Google app data (Chrome, Drive, Earth, etc.) including browser cache and profile data.",
        "steps": [
            "Chrome cache (safe): Settings → More Tools → Clear Browsing Data",
            "Or delete cache only:  rm -rf ~/Library/Caches/Google/Chrome",
            "⚠ Do NOT delete ~/Library/Application Support/Google/Chrome — that contains your profile/bookmarks",
        ],
    },
    "microsoft": {
        "risk": "caution",
        "what": "Microsoft Office and related app data including update cache and document history.",
        "steps": [
            "Safe to remove update cache:  ~/Library/Application Support/Microsoft/MAU2.0",
            "Clear Office font cache:  ~/Library/Caches/com.microsoft.Office",
            "Keep ~/Library/Application Support/Microsoft/Office if you want to preserve settings",
        ],
    },
    "creativecloud": {
        "risk": "caution",
        "what": "Adobe Creative Cloud logs, crash reports, and cached installers.",
        "steps": [
            "Use Creative Cloud Desktop → Preferences → Creative Cloud → Clean Up (in some versions)",
            "Safe to delete:  ~/Library/Logs/CreativeCloud",
            "Cached installers in ~/Library/Application Support/Adobe/AAMUpdater",
        ],
    },
    "adobe": {
        "risk": "caution",
        "what": "Adobe app data including cache, scratch disks, and media cache.",
        "steps": [
            "In Premiere/After Effects: Preferences → Media Cache → Clean Database and Cache",
            "Scratch disks can be relocated in app preferences",
            "Logs at ~/Library/Logs/Adobe are safe to delete",
        ],
    },
    "cursor": {
        "risk": "caution",
        "what": "Cursor IDE app support data including workspace storage, extensions, and logs.",
        "steps": [
            "Close Cursor first",
            "Safe to delete logs:  ~/Library/Logs/Cursor",
            "Workspace storage (large): ~/Library/Application Support/Cursor/User/workspaceStorage",
            "Extensions can be reinstalled if removed",
        ],
    },
    "windsurf": {
        "risk": "caution",
        "what": "Windsurf IDE app support data including workspace storage and logs.",
        "steps": [
            "Close Windsurf first",
            "Safe to delete logs:  ~/Library/Logs/Windsurf",
            "Workspace storage:  ~/Library/Application Support/Windsurf/User/workspaceStorage",
        ],
    },
    "claude": {
        "risk": "caution",
        "what": "Claude desktop app data and cache.",
        "steps": [
            "Close the Claude app first",
            "Cache is safe to delete:  ~/Library/Caches/Claude",
            "App Support contains conversation history — delete only if you want a fresh start",
        ],
    },
    "simulator": {
        "risk": "safe",
        "what": "iOS/macOS Simulator device data and disk images.",
        "steps": [
            "Delete unavailable simulators:  xcrun simctl delete unavailable",
            "Remove all simulator data:  xcrun simctl delete all  (use with caution)",
            "Manage runtimes in Xcode → Settings → Platforms",
        ],
    },
}

CATEGORY_ADVICE = {
    "Cache": {
        "risk": "safe",
        "what": "Temporary files apps create to speed up operations. Apps automatically rebuild their caches — deleting them is always safe.",
        "steps": [
            "Right-click any row → Move to Trash  (or use the button below)",
            "Or in Terminal:  rm -rf \"<path>\"",
            "Restart the app if it feels slow after clearing its cache",
        ],
    },
    "App Support": {
        "risk": "caution",
        "what": "Application data including settings, databases, and saved state. Some is expendable; some contains important user data.",
        "steps": [
            "Use 'Reveal in Finder' to inspect the folder contents first",
            "If the app is uninstalled, this folder is safe to delete",
            "If the app is installed, deleting resets it to a fresh state (settings lost)",
        ],
    },
    "Log": {
        "risk": "safe",
        "what": "Log files written by apps for debugging purposes. Apps create new log files automatically.",
        "steps": [
            "Safe to delete entirely — right-click → Move to Trash",
            "Or reset all system logs:  sudo log erase --all",
        ],
    },
    "iOS Backup": {
        "risk": "risky",
        "what": "Full device backups of your iPhone or iPad. Deleting removes your ability to restore that device from this Mac.",
        "steps": [
            "In Finder: connect your device → select it → Manage Backups → delete old backups",
            "Keep at least one recent backup before deleting any",
            "Consider using iCloud Backup as an alternative before removing local backups",
        ],
    },
    "Snapshot": {
        "risk": "caution",
        "what": "Time Machine local snapshots kept on your drive for quick recovery without an external disk.",
        "steps": [
            "macOS manages these automatically and removes them when space is needed",
            "Force-delete all local snapshots:  sudo tmutil deletelocalsnapshots /",
            "Or delete a specific one:  sudo tmutil deletelocalsnapshots <date>",
        ],
    },
    "Trash": {
        "risk": "safe",
        "what": "Files already moved to the Trash. They still occupy disk space until the Trash is emptied.",
        "steps": [
            "Right-click the Trash icon in the Dock → Empty Trash",
            "Or in Finder: Finder menu → Empty Trash  (⌘⇧⌫)",
        ],
    },
    "Container": {
        "risk": "caution",
        "what": "Sandboxed app container managed by macOS, containing the app's private databases and preferences.",
        "steps": [
            "If the app is uninstalled: safe to delete — use Finder (terminal rm may be blocked)",
            "Open Finder → ⌘⇧G → ~/Library/Containers → drag folder to Trash",
            "If the app is still installed: deleting resets it completely (like a fresh install)",
        ],
    },
    "Developer": {
        "risk": "caution",
        "what": "Xcode build products, simulator devices, and iOS device support files. Large, and safe to remove only if you do not need those builds or simulators.",
        "steps": [
            "Derived Data can be deleted: Xcode rebuilds it",
            "Old device-support folders are leftovers from iPhones you plugged in",
            "Removing CoreSimulator devices deletes those simulators",
        ],
    },
}

RISK_COLORS = {
    "safe":    "#27AE60",
    "caution": "#F39C12",
    "risky":   "#E74C3C",
}

RISK_LABELS = {
    "safe":    "✓  Safe to delete",
    "caution": "⚠  Delete with caution",
    "risky":   "✗  High risk — read carefully before deleting",
}

SCAN_TARGETS = [
    (Path("~/Library/Caches").expanduser(),                                "Cache"),
    (Path("~/Library/Application Support").expanduser(),                   "App Support"),
    (Path("~/Library/Logs").expanduser(),                                  "Log"),
    (Path("~/Library/Containers").expanduser(),                            "Container"),
    (Path("~/Library/Group Containers").expanduser(),                      "Container"),
    (Path("~/Library/Application Support/MobileSync/Backup").expanduser(), "iOS Backup"),
    (Path("~/.Trash").expanduser(),                                        "Trash"),
    (Path("/private/var/folders"),                                          "Cache"),
    (Path("~/Library/Developer").expanduser(),                             "Developer"),
]

# Flags macOS uses to stop a file from being removed.
# UF_IMMUTABLE, UF_APPEND, SF_IMMUTABLE, SF_APPEND, SF_RESTRICTED, SF_NOUNLINK.
MACOS_PROTECT_FLAGS = 0x00000002 | 0x00000004 | 0x00020000 | 0x00040000 | 0x00080000 | 0x00100000
VAR_FOLDERS = Path("/private/var/folders")
DEVELOPER_ROOT = Path("~/Library/Developer").expanduser()
DATA_VOLUME = Path("/System/Volumes/Data")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_size(n: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


_BUNDLE_SEGMENT_NAMES = {
    "goodnotesapp": "GoodNotes",
    "spotify": "Spotify",
    "google": "Google",
    "microsoft": "Microsoft",
    "adobe": "Adobe",
    "dropbox": "Dropbox",
    "docker": "Docker",
    "slack": "Slack",
    "zoom": "Zoom",
    "figma": "Figma",
    "notion": "Notion",
    "obsidian": "Obsidian",
    "1password": "1Password",
    "lastpass": "LastPass",
    "nordvpn": "NordVPN",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "signal": "Signal",
    "discord": "Discord",
    "twitch": "Twitch",
    "netflix": "Netflix",
    "plex": "Plex",
    "vlc": "VLC",
    "handbrake": "HandBrake",
    "bbedit": "BBEdit",
    "transmit": "Transmit",
    "istatmenus": "iStat Menus",
    "bartender": "Bartender",
    "alfredapp": "Alfred",
    "raycast": "Raycast",
    "rectangle": "Rectangle",
    "magnet": "Magnet",
}

_GENERIC_SUFFIXES = {
    "client", "app", "macos", "mac", "helper", "agent",
    "extension", "plugin", "service", "daemon", "x",
}


def bundle_id_to_app_name(folder_name: str) -> str:
    """
    'com.apple.Safari'        → 'Safari'
    'com.spotify.client'      → 'Spotify'
    'com.goodnotesapp.x'      → 'GoodNotes'
    'group.com.apple.notes'   → 'Notes'
    Fallback: title-case the last meaningful component.
    """
    name = folder_name.strip()
    if name.lower().startswith("group."):
        name = name[6:]
    parts = name.split(".")
    if len(parts) < 2:
        return folder_name.replace("-", " ").replace("_", " ").title()

    # Check all segments against known name map (right-to-left for specificity)
    for part in reversed(parts):
        mapped = _BUNDLE_SEGMENT_NAMES.get(part.lower())
        if mapped:
            return mapped

    # Walk right-to-left, skip generic/single-char suffixes
    last = parts[-1]
    for part in reversed(parts):
        if part.lower() not in _GENERIC_SUFFIXES and len(part) > 1:
            last = part
            break

    return last.replace("-", " ").replace("_", " ").title()


def get_dir_size(path: Path, max_depth: int = None, _current_depth: int = 0) -> int:
    """Recursively sum file sizes, skipping symlinks and permission errors."""
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        try:
                            total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                    elif entry.is_dir(follow_symlinks=False):
                        if max_depth is None or _current_depth < max_depth:
                            total += get_dir_size(
                                Path(entry.path), max_depth, _current_depth + 1
                            )
                except (PermissionError, OSError):
                    pass
    except (PermissionError, OSError):
        pass
    return total


# ---------------------------------------------------------------------------
# Repeat Offender Log
# ---------------------------------------------------------------------------

LOG_PATH = Path(
    "~/Library/Application Support/CleanMeMacOS/offender_log.json"
).expanduser()


class OffenderLog:
    """Persistent log that tracks apps appearing across multiple scans."""

    VERSION = 1

    def __init__(self):
        self._data: dict = {"version": self.VERSION, "apps": {}}
        self._load()

    def _load(self):
        if LOG_PATH.exists():
            try:
                with open(LOG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and "apps" in loaded:
                    self._data = loaded
            except Exception:
                pass

    def _save(self):
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, default=str)
        except Exception:
            pass

    def record_scan(self, items: list):
        """Called after each scan; groups items by app and logs cumulative stats."""
        now = datetime.now().isoformat()
        by_app: dict[str, dict] = {}
        for item in items:
            name = item["app_name"]
            if name not in by_app:
                by_app[name] = {"size_bytes": 0, "categories": set(), "locations": []}
            by_app[name]["size_bytes"] += item["size_bytes"]
            by_app[name]["categories"].add(item["category"])
            by_app[name]["locations"].append({
                "path": item["path"],
                "category": item["category"],
                "size_bytes": item["size_bytes"],
            })

        apps = self._data["apps"]
        for name, agg in by_app.items():
            if name not in apps:
                apps[name] = {
                    "times_seen": 0,
                    "first_seen": now,
                    "last_seen": now,
                    "categories": [],
                    "notes": "",
                    "flagged": False,
                    "scan_history": [],
                    "locations": [],
                }
            entry = apps[name]
            entry["times_seen"] += 1
            entry["last_seen"] = now
            entry["categories"] = sorted(
                set(entry["categories"]) | agg["categories"]
            )
            entry["locations"] = sorted(
                agg["locations"], key=lambda loc: loc["size_bytes"], reverse=True
            )
            entry["scan_history"].append({
                "date": now,
                "size_bytes": agg["size_bytes"],
                "categories": sorted(agg["categories"]),
            })
            if len(entry["scan_history"]) > 50:
                entry["scan_history"] = entry["scan_history"][-50:]

        self._save()

    def flag_app(self, app_name: str, note: str = ""):
        """Manually mark an app as a person of interest."""
        now = datetime.now().isoformat()
        apps = self._data["apps"]
        if app_name not in apps:
            apps[app_name] = {
                "times_seen": 0,
                "first_seen": now,
                "last_seen": now,
                "categories": [],
                "notes": note,
                "flagged": True,
                "scan_history": [],
                "locations": [],
            }
        else:
            apps[app_name]["flagged"] = True
            if note:
                apps[app_name]["notes"] = note
        self._save()

    def clear_app(self, app_name: str):
        if app_name in self._data["apps"]:
            del self._data["apps"][app_name]
            self._save()

    def clear_all(self):
        self._data["apps"] = {}
        self._save()

    def forget_locations(self, app_name: str, paths: list):
        """Drop trashed folders from the last known footprint of an app."""
        entry = self._data["apps"].get(app_name)
        if not entry:
            return
        drop = set(paths)
        entry["locations"] = [
            loc for loc in entry.get("locations", []) if loc.get("path") not in drop
        ]
        self._save()

    def get_offenders(self) -> list:
        """Return all tracked apps sorted by sightings desc, then peak size desc."""
        result = []
        for name, entry in self._data["apps"].items():
            history = entry.get("scan_history", [])
            sizes = [h["size_bytes"] for h in history]
            peak = max(sizes) if sizes else 0
            last_size = sizes[-1] if sizes else 0
            prev_size = sizes[-2] if len(sizes) >= 2 else last_size
            if last_size > prev_size * 1.05:
                trend = "↑ Growing"
            elif last_size < prev_size * 0.95:
                trend = "↓ Shrinking"
            else:
                trend = "~ Stable"
            result.append({
                "app_name": name,
                "times_seen": entry["times_seen"],
                "first_seen": entry["first_seen"],
                "last_seen": entry["last_seen"],
                "categories": ", ".join(entry.get("categories", [])),
                "peak_size_bytes": peak,
                "last_size_bytes": last_size,
                "trend": trend,
                "flagged": entry.get("flagged", False),
                "notes": entry.get("notes", ""),
                "locations": list(entry.get("locations") or []),
            })
        result.sort(key=lambda x: (-x["times_seen"], -x["peak_size_bytes"]))
        return result

    def offender_count(self) -> int:
        """Number of apps seen 2+ times or manually flagged."""
        return sum(
            1 for e in self._data["apps"].values()
            if e["times_seen"] >= 2 or e.get("flagged")
        )

    def previous_size(self, app_name: str):
        """Size from the scan before the latest one, or None if this is the first."""
        history = self._data["apps"].get(app_name, {}).get("scan_history", [])
        if len(history) < 2:
            return None
        return history[-2].get("size_bytes")

    def is_ignored(self, app_name: str) -> bool:
        return app_name in self._data.setdefault("ignored_apps", [])

    def set_ignored(self, app_name: str, ignored: bool):
        names = self._data.setdefault("ignored_apps", [])
        if ignored and app_name not in names:
            names.append(app_name)
        elif not ignored and app_name in names:
            names.remove(app_name)
        self._save()

    @property
    def log_path(self) -> Path:
        return LOG_PATH


# ---------------------------------------------------------------------------
# Scan Worker
# ---------------------------------------------------------------------------

class ScanWorker(QThread):
    progress = Signal(str)
    item_found = Signal(dict)
    permission_warning = Signal(str)
    finished = Signal()

    def __init__(self, min_size_bytes: int = 0):
        super().__init__()
        self._min_size = min_size_bytes
        self._abort = False
        self._files_scanned = 0
        self._items_found = 0
        self._bytes_found = 0
        self.protected_kept: list[str] = []
        self.volume_report: dict = {"purgeable_bytes": 0, "snapshots": []}

    def abort(self):
        self._abort = True

    def _check_full_disk_access(self):
        """Probe /private/var/folders to detect missing Full Disk Access."""
        try:
            os.listdir("/private/var/folders")
        except PermissionError:
            self.permission_warning.emit(
                "Full Disk Access is not granted to this terminal/app.\n\n"
                "The scan will continue but /private/var/folders will be skipped.\n\n"
                "Click \"Full Disk Access\" in the Controls panel to open "
                "System Settings and grant access."
            )

    def _get_dir_size(self, path: Path, max_depth: int = None, _current_depth: int = 0) -> int:
        """Recursively sum file sizes, emitting periodic progress while counting."""
        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if self._abort:
                        return total
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            try:
                                total += entry.stat(follow_symlinks=False).st_size
                                self._files_scanned += 1
                                if self._files_scanned % 500 == 0:
                                    self.progress.emit(
                                        f"{self._items_found} items "
                                        f"({format_size(self._bytes_found)}) — "
                                        f"{self._files_scanned:,} files counted…"
                                    )
                            except OSError:
                                pass
                        elif entry.is_dir(follow_symlinks=False):
                            if max_depth is None or _current_depth < max_depth:
                                total += self._get_dir_size(
                                    Path(entry.path), max_depth, _current_depth + 1
                                )
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass
        return total

    def run(self):
        self._check_full_disk_access()
        # Scan directory targets
        for base_path, category in SCAN_TARGETS:
            if self._abort:
                break
            if not base_path.exists():
                continue

            self.progress.emit(f"Scanning {base_path} …")

            if base_path == VAR_FOLDERS:
                self._scan_var_folders(base_path, category)
                continue
            if base_path == DEVELOPER_ROOT:
                self._scan_developer(base_path, category)
                continue

            # Regular top-level scan: each immediate child becomes one item
            try:
                with os.scandir(base_path) as it:
                    entries = list(it)
            except (PermissionError, OSError):
                self.progress.emit(f"⚠ Permission denied: {base_path}")
                continue

            for entry in entries:
                if self._abort:
                    break
                try:
                    p = Path(entry.path)
                    if entry.is_symlink():
                        continue
                    if _is_protected_by_macos(p):
                        self._note_protected(p)
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        self._scan_subdir(p, category, max_depth=None)
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        self._emit_item(p, size, category, p.name)
                except (PermissionError, OSError):
                    pass

        # Time Machine local snapshots
        if not self._abort:
            self.progress.emit("Querying Time Machine snapshots …")
            self._scan_snapshots()

        self.finished.emit()

    def _scan_var_folders(self, base_path: Path, category: str):
        """List deletable caches inside /private/var/folders.

        Layout is <2-char>/<per-user-id>/{C,T,0,X}. The per-user directory
        and C/T/0/X carry SF_NOUNLINK, so Finder refuses them with
        "required by macOS". Reclaimable caches are the children of C/.
        """
        uid = os.getuid()
        try:
            prefixes = list(os.scandir(base_path))
        except (PermissionError, OSError):
            self.progress.emit(f"⚠ Permission denied: {base_path}")
            return

        for prefix in prefixes:
            if self._abort:
                return
            if not prefix.is_dir(follow_symlinks=False):
                continue
            try:
                user_dirs = list(os.scandir(prefix.path))
            except (PermissionError, OSError):
                continue
            for user_dir in user_dirs:
                if self._abort:
                    return
                if not user_dir.is_dir(follow_symlinks=False):
                    continue
                try:
                    if user_dir.stat(follow_symlinks=False).st_uid != uid:
                        continue
                except OSError:
                    continue
                cache_dir = Path(user_dir.path) / "C"
                try:
                    children = list(os.scandir(cache_dir))
                except (PermissionError, OSError):
                    continue
                for child in children:
                    if self._abort:
                        return
                    try:
                        if child.is_symlink():
                            continue
                        st = child.stat(follow_symlinks=False)
                        if st.st_flags & MACOS_PROTECT_FLAGS:
                            self._note_protected(Path(child.path))
                            continue
                        p = Path(child.path)
                        if child.is_dir(follow_symlinks=False):
                            self._scan_subdir(p, category, max_depth=None)
                        else:
                            self._emit_item(p, st.st_size, category, p.name)
                    except (PermissionError, OSError):
                        pass

    def _note_protected(self, path: Path):
        self.protected_kept.append(path.name)

    def _scan_developer(self, root: Path, category: str):
        """List Xcode and simulator folders without merging them into one blob."""
        xcode = root / "Xcode"
        named = [
            xcode / "DerivedData",
            xcode / "iOS DeviceSupport",
            xcode / "watchOS DeviceSupport",
            xcode / "tvOS DeviceSupport",
            xcode / "Archives",
            xcode / "Products",
            root / "CoreSimulator",
        ]
        seen = {path.resolve() for path in named if path.exists()}
        for path in named:
            if self._abort:
                return
            if path.is_dir():
                self._scan_subdir(path, category)
        if xcode.is_dir():
            try:
                children = list(xcode.iterdir())
            except OSError:
                children = []
            for child in children:
                if self._abort:
                    return
                try:
                    if child.is_symlink() or child.resolve() in seen:
                        continue
                    if _is_protected_by_macos(child):
                        self._note_protected(child)
                        continue
                    if child.is_dir():
                        self._scan_subdir(child, category)
                except OSError:
                    pass
        try:
            top = list(root.iterdir())
        except OSError:
            top = []
        for child in top:
            if self._abort:
                return
            try:
                if child.name == "Xcode" or child.is_symlink():
                    continue
                if child.resolve() in seen:
                    continue
                if _is_protected_by_macos(child):
                    self._note_protected(child)
                    continue
                if child.is_dir():
                    self._scan_subdir(child, category)
            except OSError:
                pass

    def _scan_subdir(self, path: Path, category: str, max_depth: int = None):
        if _is_protected_by_macos(path):
            self._note_protected(path)
            return
        self.progress.emit(
            f"{self._items_found} items ({format_size(self._bytes_found)}) "
            f"— sizing {path.name}…"
        )
        size = self._get_dir_size(path, max_depth=max_depth)
        self._emit_item(path, size, category, path.name)

    def _emit_item(self, path: Path, size: int, category: str, folder_name: str):
        if _is_protected_by_macos(path):
            self._note_protected(path)
            return
        if size < self._min_size:
            return
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            mtime = datetime.fromtimestamp(0)
        self._items_found += 1
        self._bytes_found += size
        self.progress.emit(
            f"{self._items_found} items ({format_size(self._bytes_found)}) found"
        )
        self.item_found.emit({
            "path": str(path),
            "size_bytes": size,
            "category": category,
            "app_name": bundle_id_to_app_name(folder_name),
            "last_modified": mtime,
        })

    def _scan_snapshots(self):
        report = volume_report()
        self.volume_report = report
        for snap in report["snapshots"]:
            self.item_found.emit({
                "path": snap["name"],
                "size_bytes": snap["size_bytes"],
                "category": "Snapshot",
                "app_name": "Time Machine",
                "last_modified": datetime.now(),
            })


# ---------------------------------------------------------------------------
# Table Model
# ---------------------------------------------------------------------------

COLUMNS = ["App Name", "Category", "Size", "Last Modified", "Path"]
COL_APP = 0
COL_CAT = 1
COL_SIZE = 2
COL_MTIME = 3
COL_PATH = 4


class ScanTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._items: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == COL_APP:
                name = item["app_name"]
                if item.get("grew_bytes"):
                    name = f"↑ {name}"
                return name
            if col == COL_CAT:   return item["category"]
            if col == COL_SIZE:  return format_size(item["size_bytes"])
            if col == COL_MTIME: return item["last_modified"].strftime("%Y-%m-%d %H:%M")
            if col == COL_PATH:
                folders = item.get("folders") or []
                if len(folders) > 1:
                    return f"{len(folders)} folders"
                return item["path"]
        if role == Qt.ToolTipRole and col == COL_APP and item.get("grew_bytes"):
            return f"Grew {format_size(item['grew_bytes'])} since the last scan"

        if role == Qt.BackgroundRole:
            cat = item["category"]
            hex_col = CATEGORY_COLORS.get(cat, "#555555")
            color = QColor(hex_col)
            color.setAlphaF(0.25)
            return QBrush(color)

        if role == Qt.ForegroundRole:
            return QBrush(QColor("#E8E8E8"))

        if role == Qt.UserRole:
            # raw sortable values
            if col == COL_SIZE:  return item["size_bytes"]
            if col == COL_MTIME: return item["last_modified"].timestamp()
            return self.data(index, Qt.DisplayRole)

        return None

    def add_item(self, item: dict):
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def all_items(self):
        return list(self._items)


class NumericSortProxyModel(QSortFilterProxyModel):
    def lessThan(self, left, right):
        lv = self.sourceModel().data(left, Qt.UserRole)
        rv = self.sourceModel().data(right, Qt.UserRole)
        try:
            return lv < rv
        except TypeError:
            return str(lv) < str(rv)


# ---------------------------------------------------------------------------
# Chart Widget
# ---------------------------------------------------------------------------

class ChartsWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._fig = Figure(facecolor="#1E1E1E")
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setStyleSheet("background-color: #1E1E1E;")
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._canvas)

        self._ax_bar = self._fig.add_subplot(211)
        self._ax_pie = self._fig.add_subplot(212)
        self._style_axes(self._ax_bar)
        self._style_axes(self._ax_pie)
        self._fig.tight_layout(pad=2.5)

    def _style_axes(self, ax):
        ax.set_facecolor("#2A2A2A")
        ax.tick_params(colors="#BBBBBB", labelsize=7)
        ax.xaxis.label.set_color("#BBBBBB")
        ax.yaxis.label.set_color("#BBBBBB")
        ax.title.set_color("#E8E8E8")
        for spine in ax.spines.values():
            spine.set_edgecolor("#444444")

    def update_charts(self, items: list[dict]):
        self._ax_bar.clear()
        self._ax_pie.clear()
        self._style_axes(self._ax_bar)
        self._style_axes(self._ax_pie)

        if not items:
            self._ax_bar.set_title("Top 15 Apps by Size", fontsize=9, pad=6)
            self._ax_pie.set_title("By Category", fontsize=9, pad=6)
            self._fig.tight_layout(pad=2.5)
            self._canvas.draw()
            return

        # --- Bar chart: top 15 apps by total size ---
        app_sizes: dict[str, int] = {}
        for item in items:
            app_sizes[item["app_name"]] = app_sizes.get(item["app_name"], 0) + item["size_bytes"]

        sorted_apps = sorted(app_sizes.items(), key=lambda x: x[1], reverse=True)[:15]
        app_names = [a[0] for a in sorted_apps]
        app_vals = [a[1] / (1024 ** 3) for a in sorted_apps]  # GB
        bar_colors = ["#4A90D9"] * len(app_names)

        self._ax_bar.barh(app_names[::-1], app_vals[::-1], color=bar_colors[::-1])
        self._ax_bar.set_xlabel("Size (GB)", color="#BBBBBB", fontsize=8)
        self._ax_bar.set_title("Top 15 Apps by Size", color="#E8E8E8", fontsize=9, pad=6)
        self._style_axes(self._ax_bar)

        # --- Pie chart: by category ---
        cat_sizes: dict[str, int] = {}
        for item in items:
            cat_sizes[item["category"]] = cat_sizes.get(item["category"], 0) + item["size_bytes"]

        labels = list(cat_sizes.keys())
        sizes = list(cat_sizes.values())
        colors = [CATEGORY_COLORS.get(l, "#888888") for l in labels]

        wedges, texts, autotexts = self._ax_pie.pie(
            sizes, labels=labels, colors=colors,
            autopct="%1.1f%%", startangle=140,
            textprops={"color": "#E8E8E8", "fontsize": 7},
            wedgeprops={"linewidth": 0.5, "edgecolor": "#1E1E1E"},
        )
        for at in autotexts:
            at.set_fontsize(6)
        self._ax_pie.set_title("By Category", fontsize=9, pad=6)
        self._style_axes(self._ax_pie)

        self._fig.tight_layout(pad=2.5)
        self._canvas.draw()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _age_analysis(last_modified: "datetime", risk: str) -> tuple:
    """Return (headline, detail, color) based on days since last modification."""
    days = (datetime.now() - last_modified).days
    years = days / 365
    months = days / 30

    if days < 14:
        return (
            f"Modified {days} day(s) ago — actively in use",
            "This data is recent. Only delete if you are uninstalling the app entirely.",
            "#E74C3C",
        )
    if days < 90:
        return (
            f"Modified ~{round(months)} month(s) ago — used recently",
            "Reasonably recent. Inspect contents before deciding.",
            "#E67E22",
        )
    if days < 365:
        return (
            f"Modified {round(months)} months ago — not used recently",
            "Not touched in a while. Likely safe if the app is also removed.",
            "#F39C12",
        )
    if days < 730:
        return (
            f"Modified over a year ago ({round(years, 1)} yrs) — probably stale",
            "Low risk. If the app is uninstalled this data serves no purpose.",
            "#A8C939",
        )
    return (
        f"Modified {round(years, 1)} years ago — almost certainly stale",
        "Very safe to delete. This data has not been touched in years.",
        "#27AE60",
    )


def _iter_app_bundles():
    """User-installable .app bundles in /Applications and ~/Applications.

    Walks one folder deeper so apps in Utilities and vendor folders are found.
    System apps under /System are skipped so they cannot be uninstalled here.
    """
    roots = [Path("/Applications"), Path.home() / "Applications"]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.suffix == ".app" and entry.is_dir():
                    found.append(entry)
                elif entry.is_dir() and not entry.name.startswith("."):
                    for child in entry.iterdir():
                        if child.suffix == ".app" and child.is_dir():
                            found.append(child)
            except OSError:
                continue
    return found


def _app_match_score(app_name: str, bundle: Path) -> int:
    """Higher is a closer name match. 0 means do not treat it as this app."""
    wanted = app_name.lower().strip()
    stem = bundle.stem.lower().strip()
    if not wanted or not stem:
        return 0
    if stem == wanted:
        return 100
    compact_wanted = wanted.replace(" ", "")
    compact_stem = stem.replace(" ", "")
    if compact_stem == compact_wanted:
        return 90
    if len(wanted) >= 4 and (stem.startswith(wanted) or wanted.startswith(stem)):
        return 70
    if len(wanted) >= 5:
        idx = stem.find(wanted)
        if idx == 0 or (idx > 0 and not stem[idx - 1].isalnum()):
            return 40
    return 0


def _find_installed_apps(app_name: str) -> list:
    """Installed .app paths that belong to this name, best match first.

    A loose substring hit is returned only when it is the single candidate,
    so uninstall never guesses between two different apps.
    """
    scored = []
    for bundle in _iter_app_bundles():
        score = _app_match_score(app_name, bundle)
        if score:
            scored.append((score, str(bundle)))
    scored.sort(key=lambda pair: (-pair[0], pair[1].lower()))
    strong = [path for score, path in scored if score >= 70]
    if strong:
        return strong
    weak = [path for score, path in scored if score > 0]
    if len(weak) == 1:
        return weak
    return []


def _is_app_installed(app_name: str) -> tuple:
    """
    Returns (installed: bool, app_path: str | None).
    Checks /Applications and ~/Applications for a matching .app bundle.
    """
    matches = _find_installed_apps(app_name)
    if matches:
        return True, matches[0]
    return False, None


def _is_protected_by_macos(path: Path) -> bool:
    """True when macOS has marked the path required, restricted, or immutable."""
    try:
        return bool(path.lstat().st_flags & MACOS_PROTECT_FLAGS)
    except OSError:
        return False


def _parse_bytes(text: str) -> int:
    match = re.search(r"\((\d+)\s+Bytes\)", text)
    return int(match.group(1)) if match else 0


def volume_report() -> dict:
    """Purgeable space and local APFS snapshots, with sizes when macOS reports them."""
    purgeable = 0
    try:
        info = subprocess.run(
            ["diskutil", "info", str(DATA_VOLUME)],
            capture_output=True, text=True, timeout=15,
        )
        for line in info.stdout.splitlines():
            if "purgeable" in line.lower():
                purgeable = max(purgeable, _parse_bytes(line))
    except Exception:
        pass

    snapshots = []
    seen = set()
    for target in (str(DATA_VOLUME), "/"):
        try:
            result = subprocess.run(
                ["diskutil", "apfs", "listSnapshots", target, "-plist"],
                capture_output=True, timeout=15,
            )
            if result.returncode != 0 or not result.stdout:
                continue
            payload = plistlib.loads(result.stdout)
        except Exception:
            continue
        for snap in payload.get("Snapshots") or []:
            name = snap.get("SnapshotName") or snap.get("Name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            size = 0
            for key, value in snap.items():
                if isinstance(value, int) and "size" in key.lower():
                    size = max(size, value)
            snapshots.append({"name": name, "size_bytes": size})

    if not snapshots:
        try:
            listed = subprocess.run(
                ["tmutil", "listlocalsnapshots", "/"],
                capture_output=True, text=True, timeout=10,
            )
            for line in listed.stdout.splitlines():
                name = line.strip()
                if name and name not in seen:
                    seen.add(name)
                    snapshots.append({"name": name, "size_bytes": 0})
        except Exception:
            pass
    return {"purgeable_bytes": purgeable, "snapshots": snapshots}


def system_data_line(scanned_bytes: int, report: dict) -> str:
    """'Found X of about Y' when macOS reports purgeable space or snapshot sizes."""
    snaps = report.get("snapshots") or []
    purgeable = report.get("purgeable_bytes") or 0
    snap_bytes = sum(s.get("size_bytes") or 0 for s in snaps)
    extra = purgeable if purgeable else snap_bytes
    if extra:
        line = (
            f"Found {format_size(scanned_bytes)} of about {format_size(scanned_bytes + extra)} "
            f"in System Data ({format_size(extra)} purgeable or in local snapshots)."
        )
    else:
        line = f"Found {format_size(scanned_bytes)} in this scan."
    if snaps and not snap_bytes:
        line += f" {len(snaps)} local snapshot(s); macOS did not report their size."
    return line


def _finder_delete(paths: list[str]) -> tuple[bool, str]:
    """Move paths to the Trash via Finder. Returns (ok, error detail)."""
    if not paths:
        return True, ""
    for start in range(0, len(paths), 40):
        chunk = paths[start:start + 40]
        files = ", ".join(
            'POSIX file "' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'
            for p in chunk
        )
        script = f'tell application "Finder" to delete {{{files}}}'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
        except Exception as exc:
            return False, str(exc)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Finder could not move the item to the Trash.").strip()
            return False, detail
    return True, ""


def _move_to_trash_mac(path: str) -> tuple[bool, str]:
    """Move a path to the Trash. Protected items are refused and left untouched."""
    p = Path(path)
    if _is_protected_by_macos(p):
        return False, (
            f"“{p.name}” can’t be deleted because it is required by macOS."
        )
    if not p.exists():
        return False, "That item is no longer there."
    return _finder_delete([path])


def _reveal_path(path: str):
    """Show a file or folder in Finder."""
    try:
        subprocess.run(["open", "-R", path], check=False)
    except Exception as exc:
        QMessageBox.warning(None, "Error", f"Could not open Finder:\n{exc}")


def _confirm_remove_app(parent, app_name: str, app_path: str) -> bool:
    reply = QMessageBox.question(
        parent, "Remove App",
        f"Move {app_name} to the Trash?\n\n{app_path}\n\n"
        "The app can be restored from the Trash until you empty it. "
        "Leftover caches and support files stay on disk until you remove those separately.",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
    )
    return reply == QMessageBox.Yes


# ---------------------------------------------------------------------------
# Cleanup Advice Dialog
# ---------------------------------------------------------------------------

class CleanupAdviceDialog(QDialog):
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Cleanup Advisor — {item['app_name']}")
        self.setMinimumWidth(600)
        self.setMinimumHeight(560)
        self.setModal(True)
        self._item = item
        self.deleted = False
        self.deleted_paths: list[str] = []
        self._build_ui()
        self._apply_style()

    def _get_advice(self) -> dict:
        app_key = self._item["app_name"].lower()
        folders = self._item.get("folders") or [self._item]
        cat = folders[0].get("category", self._item["category"])
        return CLEANUP_ADVICE.get(app_key) or CATEGORY_ADVICE.get(cat, {
            "risk": "caution",
            "what": "No specific advice available for this item.",
            "steps": ["Use 'Reveal in Finder' to inspect the contents before deciding."],
        })

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 14)

        advice = self._get_advice()
        risk = advice.get("risk", "caution")
        risk_color = RISK_COLORS[risk]

        # Header
        hdr = QFrame()
        hdr.setStyleSheet("background-color: #252525; border-radius: 6px;")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(12, 10, 12, 10)
        hdr_layout.setSpacing(3)

        name_lbl = QLabel(self._item["app_name"])
        name_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #E8E8E8;")
        hdr_layout.addWidget(name_lbl)

        cat_color = CATEGORY_COLORS.get(self._item["category"], "#888888")
        meta_lbl = QLabel(
            f"<span style='color:{cat_color}'>{self._item['category']}</span>"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;<b>{format_size(self._item['size_bytes'])}</b>"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;Last modified "
            f"{self._item['last_modified'].strftime('%Y-%m-%d')}"
        )
        meta_lbl.setStyleSheet("font-size: 11px; color: #AAAAAA;")
        meta_lbl.setTextFormat(Qt.RichText)
        hdr_layout.addWidget(meta_lbl)
        layout.addWidget(hdr)

        # Risk badge
        risk_lbl = QLabel(RISK_LABELS[risk])
        risk_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {risk_color}; "
            f"border: 1px solid {risk_color}; border-radius: 4px; padding: 4px 10px;"
        )
        layout.addWidget(risk_lbl)

        # Age analysis
        age_head, age_detail, age_color = _age_analysis(
            self._item["last_modified"], risk
        )
        age_frame = QFrame()
        age_frame.setStyleSheet(
            f"background-color: #1A1A1A; border-left: 3px solid {age_color}; "
            f"border-radius: 0px 4px 4px 0px;"
        )
        age_layout = QVBoxLayout(age_frame)
        age_layout.setContentsMargins(10, 6, 8, 6)
        age_layout.setSpacing(2)
        age_head_lbl = QLabel(f"⏰  {age_head}")
        age_head_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {age_color};"
        )
        age_detail_lbl = QLabel(age_detail)
        age_detail_lbl.setStyleSheet("font-size: 10px; color: #888888;")
        age_detail_lbl.setWordWrap(True)
        age_layout.addWidget(age_head_lbl)
        age_layout.addWidget(age_detail_lbl)
        layout.addWidget(age_frame)

        # App installed check
        installed, app_path = _is_app_installed(self._item["app_name"])
        inst_frame = QFrame()
        if installed:
            inst_color = "#F39C12"
            inst_icon = "⚠"
            inst_text = f"App is installed: {Path(app_path).name}"
            inst_sub = "Deleting this folder resets the app to factory defaults."
        else:
            inst_color = "#27AE60"
            inst_icon = "✓"
            inst_text = f"{self._item['app_name']} is NOT installed"
            inst_sub = "The parent app is gone — this is leftover data, safe to delete."
        inst_frame.setStyleSheet(
            f"background-color: #1A1A1A; border-left: 3px solid {inst_color}; "
            f"border-radius: 0px 4px 4px 0px;"
        )
        inst_layout = QVBoxLayout(inst_frame)
        inst_layout.setContentsMargins(10, 6, 8, 6)
        inst_layout.setSpacing(2)
        inst_head = QLabel(f"{inst_icon}  {inst_text}")
        inst_head.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {inst_color};"
        )
        inst_sub_lbl = QLabel(inst_sub)
        inst_sub_lbl.setStyleSheet("font-size: 10px; color: #888888;")
        inst_sub_lbl.setWordWrap(True)
        inst_layout.addWidget(inst_head)
        inst_layout.addWidget(inst_sub_lbl)
        if installed and app_path:
            app_btns = QHBoxLayout()
            app_btns.setContentsMargins(0, 4, 0, 0)
            find_app_btn = QPushButton("📂  Find App")
            find_app_btn.clicked.connect(lambda: _reveal_path(app_path))
            remove_app_btn = QPushButton("🗑  Remove App")
            remove_app_btn.setStyleSheet(
                "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; "
                "color: #FF7070; font-weight: bold; }"
                "QPushButton:hover { background-color: #7A2222; }"
            )
            remove_app_btn.clicked.connect(lambda: self._on_remove_app(app_path))
            app_btns.addWidget(find_app_btn)
            app_btns.addWidget(remove_app_btn)
            app_btns.addStretch()
            inst_layout.addLayout(app_btns)
        layout.addWidget(inst_frame)

        # What is this
        layout.addWidget(self._section("What is this?"))
        what_lbl = QLabel(advice.get("what", ""))
        what_lbl.setWordWrap(True)
        what_lbl.setStyleSheet("font-size: 11px; color: #CCCCCC; padding: 2px 0;")
        layout.addWidget(what_lbl)

        # How to clean
        layout.addWidget(self._section("How to clean:"))
        for i, step in enumerate(advice.get("steps", []), 1):
            step_lbl = QLabel(f"{i}.  {step}")
            step_lbl.setWordWrap(True)
            step_lbl.setStyleSheet(
                "font-size: 11px; color: #E0E0E0; background: #1E1E1E; "
                "border-radius: 4px; padding: 5px 8px;"
            )
            step_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(step_lbl)

        # Path
        layout.addWidget(self._section("Folders:"))
        folder_lines = "\n".join(
            f"{format_size(f['size_bytes'])}  {f['category']}  {f['path']}"
            for f in (self._item.get("folders") or [self._item])
        )
        path_lbl = QLabel(folder_lines)
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet(
            "font-size: 10px; color: #777777; font-family: monospace; "
            "background: #1A1A1A; border-radius: 4px; padding: 4px 8px;"
        )
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_lbl)

        layout.addStretch()

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        trash_btn = QPushButton("🗑  Move to Trash")
        trash_btn.setStyleSheet(
            "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; "
            "border-radius: 4px; padding: 6px 14px; color: #FF7070; font-weight: bold; }"
            "QPushButton:hover { background-color: #7A2222; }"
        )
        trash_btn.clicked.connect(self._on_trash)

        finder_btn = QPushButton("📂  Reveal in Finder")
        finder_btn.clicked.connect(self._on_reveal)

        web_btn = QPushButton("🔍  Search Web")
        web_btn.setToolTip(
            f"Search the web for info on deleting {self._item['app_name']} data"
        )
        web_btn.clicked.connect(self._on_search_web)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(trash_btn)
        btn_row.addWidget(finder_btn)
        btn_row.addWidget(web_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #888888; margin-top: 4px;"
        )
        return lbl

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #2E2E2E; }
            QPushButton {
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 14px;
                color: #E8E8E8;
            }
            QPushButton:hover { background-color: #4A4A4A; }
        """)

    def _on_trash(self):
        folders = self._item.get("folders") or [self._item]
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Move to Trash?\n\n{self._item['app_name']}\n({format_size(self._item['size_bytes'])})",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.deleted_paths = []
        failed = []
        for folder in folders:
            ok, detail = _move_to_trash_mac(folder["path"])
            if ok:
                self.deleted_paths.append(folder["path"])
            else:
                failed.append(detail or folder["path"])
        if self.deleted_paths:
            self.deleted = True
        if failed:
            QMessageBox.critical(self, "Error", "\n".join(failed))
        if self.deleted:
            self.accept()

    def _on_remove_app(self, app_path: str):
        if not _confirm_remove_app(self, self._item["app_name"], app_path):
            return
        ok, detail = _move_to_trash_mac(app_path)
        if ok:
            QMessageBox.information(
                self, "App Moved to Trash",
                detail or f"{Path(app_path).name} is in the Trash.\n\n"
                "Its leftover data is still on disk until you remove that too.",
            )
        else:
            QMessageBox.critical(self, "Error", detail or "Could not move the app to Trash.")

    def _on_reveal(self):
        try:
            subprocess.run(["open", "-R", self._item["path"]], check=False)
        except Exception:
            pass

    def _on_search_web(self):
        app = self._item["app_name"]
        cat = self._item["category"]
        folder = Path(self._item["path"]).name
        query = urllib.parse.quote(
            f'mac {app} {cat} folder safe to delete'
        )
        url = f"https://www.google.com/search?q={query}"
        try:
            subprocess.run(["open", url], check=False)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Quick Wins Dialog
# ---------------------------------------------------------------------------

class QuickWinsDialog(QDialog):
    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯  Quick Wins — Free Up Space Safely")
        self.setMinimumWidth(680)
        self.setMinimumHeight(580)
        self.setModal(True)
        self._all_items = items
        self._checkboxes: list[tuple] = []
        self.deleted_paths: list[str] = []
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 14)

        total = sum(i["size_bytes"] for i in self._all_items)

        title = QLabel("🎯  Recommended Quick Wins")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #E8E8E8;")
        layout.addWidget(title)

        subtitle = QLabel(
            f"These <b>{len(self._all_items)}</b> items are safe to delete — "
            f"apps rebuild them automatically. Total potential savings: "
            f"<b><span style='color:#27AE60'>{format_size(total)}</span></b>"
        )
        subtitle.setTextFormat(Qt.RichText)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 11px; color: #AAAAAA; margin-bottom: 2px;")
        layout.addWidget(subtitle)

        self._savings_lbl = QLabel()
        self._savings_lbl.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #27AE60; "
            "border: 1px solid #27AE60; border-radius: 4px; padding: 4px 10px;"
        )
        layout.addWidget(self._savings_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #2E2E2E; }")

        inner = QWidget()
        inner.setStyleSheet("background-color: #2E2E2E;")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(4)
        inner_layout.setContentsMargins(0, 0, 4, 0)

        for item in self._all_items:
            row_widget, cb = self._make_row(item)
            self._checkboxes.append((cb, item))
            cb.stateChanged.connect(self._update_savings)
            inner_layout.addWidget(row_widget)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        sel_row = QHBoxLayout()
        sel_all = QPushButton("Select All")
        sel_all.setFixedWidth(100)
        sel_all.clicked.connect(lambda: self._set_all(True))
        sel_none = QPushButton("Deselect All")
        sel_none.setFixedWidth(100)
        sel_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        self._delete_btn = QPushButton("🗑  Move Selected to Trash")
        self._delete_btn.setStyleSheet(
            "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; "
            "border-radius: 4px; padding: 8px 14px; color: #FF7070; "
            "font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: #7A2222; }"
            "QPushButton:disabled { background-color: #2A2A2A; color: #555555; border-color: #444444; }"
        )
        self._delete_btn.clicked.connect(self._delete_selected)
        layout.addWidget(self._delete_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._update_savings()

    def _make_row(self, item: dict) -> tuple:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: #1E1E1E; border-radius: 5px; border: none; }"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        cb = QCheckBox()
        cb.setChecked(True)
        row.addWidget(cb)

        name_lbl = QLabel(item["app_name"])
        name_lbl.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #E8E8E8; min-width: 110px; max-width: 110px;"
        )
        row.addWidget(name_lbl)

        cat_color = CATEGORY_COLORS.get(item["category"], "#888888")
        cat_lbl = QLabel(item["category"])
        cat_lbl.setAlignment(Qt.AlignCenter)
        cat_lbl.setFixedWidth(80)
        cat_lbl.setStyleSheet(
            f"font-size: 10px; color: {cat_color}; border: 1px solid {cat_color}; "
            f"border-radius: 3px; padding: 1px 4px;"
        )
        row.addWidget(cat_lbl)

        size_lbl = QLabel(format_size(item["size_bytes"]))
        size_lbl.setFixedWidth(72)
        size_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        size_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #27AE60;")
        row.addWidget(size_lbl)

        advice = (
            CLEANUP_ADVICE.get(item["app_name"].lower())
            or CATEGORY_ADVICE.get(item["category"], {})
        )
        what = advice.get("what", "")
        first_sentence = (what.split(".")[0] + ".") if what else ""
        desc_lbl = QLabel(first_sentence)
        desc_lbl.setWordWrap(False)
        desc_lbl.setStyleSheet("font-size: 10px; color: #666666;")
        desc_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(desc_lbl, 1)

        return frame, cb

    def _update_savings(self):
        total = sum(item["size_bytes"] for cb, item in self._checkboxes if cb.isChecked())
        count = sum(1 for cb, _ in self._checkboxes if cb.isChecked())
        self._savings_lbl.setText(
            f"Selected: {count} items  —  estimated savings: {format_size(total)}"
        )
        self._delete_btn.setEnabled(count > 0)

    def _set_all(self, checked: bool):
        for cb, _ in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(checked)

    def _delete_selected(self):
        to_delete = [(cb, item) for cb, item in self._checkboxes
                     if cb.isChecked() and cb.isEnabled()]
        if not to_delete:
            return
        total_size = sum(item["size_bytes"] for _, item in to_delete)
        reply = QMessageBox.question(
            self, "Confirm",
            f"Move {len(to_delete)} items ({format_size(total_size)}) to Trash?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        failed = []
        failed_names = set()
        notes = []
        for cb, item in to_delete:
            ok, detail = _move_to_trash_mac(item["path"])
            if ok:
                self.deleted_paths.append(item["path"])
                cb.setEnabled(False)
                cb.setChecked(False)
                if detail:
                    notes.append(detail)
            else:
                failed_names.add(item["app_name"])
                failed.append(f"{item['app_name']}: {detail}" if detail else item["app_name"])

        self._update_savings()
        freed = total_size - sum(
            item["size_bytes"] for _, item in to_delete
            if item["app_name"] in failed_names
        )

        if failed:
            QMessageBox.warning(
                self, "Some Items Failed",
                "Could not move to Trash:\n• " + "\n• ".join(failed),
            )
        else:
            if notes:
                QMessageBox.information(self, "Moved to Trash", "\n\n".join(notes))
            QMessageBox.information(
                self, "Done",
                f"Moved {len(to_delete) - len(failed)} items to Trash.\n"
                f"Approx. {format_size(freed)} freed.",
            )

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog  { background-color: #2E2E2E; }
            QPushButton {
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 5px 12px;
                color: #E8E8E8;
            }
            QPushButton:hover { background-color: #4A4A4A; }
            QCheckBox { color: #E8E8E8; }
            QLabel    { background: transparent; }
        """)


# ---------------------------------------------------------------------------
# System Data Analyzer Dialog
# ---------------------------------------------------------------------------

class SystemDataDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔍  System Data Analyzer")
        self.setMinimumWidth(660)
        self.setMinimumHeight(580)
        self.setModal(True)
        self._runtime_checkboxes: list[tuple] = []
        self._build_ui()
        self._apply_style()

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_runtimes() -> tuple:
        """Returns (list of runtime dicts, total_size_str)."""
        try:
            r = subprocess.run(
                ["xcrun", "simctl", "runtime", "list"],
                capture_output=True, text=True, timeout=15,
            )
            runtimes, total_str = [], "unknown"
            pattern = re.compile(
                r"^(.+?)\s+\(([^)]+)\)\s+-\s+([A-F0-9\-]{36})\s+\(([^)]+)\)"
            )
            for line in r.stdout.splitlines():
                m = pattern.match(line.strip())
                if m:
                    runtimes.append({
                        "name":   m.group(1).strip(),
                        "build":  m.group(2),
                        "uuid":   m.group(3),
                        "status": m.group(4),
                    })
                elif "Total Disk Images:" in line:
                    total_str = line.split(":", 1)[1].strip()
            return runtimes, total_str
        except FileNotFoundError:
            return [], "Xcode not installed"
        except Exception:
            return [], "unavailable"

    @staticmethod
    def _fetch_snapshots() -> list:
        try:
            r = subprocess.run(
                ["tmutil", "listlocalsnapshots", "/"],
                capture_output=True, text=True, timeout=10,
            )
            return [l.strip() for l in r.stdout.splitlines()
                    if l.strip().startswith("com.apple")]
        except Exception:
            return []

    @staticmethod
    def _fetch_vm_files() -> list:
        files = []
        try:
            for f in Path("/private/var/vm").iterdir():
                try:
                    files.append({"name": f.name, "size": f.stat().st_size})
                except OSError:
                    pass
        except OSError:
            pass
        return sorted(files, key=lambda x: x["size"], reverse=True)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 14)

        title = QLabel("🔍  System Data Analyzer")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #E8E8E8;")
        layout.addWidget(title)

        sub = QLabel(
            "These items live <b>outside</b> your user Library and are counted by macOS as "
            "\"System Data\" — invisible to the main scan."
        )
        sub.setTextFormat(Qt.RichText)
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 11px; color: #888888; margin-bottom: 2px;")
        layout.addWidget(sub)

        # ── Simulator Runtimes ──────────────────────────────────────
        runtimes, total_str = self._fetch_runtimes()
        rt_group = QGroupBox(f"iOS / macOS Simulator Runtimes  —  {total_str}")
        rt_layout = QVBoxLayout(rt_group)
        rt_layout.setSpacing(4)

        if runtimes:
            for rt in runtimes:
                cb = QCheckBox(
                    f"{rt['name']}  ({rt['build']})  "
                    f"[{rt['status']}]"
                )
                cb.setChecked(False)
                cb.setStyleSheet("font-size: 11px; color: #E0E0E0;")
                rt_layout.addWidget(cb)
                self._runtime_checkboxes.append((cb, rt))

            btn_row = QHBoxLayout()
            sel_all = QPushButton("Select All")
            sel_all.setFixedWidth(88)
            sel_all.clicked.connect(
                lambda: [cb.setChecked(True)
                         for cb, _ in self._runtime_checkboxes if cb.isEnabled()]
            )
            sel_none = QPushButton("Deselect All")
            sel_none.setFixedWidth(88)
            sel_none.clicked.connect(
                lambda: [cb.setChecked(False)
                         for cb, _ in self._runtime_checkboxes if cb.isEnabled()]
            )
            self._rt_btn = QPushButton("🗑  Delete Selected Runtimes")
            self._rt_btn.setStyleSheet(
                "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; "
                "border-radius: 4px; padding: 5px 12px; color: #FF7070; font-weight: bold; }"
                "QPushButton:hover { background-color: #7A2222; }"
                "QPushButton:disabled { background-color: #2A2A2A; color: #555; border-color: #444; }"
            )
            self._rt_btn.clicked.connect(self._delete_runtimes)
            btn_row.addWidget(sel_all)
            btn_row.addWidget(sel_none)
            btn_row.addStretch()
            btn_row.addWidget(self._rt_btn)
            rt_layout.addLayout(btn_row)

            hint = QLabel(
                "Runtimes can be re-downloaded: Xcode → Settings → Platforms"
            )
            hint.setStyleSheet("font-size: 10px; color: #555555; margin-top: 2px;")
            rt_layout.addWidget(hint)
        else:
            ok = QLabel("✓  No simulator runtimes installed.")
            ok.setStyleSheet("font-size: 11px; color: #27AE60;")
            rt_layout.addWidget(ok)

        layout.addWidget(rt_group)

        # ── Time Machine Snapshots ──────────────────────────────────
        snaps = self._fetch_snapshots()
        snap_group = QGroupBox(
            f"Time Machine Local Snapshots  —  {len(snaps)} found"
        )
        snap_layout = QVBoxLayout(snap_group)
        snap_layout.setSpacing(3)

        if snaps:
            for s in snaps:
                lbl = QLabel(f"  • {s}")
                lbl.setStyleSheet(
                    "font-size: 10px; color: #AAAAAA; font-family: monospace;"
                )
                snap_layout.addWidget(lbl)
            del_snap_btn = QPushButton(
                "🗑  Delete All Snapshots  (requires admin password)"
            )
            del_snap_btn.setStyleSheet(
                "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; "
                "border-radius: 4px; padding: 5px 12px; color: #FF7070; font-weight: bold; }"
                "QPushButton:hover { background-color: #7A2222; }"
            )
            del_snap_btn.clicked.connect(self._delete_snapshots)
            snap_layout.addWidget(del_snap_btn)
        else:
            ok = QLabel("✓  No local Time Machine snapshots found.")
            ok.setStyleSheet("font-size: 11px; color: #27AE60;")
            snap_layout.addWidget(ok)

        layout.addWidget(snap_group)

        # ── Virtual Memory ──────────────────────────────────────────
        vm_files = self._fetch_vm_files()
        total_vm = sum(f["size"] for f in vm_files)
        vm_group = QGroupBox(f"Virtual Memory  —  {format_size(total_vm)}")
        vm_layout = QVBoxLayout(vm_group)
        vm_layout.setSpacing(3)

        for f in vm_files:
            lbl = QLabel(f"  {f['name']}:  {format_size(f['size'])}")
            lbl.setStyleSheet("font-size: 11px; color: #AAAAAA;")
            vm_layout.addWidget(lbl)

        note = QLabel(
            "Managed automatically by macOS — do not delete manually.\n"
            "sleepimage size equals your installed RAM."
        )
        note.setStyleSheet("font-size: 10px; color: #555555;")
        vm_layout.addWidget(note)
        layout.addWidget(vm_group)

        layout.addStretch()

        disclaimer = QLabel(
            "<b>⏳  Cleaned something? Storage Settings may not update right away.</b><br><br>"
            "macOS tracks disk usage through a metadata cache managed by a background daemon "
            "(<i>storagekitd</i>) that refreshes on its own schedule — not instantly. "
            "Freed space is reclaimed on disk immediately, but the number shown under "
            "<i>Settings → General → Storage → System Data</i> can lag by minutes or hours.<br><br>"
            "<b>Why the delay?</b><br>"
            "• <b>APFS deferred reclamation</b> — freed blocks are not always returned to the "
            "pool until a checkpoint occurs.<br>"
            "• <b>Local Time Machine snapshots</b> — macOS temporarily retains deleted data "
            "in snapshots before they expire or are purged.<br>"
            "• <b>Storage accounting daemon</b> — <i>storagekitd</i> re-tallies usage "
            "periodically in the background, not on every delete.<br>"
            "• <b>Spotlight re-indexing</b> — deletions trigger a brief re-index which can "
            "cause the storage count to appear stale.<br><br>"
            "<b>To see updated numbers sooner:</b> restart your Mac, or open "
            "<i>Disk Utility → select your disk → First Aid</i>.<br><br>"
            "<i>If you are unsure whether something is safe to delete — don't. "
            "Use 'Search the Web' to research first, then make a deliberate decision.</i>"
        )
        disclaimer.setTextFormat(Qt.RichText)
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            "font-size: 10px; color: #AAAAAA; background-color: #1E1E1E; "
            "border: 1px solid #3A3A3A; border-radius: 5px; padding: 10px; "
            "margin-top: 4px;"
        )
        layout.addWidget(disclaimer)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _delete_runtimes(self):
        selected = [(cb, rt) for cb, rt in self._runtime_checkboxes
                    if cb.isChecked() and cb.isEnabled()]
        if not selected:
            QMessageBox.information(
                self, "None Selected", "Select at least one runtime to delete."
            )
            return
        names = "\n".join(
            f"  • {rt['name']} ({rt['build']})" for _, rt in selected
        )
        reply = QMessageBox.question(
            self, "Delete Runtimes",
            f"Delete {len(selected)} runtime(s)?\n\n{names}\n\n"
            "They can be re-downloaded via Xcode → Settings → Platforms.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._rt_btn.setEnabled(False)
        self._rt_btn.setText("Deleting…")
        QApplication.processEvents()

        for cb, rt in selected:
            try:
                subprocess.run(
                    ["xcrun", "simctl", "runtime", "delete", rt["uuid"]],
                    capture_output=True, timeout=90,
                )
                cb.setEnabled(False)
                cb.setText(cb.text() + "  ✓")
            except Exception:
                cb.setText(cb.text() + "  ✗ failed")
            QApplication.processEvents()

        self._rt_btn.setText("✓  Done")
        QMessageBox.information(
            self, "Done",
            "Deletion initiated. macOS may take a few minutes to reclaim space.\n"
            "Refresh System Settings → Storage to see the updated number.",
        )

    def _delete_snapshots(self):
        reply = QMessageBox.question(
            self, "Delete All Snapshots",
            "Delete all local Time Machine snapshots?\n\n"
            "You will be prompted for your admin password.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            r = subprocess.run(
                ["osascript", "-e",
                 'do shell script "tmutil deletelocalsnapshots /" '
                 "with administrator privileges"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                QMessageBox.information(
                    self, "Done", "Local snapshots deleted successfully."
                )
            else:
                QMessageBox.warning(
                    self, "Error", r.stderr or "Could not delete snapshots."
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #2E2E2E; }
            QGroupBox {
                color: #888888;
                border: 1px solid #444444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 5px 12px;
                color: #E8E8E8;
            }
            QPushButton:hover { background-color: #4A4A4A; }
            QCheckBox { color: #E8E8E8; }
            QLabel { background: transparent; }
        """)


# ---------------------------------------------------------------------------
# Repeat Offenders Dialog
# ---------------------------------------------------------------------------

_OFF_COLS = ["App", "Sightings", "Peak Size", "Last Size", "Trend", "Last Seen", "Categories"]
_OFF_APP, _OFF_SEEN, _OFF_PEAK, _OFF_LAST, _OFF_TREND, _OFF_DATE, _OFF_CATS = range(7)


class OffenderTableModel(QAbstractTableModel):
    def __init__(self, items: list):
        super().__init__()
        self._items = items

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(_OFF_COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _OFF_COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == _OFF_APP:
                return ("★ " if item["flagged"] else "") + item["app_name"]
            if col == _OFF_SEEN:
                return str(item["times_seen"])
            if col == _OFF_PEAK:
                return format_size(item["peak_size_bytes"])
            if col == _OFF_LAST:
                return format_size(item["last_size_bytes"])
            if col == _OFF_TREND:
                return item["trend"]
            if col == _OFF_DATE:
                try:
                    return datetime.fromisoformat(item["last_seen"]).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    return item["last_seen"]
            if col == _OFF_CATS:
                return item["categories"]

        if role == Qt.ForegroundRole:
            n = item["times_seen"]
            if item["flagged"] and n == 0:
                return QBrush(QColor("#BB88FF"))
            if n >= 5:
                return QBrush(QColor("#E74C3C"))
            if n >= 3:
                return QBrush(QColor("#F39C12"))
            if n >= 2:
                return QBrush(QColor("#E8C63A"))
            return QBrush(QColor("#CCCCCC"))

        if role == Qt.UserRole:
            if col == _OFF_SEEN:
                return item["times_seen"]
            if col == _OFF_PEAK:
                return item["peak_size_bytes"]
            if col == _OFF_LAST:
                return item["last_size_bytes"]
            if col == _OFF_DATE:
                return item["last_seen"]
            return self.data(index, Qt.DisplayRole)

        return None


def _locations_for_app(app_name: str, logged: list, scan_items: list) -> list:
    """Folders for an app, preferring the current scan over the saved log."""
    live = [
        {"path": item["path"], "category": item["category"], "size_bytes": item["size_bytes"]}
        for item in scan_items
        if item.get("app_name") == app_name
    ]
    source = live or list(logged or [])
    seen = set()
    locations = []
    for loc in sorted(source, key=lambda row: row.get("size_bytes", 0), reverse=True):
        path = loc.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        locations.append(loc)
    return locations


class OffenderManageDialog(QDialog):
    """Find or remove one offender's application and the folders it left behind."""

    def __init__(self, offender: dict, locations: list, parent=None):
        super().__init__(parent)
        self._offender = offender
        self._locations = locations
        self._apps = _find_installed_apps(offender["app_name"])
        self.deleted_paths: list[str] = []
        self.removed_app = False
        self.setWindowTitle(f"Find or Remove — {offender['app_name']}")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self.setModal(True)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 14)

        title = QLabel(self._offender["app_name"])
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #E8E8E8;")
        layout.addWidget(title)

        app_group = QGroupBox("The program")
        app_layout = QVBoxLayout(app_group)
        if self._apps:
            self._app_checks = []
            for path in self._apps:
                cb = QCheckBox(path)
                cb.setChecked(len(self._apps) == 1)
                cb.setStyleSheet("font-size: 11px; color: #E0E0E0;")
                app_layout.addWidget(cb)
                self._app_checks.append(cb)
            app_btns = QHBoxLayout()
            find_btn = QPushButton("📂  Find App")
            find_btn.clicked.connect(self._find_apps)
            remove_btn = QPushButton("🗑  Remove App")
            remove_btn.setStyleSheet(
                "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; color: #FF7070; }"
                "QPushButton:hover { background-color: #7A2222; }"
            )
            remove_btn.clicked.connect(self._remove_apps)
            app_btns.addWidget(find_btn)
            app_btns.addWidget(remove_btn)
            app_btns.addStretch()
            app_layout.addLayout(app_btns)
        else:
            missing = QLabel(
                "Not installed in /Applications or your personal Applications folder. "
                "What remains is leftover data."
            )
            missing.setWordWrap(True)
            missing.setStyleSheet("font-size: 11px; color: #AAAAAA;")
            app_layout.addWidget(missing)
            self._app_checks = []
        layout.addWidget(app_group)

        data_group = QGroupBox("Its data")
        data_layout = QVBoxLayout(data_group)
        self._data_checks = []
        if self._locations:
            for loc in self._locations:
                exists = Path(loc["path"]).exists()
                label = f"{format_size(loc.get('size_bytes', 0))}   {loc.get('category', '')}   {loc['path']}"
                cb = QCheckBox(label)
                cb.setChecked(exists)
                cb.setEnabled(exists)
                if not exists:
                    cb.setText(label + "   (already gone)")
                cb.setStyleSheet("font-size: 11px; color: #E0E0E0;")
                data_layout.addWidget(cb)
                self._data_checks.append((cb, loc))
            data_btns = QHBoxLayout()
            find_data = QPushButton("📂  Find Data")
            find_data.clicked.connect(self._find_data)
            remove_data = QPushButton("🗑  Remove Data")
            remove_data.setStyleSheet(
                "QPushButton { background-color: #5A1A1A; border: 1px solid #993333; color: #FF7070; }"
                "QPushButton:hover { background-color: #7A2222; }"
            )
            remove_data.clicked.connect(self._remove_data)
            data_btns.addWidget(find_data)
            data_btns.addWidget(remove_data)
            data_btns.addStretch()
            data_layout.addLayout(data_btns)
        else:
            empty = QLabel(
                "No folders recorded yet. Run a scan, then open this app again to locate its data."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet("font-size: 11px; color: #AAAAAA;")
            data_layout.addWidget(empty)
        layout.addWidget(data_group)

        layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _checked_apps(self) -> list:
        return [cb.text() for cb in self._app_checks if cb.isChecked() and cb.isEnabled()]

    def _checked_data(self) -> list:
        return [loc for cb, loc in self._data_checks if cb.isChecked() and cb.isEnabled()]

    def _find_apps(self):
        paths = self._checked_apps()
        if not paths:
            QMessageBox.information(self, "Nothing Selected", "Select an app to reveal in Finder.")
            return
        for path in paths:
            _reveal_path(path)

    def _remove_apps(self):
        paths = self._checked_apps()
        if not paths:
            QMessageBox.information(self, "Nothing Selected", "Select an app to remove.")
            return
        names = "\n".join(f"  • {p}" for p in paths)
        reply = QMessageBox.question(
            self, "Remove App",
            f"Move {len(paths)} app(s) to the Trash?\n\n{names}\n\n"
            "You can restore them until you empty the Trash. Leftover data stays until you remove it below.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        failed = []
        for cb in self._app_checks:
            if not cb.isChecked() or not cb.isEnabled():
                continue
            ok, detail = _move_to_trash_mac(cb.text())
            if ok:
                cb.setEnabled(False)
                cb.setChecked(False)
                cb.setText(cb.text() + "   (moved to Trash)")
                self.removed_app = True
            else:
                failed.append(detail or cb.text())
        if failed:
            QMessageBox.warning(self, "Some Apps Failed", "\n".join(failed))

    def _find_data(self):
        locs = self._checked_data()
        if not locs:
            QMessageBox.information(self, "Nothing Selected", "Select a folder to reveal in Finder.")
            return
        for loc in locs:
            _reveal_path(loc["path"])

    def _remove_data(self):
        locs = self._checked_data()
        if not locs:
            QMessageBox.information(self, "Nothing Selected", "Select folders to remove.")
            return
        total = sum(loc.get("size_bytes", 0) for loc in locs)
        names = "\n".join(f"  • {Path(loc['path']).name}" for loc in locs[:8])
        if len(locs) > 8:
            names += f"\n  … and {len(locs) - 8} more"
        reply = QMessageBox.question(
            self, "Remove Data",
            f"Move {len(locs)} folder(s) ({format_size(total)}) to the Trash?\n\n{names}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        failed = []
        for cb, loc in self._data_checks:
            if not cb.isChecked() or not cb.isEnabled():
                continue
            ok, detail = _move_to_trash_mac(loc["path"])
            if ok:
                self.deleted_paths.append(loc["path"])
                cb.setEnabled(False)
                cb.setChecked(False)
                cb.setText(cb.text() + "   (moved to Trash)")
            else:
                failed.append(f"{Path(loc['path']).name}: {detail}" if detail else Path(loc["path"]).name)
        if failed:
            QMessageBox.warning(self, "Some Folders Failed", "Could not move to Trash:\n• " + "\n• ".join(failed))

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #2E2E2E; }
            QGroupBox {
                color: #888888;
                border: 1px solid #444444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton {
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 14px;
                color: #E8E8E8;
            }
            QPushButton:hover { background-color: #4A4A4A; }
            QCheckBox { color: #E8E8E8; }
            QLabel { background: transparent; }
        """)


class RepeatOffendersDialog(QDialog):
    def __init__(self, offender_log: OffenderLog, scan_items=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🚨  Repeat Offenders Log")
        self.setMinimumWidth(820)
        self.setMinimumHeight(540)
        self.setModal(True)
        self._log = offender_log
        self._scan_items = list(scan_items or [])
        self.deleted_paths: list[str] = []
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 14)

        title = QLabel("🚨  Repeat Offenders Log")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #E8E8E8;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Apps spotted across multiple scans. Select one, then Find or Remove "
            "to open the program in Finder or move it — and its leftover data — to the Trash."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 11px; color: #AAAAAA; margin-bottom: 4px;")
        layout.addWidget(subtitle)

        self._table = QTableView()
        self._model = OffenderTableModel(self._log.get_offenders())
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(Qt.UserRole)
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.sortByColumn(_OFF_SEEN, Qt.DescendingOrder)
        self._table.doubleClicked.connect(lambda _idx: self._manage_selected())
        layout.addWidget(self._table)

        legend = QLabel(
            "<span style='color:#E8C63A'>●</span> 2 sightings &nbsp; "
            "<span style='color:#F39C12'>●</span> 3–4 sightings &nbsp; "
            "<span style='color:#E74C3C'>●</span> 5+ sightings &nbsp; "
            "<span style='color:#BB88FF'>★</span> Manually flagged"
        )
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("font-size: 10px; color: #777777; margin-top: 2px;")
        layout.addWidget(legend)

        btn_row = QHBoxLayout()

        manage_btn = QPushButton("Find or Remove…")
        manage_btn.setStyleSheet(
            "QPushButton { background-color: #1A2A3A; border: 1px solid #4A90D9; color: #4A90D9; font-weight: bold; }"
            "QPushButton:hover { background-color: #1E3A5A; }"
        )
        manage_btn.clicked.connect(self._manage_selected)
        btn_row.addWidget(manage_btn)

        clear_sel_btn = QPushButton("✕  Clear Selected")
        clear_sel_btn.clicked.connect(self._clear_selected)
        btn_row.addWidget(clear_sel_btn)

        clear_all_btn = QPushButton("🗑  Clear All Records")
        clear_all_btn.setStyleSheet(
            "QPushButton { background-color: #3A1A1A; border: 1px solid #883333; color: #FF7070; }"
            "QPushButton:hover { background-color: #5A2222; }"
        )
        clear_all_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_all_btn)

        btn_row.addStretch()

        log_btn = QPushButton("📂  Show Log File")
        log_btn.clicked.connect(self._reveal_log)
        btn_row.addWidget(log_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _refresh(self):
        self._model._items = self._log.get_offenders()
        self._model.layoutChanged.emit()

    def _selected_offenders(self) -> list:
        rows = sorted({
            self._proxy.mapToSource(idx).row()
            for idx in self._table.selectionModel().selectedRows()
        })
        return [self._model._items[r] for r in rows if 0 <= r < len(self._model._items)]

    def _manage_selected(self):
        selected = self._selected_offenders()
        if len(selected) != 1:
            QMessageBox.information(
                self, "Select One App",
                "Select a single app, then choose Find or Remove.",
            )
            return
        offender = selected[0]
        locations = _locations_for_app(
            offender["app_name"], offender.get("locations") or [], self._scan_items
        )
        dlg = OffenderManageDialog(offender, locations, parent=self)
        dlg.exec()
        if dlg.deleted_paths:
            self.deleted_paths.extend(dlg.deleted_paths)
            self._log.forget_locations(offender["app_name"], dlg.deleted_paths)
            self._scan_items = [
                item for item in self._scan_items
                if item.get("path") not in set(dlg.deleted_paths)
            ]
            self._refresh()

    def _clear_selected(self):
        rows = sorted(
            {self._proxy.mapToSource(idx).row()
             for idx in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        if not rows:
            QMessageBox.information(self, "Nothing Selected", "Select one or more rows first.")
            return
        names = [self._model._items[r]["app_name"] for r in rows]
        reply = QMessageBox.question(
            self, "Clear Records",
            f"Remove {len(names)} app(s) from the offenders log?\n\n" +
            "\n".join(f"  • {n}" for n in names),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            for name in names:
                self._log.clear_app(name)
            self._refresh()

    def _clear_all(self):
        reply = QMessageBox.question(
            self, "Clear All Records",
            "Erase the entire offenders history?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._log.clear_all()
            self._refresh()

    def _reveal_log(self):
        path = self._log.log_path
        if path.exists():
            try:
                subprocess.run(["open", "-R", str(path)], check=False)
            except Exception:
                QMessageBox.information(self, "Log File", str(path))
        else:
            QMessageBox.information(
                self, "Log File",
                f"No log file yet.\nIt will be created at:\n{path}\n\nRun a scan first."
            )

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #2E2E2E; }
            QPushButton {
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 14px;
                color: #E8E8E8;
            }
            QPushButton:hover { background-color: #4A4A4A; }
            QTableView {
                gridline-color: #3A3A3A;
                border: 1px solid #3A3A3A;
            }
            QHeaderView::section {
                background-color: #2A2A2A;
                color: #CCCCCC;
                border: 1px solid #3A3A3A;
                padding: 4px;
                font-size: 11px;
            }
        """)


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("System Data Inspector")
        self.resize(1400, 800)

        self._items: list[dict] = []
        self._worker: Optional[ScanWorker] = None
        self._offender_log = OffenderLog()

        self._build_ui()
        self._apply_dark_theme()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([260, 680, 460])

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # Scan controls
        scan_group = QGroupBox("Scan Controls")
        sg_layout = QVBoxLayout(scan_group)

        self._scan_btn = QPushButton("⟳  Scan")
        self._scan_btn.setMinimumHeight(36)
        self._scan_btn.clicked.connect(self._start_scan)
        sg_layout.addWidget(self._scan_btn)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        sg_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("Ready")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        sg_layout.addWidget(self._status_label)

        layout.addWidget(scan_group)

        # Filters
        filter_group = QGroupBox("Filters")
        fg_layout = QVBoxLayout(filter_group)

        self._cat_checkboxes: dict[str, QCheckBox] = {}
        for cat, color in CATEGORY_COLORS.items():
            advice = CATEGORY_ADVICE.get(cat, {})
            risk = advice.get("risk", "caution")
            risk_icon = {"safe": "✓", "caution": "⚠", "risky": "✗"}.get(risk, "⚠")
            risk_color = RISK_COLORS.get(risk, "#F39C12")

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            cb = QCheckBox(cat)
            cb.setChecked(True)
            tip = (
                f"<b>{cat}</b><br>"
                f"{advice.get('what', '')}<br><br>"
                f"<span style='color:{risk_color}'>{risk_icon} {RISK_LABELS.get(risk, '')}</span>"
            )
            cb.setToolTip(tip)
            cb.setStyleSheet(f"QCheckBox {{ color: {color}; }}")
            cb.stateChanged.connect(self._apply_filters)

            risk_dot = QLabel(risk_icon)
            risk_dot.setFixedWidth(14)
            risk_dot.setStyleSheet(
                f"color: {risk_color}; font-size: 9px; font-weight: bold;"
            )
            risk_dot.setToolTip(tip)

            row_layout.addWidget(cb)
            row_layout.addStretch()
            row_layout.addWidget(risk_dot)

            fg_layout.addWidget(row)
            self._cat_checkboxes[cat] = cb

        # Min size slider
        size_label = QLabel("Min Size: 0 MB")
        size_label.setStyleSheet("color: #AAAAAA; font-size: 11px;")
        fg_layout.addWidget(size_label)
        self._size_label = size_label

        self._size_slider = QSlider(Qt.Horizontal)
        self._size_slider.setRange(0, 500)
        self._size_slider.setValue(0)
        self._size_slider.setTickInterval(50)
        self._size_slider.valueChanged.connect(self._on_slider_changed)
        fg_layout.addWidget(self._size_slider)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search apps or paths")
        self._search.textChanged.connect(self._apply_filters)
        fg_layout.addWidget(self._search)

        self._hide_ignored = QCheckBox("Hide set-aside")
        self._hide_ignored.setChecked(True)
        self._hide_ignored.setToolTip("Apps you marked Leave this alone")
        self._hide_ignored.stateChanged.connect(self._apply_filters)
        fg_layout.addWidget(self._hide_ignored)

        layout.addWidget(filter_group)

        # Actions
        actions_group = QGroupBox("Actions")
        ag_layout = QVBoxLayout(actions_group)

        sysdata_btn = QPushButton("🔍  System Data")
        sysdata_btn.setToolTip(
            "Analyze what macOS counts as 'System Data':\n"
            "Simulator runtimes, APFS snapshots, swap files"
        )
        sysdata_btn.setStyleSheet(
            "QPushButton { background-color: #1A2A3A; border: 1px solid #4A90D9; "
            "border-radius: 4px; padding: 6px; color: #4A90D9; font-weight: bold; }"
            "QPushButton:hover { background-color: #1E3A5A; }"
        )
        sysdata_btn.clicked.connect(self._show_system_data)
        ag_layout.addWidget(sysdata_btn)

        wins_btn = QPushButton("🎯  Quick Wins")
        wins_btn.setToolTip(
            "Show safe, high-impact items you can delete right now with no risk"
        )
        wins_btn.setStyleSheet(
            "QPushButton { background-color: #1A3A1A; border: 1px solid #27AE60; "
            "border-radius: 4px; padding: 6px; color: #27AE60; font-weight: bold; }"
            "QPushButton:hover { background-color: #1E4A1E; }"
            "QPushButton:disabled { background-color: #1A1A1A; color: #444; border-color: #333; }"
        )
        wins_btn.setEnabled(False)
        wins_btn.clicked.connect(self._show_quick_wins)
        ag_layout.addWidget(wins_btn)
        self._wins_btn = wins_btn

        offenders_btn = QPushButton("🚨  Repeat Offenders")
        offenders_btn.setToolTip(
            "View apps spotted across multiple scans — data leakers, "
            "cache hoarders, and general troublemakers"
        )
        offenders_btn.setStyleSheet(
            "QPushButton { background-color: #2A1A3A; border: 1px solid #8B4AFF; "
            "border-radius: 4px; padding: 6px; color: #BB88FF; font-weight: bold; }"
            "QPushButton:hover { background-color: #3A2A5A; }"
        )
        offenders_btn.clicked.connect(self._show_repeat_offenders)
        ag_layout.addWidget(offenders_btn)
        self._offenders_btn = offenders_btn

        export_btn = QPushButton("⬇  Export CSV")
        export_btn.clicked.connect(self._export_csv)
        ag_layout.addWidget(export_btn)

        fda_row = QWidget()
        fda_row_layout = QHBoxLayout(fda_row)
        fda_row_layout.setContentsMargins(0, 0, 0, 0)
        fda_row_layout.setSpacing(4)

        fda_btn = QPushButton("🔒  Full Disk Access")
        fda_btn.clicked.connect(self._open_full_disk_access)
        fda_btn.setToolTip("Open System Settings > Privacy & Security > Full Disk Access")
        fda_row_layout.addWidget(fda_btn)

        fda_help_btn = QPushButton("?")
        fda_help_btn.setFixedWidth(28)
        fda_help_btn.setToolTip("How to grant Full Disk Access")
        fda_help_btn.clicked.connect(self._show_fda_help)
        fda_help_btn.setStyleSheet(
            "QPushButton { background-color: #2A2A5A; border: 1px solid #4A4AFF; "
            "border-radius: 4px; color: #8888FF; font-weight: bold; }"
            "QPushButton:hover { background-color: #3A3A7A; }"
        )
        fda_row_layout.addWidget(fda_help_btn)

        ag_layout.addWidget(fda_row)

        layout.addWidget(actions_group)
        layout.addStretch()

        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        header = QLabel("Scan Results")
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #E8E8E8; padding: 4px;")
        layout.addWidget(header)

        self._summary_label = QLabel("Run a scan to compare with System Data.")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("font-size: 11px; color: #AAAAAA; padding: 0 4px 4px 4px;")
        layout.addWidget(self._summary_label)

        self._model = ScanTableModel()
        self._proxy = NumericSortProxyModel()
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setSectionResizeMode(COL_PATH, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(COL_APP, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_CAT, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_SIZE, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(COL_MTIME, QHeaderView.ResizeToContents)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.sortByColumn(COL_SIZE, Qt.DescendingOrder)
        self._table.selectionModel().selectionChanged.connect(self._show_selected_folders)

        layout.addWidget(self._table)

        folders_label = QLabel("Folders in the selected app")
        folders_label.setStyleSheet("font-size: 11px; color: #888888; padding: 4px 0 0 0;")
        layout.addWidget(folders_label)
        self._folder_list = QListWidget()
        self._folder_list.setMaximumHeight(140)
        layout.addWidget(self._folder_list)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        header = QLabel("Visualizations")
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #E8E8E8; padding: 4px;")
        layout.addWidget(header)

        self._charts = ChartsWidget()
        layout.addWidget(self._charts)
        return panel

    # ------------------------------------------------------------------
    # Dark theme
    # ------------------------------------------------------------------

    def _apply_dark_theme(self):
        app = QApplication.instance()
        app.setStyle("Fusion")
        palette = QPalette()
        dark = QColor(30, 30, 30)
        mid_dark = QColor(45, 45, 45)
        text = QColor(232, 232, 232)
        highlight = QColor(74, 144, 217)
        disabled = QColor(120, 120, 120)

        palette.setColor(QPalette.Window, dark)
        palette.setColor(QPalette.WindowText, text)
        palette.setColor(QPalette.Base, mid_dark)
        palette.setColor(QPalette.AlternateBase, QColor(40, 40, 40))
        palette.setColor(QPalette.ToolTipBase, dark)
        palette.setColor(QPalette.ToolTipText, text)
        palette.setColor(QPalette.Text, text)
        palette.setColor(QPalette.Button, mid_dark)
        palette.setColor(QPalette.ButtonText, text)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Highlight, highlight)
        palette.setColor(QPalette.HighlightedText, Qt.white)
        palette.setColor(QPalette.Disabled, QPalette.Text, disabled)
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, disabled)
        app.setPalette(palette)

        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #3A3A3A;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 6px;
                color: #AAAAAA;
                font-size: 11px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #3A3A3A;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 6px 10px;
                color: #E8E8E8;
            }
            QPushButton:hover { background-color: #4A4A4A; }
            QPushButton:pressed { background-color: #2A2A2A; }
            QTableView {
                gridline-color: #3A3A3A;
                border: 1px solid #3A3A3A;
            }
            QHeaderView::section {
                background-color: #2A2A2A;
                color: #CCCCCC;
                border: 1px solid #3A3A3A;
                padding: 4px;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #3A3A3A;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #4A90D9;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QProgressBar {
                border: 1px solid #3A3A3A;
                border-radius: 3px;
                text-align: center;
                color: #E8E8E8;
            }
            QProgressBar::chunk { background-color: #4A90D9; }
            QScrollBar:vertical {
                background: #2A2A2A;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: #4A4A4A;
                border-radius: 5px;
            }
        """)

    # ------------------------------------------------------------------
    # Scan logic
    # ------------------------------------------------------------------

    def _start_scan(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait()

        # Check for Full Disk Access before starting the scan
        try:
            os.listdir("/private/var/folders")
        except PermissionError:
            dlg = QMessageBox(self)
            dlg.setWindowTitle("Full Disk Access Not Granted")
            dlg.setIcon(QMessageBox.Warning)
            dlg.setText(
                "This app does not have Full Disk Access.\n\n"
                "The scan will miss data in /private/var/folders and other "
                "protected locations. Results may be incomplete."
            )
            scan_anyway_btn = dlg.addButton("Scan Anyway", QMessageBox.AcceptRole)
            grant_btn = dlg.addButton("Grant Access…", QMessageBox.ActionRole)
            dlg.addButton(QMessageBox.Cancel)
            dlg.exec()

            clicked = dlg.clickedButton()
            if clicked == grant_btn:
                self._open_full_disk_access()
                return
            if clicked != scan_anyway_btn:
                return

        self._model.clear()
        self._items.clear()
        self._charts.update_charts([])

        min_bytes = self._size_slider.value() * 1024 * 1024
        self._worker = ScanWorker(min_size_bytes=min_bytes)
        self._worker.progress.connect(self._on_progress)
        self._worker.item_found.connect(self._on_item_found)
        self._worker.permission_warning.connect(self._on_permission_warning)
        self._worker.finished.connect(self._on_scan_finished)

        self._scan_btn.setText("■  Stop")
        self._scan_btn.clicked.disconnect()
        self._scan_btn.clicked.connect(self._stop_scan)
        self._progress_bar.setVisible(True)
        self._status_label.setText("Starting scan…")
        self._worker.start()

    def _stop_scan(self):
        if self._worker:
            self._worker.abort()
        self._on_scan_finished()

    def _on_progress(self, msg: str):
        self._status_label.setText(msg)

    def _on_permission_warning(self, msg: str):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Full Disk Access Required")
        dlg.setIcon(QMessageBox.Warning)
        dlg.setText(msg)
        dlg.setStandardButtons(QMessageBox.Ok)
        dlg.setModal(False)
        dlg.show()

    def _on_item_found(self, item: dict):
        self._items.append(item)
        self._update_title()

    def _on_scan_finished(self):
        self._scan_btn.setText("⟳  Scan")
        self._scan_btn.clicked.disconnect()
        self._scan_btn.clicked.connect(self._start_scan)
        self._progress_bar.setVisible(False)
        total = sum(i["size_bytes"] for i in self._items)
        wins = self._quick_wins_items()
        wins_total = sum(i["size_bytes"] for i in wins)
        kept = self._worker.protected_kept if self._worker else []
        kept_note = f" macOS is keeping {len(kept)} protected folders." if kept else ""
        self._status_label.setText(
            f"Done — {len(self._items)} folders | {format_size(total)} total "
            f"| 🎯 {len(wins)} quick wins ({format_size(wins_total)} safe to free)."
            f"{kept_note}"
        )
        report = self._worker.volume_report if self._worker else {}
        summary = system_data_line(total, report)
        if kept:
            names = ", ".join(kept[:3])
            more = f" and {len(kept) - 3} more" if len(kept) > 3 else ""
            summary += f" macOS is keeping {len(kept)} protected folders ({names}{more})."
        self._summary_label.setText(summary)
        self._wins_btn.setEnabled(bool(wins))
        self._offender_log.record_scan(self._items)
        self._apply_filters()
        self._update_title()
        self._refresh_offenders_btn()

    def _quick_wins_items(self) -> list:
        safe = []
        for item in self._items:
            app_key = item["app_name"].lower()
            app_advice = CLEANUP_ADVICE.get(app_key)
            cat_advice = CATEGORY_ADVICE.get(item["category"], {})
            effective = app_advice if app_advice else cat_advice
            if self._offender_log.is_ignored(item["app_name"]):
                continue
            if effective.get("risk") == "safe" and item["size_bytes"] > 10 * 1024 * 1024:
                safe.append(item)
        return sorted(safe, key=lambda x: x["size_bytes"], reverse=True)

    def _show_system_data(self):
        dlg = SystemDataDialog(parent=self)
        dlg.exec()

    def _show_quick_wins(self):
        wins = self._quick_wins_items()
        if not wins:
            QMessageBox.information(
                self, "No Quick Wins",
                "No safe-to-delete items found above 10 MB.\n\nRun a scan first.",
            )
            return
        dlg = QuickWinsDialog(wins, parent=self)
        dlg.exec()
        for path in dlg.deleted_paths:
            self._remove_item(path)

    def _refresh_offenders_btn(self):
        count = self._offender_log.offender_count()
        if count:
            self._offenders_btn.setText(f"🚨  Repeat Offenders ({count})")
        else:
            self._offenders_btn.setText("🚨  Repeat Offenders")

    def _show_repeat_offenders(self):
        dlg = RepeatOffendersDialog(self._offender_log, scan_items=self._items, parent=self)
        dlg.exec()
        if dlg.deleted_paths:
            gone = set(dlg.deleted_paths)
            self._items = [item for item in self._items if item["path"] not in gone]
            self._apply_filters()
            self._update_title()
            self._charts.update_charts(self._visible_items())

    def _flag_as_offender(self, item: dict):
        self._offender_log.flag_app(item["app_name"])
        self._refresh_offenders_btn()
        QMessageBox.information(
            self, "Flagged",
            f"'{item['app_name']}' has been added to the Repeat Offenders watch list.\n\n"
            "It will appear in the log with stats from all future scans.",
        )

    def _update_title(self):
        total = sum(i["size_bytes"] for i in self._items)
        self.setWindowTitle(f"System Data Inspector — {format_size(total)} found")

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _group_items(self, items: list) -> list:
        buckets: dict[str, list] = {}
        for item in items:
            buckets.setdefault(item["app_name"], []).append(item)
        groups = []
        for name, folders in buckets.items():
            folders = sorted(folders, key=lambda i: i["size_bytes"], reverse=True)
            size = sum(i["size_bytes"] for i in folders)
            cats = list(dict.fromkeys(i["category"] for i in folders))
            prev = self._offender_log.previous_size(name)
            grew = size - prev if prev is not None and size > prev * 1.05 else 0
            groups.append({
                "app_name": name,
                "category": " · ".join(cats),
                "size_bytes": size,
                "last_modified": max(i["last_modified"] for i in folders),
                "path": folders[0]["path"],
                "folders": folders,
                "grew_bytes": grew,
                "ignored": self._offender_log.is_ignored(name),
            })
        return groups

    def _apply_filters(self):
        min_bytes = self._size_slider.value() * 1024 * 1024
        enabled_cats = {cat for cat, cb in self._cat_checkboxes.items() if cb.isChecked()}
        query = self._search.text().strip().lower() if hasattr(self, "_search") else ""
        hide_ignored = self._hide_ignored.isChecked() if hasattr(self, "_hide_ignored") else True

        leaves = [i for i in self._items if i["category"] in enabled_cats]
        self._model.clear()
        for group in self._group_items(leaves):
            if group["size_bytes"] < min_bytes:
                continue
            if hide_ignored and group["ignored"]:
                continue
            if query:
                haystack = " ".join(
                    [group["app_name"], group["category"]]
                    + [f["path"] for f in group["folders"]]
                ).lower()
                if query not in haystack:
                    continue
            self._model.add_item(group)

        self._charts.update_charts(self._visible_leaves())
        self._show_selected_folders()

    def _show_selected_folders(self):
        if not hasattr(self, "_folder_list"):
            return
        self._folder_list.clear()
        selected = self._selected_items() if self._table.selectionModel() else []
        if len(selected) != 1:
            return
        for folder in selected[0].get("folders") or [selected[0]]:
            self._folder_list.addItem(
                f"{format_size(folder['size_bytes'])}   {folder['category']}   {folder['path']}"
            )

    def _visible_leaves(self) -> list:
        leaves = []
        for group in self._model.all_items():
            leaves.extend(group.get("folders") or [group])
        return leaves

    def _on_slider_changed(self, val: int):
        self._size_label.setText(f"Min Size: {val} MB")
        self._apply_filters()

    def _visible_items(self) -> list:
        """Leaf folders currently shown, so charts are not grouped twice."""
        return self._visible_leaves()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _selected_items(self) -> list:
        """Return all items currently selected in the table, in display order."""
        seen = set()
        items = []
        for proxy_index in self._table.selectionModel().selectedRows():
            src = self._proxy.mapToSource(proxy_index)
            item = self._model.all_items()[src.row()]
            key = item["app_name"]
            if key not in seen:
                seen.add(key)
                items.append(item)
        return items

    def _show_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        selected = self._selected_items()
        # If the right-clicked row isn't already in the selection, treat it as single
        src = self._proxy.mapToSource(index)
        clicked_item = self._model.all_items()[src.row()]
        if clicked_item["app_name"] not in {i["app_name"] for i in selected}:
            selected = [clicked_item]

        menu = QMenu(self)
        n = len(selected)

        if n == 1:
            item = selected[0]
            advice_action = QAction("💡  How to Clean This…", self)
            advice_action.triggered.connect(lambda: self._show_cleanup_advice(item))
            menu.addAction(advice_action)
            menu.addSeparator()
            reveal_action = QAction("📂  Reveal in Finder", self)
            reveal_action.triggered.connect(lambda: self._reveal_in_finder(item["path"]))
            menu.addAction(reveal_action)
            trash_action = QAction("🗑  Move to Trash", self)
            trash_action.triggered.connect(lambda: self._confirm_trash(item))
            menu.addAction(trash_action)
            installed, app_path = _is_app_installed(item["app_name"])
            if installed and app_path:
                menu.addSeparator()
                find_app = QAction("📂  Find App", self)
                find_app.triggered.connect(lambda: _reveal_path(app_path))
                menu.addAction(find_app)
                remove_app = QAction("🗑  Remove App", self)
                remove_app.triggered.connect(lambda: self._remove_installed_app(item["app_name"], app_path))
                menu.addAction(remove_app)
            menu.addSeparator()
            flag_action = QAction("🚩  Flag as Offender", self)
            flag_action.setToolTip("Add to Repeat Offenders watch list without deleting")
            flag_action.triggered.connect(lambda: self._flag_as_offender(item))
            menu.addAction(flag_action)
            if item.get("ignored"):
                aside = QAction("↩  Show this again", self)
                aside.triggered.connect(lambda: self._set_aside(item, False))
            else:
                aside = QAction("🚫  Leave this alone", self)
                aside.triggered.connect(lambda: self._set_aside(item, True))
            menu.addAction(aside)
        else:
            total_size = sum(i["size_bytes"] for i in selected)
            header = QAction(f"{n} items selected  ({format_size(total_size)})", self)
            header.setEnabled(False)
            menu.addAction(header)
            menu.addSeparator()
            trash_action = QAction(
                f"🗑  Move {n} Items to Trash  ({format_size(total_size)})", self
            )
            trash_action.triggered.connect(lambda: self._confirm_trash_multiple(selected))
            menu.addAction(trash_action)
            menu.addSeparator()
            reveal_action = QAction("📂  Reveal First Item in Finder", self)
            reveal_action.triggered.connect(
                lambda: self._reveal_in_finder(selected[0]["path"])
            )
            menu.addAction(reveal_action)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _show_cleanup_advice(self, item: dict):
        dlg = CleanupAdviceDialog(item, parent=self)
        dlg.exec()
        if dlg.deleted_paths:
            gone = set(dlg.deleted_paths)
            self._items = [i for i in self._items if i["path"] not in gone]
            self._apply_filters()
            self._update_title()

    def _set_aside(self, item: dict, ignored: bool):
        self._offender_log.set_ignored(item["app_name"], ignored)
        self._apply_filters()

    def _confirm_trash(self, item: dict):
        folders = item.get("folders") or [item]
        label = item["app_name"]
        if len(folders) > 1:
            label += f" ({len(folders)} folders)"
        reply = QMessageBox.question(
            self, "Move to Trash",
            f"Move to Trash?\n\n{label}\n({format_size(item['size_bytes'])})",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        failed = []
        for folder in folders:
            ok, detail = _move_to_trash_mac(folder["path"])
            if ok:
                self._items = [i for i in self._items if i["path"] != folder["path"]]
            else:
                failed.append(detail or Path(folder["path"]).name)
        self._apply_filters()
        self._update_title()
        if failed:
            QMessageBox.critical(self, "Error", "\n".join(failed))

    def _confirm_trash_multiple(self, items: list):
        total_size = sum(i["size_bytes"] for i in items)
        names = "\n".join(f"  • {Path(i['path']).name}" for i in items[:8])
        if len(items) > 8:
            names += f"\n  … and {len(items) - 8} more"
        reply = QMessageBox.question(
            self, "Move to Trash",
            f"Move {len(items)} items ({format_size(total_size)}) to Trash?\n\n{names}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        failed = []
        notes = []
        for item in items:
            for folder in item.get("folders") or [item]:
                ok, detail = _move_to_trash_mac(folder["path"])
                if ok:
                    self._items = [i for i in self._items if i["path"] != folder["path"]]
                    if detail:
                        notes.append(detail)
                else:
                    name = Path(folder["path"]).name
                    failed.append(f"{name}: {detail}" if detail else name)

        self._apply_filters()
        self._update_title()
        self._charts.update_charts(self._visible_items())

        if failed:
            QMessageBox.warning(
                self, "Some Items Failed",
                "Could not move to Trash:\n• " + "\n• ".join(failed),
            )
        elif notes:
            QMessageBox.information(self, "Moved to Trash", "\n\n".join(notes))

    def _remove_item(self, path: str):
        self._items = [i for i in self._items if i["path"] != path]
        self._apply_filters()
        self._update_title()
        self._charts.update_charts(self._visible_items())

    def _reveal_in_finder(self, path: str):
        _reveal_path(path)

    def _remove_installed_app(self, app_name: str, app_path: str):
        if not _confirm_remove_app(self, app_name, app_path):
            return
        ok, detail = _move_to_trash_mac(app_path)
        if ok:
            QMessageBox.information(
                self, "App Moved to Trash",
                detail or f"{Path(app_path).name} is in the Trash.\n\n"
                "Its leftover data is still listed here until you remove those folders too.",
            )
        else:
            QMessageBox.critical(self, "Error", detail or "Could not move the app to Trash.")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_csv(self):
        dest = Path("~/Desktop/system_data_report.csv").expanduser()
        try:
            with open(dest, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["app_name", "category", "size_bytes", "size_human",
                                "last_modified", "path"]
                )
                writer.writeheader()
                for item in self._items:
                    writer.writerow({
                        "app_name": item["app_name"],
                        "category": item["category"],
                        "size_bytes": item["size_bytes"],
                        "size_human": format_size(item["size_bytes"]),
                        "last_modified": item["last_modified"].isoformat(),
                        "path": item["path"],
                    })
            QMessageBox.information(self, "Export Complete", f"Saved to:\n{dest}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    # ------------------------------------------------------------------
    # Full Disk Access
    # ------------------------------------------------------------------

    def _show_fda_help(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("How to Grant Full Disk Access")
        dlg.setIcon(QMessageBox.Information)
        dlg.setTextFormat(Qt.RichText)
        dlg.setText(
            "<b>Full Disk Access</b> lets this app scan<br>"
            "<code>/private/var/folders</code> for hidden caches.<br><br>"
            "<b>Steps:</b><br>"
            "<ol>"
            "<li>Click <b>Full Disk Access</b> below (or the button in the panel)</li>"
            "<li>System Settings opens to <i>Privacy &amp; Security → Full Disk Access</i></li>"
            "<li>Click the <b>+</b> button</li>"
            "<li>Navigate to your <b>Terminal</b> app<br>"
            "&nbsp;&nbsp;&nbsp;(usually <code>/Applications/Utilities/Terminal.app</code>)<br>"
            "&nbsp;&nbsp;&nbsp;or your IDE / Python launcher if running from there</li>"
            "<li>Click <b>Open</b> to add it to the list</li>"
            "<li>Make sure the toggle next to Terminal is <b>ON</b></li>"
            "<li><b>Quit and reopen Terminal</b>, then re-run this app</li>"
            "</ol>"
            "<br><i>You only need to do this once.</i>"
        )
        open_btn = dlg.addButton("Open System Settings", QMessageBox.ActionRole)
        dlg.addButton(QMessageBox.Close)
        dlg.exec()
        if dlg.clickedButton() == open_btn:
            self._open_full_disk_access()

    def _open_full_disk_access(self):
        try:
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"],
                check=False
            )
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open System Settings:\n{e}")

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait()
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("System Data Inspector")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
