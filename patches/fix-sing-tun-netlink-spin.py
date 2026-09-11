#!/usr/bin/env python3
"""
Fix sing-tun netlink subscription CPU spin (busy-loop) on Linux.

Root cause (production incident 2026-09-11, hy-e5):
  sing-tun v0.9.0-beta.4 monitor_linux.go uses the old netlink.Subscribe API
  (routeSubscribeAt etc). When the kernel netlink receive buffer overflows
  (ENOBUFS, likely on hosts with many routes / frequent route churn — e.g.
  BGP + WireGuard mesh + policy routing), the internal subscription goroutine
  exits and `defer close(ch)` closes m.routeUpdate/m.linkUpdate/m.addressUpdate,
  while loopUpdate() has no closed-channel check — a closed channel is always
  readable, so the select spins forever: one goroutine pinned at 100% CPU
  (observed: 6h+ CPU time accumulated, sing-box process at ~98% busy on a
  1-core host, service still functional but host starved).

Fix:
  Replace monitor_linux.go with the upstream rewritten implementation
  (sing-tun v0.9.3+): self-managed AF_NETLINK socket with SO_RCVBUF(1MB) /
  SO_RCVBUFFORCE, non-blocking reads tolerating ENOBUFS, and a coalescing
  `update` channel — the original subscription-failure spin is structurally
  impossible (loopRead never closes the channel on overrun).

  This mirrors upstream commit(s) adding monitor_linux.go loopRead() and the
  TestNetworkUpdateMonitorReceiveOverrun regression test.

Usage:
  python3 fix-sing-tun-netlink-spin.py --vendor-dir vendor

Must be run after 'go mod vendor' in the sing-box source dir.

Behavior:
  - Old file (v0.9.0-beta.4 style) -> replaced with fixed implementation.
  - Already fixed (loopRead present) -> no-op, prints skip.
  - Unknown structure -> error exit (manual review needed).
"""

import argparse
import os
import sys

OLD_MARKERS = (
    "case <-m.routeUpdate:",
    "netlink.RouteSubscribe(m.routeUpdate, m.close)",
)
NEW_MARKER = "func (m *networkUpdateMonitor) loopRead()"

