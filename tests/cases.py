import unittest
from functools import wraps
from urllib2 import urlopen, URLError

from server import TPBApp


def remote_func(func):
    """
    Skip func if remote url is not available.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        f = unittest.skipUnless(self._is_remote_available,
                'Remote URL {} is not available'.format(self.url))(func)
        return f(self, *args, **kwargs)
    return wrapper


class RemoteTestMetaclass(type):
    """
    Duplicate all tests so every test is executed with local and remote urls.
    """
    def __new__(cls, clsname, bases, dct):
        attrs = {}
        for attr, value in dct.items():
            if attr.startswith('test') and hasattr(value, '__call__'):
                attrs[attr+'_local'] = value
                attrs[attr+'_remote'] = remote_func(value)
            else:
                attrs[attr] = value
        return super(RemoteTestMetaclass, cls).__new__(cls, clsname, bases, attrs)


class RemoteTestCase(unittest.TestCase):
    __metaclass__ = RemoteTestMetaclass

    def run(self, *args, **kwargs):
        """
        Set url to local or remote depending of function name.
        """
        if self._testMethodName.endswith('_local'):
            self.url = self.local
        elif self._testMethodName.endswith('_remote'):
            self.url = self.remote
        super(RemoteTestCase, self).run(*args, **kwargs)

    @classmethod
    def setUpClass(cls):
        """
        Start local server and setup local and remote urls defaulting to local
        one.
        """
        cls.server = TPBApp('localhost', 8000)
        cls.server.start()
        cls.remote = 'http://thepiratebay.sx'
        cls.local = cls.server.url

    @classmethod
    def tearDownClass(cls):
        """
        Stop local server.
        """
        cls.server.stop()

    @property
    def _is_remote_available(self):
        """
        Check connectivity to remote.
        """
        try:
            urlopen(self.remote)
        except URLError:
            return False
        else:
            return True
