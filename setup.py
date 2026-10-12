#!/usr/bin/env python

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='tpb',
    version='1.4.0',
    install_requires=['purl', 'dateutils', 'lxml', 'cssselect', 'requests', 'platformdirs'],
    entry_points={'console_scripts': ['tpb=tpb.cli:main']},
    author='Karan Goel',
    author_email='karan@goel.im',
    packages=['tpb', 'tests'],
    test_suite='tests',
    url='https://github.com/pawamoy/TPB/',
    license='MIT License',
    description='Unofficial Python API for ThePirateBay.',
    long_description='Unofficial Python API for ThePirateBay.',
    classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Programming Language :: Python :: 3.15',
        'Topic :: Internet :: WWW/HTTP :: Browsers',
        'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
        'Topic :: Utilities',
    ],
)
