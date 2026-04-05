# Windows Installer + Code Signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Windows `.zip` distribution with a signed Inno Setup installer for a professional install experience and SmartScreen trust.

**Architecture:** Add an Inno Setup script (`GitStack.iss`) that packages the PyInstaller output into an installer with Start Menu/Desktop shortcuts and uninstaller. Modify the GitHub Actions release workflow to compile the installer and conditionally sign it via SignPath Foundation.

**Tech Stack:** Inno Setup 6 (`iscc` compiler), SignPath GitHub Action, GitHub Actions

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `installer.iss` | Create | Inno Setup script defining installer behavior |
| `.github/workflows/release.yml` | Modify | Install Inno Setup, compile installer, conditional signing, update artifact |

---

### Task 1: Create the Inno Setup script

**Files:**
- Create: `installer.iss`

- [ ] **Step 1: Create the Inno Setup script**

Create `installer.iss` at the repo root:

```iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppName=GitStack
AppVersion={#AppVersion}
AppPublisher=Aidan Wang
DefaultDirName={autopf}\GitStack
DefaultGroupName=GitStack
UninstallDisplayIcon={app}\GitStack.exe
OutputBaseFilename=GitStack-windows-setup
OutputDir=.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\GitStack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GitStack"; Filename: "{app}\GitStack.exe"
Name: "{group}\Uninstall GitStack"; Filename: "{uninstallexe}"
Name: "{userdesktop}\GitStack"; Filename: "{app}\GitStack.exe"; Tasks: desktopicon
```

Key points:
- `{autopf}` resolves to `C:\Program Files` on 64-bit systems
- `ArchitecturesAllowed=x64compatible` rejects install on 32-bit Windows
- `WizardStyle=modern` gives a clean, modern look
- `#ifndef AppVersion` provides a fallback so the script compiles without `/D` flag for local testing
- Desktop icon task is unchecked by default per spec

- [ ] **Step 2: Test the script compiles locally (if Inno Setup is installed)**

If you have Inno Setup installed, run:

```bash
iscc installer.iss
```

Expected: produces `GitStack-windows-setup.exe` in the repo root (it won't contain the actual app files unless you've run PyInstaller first, but it should compile without errors).

- [ ] **Step 3: Commit**

```bash
git add installer.iss
git commit -m "build: add Inno Setup installer script for Windows"
```

---

### Task 2: Update CI — install Inno Setup and compile installer

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Change Windows matrix entry**

In the `matrix.include` section, change the Windows entry from:

```yaml
          - os: windows-latest
            artifact: GitStack-windows
            archive_ext: zip
```

to:

```yaml
          - os: windows-latest
            artifact: GitStack-windows
            archive_ext: exe
```

- [ ] **Step 2: Add Inno Setup install step**

Add this step after the `Build with PyInstaller` step (before the existing `Archive build (Windows)` step):

```yaml
      - name: Install Inno Setup
        if: runner.os == 'Windows'
        run: choco install innosetup --yes --no-progress
        shell: pwsh
```

`windows-latest` runners have Chocolatey pre-installed.

- [ ] **Step 3: Replace the Windows archive step**

Replace the existing step:

```yaml
      - name: Archive build (Windows)
        if: runner.os == 'Windows'
        run: Compress-Archive -Path dist/GitStack/* -DestinationPath ${{ matrix.artifact }}.zip
        shell: pwsh
```

with:

```yaml
      - name: Build installer (Windows)
        if: runner.os == 'Windows'
        run: |
          $tag = "${{ github.ref_name }}" -replace '^v', ''
          & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=$tag installer.iss
          Move-Item GitStack-windows-setup.exe "${{ matrix.artifact }}.exe"
        shell: pwsh
```

This strips the `v` prefix from the git tag (e.g., `v1.2.3` → `1.2.3`) and passes it as the app version. The output is renamed to match the artifact naming convention.

- [ ] **Step 4: Run the full CI changes through**

Verify the release job's `gh release create` command references the correct filename. The current line:

```yaml
            artifacts/GitStack-windows/GitStack-windows.zip \
```

becomes:

```yaml
            artifacts/GitStack-windows/GitStack-windows.exe \
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: replace Windows zip with Inno Setup installer"
```

---

### Task 3: Add conditional SignPath signing step

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Add SignPath signing step**

Add this step after the `Build installer (Windows)` step and before the `Upload artifact` step:

```yaml
      - name: Sign installer (Windows)
        if: runner.os == 'Windows' && vars.SIGNPATH_SIGNING_POLICY_SLUG != ''
        uses: signpath/github-action-submit-signing-request@v1
        with:
          api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
          organization-id: ${{ vars.SIGNPATH_ORGANIZATION_ID }}
          project-slug: "GitStack"
          signing-policy-slug: ${{ vars.SIGNPATH_SIGNING_POLICY_SLUG }}
          input-artifact-path: "${{ matrix.artifact }}.exe"
          output-artifact-path: "${{ matrix.artifact }}.exe"
          wait-for-completion: true
          wait-for-completion-timeout-in-seconds: 600
```

Key points:
- The `if` condition checks `vars.SIGNPATH_SIGNING_POLICY_SLUG` — if this repository variable isn't set, the step is skipped entirely. This makes signing opt-in.
- `SIGNPATH_API_TOKEN` is a secret (sensitive), while `SIGNPATH_ORGANIZATION_ID` and `SIGNPATH_SIGNING_POLICY_SLUG` are repository variables (non-sensitive).
- `input-artifact-path` and `output-artifact-path` are the same file — SignPath replaces it in-place.
- 10-minute timeout is generous for signing.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add conditional SignPath code signing for Windows installer"
```

---

### Task 4: End-to-end verification

- [ ] **Step 1: Review the full workflow file**

Read `.github/workflows/release.yml` and verify:
1. Windows matrix entry has `archive_ext: exe`
2. Inno Setup install step exists (Windows only)
3. Installer build step exists, passes version from tag
4. SignPath signing step exists with correct condition
5. Release job references `.exe` not `.zip` for Windows
6. macOS and Linux steps are untouched

- [ ] **Step 2: Verify installer.iss is correct**

Read `installer.iss` and verify:
1. `AppVersion` uses the `#ifndef` fallback pattern
2. `Source` points to `dist\GitStack\*`
3. Desktop icon task is `unchecked` by default
4. Architecture is `x64compatible`
5. `OutputBaseFilename` is `GitStack-windows-setup`

- [ ] **Step 3: Dry-run tag push (optional)**

If you want to test the full pipeline without a real release, create and push a test tag:

```bash
git tag v0.0.0-test
git push origin v0.0.0-test
```

Watch the GitHub Actions run. After verification, clean up:

```bash
git push origin --delete v0.0.0-test
git tag -d v0.0.0-test
```
