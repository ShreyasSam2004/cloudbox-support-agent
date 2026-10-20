---
doc_id: account-management
title: Account and Organization Management
doc_type: guide
category: account
authority: official
effective_date: 2026-01-15
version: "2.0"
audience: customer
url: https://docs.cloudbox.example/admin/account-management
---

# Account and Organization Management

## 1. Organizations and users

Every CloudBox subscription belongs to an organization. Users are invited by email from **Admin Console > Users > Invite**. Each user occupies one seat.

## 2. Roles and permissions

| Permission | Owner | Admin | Billing Admin | Member | Viewer |
|---|---|---|---|---|---|
| Manage files they have access to | Yes | Yes | Yes | Yes | View only |
| Invite and remove users | Yes | Yes | No | No | No |
| Unlock member accounts | Yes | Yes | No | No | No |
| Create organization API keys | Yes | Yes | No | No | No |
| View invoices, change payment method | Yes | No | Yes | No | No |
| Change plan, cancel subscription, request refunds | Yes | No | Yes | No | No |
| Delete the organization | Yes | No | No | No | No |

There is exactly one Owner per organization.

## 3. Transferring ownership

The current Owner can transfer ownership to an existing Admin in **Admin Console > Organization > Transfer ownership**. The new Owner must accept within 7 days. If the Owner has left the company and cannot be reached, contact support with proof of authority (for example a letter on company letterhead signed by an officer).

## 4. Changing your email address

Change your email in **Profile > Email**. A verification link is sent to the new address and the change takes effect once it is confirmed. SSO-managed users change their email in the identity provider.

## 5. Adding and removing seats

Admins add seats by inviting users; Business seats are prorated (see [Billing Policy §3](billing-policy.md#3-proration)). Removing a user frees the seat but does not reduce the bill until the next renewal.

## 6. Deleting an organization

The Owner can delete the organization in **Admin Console > Organization > Delete**. The subscription is cancelled immediately and data is deleted as described in [Data Retention Policy §6](data-retention.md#6-account-deletion).
