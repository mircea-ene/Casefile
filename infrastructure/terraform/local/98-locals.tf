locals {
  project_name = "local-infra"
  team_name    = "accelerise"
  environment  = "local"

  common_tags = {
    Project        = local.project_name
    Environment    = local.environment
    Deployment     = "terraform"
    DeploymentCICD = "yes"
    Team           = local.team_name
    DeployedBy     = "accelerise"
  }
}
