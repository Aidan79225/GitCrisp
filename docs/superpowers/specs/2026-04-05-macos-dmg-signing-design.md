# macOS DMG + Code Signing + Notarization Design

## Problem

macOS users see "Apple could not verify GitStack is free of malware" when opening the app, because the binary is unsigned and not notarized by Apple.

## Solution

Package the macOS build as a signed, notarized `.app` inside a `.dmg` with an Applications shortcut, all automated in GitHub Actions CI.

## Approach

PyInstaller `BUNDLE` for `.app` output + Apple native `codesign`/`notarytool` + `create-dmg` for DMG packaging.

## Design

### 1. PyInstaller `.app` Bundle

Add a `BUNDLE` block to `GitStack.spec` after the existing `COLLECT`:

```python
app = BUNDLE(
    coll,
    name='GitStack.app',
    icon=None,
    bundle_identifier='com.gitstack.app',
    info_plist={
        'CFBundleShortVersionString': '0.1.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
    },
)
```

`BUNDLE` only takes effect on macOS; Windows/Linux builds are unaffected.

### 2. Entitlements

A new `entitlements.plist` file at the repo root:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
</dict>
</plist>
```

Required for hardened runtime with pygit2's native libraries.

### 3. Code Signing

After PyInstaller produces the `.app`, sign it with:

```bash
codesign --force --deep --options runtime \
  --sign "Developer ID Application: $DEVELOPER_ID_NAME" \
  --entitlements entitlements.plist \
  dist/GitStack.app
```

- `--options runtime` enables hardened runtime (required for notarization)
- `--deep` signs all nested frameworks and dylibs

### 4. Notarization

Submit to Apple for notarization and staple the ticket:

```bash
ditto -c -k --keepParent dist/GitStack.app GitStack.zip

xcrun notarytool submit GitStack.zip \
  --apple-id "$APPLE_ID" \
  --password "$APP_SPECIFIC_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" \
  --wait

xcrun stapler staple dist/GitStack.app
```

`--wait` blocks until Apple returns a result (typically 2-5 minutes).

### 5. DMG Packaging

Use `create-dmg` to produce a DMG with an Applications shortcut:

```bash
create-dmg \
  --volname "GitStack" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "GitStack.app" 175 190 \
  --app-drop-link 425 190 \
  "GitStack-macos.dmg" \
  "dist/GitStack.app"
```

Sign the DMG itself:

```bash
codesign --force --sign "Developer ID Application: $DEVELOPER_ID_NAME" GitStack-macos.dmg
```

### 6. GitHub Actions Workflow Changes

The macOS job in `release.yml` diverges after PyInstaller build:

1. Import certificate - create temp keychain, import `.p12` from secrets
2. Code sign the `.app`
3. Notarize with `notarytool` + staple
4. Install `create-dmg` via brew, produce and sign `.dmg`
5. Cleanup temp keychain

Windows and Linux jobs are unchanged.

### 7. GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `MACOS_CERTIFICATE` | Developer ID Application certificate, `.p12` base64 encoded |
| `MACOS_CERTIFICATE_PWD` | Password for the `.p12` file |
| `MACOS_KEYCHAIN_PWD` | Password for the temp CI keychain (arbitrary) |
| `APPLE_ID` | Apple Developer account email |
| `APP_SPECIFIC_PASSWORD` | App-specific password from appleid.apple.com |
| `APPLE_TEAM_ID` | 10-character Team ID |

### 8. Release Artifact Changes

| Platform | Before | After |
|----------|--------|-------|
| Windows | `.zip` | `.zip` (unchanged) |
| macOS | `.tar.gz` | `.dmg` |
| Linux | `.tar.gz` | `.tar.gz` (unchanged) |

## Files Changed

| File | Change |
|------|--------|
| `GitStack.spec` | Add `BUNDLE` block |
| `.github/workflows/release.yml` | macOS signing + notarize + DMG steps |

## Files Added

| File | Purpose |
|------|---------|
| `entitlements.plist` | Hardened runtime entitlements |
