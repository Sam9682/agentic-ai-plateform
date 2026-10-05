terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.54.0"
    }
  }
}

variable "ovh_project_id" {
  description = "OVH Project ID"
  type        = string
}

variable "ovh_username" {
  description = "OVH Username"
  type        = string
}

variable "ovh_password" {
  description = "OVH Password"
  type        = string
  sensitive   = true
}

provider "openstack" {
  auth_url          = "https://auth.cloud.ovh.net/v3/"
  region            = "GRA11"
  tenant_id         = var.ovh_project_id
  user_name         = var.ovh_username
  password          = var.ovh_password
  user_domain_name  = "Default"
}

resource "openstack_compute_keypair_v2" "MainSSHSamKey" {
  name       = "MainSSHSamKey"
  public_key = file("~/.ssh/MainSSHSamKey.pub")  # Path to your public key
}

resource "openstack_compute_instance_v2" "softfluid_second" {
  name            = "softfluid-second"
  flavor_name     = "b2-14"
  image_name      = "Ubuntu 25.04"
  key_pair        = openstack_compute_keypair_v2.MainSSHSamKey.name

  network {
    name = "Ext-Net"
  }

  network {
    name = "SamNetwork"
  }

  metadata = {
    managed_by = "terraform"
  }
}

output "instance_ipv4" {
  value = openstack_compute_instance_v2.softfluid_main.access_ip_v4
}

output "instance_ipv6" {
  value = openstack_compute_instance_v2.softfluid_main.access_ip_v6
}
