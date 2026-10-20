---
doc_id: refund-policy
title: Refund Policy
doc_type: policy
category: billing
authority: official
effective_date: 2026-01-01
version: "3.0"
supersedes: "Refund Policy v2.4 (30-day money-back guarantee), retired 2025-12-31"
audience: customer
url: https://docs.cloudbox.example/billing/refund-policy
---

# Refund Policy

Version 3.0, effective 2026-01-01. This version replaces Refund Policy v2.4. **The former 30-day money-back guarantee was retired on 2025-12-31 and no longer applies to any purchase or renewal.**

## 1. Scope

This policy applies to self-serve Starter, Pro and Business subscriptions. **Enterprise subscriptions are governed by the customer's Master Subscription Agreement and the [Enterprise Subscription Addendum §5](enterprise-addendum.md#5-refunds-and-credits); sections 3 and 4 of this policy do not apply to Enterprise.** The Free plan has no charges.

## 2. Refunds that are always available

### 2.1 Duplicate charges

If you were charged twice for the same invoice, the duplicate amount is refunded in full. See [Billing Policy §5.2](billing-policy.md#52-true-duplicate-charges). Note that a *pending authorization hold* is not a charge and is not refunded — it is released by your bank (see [Billing Policy §5.1](billing-policy.md#51-pending-authorization-holds)).

### 2.2 Billing errors

If CloudBox charged an incorrect amount (for example the wrong plan price or seat count), the overcharge is refunded in full.

## 3. Monthly plans

### 3.1 General rule

Monthly subscription fees are **non-refundable**, including partially used months, except as described in section 2 and section 3.2. Cancelling a monthly plan stops future renewals; you keep access until the end of the period you paid for (see [Cancellation Policy](cancellation-policy.md)).

### 3.2 Charges after cancellation

If you cancelled **before** the renewal timestamp (00:00 UTC on the renewal date) and were still charged for the next billing period, the renewal charge was made in error and you are eligible for a **full refund** of that charge. The refund must be requested within **30 days** of the charge.

Cancellations are recorded in UTC. A cancellation submitted *after* 00:00 UTC on the renewal date applies from the following period: the renewal charge for the current period is valid and is not refunded.

## 4. Annual plans

### 4.1 First annual purchase

For your first purchase of an annual plan, you can request a **prorated refund for the unused full months** of the term within **30 days** of the purchase date. The month in progress is not refunded.

### 4.2 Annual renewals

An annual renewal charge is refunded in full if **both** conditions are met:

1. the refund is requested within **7 days** of the renewal charge, and
2. there has been **no usage since the renewal**. "Usage" means more than 100 API calls or any file upload after the renewal timestamp.

### 4.3 Otherwise

Outside these windows annual fees are non-refundable. You can turn off auto-renewal at any time to prevent the next renewal.

## 5. Plan downgrades

Downgrades take effect at the next renewal. No refunds or credits are issued for the remainder of the current period.

## 6. SLA service credits

Compensation for downtime is provided as **service credits** under the [Service Level Agreement](sla.md), not as refunds. Service credits are applied to future invoices and have no cash value.

## 7. How to request a refund

* The Owner or a Billing Admin can request a refund in **Settings > Billing > Invoices > Request refund**, or
* email billing@cloudbox.example with the invoice ID.

Approved refunds are issued to the original payment method within **5–10 business days**. Refunds in US dollars may be affected by your bank's exchange rate (see [Billing Policy §8](billing-policy.md#8-currency)).

## 8. Trial conversions

If a free trial converted to a paid plan because a payment method was on file, you can request a **full refund within 48 hours** of the first charge, provided there has been no usage after the conversion (as defined in §4.2). See the [Free Trial Policy](trial-policy.md).
