---
doc_id: plans-and-pricing
title: CloudBox Plans and Pricing
doc_type: policy
category: billing
authority: official
effective_date: 2026-07-01
version: "2026.3"
audience: customer
url: https://docs.cloudbox.example/billing/plans-and-pricing
---

# CloudBox Plans and Pricing

CloudBox offers five subscription tiers. Self-serve plans (Free, Starter, Pro, Business) can be purchased and changed in **Settings > Billing > Plan**. Enterprise is sold under a signed agreement; see the [Enterprise Subscription Addendum](enterprise-addendum.md).

All prices are in US dollars and exclude applicable taxes (see [Billing Policy §6](billing-policy.md#6-taxes)).

## 1. Plan comparison

| Feature | Free | Starter | Pro | Business | Enterprise |
|---|---|---|---|---|---|
| Price, monthly billing | $0 | $15 / month | $49 / month | $29 / user / month (min. 5 users) | Custom (annual contract) |
| Price, annual billing | $0 | $144 / year ($12 / month) | $468 / year ($39 / month) | $24 / user / month, billed annually | Custom |
| Users included | 1 | Up to 3 | Up to 10 | 5 or more | Custom |
| Storage | 5 GB | 500 GB | 2 TB | 5 TB per user (pooled) | Custom |
| Maximum single file upload | 250 MB | 2 GB | 10 GB | 50 GB | 100 GB |
| API rate limit | 60 requests / min | 300 requests / min | 1,000 requests / min | 3,000 requests / min | Custom (from 10,000 / min) |
| Monthly API request quota | 10,000 | 250,000 | 2,000,000 | 10,000,000 | Custom |
| File version history | 30 days | 90 days | 180 days | 1 year | Custom (up to 10 years) |
| SAML single sign-on (SSO) | Not available | Not available | Paid add-on, $4 / user / month ¹ | Included | Included |
| SCIM user provisioning | Not available | Not available | Not available | Included | Included |
| Audit logs | Not available | Not available | Not available | Included (1-year retention) | Included (custom retention) |
| Webhook endpoints | Not available | 2 | 10 | Unlimited | Unlimited |
| Bulk API | Not available | Not available | Yes (5 concurrent jobs) | Yes (20 concurrent jobs) | Yes (custom) |
| Uptime SLA with service credits | No | No | No ² | 99.9% | 99.95% |
| Support | Community forum | Email | Email and chat | Priority (24/5, phone) | 24/7 with dedicated CSM |

¹ The SSO add-on for Pro has been available since 2026-03-01. Before that date SSO required Business or Enterprise. See [Release Notes 2026](release-notes-2026.md).
² Pro has an internal availability target of 99.5% but no contractual SLA and no service credits. See the [Service Level Agreement](sla.md).

## 2. Add-ons

| Add-on | Available on | Price |
|---|---|---|
| SSO (SAML 2.0) | Pro | $4 / user / month |
| Extra API quota (+1,000,000 requests in the current billing period) | Pro, Business | $20 per block |
| Additional storage (+1 TB) | Starter, Pro | $10 / month |
| EU data residency | Enterprise only | Contract |
| Customer-managed encryption keys (BYOK) | Enterprise only | Contract |

Extra API quota blocks apply only to the billing period in which they are purchased and do not roll over.

## 3. Changing plans

### 3.1 Upgrades

Upgrades take effect immediately. You are charged a prorated amount for the remainder of the current billing period (see [Billing Policy §3](billing-policy.md#3-proration)).

### 3.2 Downgrades

Downgrades take effect at the next renewal date. No credit or refund is issued for the remainder of the current period (see [Refund Policy §5](refund-policy.md#5-plan-downgrades)). If your usage exceeds the limits of the lower plan when the downgrade takes effect, the excess data becomes read-only until you are within limits.

### 3.3 Switching between monthly and annual billing

You can switch from monthly to annual billing at any time; the annual term starts immediately and the unused part of the current month is credited. Switching from annual to monthly takes effect at the end of the annual term.

## 4. Discounts

Verified non-profit organizations receive 30% off Pro and Business **annual** plans. Discounts are applied by the sales team after verification and are not available on monthly billing. No other standing discounts (for example student or education pricing) are offered on self-serve plans.
