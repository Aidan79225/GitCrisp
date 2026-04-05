# Windows Installer + Code Signing Design

## Overview

Replace the current Windows `.zip` distribution with a proper Inno Setup installer (`.exe`), and integrate free code signing via SignPath Foundation for SmartScreen trust.

## Goals

- Professional install experience for Windows users (install wizard, Start Menu, uninstaller)
- Code signing with EV-level SmartScreen reputation (free via SignPath Foundation)
- Clean CI integration that works with or without signing configured

## Installer: Inno Setup

### Configuration (`GitStack.iss`)

- **App name:** GitStack
- **Install directory:** `{autopf}\GitStack` (Program Files, auto-detect 64-bit)
- **Content:** Entire PyInstaller `dist/GitStack/` output directory
- **Shortcuts:**
  - Start Menu group (default: on)
  - Desktop icon (optional, unchecked by default)
- **Uninstaller:** Auto-registered in Add/Remove Programs
- **Output file:** `GitStack-windows-setup.exe`
- **Architecture:** x64 only
- **Version:** Passed from git tag at compile time via `/D` flag
- **Install wizard flow:** Install location -> Shortcuts -> Install -> Done (no license page)

### File location

`GitStack.iss` in the repo root (alongside `GitStack.spec`).

## CI Pipeline Changes

### Windows build steps (replaces current `Archive build (Windows)`)

1. **Install Inno Setup** on the `windows-latest` runner
2. **Compile installer:** `iscc /DAppVersion=<tag> GitStack.iss`
3. **Upload:** `GitStack-windows-setup.exe` as the release artifact

### Matrix config changes

- `archive_ext: zip` -> `archive_ext: exe`
- Remove `Compress-Archive` PowerShell step
- Add Inno Setup install + compile steps (Windows only)

### Release job changes

- Upload `GitStack-windows-setup.exe` instead of `GitStack-windows.zip`

## Code Signing: SignPath Foundation

### Why SignPath Foundation

- Free for open-source projects
- EV-level certificate with immediate SmartScreen trust
- No hardware token or certificate management needed
- GitHub Actions integration via official action

### Integration flow

1. Apply for SignPath Foundation (requires public GitHub repo)
2. Configure signing policy on signpath.io
3. Add `signpath/github-action-submit-signing-request` step after Inno Setup compile
4. Flow: CI builds installer -> submits to SignPath -> signed artifact returned -> uploaded to release

### What gets signed

- `GitStack-windows-setup.exe` (the installer bundles everything, so signing the installer is sufficient)

### Conditional signing

The signing step is conditional on SignPath secrets being configured. This means:
- **Before approval:** Pipeline produces an unsigned installer (fully functional)
- **After approval:** Same pipeline produces a signed installer (no workflow changes needed)

## Design for future auto-update

The installer does not include auto-update functionality. However, the design is compatible with adding it later:
- Inno Setup supports update detection via registry keys
- A future update checker could download the new installer from GitHub Releases
- No architectural decisions here block that path

## Artifacts

The Windows release will ship a single artifact:
- `GitStack-windows-setup.exe` (installer, signed when SignPath is active)

The `.zip` portable distribution is removed.
