# State is kept locally: Floci is an ephemeral emulator, so there is no point
# storing its state in a shared remote bucket.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
