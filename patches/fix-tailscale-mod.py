#!/usr/bin/env python3
"""
Patch tailscale vendored go-json-experiment for Go 1.24+ compatibility.

Replace reflect.TypeAssert[T](v) with v.Interface().(T) in the Go module cache.
reflect.TypeAssert was added in Go 1.22 and removed in Go 1.24;
tailscale v1.92.4-sing-box-1.13-mod.10 vendored go-json-experiment code
that depends on it.

Must be run after 'go mod download' in the sing-box source dir.
"""

import glob
import os
import sys

GOMODCACHE = os.path.expanduser(
    os.environ.get("GOMODCACHE") or
    os.path.join(os.environ.get("HOME", "/root"), "go", "pkg", "mod")
)

TS_MODULE = "github.com/sagernet/tailscale@v1.92.4-sing-box-1.13-mod.10"
JSON_DIR = os.path.join(GOMODCACHE, TS_MODULE,
    "internal/godown/github.com/go-json-experiment/json")

TYPEASSERT_LEN = len("reflect.TypeAssert[")


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
            # Should not happen - copy as-is
            result.append(content[pos:type_end + 1])
            i = type_end + 1

    new_content = "".join(result)
    if new_content != content:
        with open(fpath, 'w') as f:
            f.write(new_content)
        return True
    return False


def main():
    if not os.path.isdir(JSON_DIR):
        print(f"ERROR: go-json-experiment dir not found at {JSON_DIR}", file=sys.stderr)
        print("Run 'go mod download' in the sing-box source tree first.", file=sys.stderr)
        return 1

    patched = 0
    for fpath in glob.glob(os.path.join(JSON_DIR, "*.go")):
        if patch_file(fpath):
            name = os.path.basename(fpath)
            print(f"  Patched: {name}")
            patched += 1

    # Verify
    remaining = 0
    for fpath in glob.glob(os.path.join(JSON_DIR, "*.go")):
        with open(fpath, 'r') as f:
            if "reflect.TypeAssert" in f.read():
                remaining += 1
                print(f"  WARNING: {os.path.basename(fpath)} still has reflect.TypeAssert")

    print(f"Patched {patched} files, {remaining} remaining")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())