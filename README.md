# NoLabel

**NoLabel** is a macOS suite for automatically removing and healing bottom-right corner labels or watermarks from images, PDFs, Apple Keynote presentations, and PowerPoint presentations. 

It uses **100% local, privacy-first processing** combining macOS Native Apple Vision, OpenCV inpainting (Telea/Navier-Stokes), PyMuPDF, and AppleScript object manipulation to cleanly erase and seamlessly patch labeled areas.

## Features

- **Images**: Automatically detects corner labels using Apple Vision OCR and inpaints the area.
- **PDFs**: Scans each page, identifies corner text/images, and applies intelligent inpainting to precisely remove them without affecting layout.
- **Apple Keynote**: Uses native AppleScript to find and surgically remove overlay text or image objects in the bottom right corner.
- **PowerPoint (PPTX)**: Scans Slide XML objects, deletes labels/watermarks, and repackages the deck.

## 3 Ways to Use

1. **Folder Watcher Daemon**: A background service monitors `~/Documents/Label-Cleaner`. Simply drop files in this folder, and they are automatically patched in-place.
2. **Finder Quick Action**: Right-click any supported file in Finder, go to **Quick Actions -> Remove Corner Label**, and it will be processed instantly.
3. **Command Line (CLI)**: Process files or folders directly via terminal using the `nolabel` command.

---

## Installation

You can install this tool suite entirely via a single terminal command.

### One-Line Install

```bash
git clone https://github.com/studiohelioripple/NoLabel.git ~/.local/share/nolabel && cd ~/.local/share/nolabel && ./install.sh
```

*(You will need `python3` and macOS Xcode Command Line Tools `swiftc` installed prior to running.)*

### What the installer does:
1. Creates a Python virtual environment (`.venv`) to isolate dependencies.
2. Installs requirements (`opencv-python`, `pillow`, `pymupdf`, `python-pptx`, `lxml`, `numpy`).
3. Compiles the Swift Vision binary for native OCR.
4. Symlinks the CLI launcher to `~/.local/bin/nolabel`.
5. Installs the macOS Finder **Quick Action** into `~/Library/Services/`.
6. Configures and starts the background folder watcher daemon via macOS `launchd`.

---

## Usage

### 1. Folder Watcher (Fully Automated)
After installation, a daemon runs in the background watching `~/Documents/Label-Cleaner`.
- **Drag and drop** any image, PDF, Keynote, or PPTX file into this directory.
- Within 1 second, it will patch the file **in-place**.
- A pristine original will automatically be preserved in `~/Documents/Label-Cleaner/backup/`.

### 2. Finder Quick Action
- Right-click an image, `.pdf`, `.key`, or `.pptx` file anywhere in Finder.
- Select **Quick Actions** -> **Remove Corner Label**.
- The file is patched in-place, and a `backup/` folder is created alongside the file for safety.

### 3. CLI Options
You can use the `nolabel` command line tool directly from terminal. 

```bash
# Process a single file
nolabel process presentation.pdf

# Process a whole directory (will only target valid extensions)
nolabel process ./my_files/

# Adjust the inpainting radius (default 3) and method (telea or ns)
nolabel process photo.jpg --radius 5 --method ns

# Check system status (queue status, daemon status, etc.)
nolabel status

# View live processing logs
nolabel logs
```

## System Requirements

- **Apple Silicon Mac** (M1, M2, M3, M4 series). *Intel Macs are explicitly not supported.*
- **8GB RAM** minimum.
- **macOS 12.0+**
- **Python 3.9+**
- **Xcode Command Line Tools** (for `swiftc`)

## Safety & Backups
**In-Place Patching & Original Retention:**
Whenever NoLabel processes a file, it edits the file *in-place* to preserve file tracking and links, but it **always** creates a copy of the original, un-edited file inside a `backup/` folder located in the same directory as the target file.

Enjoy clean, label-free media!
