#!/usr/bin/env bash
# 薄包裝：等同 ./install.sh --uninstall
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh" --uninstall
