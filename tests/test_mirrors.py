from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from requests import Response
from requests.exceptions import ConnectionError

from tpb import CATEGORIES, ORDERS, TPB
from tpb.cli import main
from tpb.mirrors import cache_path, load_mirrors, rank_mirrors, read_urls, save_ranking
from tests.test_api import json_response, torrent_record


def html_response(preset=None, text=None, status=200):
    response = Response()
    response.status_code = status
    response.encoding = 'utf-8'
    response._content = (Path(__file__).with_name('presets') / preset).read_bytes() if preset else text.encode('utf-8')
    return response


def working_mirror(base_url='https://mirror.example', api_url=None, elapsed=1):
    return dict(base_url=base_url, api_url=api_url, elapsed=elapsed, status='ok')


class MirrorCacheTestCase(unittest.TestCase):

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        cache_directory = patch('tpb.mirrors.user_cache_path', return_value=self.directory / 'tpb')
        cache_directory.start()
        self.addCleanup(cache_directory.stop)

    def test_read_urls_ignores_comments_blanks_and_duplicates(self):
        filename = self.directory / 'mirrors.txt'
        filename.write_text('# My mirrors\n\n HTTPS://Mirror.Example/ \nhttps://mirror.example\nhttps://second.example\n', encoding='utf-8-sig')

        urls = read_urls(filename)

        self.assertEqual(urls, ['https://mirror.example', 'https://second.example'])

    def test_read_urls_reports_invalid_url_and_line_number(self):
        filename = self.directory / 'mirrors.txt'
        filename.write_text('https://mirror.example\nfile:///tmp/mirror\n', encoding='utf-8')

        with self.assertRaisesRegex(ValueError, 'mirrors.txt:2:'):
            read_urls(filename)

    def test_empty_url_file_is_an_error(self):
        filename = self.directory / 'mirrors.txt'
        filename.write_text('# No candidates\n\n', encoding='utf-8')

        with self.assertRaisesRegex(ValueError, 'no mirrors'):
            read_urls(filename)

    def test_cache_round_trip_keeps_rank_order_and_backend(self):
        results = [
            working_mirror('https://fast.example', api_url='https://api.example', elapsed=0.5),
            working_mirror('https://slow.example', elapsed=2),
            dict(base_url='https://broken.example', api_url=None, status='failed', elapsed=0.1, error='unreachable'),
        ]

        path = save_ranking(results)
        mirrors = load_mirrors()

        self.assertEqual(path, self.directory / 'tpb' / 'mirrors.json')
        self.assertEqual(mirrors, [
            dict(base_url='https://fast.example', api_url='https://api.example'),
            dict(base_url='https://slow.example', api_url=None),
        ])
        self.assertEqual(json.loads(path.read_text())['results'], results)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_all_failed_probes_keep_previous_cache(self):
        path = save_ranking([working_mirror()])
        original = path.read_bytes()
        results = [dict(base_url='https://broken.example', status='failed', elapsed=1, error='unreachable')]

        with self.assertRaisesRegex(ValueError, 'previous cache was kept'):
            save_ranking(results)

        self.assertEqual(path.read_bytes(), original)

    def test_failed_atomic_write_keeps_previous_cache(self):
        path = save_ranking([working_mirror()])
        original = path.read_bytes()

        with patch('tpb.mirrors.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                save_ranking([working_mirror('https://new.example')])

        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_default_client_loads_cache_without_requests(self):
        save_ranking([working_mirror(api_url='https://api.example')])

        with patch('tpb.tpb.get', side_effect=AssertionError('unexpected network request')):
            with patch('tpb.api.get', side_effect=AssertionError('unexpected API request')):
                client = TPB()

        self.assertEqual(client.base_url, 'https://mirror.example')
        self.assertEqual(client.api_url, 'https://api.example')

    def test_explicit_url_bypasses_cache(self):
        with patch('tpb.tpb.load_mirrors', side_effect=AssertionError('unexpected cache access')):
            client = TPB('https://explicit.example')

        self.assertEqual(client.base_url, 'https://explicit.example')
        self.assertIsNone(client.api_url)

    def test_explicit_api_overrides_cached_backend(self):
        save_ranking([working_mirror(api_url='https://old-api.example')])

        client = TPB(api_url='https://new-api.example')
        with patch('tpb.tpb.get', return_value=html_response('modern_search.html')):
            with patch('tpb.api.get', return_value=json_response([torrent_record()])) as request:
                torrents = list(client.search('public domain'))

        self.assertEqual(len(torrents), 1)
        self.assertTrue(request.call_args.args[0].startswith('https://new-api.example/'))

    def test_missing_or_invalid_cache_explains_configuration(self):
        with self.assertRaisesRegex(RuntimeError, 'tpb rank-mirrors urls.txt'):
            TPB()

        path = save_ranking([working_mirror()])
        for content in ['not JSON', '{}', '[]', '{"version": 2, "results": []}', '{"version": 1, "results": []}']:
            with self.subTest(content=content):
                path.write_text(content, encoding='utf-8')

                with self.assertRaisesRegex(RuntimeError, 'tpb rank-mirrors urls.txt'):
                    TPB()

    def test_search_falls_back_and_preserves_query_options(self):
        save_ranking([working_mirror('https://broken.example'), working_mirror('https://working.example')])
        search = TPB().search('tpb afk').category(CATEGORIES.VIDEO.MOVIES).order(ORDERS.SEEDERS.ASC).page(2)

        with patch('tpb.tpb.get', side_effect=[ConnectionError('unreachable'), html_response('search.html')]) as request:
            torrents = list(search)

        self.assertEqual(len(torrents), 30)
        self.assertTrue(all(str(torrent.url).startswith('https://working.example/') for torrent in torrents))
        self.assertEqual([call.args[0] for call in request.call_args_list], [
            'https://broken.example/search/tpb%20afk/2/8/201',
            'https://working.example/search/tpb%20afk/2/8/201',
        ])

    def test_broken_javascript_mirror_falls_back_even_when_api_works(self):
        save_ranking([
            working_mirror('https://broken.example', api_url='https://api.example'),
            working_mirror('https://working.example', api_url='https://api.example'),
        ])
        responses = [html_response(text='Not found', status=404), html_response('modern_search.html')]

        with patch('tpb.tpb.get', side_effect=responses) as mirror_request:
            with patch('tpb.api.get', return_value=json_response([torrent_record()])) as api_request:
                torrents = list(TPB().search('public domain'))

        self.assertEqual(str(torrents[0].url), 'https://working.example/torrent.html?id=1')
        self.assertEqual(mirror_request.call_count, 2)
        self.assertEqual(api_request.call_count, 1)

    def test_bad_api_rows_do_not_yield_duplicates_before_fallback(self):
        save_ranking([
            working_mirror('https://first.example', api_url='https://bad-api.example'),
            working_mirror('https://second.example', api_url='https://good-api.example'),
        ])
        responses = [
            json_response([torrent_record(2), torrent_record(1, category='invalid')]),
            json_response([torrent_record(2), torrent_record(1)]),
        ]

        with patch('tpb.tpb.get', return_value=html_response('modern_search.html')):
            with patch('tpb.api.get', side_effect=responses):
                torrents = list(TPB().search('public domain'))

        self.assertEqual([torrent.id for torrent in torrents], ['2', '1'])
        self.assertTrue(all(str(torrent.url).startswith('https://second.example/') for torrent in torrents))

    def test_empty_results_do_not_try_another_mirror(self):
        save_ranking([working_mirror('https://first.example'), working_mirror('https://second.example')])
        response = html_response(text='<html><table id="searchResult"><tr><th>Name</th></tr></table></html>')

        with patch('tpb.tpb.get', return_value=response) as request:
            torrents = list(TPB().search('no matching torrents'))

        self.assertEqual(torrents, [])
        self.assertEqual(request.call_count, 1)

    def test_multipage_keeps_using_the_mirror_that_succeeded(self):
        save_ranking([
            working_mirror('https://first.example', api_url='https://bad-api.example'),
            working_mirror('https://second.example', api_url='https://good-api.example'),
        ])
        records = [torrent_record(number) for number in range(1, 36)]
        responses = [ConnectionError('unreachable')] + [json_response(records)] * 3

        with patch('tpb.tpb.get', return_value=html_response('modern_search.html')):
            with patch('tpb.api.get', side_effect=responses) as request:
                torrents = list(TPB().search('public domain', multipage=True))

        self.assertEqual(len(torrents), 35)
        self.assertEqual(len({torrent.id for torrent in torrents}), 35)
        self.assertEqual(request.call_count, 4)
        self.assertTrue(all(call.args[0].startswith('https://good-api.example/') for call in request.call_args_list[1:]))

    def test_all_cached_mirrors_failing_raise_an_actionable_error(self):
        save_ranking([working_mirror('https://first.example'), working_mirror('https://second.example')])

        with patch('tpb.tpb.get', side_effect=ConnectionError('unreachable')):
            with self.assertRaisesRegex(RuntimeError, 'All cached mirrors failed.*rank-mirrors'):
                list(TPB().search('public domain'))

    def test_recent_and_top_use_fallback_mirrors(self):
        save_ranking([working_mirror('https://first.example'), working_mirror('https://second.example')])
        client = TPB()

        for listing, preset, count in [(client.recent(), 'recent.html', 30), (client.top(), 'top.html', 100)]:
            with self.subTest(preset=preset):
                with patch('tpb.tpb.get', side_effect=[ConnectionError('unreachable'), html_response(preset)]):
                    torrents = list(listing)

                self.assertEqual(len(torrents), count)
                self.assertTrue(all(str(torrent.url).startswith('https://second.example/') for torrent in torrents))

    def test_cli_ranks_saves_and_default_client_uses_the_cache(self):
        filename = self.directory / 'mirrors.txt'
        filename.write_text('https://mirror.example\n', encoding='utf-8')
        output = io.StringIO()

        with patch('tpb.mirrors.get', return_value=html_response('search.html')):
            with redirect_stdout(output):
                status = main(['rank-mirrors', str(filename)])
        client = TPB()

        self.assertEqual(status, 0)
        self.assertIn('OK', output.getvalue())
        self.assertIn('Saved ranking to', output.getvalue())
        self.assertEqual(client.base_url, 'https://mirror.example')
        self.assertIsNone(client.api_url)

    def test_cli_reports_failures_and_preserves_existing_cache(self):
        path = save_ranking([working_mirror()])
        original = path.read_bytes()
        filename = self.directory / 'mirrors.txt'
        filename.write_text('https://broken.example\n', encoding='utf-8')
        output, errors = io.StringIO(), io.StringIO()

        with patch('tpb.mirrors.get', side_effect=ConnectionError('unreachable')):
            with redirect_stdout(output), redirect_stderr(errors):
                status = main(['rank-mirrors', str(filename)])

        self.assertEqual(status, 1)
        self.assertIn('FAILED https://broken.example', output.getvalue())
        self.assertIn('previous cache was kept', errors.getvalue())
        self.assertEqual(path.read_bytes(), original)

    def test_cli_invalid_file_and_timeout_are_errors(self):
        with redirect_stderr(io.StringIO()):
            status = main(['rank-mirrors', str(self.directory / 'missing.txt')])
        self.assertEqual(status, 1)

        for timeout in ['0', '-1', 'nan', 'inf', 'not-a-number']:
            with self.subTest(timeout=timeout):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main(['rank-mirrors', 'urls.txt', '--timeout', timeout])

                self.assertEqual(error.exception.code, 2)


class MirrorProbeTestCase(unittest.TestCase):

    def test_rank_successes_by_elapsed_time_and_failures_last(self):
        urls = ['https://slow.example', 'https://broken.example', 'https://fast.example']
        outcomes = [None, ConnectionError('unreachable'), 'https://api.example']

        with patch('tpb.mirrors.probe_mirror', side_effect=outcomes):
            with patch('tpb.mirrors.time.monotonic', side_effect=[0, 3, 3, 3.1, 3.1, 4.1]):
                results = rank_mirrors(urls)

        self.assertEqual([result['base_url'] for result in results], ['https://fast.example', 'https://slow.example', 'https://broken.example'])
        self.assertEqual([result['status'] for result in results], ['ok', 'ok', 'failed'])
        self.assertEqual(results[0]['api_url'], 'https://api.example')

    def test_legacy_mirror_must_have_parseable_torrents(self):
        with patch('tpb.mirrors.get', return_value=html_response('search.html')):
            results = rank_mirrors(['https://mirror.example'])

        self.assertEqual(results[0]['status'], 'ok')
        self.assertIsNone(results[0]['api_url'])

    def test_modern_mirror_uses_configured_api_and_timeout(self):
        responses = [html_response(text='Not found', status=404), html_response('modern_search.html')]

        with patch('tpb.mirrors.get', side_effect=responses) as mirror_request:
            with patch('tpb.api.get', return_value=json_response([torrent_record()])) as api_request:
                results = rank_mirrors(['https://mirror.example'], api_url='https://api.example', timeout=2)

        self.assertEqual(results[0]['status'], 'ok')
        self.assertEqual(results[0]['api_url'], 'https://api.example')
        self.assertEqual(mirror_request.call_args.kwargs['timeout'], 2)
        self.assertEqual(api_request.call_args.kwargs['timeout'], 2)

    def test_http_200_landing_page_is_not_a_working_mirror(self):
        with patch('tpb.mirrors.get', return_value=html_response(text='<html>Domain for sale</html>')):
            results = rank_mirrors(['https://parked.example'])

        self.assertEqual(results[0]['status'], 'failed')
        self.assertIn('no supported torrent listing', results[0]['error'])

    def test_modern_page_with_broken_or_empty_api_is_not_ranked_as_working(self):
        for response in [json_response([], status=429), json_response([]), json_response({'error': 'broken'})]:
            with self.subTest(response=response):
                with patch('tpb.mirrors.get', return_value=html_response('modern_search.html')):
                    with patch('tpb.api.get', return_value=response):
                        results = rank_mirrors(['https://mirror.example'])

                self.assertEqual(results[0]['status'], 'failed')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'XDG cache paths apply on Linux')
    def test_cache_path_respects_xdg_cache_home(self):
        with TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'XDG_CACHE_HOME': directory}):
                path = cache_path()

            self.assertEqual(path, Path(directory) / 'tpb' / 'mirrors.json')
            self.assertFalse(path.parent.exists())
