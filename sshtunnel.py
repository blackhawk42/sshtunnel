#!/usr/bin/env python3

import argparse
import getpass
import io
import logging
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import tomllib

CONFIG_FILE_NAME = Path("sshtunnel.toml")


@dataclass
class PortForward:
    localPort: int
    remotePort: int
    remoteAddress: str = "localhost"


def cli_port_forward(s: str) -> PortForward:
    parts = s.split(":")
    localPort = int(parts[0])
    remotePort = int(parts[-1])
    remoteAddress = ":".join(parts[1:-1]) if len(parts) > 2 else "localhost"
    return PortForward(
        localPort=localPort,
        remotePort=remotePort,
        remoteAddress=remoteAddress,
    )


def toml_port_forward(toml_fwd: dict) -> PortForward:
    return PortForward(
        localPort=toml_fwd["local_port"],
        remotePort=toml_fwd["remote_port"],
        remoteAddress=toml_fwd.get("remote_address", "localhost"),
    )


def find_config(args_config: Path | None) -> Path | None:
    if args_config is not None:
        if args_config.exists():
            return args_config
        logging.error("config file not found: %s", args_config)
        sys.exit(1)

    paths = [
        Path(__file__).resolve().parent / CONFIG_FILE_NAME,
        Path.home() / ".config" / CONFIG_FILE_NAME,
        Path.home() / ("." + CONFIG_FILE_NAME.name),
    ]
    for p in paths:
        if p.exists():
            return p

    return None


def apply_config(args: argparse.Namespace, config_file: io.IOBase) -> None:
    data = tomllib.load(config_file)
    ssh_cfg = data.get("ssh", {})

    if args.host is None and "host" in ssh_cfg:
        args.host = ssh_cfg["host"]
    if args.user is None and "user" in ssh_cfg:
        args.user = ssh_cfg["user"]
    if args.port is None and "port" in ssh_cfg:
        args.port = ssh_cfg["port"]
    if not args.no_shell and "no_shell" in ssh_cfg:
        args.no_shell = ssh_cfg["no_shell"]
    if not args.verbose and "verbose" in ssh_cfg:
        args.verbose = ssh_cfg["verbose"]
    if not args.exe and "exe" in ssh_cfg:
        args.exe = ssh_cfg["exe"]
    if args.host_file is None and "host_file" in ssh_cfg:
        args.host_file = Path(ssh_cfg["host_file"])

    toml_forwards = [toml_port_forward(fwd) for fwd in data.get("forwards", [])]
    args.forwards = toml_forwards + args.forwards


def build_command(
    serverAddress: str,
    user: str,
    forwards: Iterable[PortForward],
    serverPort: int = 22,
    asList: bool = True,
    addExe: bool = False,
    noShell: bool = False,
) -> str | list[str]:
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


def read_host_file(host_file: Path) -> str | None:
    if not host_file.exists():
        logging.error("host file not found: %s", host_file)
        return None

    try:
        with host_file.open(encoding="utf-8-sig") as f:
            host_from_file = f.readline().strip()
    except Exception as e:
        logging.error("error while reading host file %s: %s", host_file, e)
        return None

    if host_from_file == "":
        logging.error("first line of host file is empty: %s", host_file)
        return None

    return host_from_file


def main():
    argParser = argparse.ArgumentParser(
        description="Open a series of ssh local tunnels"
    )
    argParser.add_argument(
        "-u", "--user", help="SSH username (default: autodetected by getpass.getuser())"
    )
    argParser.add_argument("--host", help="SSH server address")
    argParser.add_argument(
        "--host-file",
        type=Path,
        help="Path to a file whose first line contains the SSH server address",
    )
    argParser.add_argument(
        "-p", "--port", type=int, default=None, help="SSH server port (default: 22)"
    )
    argParser.add_argument(
        "-L",
        "--forward",
        action="append",
        dest="forwards",
        default=[],
        type=cli_port_forward,
        help="Port forward in either localPort:remoteAddress:remotePort or localPort:remotePort (remoteAddress is localhost) formats (repeatable)",
    )
    argParser.add_argument(
        "-N", "--no-shell", action="store_true", help="Add -N flag (no remote shell)"
    )
    argParser.add_argument(
        "--exe",
        action="store_true",
        help='add a ".exe" to the final command, sometimes useful on Windows',
    )
    argParser.add_argument(
        "--print", action="store_true", help="Print the command instead of executing it"
    )
    argParser.add_argument(
        "--config",
        type=Path,
        help="Path to TOML configuration file",
    )
    argParser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = argParser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    cli_host_was_set = args.host is not None
    cli_host_file_was_set = args.host_file is not None

    config_path = find_config(args.config)
    if config_path is not None:
        with config_path.open("rb") as f:
            apply_config(args, f)
        if args.verbose:
            logging.getLogger().setLevel(logging.INFO)
        logging.info("using config file: %s", config_path)
    else:
        if args.verbose:
            logging.getLogger().setLevel(logging.INFO)
        logging.info("no config file found")

    # Priority: host (CLI) → host file (CLI) → host (TOML) → host file (TOML)
    if cli_host_was_set:
        # host was provided via CLI → use it directly
        pass
    elif cli_host_file_was_set:
        # host file was provided via CLI → read host from file
        args.host = read_host_file(args.host_file)
        if args.host is None:
            sys.exit(1)
    elif args.host is not None:
        # host was provided via TOML → use it directly
        pass
    elif args.host_file is not None:
        # host file was provided via TOML → read host from file
        args.host = read_host_file(args.host_file)
        if args.host is None:
            sys.exit(1)
    else:
        argParser.error("either a host or a host file should be provided")

    user = args.user or getpass.getuser()
    if args.port is None:
        args.port = 22

    logging.info(
        "host=%s, user=%s, port=%s, no_shell=%s, forwards=%s",
        args.host,
        user,
        args.port,
        args.no_shell,
        args.forwards,
    )

    command = build_command(
        serverAddress=args.host,
        user=user,
        forwards=args.forwards,
        serverPort=args.port,
        noShell=args.no_shell,
        addExe=args.exe,
    )

    if args.print:
        print(" ".join(command))
        return

    logging.info("executing: %s", " ".join(command))
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
