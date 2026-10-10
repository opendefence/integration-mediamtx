#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cluster_name="mediamtx-$(printf '%s' "$repo_root" | shasum -a 256 | cut -c 1-12)"
state_dir="$repo_root/.local/kind"
export KIND_EXPERIMENTAL_PROVIDER=podman

# shortcut: lifecycle commands run serially; add a lock if automated callers overlap.
case "${1:-}" in
  up)
    clusters=$(kind get clusters)
    if printf '%s\n' "$clusters" | grep -Fxq "$cluster_name"; then
      echo "Cluster $cluster_name already exists. Refusing to adopt it." >&2
      exit 1
    fi
    mkdir -p "$repo_root/.local"
    mkdir "$state_dir"
    printf '%s\n' "$cluster_name" > "$state_dir/owner"
    kind create cluster --name "$cluster_name" --kubeconfig "$state_dir/kubeconfig" \
      --config "$repo_root/deploy/kind.yaml" --wait 180s
    echo "Use kubectl --kubeconfig $state_dir/kubeconfig --context kind-$cluster_name"
    ;;
  load|down)
    if [[ ! -f "$state_dir/owner" ]] || [[ $(cat "$state_dir/owner") != "$cluster_name" ]]; then
      echo "No owned cluster for this checkout. Refusing operation." >&2
      exit 1
    fi
    if [[ $1 == load ]]; then
      [[ -f "${2:-}" ]] || { echo "Pass an image archive file." >&2; exit 1; }
      kind load image-archive "$2" --name "$cluster_name"
    else
      kind delete cluster --name "$cluster_name" --kubeconfig "$state_dir/kubeconfig"
      rm -f "$state_dir/owner" "$state_dir/kubeconfig"
      rmdir "$state_dir"
    fi
    ;;
  *)
    echo "Usage: bash scripts/kind.sh {up|load ARCHIVE|down}" >&2
    exit 2
    ;;
esac
