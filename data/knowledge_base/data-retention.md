---
doc_id: data-retention
title: Data Retention Policy
doc_type: policy
category: data
authority: official
effective_date: 2026-04-01
version: "2.3"
audience: customer
url: https://docs.cloudbox.example/legal/data-retention
---

# Data Retention Policy

## 1. File version history

| Plan | Versions kept for |
|---|---|
| Free | 30 days |
| Starter | 90 days |
| Pro | 180 days (90 days before 2026-04-01) |
| Business | 1 year |
| Enterprise | Custom, up to 10 years |

Restore a version from the file's **⋯ > Version history** menu.

## 2. Deleted files (trash)

Deleted files stay in the trash for **30 days on Free and Starter** and **90 days on Pro, Business and Enterprise**. After that they are permanently deleted and cannot be restored by support.

## 3. Backups

CloudBox keeps encrypted infrastructure backups for 35 days for disaster recovery. Backups are not used to restore individual files or accounts.

## 4. Suspended accounts

Accounts suspended for non-payment (see [Billing Policy §4](billing-policy.md#4-failed-payments)) are read-only for **30 days**. If payment is not resolved, all files are then permanently deleted.

## 5. After cancellation

When a cancelled subscription ends, the organization moves to the Free plan. Files beyond Free plan limits are read-only during a grace period and then permanently deleted:

| Plan at cancellation | Read-only grace period |
|---|---|
| Starter, Pro | 30 days |
| Business | 90 days |
| Enterprise | As specified in the contract (default 90 days) |

## 6. Account deletion

Deleting an organization or a personal account starts a **30-day** soft-delete period during which the Owner can ask support to restore it. After 30 days all data is permanently deleted. Deletion requests under GDPR Article 17 are completed within 30 days.

## 7. Exporting your data

Export all files from **Settings > Data > Export** (ZIP archive emailed as a download link, valid 7 days) or with the API.

## 8. Logs

Audit logs are kept for 1 year on Business and as contracted on Enterprise. Access logs used for security monitoring are kept for 90 days.
