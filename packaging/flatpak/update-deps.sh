#!/bin/sh
# Regenerate python-deps.json: the exact wheels (URL + SHA-256) the Flatpak
# installs, for the Freedesktop 24.08 runtime's Python 3.12 on x86_64.
set -eu
cd "$(dirname "$0")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
deps="$(python3 -c 'import tomllib;print(" ".join(tomllib.load(open("../../pyproject.toml","rb"))["project"]["dependencies"]))')"
# shellcheck disable=SC2086
python3 -m pip install --dry-run --ignore-installed --quiet --only-binary=:all: \
    --python-version 3.12 --implementation cp --abi cp312 --abi abi3 --abi none \
    --platform manylinux_2_39_x86_64 --platform manylinux_2_34_x86_64 --platform manylinux_2_28_x86_64 \
    --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_12_x86_64 \
    --platform manylinux2010_x86_64 --platform linux_x86_64 --platform any \
    --target "$tmp/t" --report "$tmp/report.json" $deps
python3 - "$tmp/report.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
srcs, names = [], []
for i in r["install"]:
    di = i["download_info"]
    ai = di.get("archive_info", {})
    sha = ai.get("hashes", {}).get("sha256") or ai["hash"].split("=", 1)[1]
    srcs.append({"type": "file", "url": di["url"], "sha256": sha})
    names.append(i["metadata"]["name"])
mod = {"name": "python-deps", "buildsystem": "simple",
       "build-commands": ['pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}" '
                          "--prefix=${FLATPAK_DEST} --no-build-isolation " + " ".join(sorted(names))],
       "sources": srcs}
json.dump(mod, open("python-deps.json", "w"), indent=2)
print(f"python-deps.json: {len(srcs)} wheels")
EOF
