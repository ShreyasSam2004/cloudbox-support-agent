---
doc_id: release-notes-2026
title: Release Notes 2026
doc_type: release_notes
category: product
authority: official
effective_date: 2026-09-10
version: "2026.09"
audience: customer
url: https://docs.cloudbox.example/release-notes/2026
---

# Release Notes 2026

## 2026-09-10 — Webhooks v2

* New signature header `X-CloudBox-Signature-256` (HMAC-SHA256 over the raw body and timestamp).
* The v1 header `X-CloudBox-Signature` is deprecated and will be removed on 2027-03-01.
* Failed deliveries are retried up to 8 times over 24 hours with exponential backoff.

## 2026-07-01 — Higher API limits for Pro

* Pro rate limit raised from 600 to **1,000 requests per minute**.
* Pro monthly API quota is now **2,000,000** requests.
* New `X-Quota-Remaining` response header on all plans.

## 2026-05-15 — Bulk API generally available

* The Bulk API is generally available on Pro (5 concurrent jobs), Business (20 concurrent jobs) and Enterprise (custom).
* Bulk jobs have their own limits and do not consume the per-minute rate limit.

## 2026-04-01 — Longer version history on Pro

* Pro file version history increased from 90 days to **180 days**.

## 2026-03-01 — SSO add-on for Pro

* **SAML single sign-on is now available on the Pro plan as a paid add-on for $4 per user per month.** Previously SSO required the Business plan.
* Enable it in **Settings > Billing > Add-ons > SSO**, then configure your identity provider in **Admin Console > Security > SSO**.
* SCIM provisioning remains Business and Enterprise only.

## Coming later

* EU data residency for Business is planned for 2027. It is **not available yet**; today EU data residency is offered only on Enterprise contracts.
