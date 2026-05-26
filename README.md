# Clean Me :) — macOS System Data Inspector

> **This is written for you — not for programmers.**
> Think of this guide like advice from a knowledgeable friend who wants to help you reclaim space on your Mac without breaking anything.

---

## What Is This?

If you've ever looked at your Mac's storage settings and seen a giant, mysterious **"System Data"** category eating up tens or even hundreds of gigabytes — this tool is for you.

Apple doesn't tell you what's inside "System Data." This app does.

**Clean Me** scans your Mac, finds all the hidden files that make up that number, tells you exactly what they are, how big they are, and — most importantly — whether it's safe to delete them.

It will **never delete anything without your permission.** You are always in control.

---

## What It Finds

The app looks in the places macOS uses to quietly store things over time:

| What It's Called | What It Actually Is |
|---|---|
| **Cache** | Temporary files apps create to run faster. Always safe to delete — apps just rebuild them. |
| **Logs** | Records apps keep of what they've done. Useful for developers; useless for you. Safe to delete. |
| **App Support** | Settings and data saved by your apps. Delete only if an app is uninstalled, or if you want a fresh start. |
| **iOS Backup** | Full backups of your iPhone or iPad stored on this Mac. **Be careful** — deleting these removes your safety net. |
| **Containers** | Sandboxed storage macOS assigns to each app. Safe to remove if the app is already gone. |
| **Trash** | Files you've already deleted but haven't permanently removed. Always safe to empty. |
| **Snapshots** | Time Machine's local recovery points. macOS manages these automatically. |

---

## Before You Begin — Two Things to Know

### 1. This app is safe to run
It reads your files to measure them. It does **not** automatically delete anything. Every deletion requires your deliberate action.

### 2. Risk levels are labeled clearly
Every item in the app is color-coded:

- 🟢 **Safe to delete** — go for it, no consequences
- 🟡 **Delete with caution** — read the description first, then decide
- 🔴 **High risk** — read carefully; some things here can't be undone

---

## How to Run It

You'll need to open the **Terminal** app. Don't worry — you only need to type one thing.

### Step 1 — Make sure Python is installed

Python usually comes with macOS. To check, open **Terminal** (search for it in Spotlight with `⌘ Space`) and type:

```
python3 --version
```

If you see a version number, you're good. If not, download Python from [python.org](https://www.python.org/downloads/) and install it.

### Step 2 — Navigate to this folder

In Terminal, type `cd ` (with a space after it), then drag the **Clean Me** folder from Finder directly into the Terminal window. The path will fill in automatically. Press **Return**.

### Step 3 — Run the app

Type this and press **Return**:

```
python3 system_data_inspector.py
```

The first time you run it, the app may ask to install two helper libraries (`PySide6` and `matplotlib`). Just type `y` and press **Return** — it handles the rest automatically.

The app window will open and begin scanning. Scanning usually takes 1–3 minutes depending on how much is on your drive.

---

## Using the App

Once the scan finishes, you'll see a list of folders sorted by size — biggest offenders at the top.

**To learn what something is:** Click any row. A panel on the right explains what that folder contains and whether it's safe to remove.

**To delete something:**
1. Right-click the item in the list
2. Choose **Move to Trash**
3. Empty your Trash when you're done

**To filter by size:** Use the slider at the top to hide items below a certain size — useful for cutting through the clutter.

**To export a report:** Use the Export button to save a CSV spreadsheet of everything the scan found, so you can review it at your own pace.

---

## Frequently Asked Questions

**Q: Will this break my Mac?**
No. The app only reads files — it never deletes anything on its own. You choose what to remove, one item at a time.

**Q: My "System Data" in Settings is 80 GB but the app only found 40 GB. Why?**
Apple's "System Data" number includes things that require special system permissions to access. The app scans everything it *can* access. You can grant **Full Disk Access** to Terminal in System Settings → Privacy & Security → Full Disk Access for a more complete scan.

**Q: I deleted things but System Data in Settings still shows the same number.**
macOS updates that number slowly — sometimes it takes a few minutes, or requires a restart, to reflect changes.

**Q: Is it safe to delete all the Caches?**
Yes. Caches are temporary files that apps recreate on their own. The worst that happens is an app feels slightly slower the first time you open it after its cache is cleared.

**Q: What about iOS Backups? I see one from 3 years ago.**
If you have a more recent backup (or you use iCloud Backup), old local backups are safe to delete. Before removing any backup, make sure your iPhone is backed up somewhere current. You can verify this in Finder by connecting your device.

**Q: I see "Docker" taking up 80 GB and I've never used it.**
This is common. Docker (software used by developers) can leave behind a large disk image even after being uninstalled. The app will give you exact steps to remove it safely.

---

## What This App Does NOT Do

- It does **not** touch your personal files (Documents, Photos, Downloads, etc.)
- It does **not** modify the macOS system itself
- It does **not** require administrator access for most operations
- It does **not** send any data anywhere — it runs entirely on your Mac, offline

---

## A Note on Trust

This app was built to be something you can hand to a friend or family member with confidence. The goal is transparency: show you what's there, explain it plainly, and let you make an informed decision. Nothing happens behind the scenes.

If you're ever unsure about an item, the safest choice is to leave it alone. Reclaiming even half of what's flagged as "safe" can make a meaningful difference.

---

*Built with Python · Runs entirely on your Mac · No data leaves your machine*
