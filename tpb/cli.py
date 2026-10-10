"""Command-line tools for configuring TPB mirrors."""

import argparse
import math
import sys

from .mirrors import DEFAULT_API_URL, rank_mirrors, read_urls, save_ranking


def positive_timeout(value):
    """Parse a positive, finite timeout for argparse."""
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError('timeout must be a positive finite number')
    return timeout


def main(argv=None):
    parser = argparse.ArgumentParser(prog='tpb')
    commands = parser.add_subparsers(dest='command', required=True)
    rank = commands.add_parser('rank-mirrors', help='probe URLs from a file and cache working mirrors')
    rank.add_argument('urls_file', help='UTF-8 file containing one mirror site URL per line')
    rank.add_argument('--api-url', default=DEFAULT_API_URL, help='Apibay-compatible API for JavaScript mirrors (default: %(default)s)')
    rank.add_argument('--query', default='public domain', help='search query used to check torrent results (default: %(default)s)')
    rank.add_argument('--timeout', type=positive_timeout, default=10, help='timeout in seconds per request (default: %(default)s)')
    args = parser.parse_args(argv)

    try:
        results = rank_mirrors(
            read_urls(args.urls_file), api_url=args.api_url, query=args.query, timeout=args.timeout,
            progress=lambda url: print('Checking {0}...'.format(url), flush=True),
        )
        for result in results:
            if result['status'] == 'ok':
                backend = result['api_url'] or 'HTML'
                print('OK {0:.3f}s {1} [{2}]'.format(result['elapsed'], result['base_url'], backend))
            else:
                print('FAILED {0}: {1}'.format(result['base_url'], result['error']))
        path = save_ranking(results, query=args.query)
    except (OSError, ValueError) as error:
        print('tpb: {0}'.format(error), file=sys.stderr)
        return 1
    print('Saved ranking to {0}'.format(path))
    return 0
