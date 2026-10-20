# Security Policy

## Reporting a vulnerability

Please report security issues privately to **security@cloudbox.example** (fictional company — for this
repository, open a private security advisory on GitHub). Do not open public issues for vulnerabilities.
Include reproduction steps, affected component and impact. We aim to acknowledge reports within two
business days.

## Supported versions

Only the latest `main` is supported.

## Security model (summary)

* The language model is **not** trusted as a security boundary. Authorization, input validation, rate
  limiting and output validation are enforced in code. See [docs/security.md](docs/security.md).
* Retrieved documents and web pages are treated as untrusted data and can never change instructions,
  permissions or tool access.
* No secrets are stored in this repository, in CI configuration or in Terraform state. Azure access uses
  managed identities and GitHub OIDC; the Anthropic/OpenAI API keys and other third-party keys live in Key Vault.
* Production refuses to start with demo-grade settings (unauthenticated mode, unverified customer
  lookups, test doubles, in-memory stores, local models).

## Automated checks

Every pull request runs: Ruff (incl. Bandit rules), mypy, tests, pip-audit, npm audit, gitleaks,
CodeQL, Trivy image scanning (blocking on fixable HIGH/CRITICAL), Trivy IaC scanning and TFLint.
Dependabot keeps Python, npm, Docker, GitHub Actions and Terraform dependencies current.
