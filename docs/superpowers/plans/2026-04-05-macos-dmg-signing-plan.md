# macOS DMG + Code Signing + Notarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate macOS code signing, notarization, and DMG packaging in CI so users don't see the Gatekeeper malware warning.

**Architecture:** Add `BUNDLE` to PyInstaller spec for `.app` output, create an `entitlements.plist` for hardened runtime, and extend the GitHub Actions release workflow with macOS-specific steps for certificate import, code signing, notarization, DMG creation, and cleanup.

**Tech Stack:** PyInstaller BUNDLE, Apple `codesign`/`notarytool`/`stapler`, `create-dmg` (brew), GitHub Actions secrets

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `entitlements.plist` | Create | Hardened runtime entitlements for pygit2 native libs |
| `GitStack.spec` | Modify | Add `BUNDLE` block for macOS `.app` output |
| `.github/workflows/release.yml` | Modify | macOS signing, notarization, DMG steps; update artifact format |

---

### Task 1: Create entitlements.plist

**Files:**
- Create: `entitlements.plist`

- [ ] **Step 1: Create the entitlements file**

Create `entitlements.plist` at the repo root:

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

This entitlement is required because pygit2 uses native C libraries (libgit2/cffi) that need unsigned executable memory under hardened runtime.

- [ ] **Step 2: Commit**

```bash
git add entitlements.plist
git commit -m "build: add macOS hardened runtime entitlements"
```

---

### Task 2: Add BUNDLE to PyInstaller spec

**Files:**
- Modify: `GitStack.spec:41-49` (after the `COLLECT` block)

- [ ] **Step 1: Add the BUNDLE block**

Append the following after the existing `coll = COLLECT(...)` block at the end of `GitStack.spec`:

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

`BUNDLE` is a macOS-only PyInstaller directive. On Windows and Linux, PyInstaller silently ignores it, so adding it unconditionally is safe.

- [ ] **Step 2: Verify spec syntax**

Run (on any platform — this just checks the spec parses):

```bash
uv run python -c "exec(open('GitStack.spec').read())" 2>&1 || echo "Syntax OK if only NameError for Analysis/PYZ/EXE/COLLECT/BUNDLE"
```

