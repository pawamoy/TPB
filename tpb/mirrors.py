"""Probe mirror URLs and store their ranking in the user's cache directory."""

import json
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

from lxml import html
from lxml.etree import LxmlError
from platformdirs import user_cache_path
from requests import get
from requests.exceptions import RequestException

from .api import API
from .utils import headers


DEFAULT_API_URL = 'https://apibay.org'
PROBE_ERRORS = (RequestException, LxmlError, ValueError, KeyError, IndexError, TypeError, AttributeError)


def cache_path():
    """Return the mirror cache path without creating the directory."""
    return user_cache_path('tpb', appauthor=False) / 'mirrors.json'


def normalize_url(url):
    """Validate and normalize an HTTP(S) site root."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
        raise ValueError('Expected an absolute HTTP(S) URL: {0}'.format(url))
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('', '/'):
        raise ValueError('Expected a site root without credentials, a query, or a fragment: {0}'.format(url))
    # Reading the port also checks whether an explicit port is valid.
    parts.port
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), '', '', ''))


def read_urls(filename):
    """Read unique mirror URLs, ignoring blank lines and comment lines."""
    urls = []
    with open(filename, encoding='utf-8-sig') as stream:
        for number, line in enumerate(stream, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                url = normalize_url(line)
            except ValueError as error:
                raise ValueError('{0}:{1}: {2}'.format(filename, number, error)) from error
            if url not in urls:
                urls.append(url)
    if not urls:
        raise ValueError('The URL file contains no mirrors')
    return urls


def probe_mirror(base_url, api_url=DEFAULT_API_URL, query='public domain', timeout=10):
    """Check that a mirror can supply parseable search results."""
    from .tpb import Search

    search = Search(base_url, query)
    urls = [str(search.url), base_url + '/search.html']
    failures = []
    for url in urls:
        try:
            params = {'q': query} if url.endswith('/search.html') else None
            response = get(url, params=params, headers=headers(), timeout=timeout)
            response.raise_for_status()
            root = html.fromstring(response.text)
            if root.xpath('//*[@id="torrents"]'):
                api = API(api_url, timeout=timeout)
                records = api.search(query, category=0, order=7, page=0)
                if not records:
                    raise ValueError('The probe query returned no torrents')
                # Check the metadata required to construct a Torrent, not only the JSON shape.
                for record in records:
                    api.torrent_fields(base_url, record)
                return api_url
            if not root.xpath('//table[@id="searchResult"]'):
                raise ValueError('The response has no supported torrent listing')
            rows = search._get_torrent_rows(root)
            if not rows:
                raise ValueError('The probe query returned no torrents')
            for row in rows:
                search._build_torrent(row)
            return None
        except PROBE_ERRORS as error:
            failures.append('{0}: {1}'.format(url, error))
    raise ValueError('; '.join(failures))


def rank_mirrors(urls, api_url=DEFAULT_API_URL, query='public domain', timeout=10, progress=None):
    """Rank successful probes by elapsed time and put failed probes last."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Timeout must be a positive finite number')
    api_url = normalize_url(api_url)
    results = []
    for url in urls:
        if progress is not None:
            progress(url)
        started = time.monotonic()
        try:
            base_url = normalize_url(url)
            backend = probe_mirror(base_url, api_url=api_url, query=query, timeout=timeout)
            result = dict(base_url=base_url, api_url=backend, status='ok')
        except PROBE_ERRORS as error:
            result = dict(base_url=url, api_url=None, status='failed', error=str(error))
        result['elapsed'] = time.monotonic() - started
        results.append(result)
    return sorted(results, key=lambda result: (result['status'] != 'ok', result['elapsed']))


def save_ranking(results, query='public domain'):
    """Atomically save a ranking that contains at least one working mirror."""
    if not any(result['status'] == 'ok' for result in results):
        raise ValueError('No working mirrors found; the previous cache was kept')
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(version=1, checked_at=time.time(), query=query, results=results)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary_path = Path(stream.name)
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return path


def load_mirrors():
    """Read working mirrors in cached rank order, without making requests."""
    path = cache_path()
    hint = 'Run `tpb rank-mirrors urls.txt` or pass base_url to TPB.'
    try:
        with path.open(encoding='utf-8') as stream:
            data = json.load(stream)
        if data['version'] != 1 or not isinstance(data['results'], list):
            raise ValueError('Unsupported mirror cache format')
        mirrors = []
        for result in data['results']:
            if result['status'] != 'ok':
                continue
            base_url = normalize_url(result['base_url'])
            api_url = normalize_url(result['api_url']) if result['api_url'] is not None else None
            mirrors.append(dict(base_url=base_url, api_url=api_url))
        if not mirrors:
            raise ValueError('The cache contains no working mirrors')
        return mirrors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise RuntimeError('Cannot load mirror cache at {0}: {1}. {2}'.format(path, error, hint)) from error
