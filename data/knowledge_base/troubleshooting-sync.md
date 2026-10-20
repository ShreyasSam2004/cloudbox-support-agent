---
doc_id: troubleshooting-sync
title: Desktop Sync Troubleshooting Guide
doc_type: guide
category: troubleshooting
authority: official
effective_date: 2026-06-15
version: "5.0"
audience: customer
url: https://docs.cloudbox.example/desktop/troubleshooting
---

# Desktop Sync Troubleshooting Guide

This guide covers the CloudBox desktop app for Windows (10 and 11) and macOS (13 or later).

## 1. Understanding sync status

| Icon | Status | Meaning |
|---|---|---|
| Green check | Up to date | All files are synced |
| Blue arrows | Syncing | Changes are uploading or downloading |
| Grey pause | Paused | Sync paused by the user or by battery saver |
| Red cross | Error | At least one file cannot sync; click the icon for details |
| Yellow triangle | Attention | Conflicts or skipped files need review |

## 2. Sync is stuck on "Preparing" or "Indexing"

### 2.1 Very large folders

Initial indexing of more than 500,000 files can take several hours. Use selective sync (section 5) to exclude folders you do not need locally.

### 2.2 Antivirus and endpoint security

Some endpoint-security products lock files while scanning them, which stalls indexing. Add the CloudBox folder and the `CloudBox.exe` / `CloudBox.app` process to your security product's exclusion list.

### 2.3 Restarting the sync engine

Quit CloudBox from the system tray / menu bar and start it again. If indexing still does not progress, reset the sync engine (section 8).

## 3. Conflicted copies

When the same file is changed on two devices before they sync, CloudBox keeps both versions. The second one is saved as `filename (conflicted copy YYYY-MM-DD).ext` next to the original. Compare the files, keep the one you want, and delete the other. Version history (see [Data Retention Policy §1](data-retention.md#1-file-version-history)) also lets you restore earlier versions.

## 4. Unsupported file names and paths

Files with unsupported names are skipped and shown under **Attention > Skipped files**. Uploading them through the API fails with `400 invalid_path` (CBX-4002).

### 4.1 Characters

The following characters are not allowed in file or folder names: `< > : " / \ | ? *`. Names cannot end with a space or a period.

### 4.2 Path length on Windows

By default Windows limits full paths to **260 characters** (`MAX_PATH`). Files whose full local path exceeds this limit are skipped. Either shorten folder names, move the CloudBox folder closer to the drive root (for example `C:\CloudBox`), or enable Windows long-path support. Enabling long paths is a Windows setting managed by your administrator; CloudBox desktop 5.0 and later honour it automatically.

### 4.3 Reserved names on Windows

Names such as `CON`, `PRN`, `AUX`, `NUL`, `COM1` and `LPT1` cannot be used on Windows.

## 5. Selective sync

**Preferences > Sync > Choose folders** lets you keep folders online-only. Online-only files still appear in the file browser and download on demand.

## 6. Proxies, firewalls and TLS inspection

The desktop app connects over HTTPS (TCP port 443) to the following domains, which must be allowed by your firewall or proxy:

* `*.cloudbox.example`
* `*.cloudbox-cdn.example`

CloudBox uses certificate pinning for its sync endpoints. **Proxies that perform TLS inspection (SSL decryption) break sync**; ask your network team to exclude the domains above from TLS inspection. Authenticated proxies are supported via **Preferences > Network > Proxy**.

## 7. Collecting logs for support

* Windows: `%LOCALAPPDATA%\CloudBox\logs`
* macOS: `~/Library/Logs/CloudBox`

Use **Help > Send diagnostics** to upload logs directly; you will receive a diagnostics ID to share with support.

## 8. Resetting the sync engine

Run `cloudbox-desktop --reset-sync`. This keeps your local files but rebuilds the sync index, which can take a while for large folders. Do not delete the CloudBox folder manually.
