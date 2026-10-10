"""Read torrent data from an Apibay-compatible JSON API."""

import datetime

from dateutil.tz import tzutc
from purl import URL
from requests import get
from requests.utils import quote

from .constants import CATEGORIES
from .utils import headers


PAGE_SIZE = 30
SORT_FIELDS = ('name', 'added', 'size', 'seeders', 'leechers', 'username', 'category')


def format_size(size):
    """Format a byte count with binary units."""
    size = int(size)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'):
        if size < 1024 or unit == 'PiB':
            return '{0:.2f} {1}'.format(size, unit)
        size /= 1024.0


def category_names(category):
    """Return the main category and subcategory names for a category ID."""
    category = int(category)
    for name, group in vars(CATEGORIES).items():
        if not isinstance(group, type) or getattr(group, 'ALL', 600) != category // 100 * 100:
            continue
        for subname, value in vars(group).items():
            if value == category:
                return name.title(), subname.replace('_', ' ').title()
        return name.title(), str(category)
    return 'Other', str(category)


class API(object):
    """Request search results, torrent descriptions, and file lists."""

    def __init__(self, url, timeout=30):
        self.url = URL(url)
        self.timeout = timeout

    def get(self, path, **params):
        url = self.url.path(path).query_params(params)
        response = get(str(url), headers=headers(), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def search(self, query, category, order, page):
        records = self._records(self.get('/q.php', q=query, cat=category))
        order = int(order)
        if order < 1 or order > 14:
            raise ValueError('Search order must be between 1 and 14')
        field = SORT_FIELDS[(order - 1) // 2]

        def sort_key(record):
            value = record[field]
            return value.lower() if field in ('name', 'username') else int(value)

        records.sort(key=sort_key, reverse=order % 2 == 1)
        return self._page(records, page)

    def recent(self, page):
        records = self.get('/precompiled/data_top100_recent.json')
        return self._page(self._records(records), page)

    def top(self, category):
        category = str(category) if int(category) else 'all'
        return self._records(self.get('/precompiled/data_top100_{0}.json'.format(category)))

    def _records(self, records):
        if not isinstance(records, list):
            raise ValueError('Expected a JSON list of torrents from {0}'.format(self.url))
        # Apibay represents an empty search with a torrent whose ID is zero.
        return [record for record in records if str(record['id']) != '0']

    def _page(self, records, page):
        page = int(page)
        if page < 0:
            raise ValueError('Page number must be nonnegative')
        start = page * PAGE_SIZE
        return records[start:start + PAGE_SIZE]

    def torrent_fields(self, base_url, record):
        category, sub_category = category_names(record['category'])
        url = URL(base_url).path('/torrent.html').query_param('id', record['id'])
        magnet = 'magnet:?xt=urn:btih:{0}&dn={1}'.format(record['info_hash'], quote(record['name'], safe=''))
        created = datetime.datetime.fromtimestamp(int(record['added']), tzutc()).isoformat()
        return dict(
            title=record['name'], url=url, category=category, sub_category=sub_category,
            magnet_link=magnet, torrent_link=None, comments=0, has_cover='No',
            user_status=record['status'].upper(), created=created,
            size=format_size(record['size']), user=record['username'],
            seeders=int(record['seeders']), leechers=int(record['leechers']),
            api_url=str(self.url),
        )
