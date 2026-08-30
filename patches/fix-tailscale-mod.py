#!/usr/bin/env python3
"""
Patch tailscale vendored go-json-experiment for Go 1.24+ compatibility.

Replaces reflect.TypeAssert[T](v) with v.Interface().(T) in the
Go module cache.

Must be run in the sing-box source dir AFTER 'go mod download'.
"""

import glob
import os
import subprocess
import sys

TYPEASSERT_LEN = len("reflect.TypeAssert[")


def get_gomodcache():
    """Get GOMODCACHE from go env, with fallback."""
    try:
        result = subprocess.run(
            ["go", "env", "GOMODCACHE"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"Warning: go env GOMODCACHE failed ({e})", file=sys.stderr)

    home = os.environ.get("HOME", "/root")
    fallback = os.path.join(home, "go", "pkg", "mod")
    print(f"Falling back to {fallback}", file=sys.stderr)
    return fallback


def find_json_dir(gomodcache):
    """Find the go-json-experiment dir inside tailscale module."""
    ts_module = "github.com/sagernet/tailscale@v1.92.4-sing-box-1.13-mod.10"
    candidate = os.path.join(gomodcache, ts_module,
        "internal/godown/github.com/go-json-experiment/json")
    if os.path.isdir(candidate):
        return candidate

    # Search with version suffixes
    base = os.path.join(gomodcache, "github.com/sagernet")
    if not os.path.isdir(base):
        return None

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

        # Type name starts after the opening [
        type_start = pos + TYPEASSERT_LEN
        type_end = content.index("]", type_start)
        type_name = content[type_start:type_end]

        # Argument starts at type_end + 1 (the '(' after ']')
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
    gomodcache = get_gomodcache()
    print(f"GOMODCACHE: {gomodcache}")

    json_dir = find_json_dir(gomodcache)
    if not json_dir:
        print("ERROR: go-json-experiment dir not found!", file=sys.stderr)
        print(f"Looked in: {gomodcache}/github.com/sagernet/", file=sys.stderr)
        # Debug: list what's available
        base = os.path.join(gomodcache, "github.com/sagernet")
        if os.path.isdir(base):
            print("Available tailscale modules:", file=sys.stderr)
            for e in os.listdir(base):
                if "tailscale" in e:
                    print(f"  {e}", file=sys.stderr)
        return 1

    print(f"JSON dir: {json_dir}")

    patched = 0
    for fpath in glob.glob(os.path.join(json_dir, "*.go")):
        if patch_file(fpath):
            name = os.path.basename(fpath)
            print(f"  Patched: {name}")
            patched += 1

    remaining = 0
    for fpath in glob.glob(os.path.join(json_dir, "*.go")):
        with open(fpath, 'r') as f:
            if "reflect.TypeAssert" in f.read():
                remaining += 1
                name = os.path.basename(fpath)
                print(f"  WARNING: {name} still has reflect.TypeAssert", file=sys.stderr)

    print(f"Patched {patched} files, {remaining} remaining")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())