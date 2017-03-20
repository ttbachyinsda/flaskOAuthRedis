"""
    GitHub Example
    --------------

    Shows how to authorize users with Github.

"""
from flask import Flask, request, g, session, redirect, url_for
from flask import render_template, render_template_string
from flask_github import GitHub
import redis
import json

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

DATABASE_URI = 'sqlite:////tmp/github-flask.db'
SECRET_KEY = 'development key'
DEBUG = True


# Set these values
GITHUB_CLIENT_ID = '4aa75bd221bc425050f4'
GITHUB_CLIENT_SECRET = '22c274f66b041681a28bc4a35e6a1dadd825f7ad'

# setup flask
app = Flask(__name__)
app.config.from_object(__name__)

# setup github-flask
github = GitHub(app)

# setup sqlalchemy
engine = create_engine(app.config['DATABASE_URI'])
db_session = scoped_session(sessionmaker(autocommit=False,
                                         autoflush=False,
                                         bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()



def init_db():
    Base.metadata.create_all(bind=engine)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(200))
    github_access_token = Column(String(200))

    def __init__(self, github_access_token):
        self.github_access_token = github_access_token


@app.before_request
def before_request():
    g.user = None
    if 'user_id' in session:
        g.user = User.query.get(session['user_id'])


@app.after_request
def after_request(response):
    db_session.remove()
    return response


@app.route('/')
def index():
    if g.user:
        return render_template('user2.html')
    else:
        return render_template('logined.html')


@github.access_token_getter
def token_getter():
    user = g.user
    if user is not None:
        return user.github_access_token


@app.route('/github-callback')
@github.authorized_handler
def authorized(access_token):
    next_url = request.args.get('next') or url_for('index')
    if access_token is None:
        return redirect(next_url)

    user = User.query.filter_by(github_access_token=access_token).first()
    if user is None:
        user = User(access_token)
        db_session.add(user)
    user.github_access_token = access_token
    db_session.commit()

    session['user_id'] = user.id
    return redirect(next_url)


@app.route('/login')
def login():
    if session.get('user_id', None) is None:
        return github.authorize()
    else:
        return 'Already logged in'


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))


@app.route('/user')
def user():
    text = github.get('user')
    return render_template('useremail.html', currentemail = text['email'])


@app.route('/search')
def search():
    value = request.args.get('subject','')
    subject = value
    if (subject == ''):
        return render_template_string('Wrong paramenters')
    r = redis.Redis(host='127.0.0.1', port=6379)
    s = str(r.get('##subject##'+subject))
    s = s.replace("\\'", "'")
    s = s[2:-1]
    list = json.loads(s)
    res = []
    for author in list.keys():
        res.append((float(list[author]), author))
    res = sorted(res, key = lambda e:e[0], reverse=True)
    html = ""
    for element in res:
        d = str(r.get('##authordataof##' + str(element[1])))
        d = d[2:-1]
        d = d.replace("\\'", "'")
        list = json.loads(d)
        name = list['name']
        hi = list['hi']
        html += '<a href="/getinfo?index='+str(element[1])+'">'+name+'    hi = '+str(hi)+'<br></a>'

    return render_template_string(html)


@app.route('/getinfo')
def getinfo():
    index = request.args.get('index','')
    if (index == ''):
        return render_template_string('Wrong paramenters')
    r = redis.Redis(host='127.0.0.1', port=6379)
    d = str(r.get('##authordataof##' + str(index)))
    d = d[2:-1]
    d = d.replace("\\'", "'")
    list = json.loads(d)
    name = list['name']
    af = list['af']
    pc = list['pc']
    cn = list['cn']
    hi = list['hi']
    pi = list['pi']
    upi = list['upi']
    t = list['t']
    s = str(r.get('##coauthorof##' + str(index)))
    s = s[2:-1]
    s = s.replace("\\'", "'")
    list = json.loads(s)
    html = ""
    html += 'index = '+str(index)+'<br>'
    html += 'name = '+str(name)+'<br>'
    html += 'affiliations = '+str(af)+'<br>'
    html += 'the count of published papers of this author = '+str(pc)+'<br>'
    html += 'the total number of citations of this author = '+str(cn)+'<br>'
    html += 'the H-index of this author = '+str(hi)+'<br>'
    html += 'the P-index with equal A-index of this author = '+str(pi)+'<br>'
    html += 'the P-index with unequal A-index of this author = '+str(upi)+'<br>'
    html += 'research interests of this author = '+str(t)+'<br>'
    html += 'coauthor of '+str(name)+' is :<br>'
    res = []
    for element in list.keys():
        res.append((int(list[element]),element))
    res = sorted(res, key = lambda e:e[0], reverse = True)
    for element in res:
        author = int(element[1])
        d = str(r.get('##authordataof##' + str(author)))
        d = d[2:-1]
        d = d.replace("\\'", "'")
        list = json.loads(d)
        html += list['name'] + ' cooperate time : '+str(element[0])+'<br>'

    return render_template_string(html)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0',port=80)
