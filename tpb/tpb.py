#!/usr/bin/env python

"""
Unofficial Python API for ThePirateBay.

@author Karan Goel
@email karan@goel.im
"""

from __future__ import unicode_literals

import datetime
import dateutil.parser
from functools import wraps
from lxml import html
import os
import re
import sys
import time

from .utils import URL, headers
from .api import API, format_size
from .mirrors import PROBE_ERRORS, load_mirrors

from requests import get

if sys.version_info >= (3, 0):
    unicode = str


def self_if_parameters(func):
    """
    If any parameter is given, the method's binded object is returned after
    executing the function. Else the function's result is returned.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        if args or kwargs:
            return self
        else:
            return result
    return wrapper


class List(object):

    """
    Abstract class for parsing a torrent list at some url and generate torrent
    objects to iterate over. Includes a resource path parser.
    """

    _meta = re.compile('Uploaded (.*), Size (.*), ULed by (.*)')
    base_path = ''
    api_url = None
    _mirrors = None

    def items(self):
        """
        Request URL and parse response. Yield a ``Torrent`` for every torrent
        on page.
        """
        if self._mirrors is None:
            for item in self._items():
                yield item
            return

        failures = []
        for index, mirror in enumerate(self._mirrors):
            self.url = URL(mirror['base_url'], self.base_path, segments=list(self.url.segments), defaults=list(self.url.segments.values()))
            self.api_url = mirror['api_url']
            try:
                # Parse a whole page before yielding so a failed mirror cannot duplicate results.
                items = list(self._items())
            except PROBE_ERRORS as error:
                failures.append('{0}: {1}'.format(mirror['base_url'], error))
                continue
            self._mirrors = self._mirrors[index:] + self._mirrors[:index]
            for item in items:
                yield item
            return
        raise RuntimeError('All cached mirrors failed. Run `tpb rank-mirrors urls.txt` to refresh them. ' + '; '.join(failures))

    def _items(self):
        if self.api_url:
            if self._mirrors is not None:
                # A shared API can still work after a mirror's torrent pages stop working.
                response = get(str(self.url.base.path('/search.html')), headers=headers(), timeout=30)
                response.raise_for_status()
                root = html.fromstring(response.text)
                if not root.xpath('//*[@id="torrents"]'):
                    raise ValueError('The cached mirror no longer serves a supported search page')
            api = API(self.api_url)
            for record in self._api_items(api):
                yield Torrent(**api.torrent_fields(str(self.url.base), record))
            return

        request = get(str(self.url), headers=headers(), timeout=30)
        request.raise_for_status()
        root = html.fromstring(request.text)
        if root.xpath('//*[@id="torrents"]'):
            raise ValueError('This site loads torrents with JavaScript. Pass api_url to TPB to use its JSON API.')
        if root.find('.//table') is None:
            raise ValueError('The response has no supported torrent listing')
        items = [self._build_torrent(row) for row in self._get_torrent_rows(root)]
        for item in items:
            yield item

    def __iter__(self):
        return self.items()

    def _get_torrent_rows(self, page):
        """
        Return torrent rows without the header or cells that span the table.
        """
        table = page.find('.//table')  # the table with all torrent listing
        if table is None:  # no table means no results:
            return []
        else:
            # Pagination and empty-result messages span the whole table.
            return [row for row in table.findall('.//tr')[1:] if not row.xpath('./td[@colspan]')]

    def _build_torrent(self, row):
        """
        Builds and returns a Torrent object for the given parsed row.
        """
        # Scrape, strip and build!!!
        cols = row.findall('.//td')  # split the row into it's columns

        # this column contains the categories
        [category, sub_category] = [c.text for c in cols[0].findall('.//a')]

        # this column with all important info
        links = cols[1].findall('.//a')  # get 4 a tags from this columns
        title = unicode(links[0].text)
        url = self.url.build().path(links[0].get('href'))
        magnet_link = links[1].get('href')  # the magnet download link
        try:
            torrent_link = links[2].get('href')  # the torrent download link
            if not torrent_link.endswith('.torrent'):
                torrent_link = None
        except IndexError:
            torrent_link = None
        comments = 0
        has_cover = 'No'
        images = cols[1].findall('.//img')
        for image in images:
            image_title = image.get('title')
            if image_title is None:
                continue
            if "comments" in image_title:
                comments = int(image_title.split(" ")[3])
            if "cover" in image_title:
                has_cover = 'Yes'
        user_status = "MEMBER"
        if links[-2].get('href').startswith("/user/"):
            user_status = links[-2].find('.//img').get('title')
        meta_col = cols[1].find('.//font').text_content()  # don't need user
        match = self._meta.match(meta_col)
        created = match.groups()[0].replace('\xa0', ' ')
        size = match.groups()[1].replace('\xa0', ' ')
        user = match.groups()[2]  # uploaded by user

        # last 2 columns for seeders and leechers
        seeders = int(cols[2].text)
        leechers = int(cols[3].text)
        t = Torrent(title, url, category, sub_category, magnet_link,
                    torrent_link, comments, has_cover, user_status, created,
                    size, user, seeders, leechers)
        return t


class Paginated(List):

    """
    Abstract class on top of ``List`` for parsing a torrent list with
    pagination capabilities.
    """

    def __init__(self, *args, **kwargs):
        super(Paginated, self).__init__(*args, **kwargs)
        self._multipage = False

    def items(self):
        """
        Request URL and parse response. Yield a ``Torrent`` for every torrent
        on page. If in multipage mode, Torrents from next pages are
        automatically chained.
        """
        if self._multipage:
            while True:
                # Pool for more torrents
                items = super(Paginated, self).items()
                # Stop if no more torrents
                first = next(items, None)
                if first is None:
                    return
                # Yield them if not
                else:
                    yield first
                    for item in items:
                        yield item
                # Go to the next page
                self.next()
        else:
            for item in super(Paginated, self).items():
                yield item

    def multipage(self):
        """
        Enable multipage iteration.
        """
        self._multipage = True
        return self

    @self_if_parameters
    def page(self, number=None):
        """
        If page is given, modify the URL correspondingly, return the current
        page otherwise.
        """
        if number is None:
            return int(self.url.page)
        self.url.page = str(number)

    def next(self):
        """
        Jump to the next page.
        """
        self.page(self.page() + 1)
        return self

    def previous(self):
        """
        Jump to the previous page.
        """
        self.page(self.page() - 1)
        return self


class Search(Paginated):

    """
    Paginated search featuring query, category and order management.
    """
    base_path = '/search'

    def __init__(self, base_url, query, page='0', order='7', category='0', api_url=None):
        super(Search, self).__init__()
        self.api_url = api_url
        self.url = URL(base_url, self.base_path,
                       segments=['query', 'page', 'order', 'category'],
                       defaults=[query, str(page), str(order), str(category)],
                       )

    def _api_items(self, api):
        return api.search(self.query(), self.category(), self.order(), self.page())

    @self_if_parameters
    def query(self, query=None):
        """
        If query is given, modify the URL correspondingly, return the current
        query otherwise.
        """
        if query is None:
            return self.url.query
        self.url.query = query

    @self_if_parameters
    def order(self, order=None):
        """
        If order is given, modify the URL correspondingly, return the current
        order otherwise.
        """
        if order is None:
            return int(self.url.order)
        self.url.order = str(order)

    @self_if_parameters
    def category(self, category=None):
        """
        If category is given, modify the URL correspondingly, return the
        current category otherwise.
        """
        if category is None:
            return int(self.url.category)
        self.url.category = str(category)


class Recent(Paginated):

    """
    Paginated most recent torrents.
    """
    base_path = '/recent'

    def __init__(self, base_url, page='0', api_url=None):
        super(Recent, self).__init__()
        self.api_url = api_url
        self.url = URL(base_url, self.base_path,
                       segments=['page'],
                       defaults=[str(page)],
                       )

    def _api_items(self, api):
        return api.recent(self.page())


class Top(List):

    """
    Top torrents featuring category management.
    """
    base_path = '/top'

    def __init__(self, base_url, category='0', api_url=None):
        self.api_url = api_url
        self.url = URL(base_url, self.base_path,
                       segments=['category'],
                       defaults=[str(category)],
                       )

    def _api_items(self, api):
        return api.top(self.category())

    @self_if_parameters
    def category(self, category=None):
        """
        If category is given, modify the URL correspondingly, return the
        current category otherwise.
        """
        if category is None:
            return int(self.url.category)
        self.url.category = str(category)


class TPB(object):

    """
    Search torrents and list recent or top torrents.

    Use base_url for torrent page links. Set api_url to an Apibay-compatible
    JSON API, or omit it to parse HTML tables from an older mirror.
    If base_url is omitted, use cached mirrors in rank order.
    """

    def __init__(self, base_url=None, api_url=None):
        self._mirrors = None
        if base_url is None:
            self._mirrors = load_mirrors()
            if api_url is not None:
                self._mirrors = [dict(base_url=mirror['base_url'], api_url=api_url) for mirror in self._mirrors]
            base_url = self._mirrors[0]['base_url']
            api_url = self._mirrors[0]['api_url']
        self.base_url = base_url
        self.api_url = api_url

    def search(self, query, page=0, order=7, category=0, multipage=False):
        """
        Searches TPB for query and returns a list of paginated Torrents capable
        of changing query, categories and orders.
        """
        search = Search(self.base_url, query, page, order, category, api_url=self.api_url)
        search._mirrors = self._mirrors
        if multipage:
            search.multipage()
        return search

    def recent(self, page=0):
        """
        Lists most recent Torrents added to TPB.
        """
        recent = Recent(self.base_url, page, api_url=self.api_url)
        recent._mirrors = self._mirrors
        return recent

    def top(self, category=0):
        """
        Lists top Torrents on TPB optionally filtering by category.
        """
        top = Top(self.base_url, category, api_url=self.api_url)
        top._mirrors = self._mirrors
        return top


class Torrent(object):

    """
    Holder of a single TPB torrent.
    """

    def __init__(self, title, url, category, sub_category, magnet_link,
                 torrent_link, comments, has_cover, user_status, created,
                 size, user, seeders, leechers, api_url=None):
        self.title = title  # the title of the torrent
        self.url = url  # TPB url for the torrent
        self.id = self.url.query_param('id') if api_url else self.url.path_segments()[1]
        self._api_url = api_url
        self.category = category  # the main category
        self.sub_category = sub_category  # the sub category
        self.magnet_link = magnet_link  # magnet download link
        self.torrent_link = torrent_link  # .torrent download link
        self.comments = comments
        self.has_cover = has_cover
        self.user_status = user_status
        self._created = (created, time.time())  # uploaded date, current time
        self.size = size  # size of torrent
        self.user = user  # username of uploader
        self.seeders = seeders  # number of seeders
        self.leechers = leechers  # number of leechers
        self._info = None
        self._files = {}

    @property
    def info(self):
        if self._info is None:
            if self._api_url:
                self._info = API(self._api_url).get('/t.php', id=self.id)['descr']
                return self._info
            request = get(str(self.url), headers=headers(), timeout=30)
            request.raise_for_status()
            root = html.fromstring(request.text)
            info = root.cssselect('#details > .nfo > pre')[0].text_content()
            self._info = info
        return self._info

    @property
    def files(self):
        if not self._files:
            if self._api_url:
                files = API(self._api_url).get('/f.php', id=self.id)
                self._files = {entry['name'][0]: format_size(entry['size'][0]) for entry in files}
                return self._files
            url = self.url.path('/ajax_details_filelist.php').query_param('id', self.id)
            request = get(str(url), headers=headers(), timeout=30)
            request.raise_for_status()
            root = html.fromstring(request.text)
            rows = root.findall('.//tr')
            for row in rows:
                td = row.findall('.//td')
                if len(td) == 2:
                    name, size = [unicode(v.text_content())
                                  for v in td]
                    self._files[name] = size.replace('\xa0', ' ')
        return self._files

    @property
    def created(self):
        """
        Attempt to parse the human readable torrent creation datetime.
        """
        timestamp, current = self._created
        if timestamp.endswith('ago'):
            quantity, kind, ago = timestamp.split()
            quantity = int(quantity)
            if 'sec' in kind:
                current -= quantity
            elif 'min' in kind:
                current -= quantity * 60
            elif 'hour' in kind:
                current -= quantity * 60 * 60
            return datetime.datetime.fromtimestamp(current)
        current = datetime.datetime.fromtimestamp(current)
        timestamp = timestamp.replace(
            'Y-day', str(current.date() - datetime.timedelta(days=1)))
        timestamp = timestamp.replace('Today', current.date().isoformat())
        try:
            return dateutil.parser.parse(timestamp)
        except:
            return current

    def print_torrent(self):
        """
        Print the details of a torrent
        """
        print('Title: %s' % self.title)
        print('URL: %s' % self.url)
        print('Category: %s' % self.category)
        print('Sub-Category: %s' % self.sub_category)
        print('Magnet Link: %s' % self.magnet_link)
        print('Torrent Link: %s' % self.torrent_link)
        print('Uploaded: %s' % self.created)
        print('Comments: %d' % self.comments)
        print('Has Cover Image: %s' % self.has_cover)
        print('User Status: %s' % self.user_status)
        print('Size: %s' % self.size)
        print('User: %s' % self.user)
        print('Seeders: %d' % self.seeders)
        print('Leechers: %d' % self.leechers)

    def __repr__(self):
        return '{0} by {1}'.format(self.title, self.user)
