# Non-secret configuration only. subscription_id is passed by CI (TF_VAR_subscription_id).
resource_group_name = "rg-cloudbox-staging"
alert_emails        = []
# Identity provider (Entra ID / Entra External ID) issuing customer tokens with a `customer_id` claim.
jwt_jwks_url = "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/discovery/v2.0/keys"
jwt_issuer   = "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/v2.0"
jwt_audience = "api://cloudbox-support"
