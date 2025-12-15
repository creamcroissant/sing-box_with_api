# Custom Sing-box Builder

This repository uses GitHub Actions to automatically build a custom version of [sing-box](https://github.com/SagerNet/sing-box).

## Features

- **Automated Updates**: Checks for new upstream releases daily.
- **Custom Tags**: Compiled with `with_v2ray_api` enabled (critical for traffic statistics) along with other standard tags.
- **Artifacts**: Provides `sing-box-linux-amd64` and `sing-box-linux-arm64`.

## Enabled Tags

- `with_v2ray_api` (Added)
- `with_gvisor`
- `with_quic`
- `with_dhcp`
- `with_wireguard`
- `with_utls`
- `with_acme`
- `with_clash_api`
- `with_tailscale`
- `with_ccm`

## Usage

1. Fork this repository.
2. Enable GitHub Actions in the "Actions" tab.
3. The workflow will run automatically every day at 00:00 UTC.
4. To trigger manually: Go to Actions -> Build Sing-box -> Run workflow.
