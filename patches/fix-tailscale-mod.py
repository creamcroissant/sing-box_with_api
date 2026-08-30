#!/usr/bin/env python3
"""
Patch tailscale vendored go-json-experiment for Go 1.24+ compatibility.

Replaces reflect.TypeAssert[T](v) with v.Interface().(T).

Usage:
  python3 fix-tailscale-mod.py                    # patch in GOMODCACHE
  python3 fix-tailscale-mod.py --vendor-dir vendor # patch in vendor dir

Must be run after 'go mod vendor' in the sing-box source dir.
"""

import glob
import argparse
import os
import subprocess
import sys

TYPEASSERT_LEN = len("reflect.TypeAssert[")


def find_json_in_vendor(vendor_dir):
    """Find go-json-experiment inside vendor directory."""
    # vendor/github.com/sagernet/tailscale/internal/godown/...
    pattern = os.path.join(vendor_dir,
        "github.com/sagernet", "tailscale*",
        "internal", "godown", "github.com", "go-json-experiment", "json")
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    return None


def find_json_in_gomodcache():
    """Find go-json-experiment in GOMODCACHE."""
    try:
        result = subprocess.run(
            ["go", "env", "GOMODCACHE"],
            capture_output=True, text=True, timeout=10
        )
        gomodcache = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        gomodcache = None

    if not gomodcache:
        gomodcache = os.path.join(os.environ.get("HOME", "/root"), "go", "pkg", "mod")

    # Exact path
    candidate = os.path.join(gomodcache,
        "github.com/sagernet/tailscale@v1.92.4-sing-box-1.13-mod.10",
        "internal/godown/github.com/go-json-experiment/json")
    if os.path.isdir(candidate):
        return candidate

    # Wildcard search
    base = os.path.join(gomodcache, "github.com/sagernet")
    if os.path.isdir(base):
        for entry in os.listdir(base):
            if entry.startswith("tailscale@") and "mod.10" in entry:
                candidate = os.path.join(base, entry,
                    "internal/godown/github.com/go-json-experiment/json")
                if os.path.isdir(candidate):
                    return candidate
    return None


def patch_file(fpath):
    with open(fpath, 'r') as f:
        content = f.read()

    if "reflect.TypeAssert" not in content:
        return False

    result = []
    i = 0
    while i < len(content):
        pos = content.find("reflect.TypeAssert[", i)
        if pos == -1:
            result.append(content[i:])
            break

        result.append(content[i:pos])

        type_start = pos + TYPEASSERT_LEN
        type_end = content.index("]", type_start)
        type_name = content[type_start:type_end]

        arg_open = type_end + 1
        if arg_open < len(content) and content[arg_open] == '(':
            paren = 1
            j = arg_open + 1
            while j < len(content) and paren > 0:
                if content[j] == '(':
                    paren += 1
                elif content[j] == ')':
                    paren -= 1
                if paren > 0:
                    j += 1
            argument = content[arg_open + 1:j]
            replacement = f"{argument}.Interface().({type_name})"
            result.append(replacement)
            i = j + 1
        else:
            result.append(content[pos:type_end + 1])
            i = type_end + 1

    new_content = "".join(result)
    if new_content != content:
        with open(fpath, 'w') as f:
            f.write(new_content)
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-dir", help="path to vendor directory")
    args = parser.parse_args()

    if args.vendor_dir:
        json_dir = find_json_in_vendor(args.vendor_dir)
        if not json_dir:
            print(f"ERROR: go-json-experiment not found under vendor/", file=sys.stderr)
            return 1
    else:
        json_dir = find_json_in_gomodcache()
        if not json_dir:
            print("ERROR: go-json-experiment not found in module cache", file=sys.stderr)
            return 1

    print(f"Patching: {json_dir}")

    patched = 0
    for fpath in glob.glob(os.path.join(json_dir, "*.go")):
        if patch_file(fpath):
            print(f"  Patched: {os.path.basename(fpath)}")
            patched += 1

    remaining = 0
    for fpath in glob.glob(os.path.join(json_dir, "*.go")):
        with open(fpath, 'r') as f:
            if "reflect.TypeAssert" in f.read():
                remaining += 1
                print(f"  WARNING: {os.path.basename(fpath)} still has TypeAssert", file=sys.stderr)

    print(f"Patched {patched} files, {remaining} remaining")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())