FIXED_SOURCE = '''package tun

import (
\t"errors"
\t"os"
\t"runtime"
\t"sync"
\t"time"

\tE "github.com/sagernet/sing/common/exceptions"
\t"github.com/sagernet/sing/common/logger"
\t"github.com/sagernet/sing/common/x/list"

\t"golang.org/x/sys/unix"
)

const (
\tnetlinkGroups = unix.RTMGRP_LINK |
\t\tunix.RTMGRP_IPV4_IFADDR |
\t\tunix.RTMGRP_IPV6_IFADDR |
\t\tunix.RTMGRP_IPV4_ROUTE |
\t\tunix.RTMGRP_IPV6_ROUTE
\tnetlinkReceiveBufferSize = 1 << 20
)

type networkUpdateMonitor struct {
\tsocket *os.File
\tupdate chan struct{}
\tclose  chan struct{}

\taccess    sync.Mutex
\tcallbacks list.List[NetworkUpdateCallback]
\tlogger    logger.Logger
}

var ErrNetlinkBanned = E.New(
\t"netlink socket in Android is banned by Google, " +
\t\t"use the root or system (ADB) user to run sing-box, " +
\t\t"or switch to the sing-box Android graphical interface client",
)

func NewNetworkUpdateMonitor(logger logger.Logger) (NetworkUpdateMonitor, error) {
\tmonitor := &networkUpdateMonitor{
\t\tupdate: make(chan struct{}, 1),
\t\tclose:  make(chan struct{}),
\t\tlogger: logger,
\t}
\t// check is netlink banned by google
\tif runtime.GOOS == "android" {
\t\tnetlinkSocket, err := unix.Socket(unix.AF_NETLINK, unix.SOCK_DGRAM, unix.NETLINK_ROUTE)
\t\tif err != nil {
\t\t\treturn nil, ErrNetlinkBanned
\t\t}
\t\terr = unix.Bind(netlinkSocket, &unix.SockaddrNetlink{
\t\t\tFamily: unix.AF_NETLINK,
\t\t})
\t\tunix.Close(netlinkSocket)
\t\tif err != nil {
\t\t\treturn nil, ErrNetlinkBanned
\t\t}
\t}
\treturn monitor, nil
}

func (m *networkUpdateMonitor) Start() error {
\tnetlinkSocket, err := unix.Socket(unix.AF_NETLINK, unix.SOCK_RAW|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, unix.NETLINK_ROUTE)
\tif err != nil {
\t\treturn E.Cause(err, "create netlink socket")
\t}
\terr = unix.Bind(netlinkSocket, &unix.SockaddrNetlink{
\t\tFamily: unix.AF_NETLINK,
\t\tGroups: netlinkGroups,
\t})
\tif err != nil {
\t\tunix.Close(netlinkSocket)
\t\treturn E.Cause(err, "subscribe netlink groups")
\t}
\terr = unix.SetsockoptInt(netlinkSocket, unix.SOL_SOCKET, unix.SO_RCVBUFFORCE, netlinkReceiveBufferSize)
\tif err != nil {
\t\tunix.SetsockoptInt(netlinkSocket, unix.SOL_SOCKET, unix.SO_RCVBUF, netlinkReceiveBufferSize)
\t}
\tm.socket = os.NewFile(uintptr(netlinkSocket), "netlink")
\tgo m.loopRead()
\tgo m.loopUpdate(time.Second)
\treturn nil
}

func (m *networkUpdateMonitor) loopRead() {
\tbuffer := make([]byte, unix.Getpagesize())
\tfor {
\t\t_, err := m.socket.Read(buffer)
\t\tif err != nil && !errors.Is(err, unix.ENOBUFS) {
\t\t\tselect {
\t\t\tcase <-m.close:
\t\t\tdefault:
\t\t\t\tm.logger.Error("read netlink socket: ", err)
\t\t\t}
\t\t\treturn
\t\t}
\t\tselect {
\t\tcase m.update <- struct{}{}:
\t\tdefault:
\t\t}
\t}
}

func (m *networkUpdateMonitor) loopUpdate(minDuration time.Duration) {
\ttimer := time.NewTimer(minDuration)
\ttimer.Stop()
\tdefer timer.Stop()
\tvar (
\t\ttimerC  <-chan time.Time
\t\tpending bool
\t)
\tfor {
\t\tselect {
\t\tcase <-m.close:
\t\t\treturn
\t\tcase <-m.update:
\t\tcase <-timerC:
\t\t\tif pending {
\t\t\t\tm.emit()
\t\t\t\tpending = false
\t\t\t\ttimer.Reset(minDuration)
\t\t\t\tcontinue
\t\t\t}
\t\t\ttimerC = nil
\t\t\tcontinue
\t\t}
\t\tif timerC != nil {
\t\t\tpending = true
\t\t\tcontinue
\t\t}
\t\tm.emit()
\t\ttimer.Reset(minDuration)
\t\ttimerC = timer.C
\t}
}

func (m *networkUpdateMonitor) Close() error {
\tselect {
\tcase <-m.close:
\t\treturn os.ErrClosed
\tdefault:
\t}
\tclose(m.close)
\tif m.socket != nil {
\t\treturn m.socket.Close()
\t}
\treturn nil
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-dir", default="vendor")
    args = parser.parse_args()

    target = os.path.join(args.vendor_dir,
                          "github.com", "sagernet", "sing-tun", "monitor_linux.go")
    if not os.path.isfile(target):
        print(f"ERROR: {target} not found — run after 'go mod vendor'", file=sys.stderr)
        return 1

    with open(target, "r", encoding="utf-8") as f:
        content = f.read()

    if NEW_MARKER in content:
        print("sing-tun monitor_linux.go already fixed (loopRead present), skip")
        return 0

    if not all(marker in content for marker in OLD_MARKERS):
        print("ERROR: sing-tun monitor_linux.go structure unrecognized — "
              "upstream may have refactored again; manual review required.",
              file=sys.stderr)
        return 1

    with open(target, "w", encoding="utf-8") as f:
        f.write(FIXED_SOURCE)
    print("Patched sing-tun monitor_linux.go (netlink spin fix, upstream v0.9.3 impl)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
