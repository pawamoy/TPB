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
import urllib.parse

# import HTMLSession from requests_htmlimport warnings
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore",category=DeprecationWarning)
    from requests_html import HTMLSession


import logging

from .utils import URL, headers

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

    def items(self):
        """
        Request URL and parse response. Yield a ``Torrent`` for every torrent
        on page.
        """
        try:

            original_method = True

            if original_method:
                hd = headers()
                strurl = str(self.url)
                request = get(strurl, headers=hd)
                root = html.fromstring(request.text)

            else:
                ##### New code to render javascript - start #####
                # create an HTML Session object
                session = HTMLSession()
                
                # Use the object above to connect to needed webpage
                resp = session.get(str(self.url))#, headers=headers())
                
                # Run JavaScript code on webpage
                resp.html.render()
                root = html.fromstring(resp.html.html)
                
                session.close()

                ##### New code to render javascript - end #####

            items = [self._build_torrent(row) for row in
                 self._get_torrent_rows(root)]
            for item in items:
                yield item
        except Exception as e:
            print(e)
            pass

    def __iter__(self):
        return self.items()

    def _get_torrent_rows(self, page):
        """
        Returns all 'tr' tag rows as a list of tuples. Each tuple is for
        a single torrent.
        """
        table = page.find('.//ol')  # the table with all torrent listing
        if table is None:  # no table means no results:
            return []
        else:
            return table.findall('.//li')[1:]  # get all rows but header

    def search_for_tag(self, row, tag_queries):
        
        for tag_query in tag_queries:
            tag_list = row.cssselect(tag_query)

            if tag_list:
                return tag_list[0]
        return None

    def _build_torrent(self, row):
        """
        Builds and returns a Torrent object for the given parsed row.
        """
        #access relevant columns
        item_types_column = self.search_for_tag(row, ["span.item-type"])
        title_column = self.search_for_tag(row, ["span.item-title"])
        icons_column = self.search_for_tag(row, ["span.item-icons"]) 
        uploaded_date_column = self.search_for_tag(row, ["span.item-uploaded"])
        size_column = self.search_for_tag(row, ["span.item-size"])
        user_column = self.search_for_tag(row, ["span.item-user > a", "span.item-user"])
        img_column = self.search_for_tag(row, ["span.item-icons > img"])
        seeders_column = self.search_for_tag(row, ["span.item-seed"])
        leechers_column = self.search_for_tag(row, ["span.item-leech"])

        # access intermediate tags
        title_anchor = title_column.findall('.//a')[0]

        # access relevant data from columns
        [category, sub_category] = [ c.text for c in item_types_column.findall('.//a') ]
        type_column = item_types_column.findall('.//a')  # get 4 a tags from this columns
        title = unicode(title_anchor.text)
        url = self.url.build().path(title_anchor.get('href'))
        magnet_link = icons_column.findall('.//a')[0].get('href')  # the magnet download link
        created = uploaded_date_column.text
        size = size_column.text
        user = user_column.text
        seeders = int(seeders_column.text)
        leechers = int(leechers_column.text)

        #deprecated fields
        torrent_link = None
        comments = None
        has_cover = None
        user_status = "NORMAL"

        if img_column is not None:
            user_status = "VIP"

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

    def __init__(self, base_url, query, page='0', order='7', category='0'):
        super(Search, self).__init__()
        self.url = URL(base_url, self.base_path,
                       segments=['query', 'page', 'order', 'category'],
                       defaults=[query, str(page), str(order), str(category)],
                       )

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

    def __init__(self, base_url, page='0'):
        super(Recent, self).__init__()
        self.url = URL(base_url, self.base_path,
                       segments=['page'],
                       defaults=[str(page)],
                       )


class Top(List):

    """
    Top torrents featuring category management.
    """
    base_path = '/top'

    def __init__(self, base_url, category='0'):
        self.url = URL(base_url, self.base_path,
                       segments=['category'],
                       defaults=[str(category)],
                       )

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
    TPB API with searching, most recent torrents and top torrents support.
    Passes on base_url to the instantiated Search, Recent and Top classes.
    """
    

    def __init__(self, base_url):
        self.base_url = base_url

    def search(self, query, page=0, order=7, category=0, multipage=False):
        """
        Searches TPB for query and returns a list of paginated Torrents capable
        of changing query, categories and orders.
        """
        search = Search(self.base_url, query, page, order, category)
        if multipage:
            search.multipage()
        return search

    def recent(self, page=0):
        """
        Lists most recent Torrents added to TPB.
        """
        return Recent(self.base_url, page)

    def top(self, category=0):
        """
        Lists top Torrents on TPB optionally filtering by category.
        """
        return Top(self.base_url, category)


class Torrent(object):

    """
    Holder of a single TPB torrent.
    """

    def __init__(self, title, url, category, sub_category, magnet_link,
                 torrent_link, comments, has_cover, user_status, created,
                 size, user, seeders, leechers):
        self.title = title  # the title of the torrent
        self.url = url  # TPB url for the torrent
        self.id = 1#self.url.path_segments()[1]
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
            getUrl = urllib.parse.unquote(str(self.url))
            request = get(getUrl, headers=headers())
            root = html.fromstring(request.text)
            info = root.cssselect('#description_text')[0].text_content()
            self._info = info
        return self._info

    @property
    def files(self):
        if not self._files:
            url = self.url.path('/ajax_details_filelist.php').query_param('id', self.id)
            request = get(str(url), headers=headers())
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
