---
doc_id: account-security
title: Account Security
doc_type: policy
category: security
authority: official
effective_date: 2026-02-01
version: "3.1"
audience: customer
url: https://docs.cloudbox.example/security/account-security
---

# Account Security

## 1. Two-factor authentication (2FA)

CloudBox supports authenticator apps (TOTP) and security keys (WebAuthn/passkeys). 2FA is optional on Free, Starter and Pro, and **required for Owners and Admins on Business and Enterprise**. Recovery codes are shown once when 2FA is enabled; store them safely.

## 2. Single sign-on (SSO)

Organizations with SAML SSO (Business and Enterprise, or Pro with the SSO add-on) can enforce SSO for all members. When SSO is enforced, passwords are disabled and sign-in, password and lockout policies are controlled by the organization's identity provider.

## 3. Account lockout

### 3.1 Temporary lockout

After **5 consecutive failed sign-in attempts**, the account is locked for **30 minutes** and then unlocks automatically. The user receives an email notification.

### 3.2 Repeated lockouts require verification

If an account is locked **3 times within 24 hours**, it no longer unlocks automatically. To unlock it, the user must:

1. use **Forgot password** on the sign-in page to reset the password via the emailed link (valid for 1 hour), and
2. complete two-factor authentication, if 2FA is enabled.

If the user can no longer access their email account, they must contact support and complete **identity verification**. Support agents cannot unlock accounts over chat or email without verification.

### 3.3 Admin unlock

Owners and Admins can unlock member accounts in **Admin Console > Users > Unlock account**. Admins cannot unlock the Owner account; the Owner follows section 3.2.

### 3.4 SSO-enforced organizations

When SSO is enforced, lockouts are managed by your identity provider. CloudBox cannot unlock these accounts — contact your IT administrator.

### 3.5 Effect on the API

API keys owned by a locked user stop working until the account is unlocked; requests fail with `403 account_locked` (CBX-4032).

## 4. Suspicious activity

If CloudBox detects sign-ins from unusual locations or impossible travel, it revokes active sessions, requires a password reset and notifies the Owner.

## 5. Sessions

Web sessions expire after 14 days of inactivity. Business and Enterprise admins can set a custom idle timeout between 1 and 30 days.

## 6. Reporting a security issue

Report vulnerabilities to security@cloudbox.example. CloudBox will never ask for your password, recovery codes or full API keys by email, chat or phone.
