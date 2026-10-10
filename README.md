![TPB](http://www.goel.im/images/tpb.jpg)

Unofficial Python API for [ThePirateBay](http://thepiratebay.org/).

This project was forked from the original one as it was not maintained anymore.

| Build Status | Test Coverage | Version | Downloads (30 days) |
| ------------ | ------------- | ------- | ------------------- |
| [![Build Status](https://travis-ci.org/pawamoy/TPB.png?branch=master)](https://travis-ci.org/pawamoy/TPB) | [![Coverage Status](https://coveralls.io/repos/pawamoy/TPB/badge.png)](https://coveralls.io/r/pawamoy/TPB) | [![Latest Version](https://img.shields.io/pypi/v/ThePirateBay.svg)](https://pypi.python.org/pypi/ThePirateBay/) | [![Downloads](https://img.shields.io/pypi/dm/ThePirateBay.svg)](https://pypi.python.org/pypi/ThePirateBay/) |

Installation
============
```sh
$ pip install tpb
```

Note that ``ThePirateBay`` depends on ``lxml``. If you run into problems in the compilation of ``lxml`` through ``pip``, install the ``libxml2-dev`` and ``libxslt-dev`` packages on your system.

Usage
=====

To configure mirrors, create a UTF-8 file with one HTTP(S) site root per line:

```text
https://thepiratebay.org
https://tpbay.site
https://tpbay.win
```

Run the CLI to test the URLs and cache the ranking:

```sh
tpb rank-mirrors mirrors.txt
# The same command is available without a console script:
python -m tpb rank-mirrors mirrors.txt
```

Blank lines and lines starting with `#` are ignored. Duplicate URLs are tested once.
The CLI requires parseable results for its probe query, then ranks working mirrors by total probe time.
JavaScript mirrors also need an accessible JSON API; the default is `https://apibay.org`.
Use `--api-url URL`, `--query TEXT`, or `--timeout SECONDS` to change the probe settings.
Failed probes appear after working mirrors. If every probe fails, the previous cache is kept and the command exits with status 1.

`platformdirs` selects the cache directory. On Linux, the ranking is saved to `$XDG_CACHE_HOME/tpb/mirrors.json` or `~/.cache/tpb/mirrors.json`.
After configuration, construct `TPB()` without a URL:

```python
from tpb import TPB

for torrent in TPB().search('public domain'):
    print(torrent.title)
```

`TPB()` reads the cache without making requests. Lists try working mirrors in rank order and switch mirrors when requests or parsing fail.
An empty search result does not trigger a switch. For JavaScript mirrors, lists also check that the mirror's search page still works.
The cache does not expire automatically. Update the URL file and run the ranking command again when mirrors break.
If the cache is missing or invalid, `TPB()` raises an error with the configuration command.
An explicit `base_url` bypasses the cache; an explicit `api_url` overrides cached API settings.

To choose a site and API explicitly:

```python
from tpb import TPB
from tpb import CATEGORIES, ORDERS

t = TPB('https://thepiratebay.org', api_url='https://apibay.org')

# search for 'public domain' in 'movies' category
search = t.search('public domain', category=CATEGORIES.VIDEO.MOVIES)

# return listings from page 2 of this search
search.page(2)

# sort this search by count of seeders, and return a multipage result
search.order(ORDERS.SEEDERS.ASC).multipage()

# search, order by seeders and return page 3 results
t.search('python').order(ORDERS.SEEDERS.ASC).page(3)

# multipage beginning on page 4
t.search('recipe book').page(4).multipage()

# search, in a category and return multipage results
t.search('something').category(CATEGORIES.OTHER.OTHER).multipage()

# get page 3 of recent torrents
t.recent().page(3)

# get top torrents in Movies category
t.top().category(CATEGORIES.VIDEO.MOVIES)

# print all torrent descriptions
for torrent in t.search('public domain'):
    print(torrent.info)

# print all torrent files and their sizes
for torrent in t.search('public domain'):
    print(torrent.files)
```

The current site loads torrent data with JavaScript. Set `api_url` to an accessible Apibay-compatible JSON API.
The `base_url` argument controls torrent page links; requests for torrent data go to `api_url`.
For an older mirror that serves HTML tables, omit `api_url`.
Lists raise request and parsing errors instead of returning empty results when a request fails.

In API mode, search and recent results use pages of 30 torrents, starting at page 0.
Sorting and pagination apply to the results returned by the API. `multipage()` stops after those results.
The API can limit the number of results; pagination cannot retrieve results beyond that limit.
The API does not provide torrent file links, comment counts, or cover information.
These attributes use `None`, `0`, and `'No'`, respectively.

Torrent details available
=========================

Attributes
----------

* **title** # the title of the torrent
* **url** # TPB url for the torrent
* **category** # the main category
* **sub_category** # the sub category
* **magnet_link** # magnet download link
* **torrent_link** # .torrent download link
* **created** # uploaded date time
* **size** # size of torrent
* **user** # username of uploader
* **seeders** # number of seeders
* **leechers** # number of leechers

Properties
----------

* **created** # creation date -- parsed when accessed
* **info** # detailed torrent description -- *needs separate request*
* **files** # dictionary of files and their size -- *needs separate request*

Tests
=====

Tests can be ran using `tox`.
```sh
$ pip install tox
$ tox
```

Alternatively, you will need to install dependencies manually:
```sh
$ pip install -r tests/requirements.txt
```

Then, to execute the tests simply run:
```sh
$ python -m unittest discover
```

By default the tests are ran on a local test server with predownloaded original
responses. You can activate the remote running option by:
```sh
$ REMOTE=true python -m unittest discover
```

Donations
=========

If *TPB* has helped you in any way, and you'd like to help the original author, please consider donating.

**- BTC: [19dLDL4ax7xRmMiGDAbkizh6WA6Yei2zP5](http://i.imgur.com/bAQgKLN.png)**

**- Gratipay: [https://www.gratipay.com/karan/](https://www.gittip.com/karan/)**

**- Flattr: [https://flattr.com/profile/thekarangoel](https://flattr.com/profile/thekarangoel)**

Contribute
==========

If you want to add any new features, or improve existing ones, feel free to send a pull request!
