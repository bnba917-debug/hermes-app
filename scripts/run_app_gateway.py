#!/usr/bin/env python3
"""启动 App Gateway，不经过完整 hermes CLI（适合 Windows 未安装 hermes 命令时）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermes_cli.env_loader import load_hermes_dotenv

load_hermes_dotenv()

from plugins.app_gateway.cli import app_gateway_command, register_cli


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="app-gateway",
        description="Hermes App Gateway (standalone launcher)",
    )
    register_cli(parser)
    args = parser.parse_args(argv)
    if not getattr(args, "app_gateway_action", None):
        parser.print_help()
        sys.exit(0)
    app_gateway_command(args)


if __name__ == "__main__":
    main()
