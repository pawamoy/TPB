import json
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from purl import URL
from requests import Response
from requests.exceptions import ConnectionError, HTTPError

from tpb import CATEGORIES, ORDERS, TPB


def json_response(data, status=200):
    response = Response()
    response.status_code = status
    response._content = json.dumps(data).encode('utf-8')
    return response


def torrent_record(number=1, **changes):
    record = dict(
        id=str(number), name='Public domain film {0}'.format(number),
        info_hash='0123456789ABCDEF0123456789ABCDEF01234567',
        leechers='2', seeders=str(number), size='1048576', num_files='1',
        username='archivist', added='1704067200', status='vip', category='201',
    )
    record.update(changes)
    return record


class APIResultsTestCase(unittest.TestCase):

    def setUp(self):
        self.tpb = TPB('https://mirror.example', api_url='https://api.example')

    def test_search_builds_torrent_metadata(self):
        # Apibay returns numeric values as strings and an info hash instead of a magnet link.
        response = json_response([torrent_record(name='Public domain / film & café')])

        with patch('tpb.api.get', return_value=response) as request:
            torrents = list(self.tpb.search('public domain', category=CATEGORIES.VIDEO.MOVIES))

        self.assertEqual(len(torrents), 1)
        torrent = torrents[0]
        self.assertEqual(torrent.title, 'Public domain / film & café')
        self.assertEqual(str(torrent.url), 'https://mirror.example/torrent.html?id=1')
        self.assertEqual(torrent.id, '1')
        self.assertEqual((torrent.category, torrent.sub_category), ('Video', 'Movies'))
        self.assertEqual(torrent.created, datetime(2024, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(torrent.size, '1.00 MiB')
        self.assertEqual(torrent.user, 'archivist')
        self.assertEqual((torrent.seeders, torrent.leechers), (1, 2))
        self.assertEqual(torrent.user_status, 'VIP')
        self.assertEqual(torrent.magnet_link, 'magnet:?xt=urn:btih:0123456789ABCDEF0123456789ABCDEF01234567&dn=Public%20domain%20%2F%20film%20%26%20caf%C3%A9')
        url = URL(request.call_args.args[0])
        self.assertEqual(url.query_param('q'), 'public domain')
        self.assertEqual(url.query_param('cat'), '201')

    def test_search_changes_query_and_category(self):
        search = self.tpb.search('old query').query('café & film').category(CATEGORIES.OTHER.EBOOKS)

        with patch('tpb.api.get', return_value=json_response([])) as request:
            self.assertEqual(list(search), [])

        url = URL(request.call_args.args[0])
        self.assertEqual(url.query_param('q'), 'café & film')
        self.assertEqual(url.query_param('cat'), '601')

    def test_numeric_sort_and_pagination(self):
        # Sorting must compare seed counts as numbers before selecting a page.
        records = [torrent_record(number) for number in range(1, 36)]
        search = self.tpb.search('public domain').order(ORDERS.SEEDERS.DES).page(1)

        with patch('tpb.api.get', return_value=json_response(records)):
            torrents = list(search)

        self.assertEqual([torrent.seeders for torrent in torrents], [5, 4, 3, 2, 1])

    def test_multipage_stops_at_end_of_api_results(self):
        records = [torrent_record(number) for number in range(1, 36)]
        search = self.tpb.search('public domain').order(ORDERS.SEEDERS.ASC).multipage()

        with patch('tpb.api.get', return_value=json_response(records)):
            torrents = list(search)

        self.assertEqual([torrent.id for torrent in torrents], [str(number) for number in range(1, 36)])
        self.assertEqual(search.page(), 2)

    def test_no_results_sentinel_is_not_a_torrent(self):
        # An empty API search returns a placeholder with ID zero.
        response = json_response([torrent_record(0, name='No results returned')])

        with patch('tpb.api.get', return_value=response):
            torrents = list(self.tpb.search('no matching torrents').multipage())

        self.assertEqual(torrents, [])

    def test_top_and_recent_use_precompiled_lists(self):
        response = json_response([torrent_record()])

        with patch('tpb.api.get', return_value=response) as request:
            top = list(self.tpb.top())
            category_top = list(self.tpb.top(CATEGORIES.VIDEO.MOVIES))
            recent = list(self.tpb.recent())

        self.assertEqual([str(item.url) for item in top], ['https://mirror.example/torrent.html?id=1'])
        self.assertEqual(len(category_top), 1)
        self.assertEqual(len(recent), 1)
        self.assertEqual([URL(call.args[0]).path() for call in request.call_args_list], [
            '/precompiled/data_top100_all.json',
            '/precompiled/data_top100_201.json',
            '/precompiled/data_top100_recent.json',
        ])

    def test_description_and_files_use_torrent_id(self):
        responses = [
            json_response([torrent_record()]),
            json_response({'descr': 'A public domain film.'}),
            json_response([{'name': ['film.mkv'], 'size': [1048576]}]),
        ]

        with patch('tpb.api.get', side_effect=responses) as request:
            torrent = next(iter(self.tpb.search('public domain')))
            description = torrent.info
            files = torrent.files
            # Accessing these properties again must reuse the downloaded details.
            self.assertEqual(torrent.info, description)
            self.assertEqual(torrent.files, files)

        self.assertEqual(description, 'A public domain film.')
        self.assertEqual(files, {'film.mkv': '1.00 MiB'})
        detail_urls = [URL(call.args[0]) for call in request.call_args_list[1:]]
        self.assertEqual([url.path() for url in detail_urls], ['/t.php', '/f.php'])
        self.assertEqual([url.query_param('id') for url in detail_urls], ['1', '1'])
        self.assertEqual(request.call_count, 3)

    def test_api_failures_are_visible(self):
        with patch('tpb.api.get', side_effect=ConnectionError('unreachable')):
            with self.assertRaises(ConnectionError):
                list(self.tpb.search('public domain'))

        with patch('tpb.api.get', return_value=json_response({}, status=429)):
            with self.assertRaises(HTTPError):
                list(self.tpb.search('public domain'))

        with patch('tpb.api.get', return_value=json_response({'error': 'service unavailable'})):
            with self.assertRaisesRegex(ValueError, 'JSON list'):
                list(self.tpb.search('public domain'))


class HTMLFailuresTestCase(unittest.TestCase):

    def test_modern_search_page_explains_how_to_use_the_api(self):
        # Reduced from the live search.html response linked by proxybay.vercel.app.
        response = Response()
        response.status_code = 200
        response._content = Path(__file__).with_name('presets').joinpath('modern_search.html').read_bytes()

        with patch('tpb.tpb.get', return_value=response):
            with self.assertRaisesRegex(ValueError, 'api_url'):
                list(TPB('https://mirror.example').search('public domain'))

    def test_http_errors_are_not_empty_searches(self):
        with patch('tpb.tpb.get', return_value=json_response({}, status=404)):
            with self.assertRaises(HTTPError):
                list(TPB('https://mirror.example').search('public domain'))

    def test_connection_errors_are_not_empty_searches(self):
        with patch('tpb.tpb.get', side_effect=ConnectionError('unreachable')):
            with self.assertRaises(ConnectionError):
                list(TPB('https://mirror.example').search('public domain'))

    def test_malformed_torrent_rows_raise_a_parsing_error(self):
        response = Response()
        response.status_code = 200
        response._content = b'<html><table><tr><th>Name</th></tr><tr><td>broken row</td></tr></table></html>'

        with patch('tpb.tpb.get', return_value=response):
            with self.assertRaises(ValueError):
                list(TPB('https://mirror.example').search('public domain'))

    def test_empty_html_results_still_return_an_empty_list(self):
        response = Response()
        response.status_code = 200
        response._content = b'<html><table><tr><th>Name</th></tr></table></html>'

        with patch('tpb.tpb.get', return_value=response):
            torrents = list(TPB('https://mirror.example').search('no matching torrents'))

        self.assertEqual(torrents, [])