Expected: NameError for `Analysis` (because PyInstaller globals aren't defined outside a build), but no `SyntaxError`.

- [ ] **Step 3: Commit**

```bash
git add GitStack.spec
git commit -m "build: add BUNDLE for macOS .app output"
```

---

### Task 3: Update release workflow — macOS certificate import

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add certificate import step**

In `.github/workflows/release.yml`, add the following step after the `Build with PyInstaller` step and before the archive steps. This step only runs on macOS:

```yaml
      - name: Import macOS signing certificate
        if: runner.os == 'macOS'
        env:
          MACOS_CERTIFICATE: ${{ secrets.MACOS_CERTIFICATE }}
          MACOS_CERTIFICATE_PWD: ${{ secrets.MACOS_CERTIFICATE_PWD }}
          MACOS_KEYCHAIN_PWD: ${{ secrets.MACOS_KEYCHAIN_PWD }}
        run: |
          CERTIFICATE_PATH=$RUNNER_TEMP/build_certificate.p12
          KEYCHAIN_PATH=$RUNNER_TEMP/app-signing.keychain-db

          echo -n "$MACOS_CERTIFICATE" | base64 --decode -o $CERTIFICATE_PATH

          security create-keychain -p "$MACOS_KEYCHAIN_PWD" $KEYCHAIN_PATH
          security set-keychain-settings -lut 21600 $KEYCHAIN_PATH
          security unlock-keychain -p "$MACOS_KEYCHAIN_PWD" $KEYCHAIN_PATH

          security import $CERTIFICATE_PATH -P "$MACOS_CERTIFICATE_PWD" \
            -A -t cert -f pkcs12 -k $KEYCHAIN_PATH
          security set-key-partition-list -S apple-tool:,apple: \
            -k "$MACOS_KEYCHAIN_PWD" $KEYCHAIN_PATH
          security list-keychain -d user -s $KEYCHAIN_PATH
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add macOS certificate import step"
```

---

### Task 4: Update release workflow — code signing

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add code signing step**

Add after the certificate import step:

```yaml
      - name: Sign macOS app
        if: runner.os == 'macOS'
        env:
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        run: |
          IDENTITY=$(security find-identity -v -p codesigning $RUNNER_TEMP/app-signing.keychain-db | grep "Developer ID Application" | head -1 | awk -F'"' '{print $2}')
          echo "Signing with: $IDENTITY"

          codesign --force --deep --options runtime \
            --sign "$IDENTITY" \
            --entitlements entitlements.plist \
            dist/GitStack.app

          echo "Verifying signature..."
          codesign --verify --deep --strict dist/GitStack.app
```

This step:
1. Extracts the signing identity name from the keychain (so it doesn't need to be hardcoded or stored as a secret)
2. Signs the `.app` with hardened runtime enabled
3. Verifies the signature is valid

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add macOS code signing step"
```

---

### Task 5: Update release workflow — notarization

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add notarization step**

Add after the signing step:

```yaml
      - name: Notarize macOS app
        if: runner.os == 'macOS'
        env:
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APP_SPECIFIC_PASSWORD: ${{ secrets.APP_SPECIFIC_PASSWORD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        run: |
          ditto -c -k --keepParent dist/GitStack.app dist/GitStack.zip

          xcrun notarytool submit dist/GitStack.zip \
            --apple-id "$APPLE_ID" \
            --password "$APP_SPECIFIC_PASSWORD" \
            --team-id "$APPLE_TEAM_ID" \
            --wait

          xcrun stapler staple dist/GitStack.app
```

`--wait` blocks until Apple returns a result (typically 2-5 minutes). If notarization fails, the step fails and the release aborts.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add macOS notarization step"
```

---

### Task 6: Update release workflow — DMG packaging

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add DMG creation step**

Add after the notarization step:

```yaml
      - name: Create macOS DMG
        if: runner.os == 'macOS'
        run: |
          brew install create-dmg

          create-dmg \
            --volname "GitStack" \
            --window-pos 200 120 \
            --window-size 600 400 \
            --icon-size 100 \
            --icon "GitStack.app" 175 190 \
            --app-drop-link 425 190 \
            --no-internet-enable \
            "GitStack-macos.dmg" \
            "dist/GitStack.app"

          IDENTITY=$(security find-identity -v -p codesigning $RUNNER_TEMP/app-signing.keychain-db | grep "Developer ID Application" | head -1 | awk -F'"' '{print $2}')
          codesign --force --sign "$IDENTITY" GitStack-macos.dmg
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add macOS DMG creation step"
```

---

### Task 7: Update release workflow — archive and cleanup

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Replace the macOS archive step and add cleanup**

The current archive steps are:

```yaml
      - name: Archive build (Windows)
        if: runner.os == 'Windows'
        run: Compress-Archive -Path dist/GitStack/* -DestinationPath ${{ matrix.artifact }}.zip
        shell: pwsh

      - name: Archive build (Unix)
        if: runner.os != 'Windows'
        run: tar -czf ${{ matrix.artifact }}.tar.gz -C dist GitStack
```

Replace these with three platform-specific steps:

```yaml
      - name: Archive build (Windows)
        if: runner.os == 'Windows'
        run: Compress-Archive -Path dist/GitStack/* -DestinationPath ${{ matrix.artifact }}.zip
        shell: pwsh

      - name: Archive build (macOS)
        if: runner.os == 'macOS'
        run: mv GitStack-macos.dmg ${{ matrix.artifact }}.dmg

      - name: Archive build (Linux)
        if: runner.os == 'Linux'
        run: tar -czf ${{ matrix.artifact }}.tar.gz -C dist GitStack

      - name: Cleanup macOS keychain
        if: runner.os == 'macOS' && always()
        run: security delete-keychain $RUNNER_TEMP/app-signing.keychain-db
```

- [ ] **Step 2: Update the matrix archive_ext for macOS**

In the strategy matrix at the top of the file, change macOS `archive_ext` from `tar.gz` to `dmg`:

```yaml
        include:
          - os: windows-latest
            artifact: GitStack-windows
            archive_ext: zip
          - os: macos-latest
            artifact: GitStack-macos
            archive_ext: dmg
          - os: ubuntu-latest
            artifact: GitStack-linux
            archive_ext: tar.gz
```

- [ ] **Step 3: Update the release job artifact path**

In the `release` job, update the macOS artifact path in the `gh release create` command:

```yaml
          gh release create "$tag" \
            --title "GitStack $tag" \
            --generate-notes \
            artifacts/GitStack-windows/GitStack-windows.zip \
            artifacts/GitStack-macos/GitStack-macos.dmg \
            artifacts/GitStack-linux/GitStack-linux.tar.gz
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: update macOS archive to DMG, add keychain cleanup"
```

---

### Task 8: Final review — verify complete workflow

**Files:**
- Read: `.github/workflows/release.yml`
- Read: `GitStack.spec`
- Read: `entitlements.plist`

- [ ] **Step 1: Read and review all changed files**

Read all three files end-to-end and verify:
1. `entitlements.plist` is valid XML
2. `GitStack.spec` has `BUNDLE` after `COLLECT`
3. `release.yml` macOS steps are in correct order: build → import cert → sign → notarize → create DMG → archive → cleanup
4. `release.yml` Windows and Linux steps are unchanged
5. Matrix `archive_ext` for macOS is `dmg`
6. Release job references `.dmg` not `.tar.gz` for macOS
7. All secrets are referenced correctly: `MACOS_CERTIFICATE`, `MACOS_CERTIFICATE_PWD`, `MACOS_KEYCHAIN_PWD`, `APPLE_ID`, `APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`

- [ ] **Step 2: Validate YAML syntax**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
```

If `yaml` is not available:

```bash
python -c "
import json, subprocess
result = subprocess.run(['python', '-c', '''
lines = open(\".github/workflows/release.yml\").readlines()
indent_errors = []
for i, line in enumerate(lines, 1):
    if \"\\t\" in line:
        indent_errors.append(f\"Tab on line {i}\")
if indent_errors:
    print(\"\\n\".join(indent_errors))
else:
    print(\"No tab indentation issues found\")
'''], capture_output=True, text=True)
print(result.stdout)
"
```

- [ ] **Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address review findings in macOS signing workflow"
```

Only run this if Step 1 or 2 found issues that were fixed.
