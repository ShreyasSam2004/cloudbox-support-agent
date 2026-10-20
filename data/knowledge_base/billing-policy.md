---
doc_id: billing-policy
title: Billing Policy
doc_type: policy
category: billing
authority: official
effective_date: 2026-01-01
version: "4.1"
audience: customer
url: https://docs.cloudbox.example/billing/billing-policy
---

# Billing Policy

This policy explains how CloudBox bills self-serve subscriptions (Starter, Pro, Business). Enterprise invoicing follows the [Enterprise Subscription Addendum](enterprise-addendum.md).

## 1. Billing cycles

* **Monthly plans** renew automatically on the same calendar day each month. The renewal charge is attempted at **00:00 UTC** on the renewal date.
* **Annual plans** are billed upfront for the full 12-month term and renew automatically at 00:00 UTC on the anniversary date unless auto-renewal is turned off.
* All times on invoices and in the billing dashboard are shown in UTC.

## 2. Payment methods

CloudBox accepts Visa, Mastercard and American Express credit or debit cards. Annual plans with a total value of $5,000 or more may also be paid by ACH transfer or wire against an invoice. Other payment methods are not accepted.

To update your payment method, go to **Settings > Billing > Payment method**. Only the **Owner** or a **Billing Admin** can change billing details (see [Account Management §2](account-management.md#2-roles-and-permissions)).

## 3. Proration

Upgrades and added seats are prorated to the day and charged immediately. Downgrades and removed seats take effect at the next renewal; no credit is issued for the current period.

## 4. Failed payments

If a renewal payment fails, the subscription enters the `past_due` state and CloudBox retries the payment automatically:

| Retry | When |
|---|---|
| Retry 1 | 3 days after the failed charge |
| Retry 2 | 7 days after the failed charge |
| Retry 3 (final) | 14 days after the failed charge |

You keep full access while the account is `past_due`. Updating the payment method triggers an immediate retry. If the final retry fails, the account is **suspended**: files become read-only for 30 days and are then deleted according to the [Data Retention Policy §4](data-retention.md#4-suspended-accounts). API requests from a suspended account return `403 account_suspended` (CBX-4033).

## 5. Duplicate or unexpected charges

### 5.1 Pending authorization holds

When you add or change a card, upgrade, or add seats, CloudBox may place a temporary **authorization hold** on the card to verify it — either $1 or the amount of the upcoming charge. A hold appears on your bank statement as **pending** and is not a charge: it is released automatically by your bank, usually within **3–5 business days**. CloudBox cannot release holds faster; your card issuer controls the timing.

A pending hold and the real charge for the same amount often appear side by side and look like a double charge. Only settled (posted) charges are billed.

### 5.2 True duplicate charges

A true duplicate is two *settled* charges for the same invoice. CloudBox's billing system detects duplicates and refunds them automatically within **7 days**. If a duplicate has not been refunded after 7 days, contact billing support at billing@cloudbox.example with the invoice ID; duplicate charges are always refunded in full (see [Refund Policy §2.1](refund-policy.md#21-duplicate-charges)).

### 5.3 Charges after cancellation

If you were charged after cancelling, see [Cancellation Policy §4](cancellation-policy.md#4-charged-after-cancelling) and [Refund Policy §3.2](refund-policy.md#32-charges-after-cancellation).

## 6. Taxes

Prices exclude VAT, GST and US sales tax. Taxes are calculated from the billing address and shown on each invoice. Tax-exempt organizations can upload an exemption certificate in **Settings > Billing > Tax**.

## 7. Invoices and receipts

Invoices are available in **Settings > Billing > Invoices** and are emailed to the billing contact. Each invoice has an ID in the format `INV-<customer>-<number>`. Invoices cannot be edited after issue; corrected invoices are issued as credit notes.

## 8. Currency

All charges are in US dollars. Currency conversion or foreign transaction fees charged by your bank are not controlled by CloudBox and are not refundable.

## 9. Chargebacks

Please contact billing support before disputing a charge with your bank. Filing a chargeback suspends the account until the dispute is resolved.
