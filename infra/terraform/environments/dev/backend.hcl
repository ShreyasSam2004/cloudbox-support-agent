# Non-secret backend settings (output of the bootstrap stack). Authentication uses Entra ID (OIDC in CI).
resource_group_name  = "rg-cloudbox-tfstate"
storage_account_name = "stcbxtfstateta6zdk"
container_name       = "tfstate"
key                  = "dev.terraform.tfstate"
use_azuread_auth     = true
use_oidc             = true
