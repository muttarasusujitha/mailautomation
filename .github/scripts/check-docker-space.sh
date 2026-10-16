#!/usr/bin/env bash
set -euo pipefail
# Space is needed for both the compressed download and expanded image layers.
minimum_gib="${MIN_DOCKER_FREE_GIB:-15}"
minimum_inodes="${MIN_DOCKER_FREE_INODES:-50000}"
[[ "$minimum_gib" =~ ^[1-9][0-9]*$ && "$minimum_inodes" =~ ^[1-9][0-9]*$ ]] || {
  echo "Disk thresholds must be positive integers." >&2
  exit 1
}

# Reclaim only unused Docker build cache and images before checking capacity.
# Docker will preserve images referenced by containers; never prune containers or volumes.
echo "Pruning unused Docker build cache and images before checking free space..."
docker builder prune -af
docker image prune -af

docker_root="$(docker info --format '{{.DockerRootDir}}')"
paths=("$docker_root")
# Docker's containerd image store may live outside DockerRootDir.
if [[ -d /var/lib/containerd ]]; then
  paths+=(/var/lib/containerd)
fi
for path in "${paths[@]}"; do
  if [[ ! -d "$path" ]]; then
    echo "::error::Cannot inspect Docker storage at $path on this runner. Check the Docker host directly."
    exit 1
  fi
  available_kib="$(df -Pk "$path" | awk 'NR==2 {print $4}')"
  available_inodes="$(df -Pi "$path" | awk 'NR==2 {print $4}')"
  df -h "$path"
  if (( available_kib < minimum_gib * 1024 * 1024 || available_inodes < minimum_inodes )); then
    echo "::error::Insufficient Docker storage at $path: need at least ${minimum_gib} GiB and ${minimum_inodes} free inodes after pruning unused images/cache. Expand the host disk/filesystem or review Docker storage usage. No containers or volumes have been removed."
    exit 1
  fi
done
