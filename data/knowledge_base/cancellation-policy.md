---
doc_id: cancellation-policy
title: Cancellation Policy
doc_type: policy
category: billing
authority: official
effective_date: 2026-01-01
version: "2.2"
audience: customer
url: https://docs.cloudbox.example/billing/cancellation-policy
---

# Cancellation Policy

## 1. Who can cancel

Only the account **Owner** or a **Billing Admin** can cancel a subscription. Go to **Settings > Billing > Plan > Cancel subscription** and confirm. Members and Admins without billing permissions cannot cancel.

## 2. When a cancellation takes effect

A cancellation takes effect at the **end of the current billing period**. Until then you keep full access to your plan, and no further renewals are charged. Every cancellation is recorded with a UTC timestamp, shown in **Settings > Billing > History**.

## 3. Annual plans

Cancelling an annual plan turns off auto-renewal. You keep access until the end of the annual term. Early termination of an annual plan is not refunded except as described in [Refund Policy §4](refund-policy.md#4-annual-plans).

## 4. Charged after cancelling

Compare your cancellation timestamp with the renewal timestamp (00:00 UTC on the renewal date):

* **Cancelled before the renewal timestamp, but charged anyway** — the renewal charge was made in error. You are eligible for a full refund of that charge under [Refund Policy §3.2](refund-policy.md#32-charges-after-cancellation). Request it within 30 days of the charge.
* **Cancelled after the renewal timestamp** — the renewal for the new period was valid. Your cancellation applies at the end of that new period and the charge is not refunded.

Remember that the renewal timestamp is in UTC: if you are in the Americas, the renewal happens on the evening *before* the renewal date in your local time.

## 5. Enterprise subscriptions

Enterprise subscriptions cannot be cancelled from the dashboard. Non-renewal requires **written notice at least 60 days before the end of the current term**, sent to your account manager. See [Enterprise Subscription Addendum §4](enterprise-addendum.md#4-cancellation-and-non-renewal).

## 6. What happens to your data

When the cancellation takes effect, the account is moved to the Free plan. Files that exceed Free plan limits stay **read-only** for a grace period and are then permanently deleted — 30 days for Starter and Pro, 90 days for Business. Export your data before the grace period ends. Details: [Data Retention Policy §5](data-retention.md#5-after-cancellation).

## 7. Reactivation

You can reactivate within the grace period from **Settings > Billing > Plan**. Your files, settings and users are restored as they were.

## 8. Cancelling a free trial

Cancelling during a free trial takes effect immediately and no charge is made. See the [Free Trial Policy](trial-policy.md).
