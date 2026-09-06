#!/usr/bin/env bash
# setup_mac.sh — give a Mac (Apple Silicon or Intel) a Docker engine for Infrahub, with no Docker Desktop.
# Uses Colima (lightweight Linux VM + Docker daemon) via Homebrew. No admin password needed.
# Run once:   ./setup_mac.sh        then:   ./demo.sh
set -euo pipefail
step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

step "0/4  machine"
MEM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
CPUS=$(sysctl -n hw.ncpu)
echo "$(hostname)  $(sysctl -n machdep.cpu.brand_string)  ${CPUS} cpu  ${MEM_GB} GB  $(sw_vers -productVersion)"
if   [ "$MEM_GB" -ge 24 ]; then VM_MEM=10
elif [ "$MEM_GB" -ge 16 ]; then VM_MEM=8
elif [ "$MEM_GB" -ge 12 ]; then VM_MEM=6
else VM_MEM=5; echo "!! only ${MEM_GB} GB on this Mac — Infrahub will be tight next to NOCternal. Giving the VM ${VM_MEM} GB; expect slow first boot."; fi
VM_CPU=$(( CPUS >= 8 ? 4 : CPUS >= 4 ? 3 : 2 ))

step "1/4  Homebrew"
if ! command -v brew >/dev/null; then
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew "$HOME/.homebrew/bin/brew"; do [ -x "$p" ] && eval "$("$p" shellenv)" && break; done
fi
command -v brew >/dev/null || die "Homebrew not found. Install it from https://brew.sh (needs your admin password once), then re-run."
echo "brew: $(command -v brew)"

step "2/4  colima + docker CLI + compose plugin"
brew list colima >/dev/null 2>&1 || brew install colima
brew list docker >/dev/null 2>&1 || brew install docker
brew list docker-compose >/dev/null 2>&1 || brew install docker-compose
mkdir -p "$HOME/.docker/cli-plugins"
ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" "$HOME/.docker/cli-plugins/docker-compose"

step "3/4  start the VM (${VM_CPU} cpu / ${VM_MEM} GB / 40 GB disk)"
if colima status >/dev/null 2>&1; then
  echo "colima already running"
else
  colima start --cpu "$VM_CPU" --memory "$VM_MEM" --disk 40 --vm-type=vz --vz-rosetta 2>/dev/null \
  || colima start --cpu "$VM_CPU" --memory "$VM_MEM" --disk 40
fi
docker context use colima >/dev/null 2>&1 || true

step "4/4  verify"
docker info --format 'engine {{.ServerVersion}}   cpus {{.NCPU}}   mem {{.MemTotal}}' || die "docker cannot reach the colima daemon"
docker compose version
echo
echo "Docker is up. Next:   ./demo.sh"
echo "Autostart on login:   brew services start colima"
