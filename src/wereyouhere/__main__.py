import argparse
import os.path
import logging
import inspect
import sys
from typing import List, Tuple, Optional, Dict
from pathlib import Path
from datetime import datetime


from kython.ktyping import PathIsh


from .common import History, Filter, make_filter, get_logger, get_tmpdir
from . import config
from .dump import dump_histories

from .common import previsits_to_history, Indexer



def _do_index():
    cfg = config.get()

    logger = get_logger()

    fallback_tz = cfg.FALLBACK_TIMEZONE
    indexers = cfg.INDEXERS

    output_dir = Path(cfg.OUTPUT_DIR)
    if not output_dir.exists():
        raise ValueError("Expecting OUTPUT_DIR to be set to a correct path!")

    filters = [make_filter(f) for f in cfg.FILTERS]
    for f in filters:
        History.add_filter(f) # meh..


    all_histories = []
    all_errors = []

    for extractor in indexers:
        ex = extractor
        # TODO isinstance indexer?
        # TODO make more defensive?
        einfo: str
        if isinstance(ex, Indexer):
            einfo = f'{ex.ff.__module__}:{ex.ff.__name__} {ex.args} {ex.kwargs}'
        else:
            einfo = f'{ex.__module__}:{ex.__name__}'

        assert isinstance(ex, Indexer)

        hist, errors = previsits_to_history(extractor, src=ex.src)
        all_errors.extend(errors)
        all_histories.append((einfo, hist))

    # TODO perhaps it's better to open connection and dump as we collect so it consumes less memory?
    dump_histories(all_histories, config=cfg)

    if len(all_errors) > 0:
        sys.exit(1)


def do_index(config_file: Path):
    try:
        config.load_from(config_file)
        _do_index()
    finally:
        config.reset()


from .wereyouhere_server import setup_parser, run as do_serve

def main():
    from kython.klogging import setup_logzero
    setup_logzero(get_logger(), level=logging.DEBUG)

    p = argparse.ArgumentParser()
    subp = p.add_subparsers(dest='mode')
    ep = subp.add_parser('index')
    ep.add_argument('--config', type=Path, default=Path('config.py'))
    # TODO use some way to override or provide config only via cmdline?
    ep.add_argument('--intermediate', required=False)
    sp = subp.add_parser('serve')
    setup_parser(sp)

    args = p.parse_args()

    # TODO maybe, it's better for server to compute intermediate represetnation?
    # the only downside is storage. dunno.
    # worst case -- could use database?

    with get_tmpdir() as tdir:
        if args.mode == 'index':
            do_index(config_file=args.config)
        elif args.mode == 'serve':
            do_serve(port=args.port, config=args.config, quiet=args.quiet)
        else:
            raise AssertionError(f'unexpected mode {args.mode}')

if __name__ == '__main__':
    main()
