variable "aws_region" {
  description = "Region used inside the Floci emulator."
  type        = string
  default     = "us-east-1"
}

variable "floci_endpoint" {
  description = "URL of the local Floci AWS emulator."
  type        = string
  default     = "http://localhost:4566"
}
