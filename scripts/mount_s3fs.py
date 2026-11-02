#!/usr/bin/env python3
import subprocess
import os
import sys

def mount_s3fs(bucket_name, mount_point, passwd_file=".passwd-s3fs"):
    """Mount OVH Cloud S3 storage using s3fs"""
    
    # Create mount point if it doesn't exist
    os.makedirs(mount_point, exist_ok=True)
    
    # S3FS command for OVH Cloud
    cmd = [
        "s3fs", bucket_name, mount_point,
        "-o", f"passwd_file={passwd_file}",
        "-o", "url=https://s3.gra.cloud.ovh.net",
        "-o", "use_path_request_style"
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Successfully mounted {bucket_name} to {mount_point}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Mount failed: {e.stderr}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 mount_s3fs.py <bucket_name> <mount_point>")
        sys.exit(1)
    
    bucket = sys.argv[1]
    mount_point = sys.argv[2]
    mount_s3fs(bucket, mount_point)
