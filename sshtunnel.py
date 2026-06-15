#!/usr/bin/env python3

import argparse
import getpass
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Union


@dataclass
class PortForward:
    localPort: int
    remotePort: int
    remoteAddress: str = "localhost"


def parse_forward(s: str) -> PortForward:
    parts = s.split(":")
    localPort = int(parts[0])
    remotePort = int(parts[-1])
    remoteAddress = ":".join(parts[1:-1]) if len(parts) > 2 else "localhost"
    return PortForward(
        localPort=localPort,
        remotePort=remotePort,
        remoteAddress=remoteAddress,
    )


def build_command(
    serverAddress: str,
    user: str,
    forwards: Iterable[PortForward],
    serverPort: int = 22,
    asList: bool = True,
    addExe: bool = False,
    noShell: bool = False,
) -> Union[str, list[str]]:
    command = ["ssh.exe"] if addExe else ["ssh"]

    if noShell:
        command.append("-N")

    for pf in forwards:
        command.append("-L")
        command.append(f"{pf.localPort}:{pf.remoteAddress}:{pf.remotePort}")

    command.extend(["-p", f"{serverPort}", f"{user}@{serverAddress}"])

    if asList:
        return command
    else:
        return " ".join(command)


def main():
    argParser = argparse.ArgumentParser(
        description="Open a series of ssh local tunnels"
    )
    argParser.add_argument("-u", "--user", help="SSH username")
    argParser.add_argument("--host", help="SSH server address")
    argParser.add_argument(
        "-p", "--port", type=int, default=22, help="SSH server port (default: 22)"
    )
    argParser.add_argument(
        "-L",
        "--forward",
        action="append",
        dest="forwards",
        default=[],
        type=parse_forward,
        help="Port forward in either localPort:remoteAddress:remotePort or localPort:remotePort (remoteAddress is localhost) formats (repeatable)",
    )
    argParser.add_argument(
        "-N", "--no-shell", action="store_true", help="Add -N flag (no remote shell)"
    )
    argParser.add_argument(
        "--print", action="store_true", help="Print the command instead of executing it"
    )
    args = argParser.parse_args()

    user = args.user or getpass.getuser()
    if not args.host:
        argParser.error("a host needs to be set")

    command = build_command(
        serverAddress=args.host,
        user=user,
        forwards=args.forwards,
        serverPort=args.port,
        noShell=args.no_shell,
    )

    if args.print:
        print(" ".join(command))
        return

    process = subprocess.Popen(command)

    def cleanup(signum, frame):
        if process.poll() is None:
            process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        process.wait()
    except KeyboardInterrupt:
        cleanup(signal.SIGINT, None)


if __name__ == "__main__":
    main()
