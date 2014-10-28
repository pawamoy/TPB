from time import sleep
from os import path
from multiprocessing import Process

from bottle import Bottle, route, run, template, request, response, redirect, \
    TEMPLATE_PATH, view
from tpb.tpb import User

PRESETS_DIR = path.join(path.dirname(__file__), 'presets')
TEMPLATE_PATH.append(PRESETS_DIR)


def template_response(func):
    def wrapper(*args, **kwargs):
        filename = func(*args, **kwargs)
        with open(path.join(PRESETS_DIR, filename)) as f:
            content = f.read()
        return template(content)
    return wrapper


class TPBApp(Bottle):
    def __init__(self, host='localhost', port=8000):
        super(TPBApp, self).__init__()
        self.host = host
        self.port = port
        self.process = None
        self.users = []
        _user = User(base_url=self.url)
        _user.username = "testuser"
        _user.password = "testpassword"
        _user.current_ip = "1.2.3.4"
        _user.current_language = "English"
        _user.status = "MEMBER"
        _user.sort_order = 5
        _user.torrents = 0
        _user.comments = 0
        self.users.append(_user)
        self.current_user = None

    def run(self):
        run(self, host=self.host, port=self.port, debug=False, quiet=True)

    def start(self):
        self.process = Process(target=self.run)
        self.process.start()
        sleep(1)

    def stop(self):
        self.process.terminate()
        self.process = None

    @property
    def url(self):
        return 'http://{}:{}'.format(self.host, self.port)

tpb = TPBApp()


@tpb.route('/search/<query>/<page>/<ordering>/<category>')
@template_response
def search(**kwargs):
    return 'search.html'


@tpb.route('/recent/<page>')
@template_response
def recent(**kwargs):
    return 'recent.html'


@tpb.route('/top/<category>')
@template_response
def top(**kwargs):
    return 'top.html'


@tpb.route('/torrent/<id>/<name>')
@template_response
def torrent(**kwargs):
    return 'torrent.html'


@tpb.route('/ajax_details_filelist.php')
@template_response
def files(**kwargs):
    return 'files.html'


@tpb.route('/logout')
def logout():
    tpb.current_username = None
    response.status = 302
    tpb.current_user = None


@tpb.get('/settings')
@view('settings')
def settings():
    return dict(user=tpb.current_user)


@tpb.post('/settings')
def settings():
    show_porn = request.forms.get("show_porn")
    pw_old = request.forms.get("pw_old")
    pw_new = request.forms.get("pw_new")
    pw_new2 = request.forms.get("pw_new2")
    sort_order = request.forms.get("setSortOrder")
    if not show_porn:
        return
    if pw_old == tpb.current_user.password and pw_new == pw_new2:
        tpb.current_user.password = pw_new
    tpb.current_user.sort_order = int(sort_order)


@tpb.post('/login')
@template_response
def login():
    username = request.forms.get("username")
    password = request.forms.get("password")
    act = request.forms.get("act")
    for user in tpb.users:
        if(act, username, password) == ("login", user.username, user.password):
            tpb.current_user = user
            redirect("/settings", 302)
            return
    return 'loginfail.html'


if __name__ == '__main__':
    tpb.run()
