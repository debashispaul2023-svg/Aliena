import argparse
import logging

from . import commands as _commands  # noqa: F401  (importing registers the commands)
from .config import load_config
from .logging_setup import configure
from .registry import commands

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='log-scanner', description='Log Scanner tool')
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_func, help_text) in sorted(commands().items()):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--text", default="")
        p.add_argument("--upper", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    configure(load_config().get("logging", {}).get("level", "INFO"))
    func = commands()[args.command][0]
    log.debug("running %s", args.command)
    print(func(args.text, args.upper))
    return 0
