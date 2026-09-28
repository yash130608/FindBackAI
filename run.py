import os,re,sqlite3,uuid
from datetime import datetime
from pathlib import Path
from flask import Flask,request,redirect,url_for,session,render_template,flash,jsonify
from werkzeug.security import generate_password_hash,check_password_hash
from werkzeug.utils import secure_filename

BASE=Path(__file__).resolve().parent
DB=BASE/'findback.db'; UP=BASE/'static'/'uploads'; UP.mkdir(parents=True,exist_ok=True)
app=Flask(__name__); app.secret_key='findback-ai-hackbios-2k26'; app.config['MAX_CONTENT_LENGTH']=5*1024*1024

SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'student',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,item_type TEXT NOT NULL,title TEXT NOT NULL,description TEXT,category TEXT NOT NULL,location TEXT NOT NULL,event_date TEXT NOT NULL,event_time TEXT,image_path TEXT,status TEXT DEFAULT 'open',created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL,claimant_id INTEGER NOT NULL,message TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT,FOREIGN KEY(item_id) REFERENCES items(id),FOREIGN KEY(claimant_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,message TEXT NOT NULL,item_id INTEGER,is_read INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id));
'''

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init():
    with db() as c:
        c.executescript(SCHEMA)
        if c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']==0:
            c.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',('Demo Student','student@findback.local',generate_password_hash('student123'),'student'))
            uid=c.execute("SELECT id FROM users WHERE email='student@findback.local'").fetchone()['id']
            demo=[('lost','Black Wallet','Black leather wallet with college ID slot.','Wallet','Central Library','2026-09-26','13:30'),('found','Black Leather Wallet','Found near library reading hall. Owner should verify.','Wallet','Central Library','2026-09-26','14:00'),('lost','Blue Water Bottle','Matte blue bottle with silver cap.','Bottle','Cafeteria','2026-09-27','12:15'),('found','Blue Steel Water Bottle','Blue bottle found beside cafeteria seating.','Bottle','Cafeteria','2026-09-27','12:40'),('lost','Wireless Earbuds','White earbuds in compact charging case.','Electronics','Computer Lab','2026-09-25','16:20'),('found','White Earbuds Case','White earbuds case near computer lab door.','Electronics','Computer Lab','2026-09-25','16:45')]
            c.executemany('INSERT INTO items(user_id,item_type,title,description,category,location,event_date,event_time) VALUES(?,?,?,?,?,?,?,?)',[(uid,)+x for x in demo])

def current():
    if not session.get('uid'): return None
    with db() as c:return c.execute('SELECT id,name,email,role FROM users WHERE id=?',(session['uid'],)).fetchone()

def toks(s): return set(x for x in re.findall(r'[a-z0-9]+',(s or '').lower()) if x not in {'the','a','an','and','or','is','are','my','i','lost','found','item','at','in','on','to','of','for','near','with'})
def sim(a,b):
    A,B=toks(a),toks(b); return len(A&B)/len(A|B) if A and B else 0
def dscore(a,b):
    try:
        d=abs((datetime.strptime(a,'%Y-%m-%d')-datetime.strptime(b,'%Y-%m-%d')).days); return 1 if d==0 else .8 if d==1 else .5 if d<=3 else 0
    except:return 0
def tscore(a,b):
    try:
        h1,m1=map(int,a.split(':'));h2,m2=map(int,b.split(':'));d=abs(h1*60+m1-h2*60-m2);return 1 if d<=30 else .7 if d<=120 else .3 if d<=300 else 0
    except:return 0
def score(l,f):
    cat=1 if l['category'].lower()==f['category'].lower() else sim(l['category'],f['category']);loc=1 if l['location'].lower()==f['location'].lower() else sim(l['location'],f['location'])
    return round((cat*.25+loc*.20+sim(l['title'],f['title'])*.20+sim(l['description'],f['description'])*.10+dscore(l['event_date'],f['event_date'])*.15+tscore(l['event_time'],f['event_time'])*.10)*100,1)
def slabel(s):return 'Strong match' if s>=78 else 'Possible match' if s>=55 else 'Low similarity'

def find_matches(iid):
    with db() as c:
        x=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone(); opp='found' if x['item_type']=='lost' else 'lost'; rows=c.execute("SELECT * FROM items WHERE item_type=? AND status='open' AND id!=?",(opp,iid)).fetchall()
        for y in rows:
            l,f=(x,y) if x['item_type']=='lost' else (y,x);s=score(l,f)
            if s>=55:c.execute('INSERT INTO notifications(user_id,title,message,item_id) VALUES(?,?,?,?)',(x['user_id'],'Possible match found',f'“{y["title"]}” scored {s}% ({slabel(s)}).',y['id']))

@app.context_processor
def inject():return {'current_user':current()}
@app.route('/')
def home():
    with db() as c:
        stats={k:c.execute(q).fetchone()['n'] for k,q in {'items':'SELECT COUNT(*) n FROM items','lost':"SELECT COUNT(*) n FROM items WHERE item_type='lost'",'found':"SELECT COUNT(*) n FROM items WHERE item_type='found'",'claims':'SELECT COUNT(*) n FROM claims'}.items()};recent=c.execute('SELECT items.*,users.name reporter FROM items JOIN users ON users.id=items.user_id ORDER BY items.id DESC LIMIT 6').fetchall()
    return render_template('index.html',stats=stats,recent=recent)
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        n=request.form.get('name','').strip();e=request.form.get('email','').strip().lower();p=request.form.get('password','')
        if not n or not e or len(p)<6:flash('Enter your name, email and a 6+ character password.','error');return redirect(url_for('register'))
        try:
            with db() as c:cur=c.execute('INSERT INTO users(name,email,password_hash) VALUES(?,?,?)',(n,e,generate_password_hash(p)));session['uid']=cur.lastrowid
            return redirect(url_for('dashboard'))
        except:flash('That email is already registered.','error')
    return render_template('auth.html',mode='register')
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        e=request.form.get('email','').strip().lower();p=request.form.get('password','')
        with db() as c:u=c.execute('SELECT * FROM users WHERE email=?',(e,)).fetchone()
        if u and check_password_hash(u['password_hash'],p):session['uid']=u['id'];return redirect(url_for('dashboard'))
        flash('Incorrect email or password.','error')
    return render_template('auth.html',mode='login')
@app.route('/logout')
def logout():session.clear();return redirect(url_for('home'))
@app.route('/dashboard')
def dashboard():
    if not current():return redirect(url_for('login'))
    u=current()
    with db() as c:
        items=c.execute('SELECT * FROM items WHERE user_id=? ORDER BY id DESC',(u['id'],)).fetchall();claims=c.execute('SELECT claims.*,items.title,items.user_id owner_id FROM claims JOIN items ON items.id=claims.item_id WHERE claims.claimant_id=? OR items.user_id=? ORDER BY claims.id DESC',(u['id'],u['id'])).fetchall();notes=c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 8',(u['id'],)).fetchall()
    return render_template('dashboard.html',items=items,claims=claims,notifications=notes)
@app.route('/report',methods=['GET','POST'])
def report():
    if not current():return redirect(url_for('login'))
    if request.method=='POST':
        vals=[request.form.get(x,'').strip() for x in ['title','description','category','location','event_date','event_time']];typ=request.form.get('item_type','lost');image=None;f=request.files.get('image')
        if f and f.filename and f.filename.rsplit('.',1)[-1].lower() in {'png','jpg','jpeg','webp'}:
            name=uuid.uuid4().hex+'_'+secure_filename(f.filename);f.save(UP/name);image='uploads/'+name
        if not vals[0] or not vals[3] or not vals[4]:flash('Title, location and date are required.','error');return redirect(url_for('report'))
        with db() as c:cur=c.execute('INSERT INTO items(user_id,item_type,title,description,category,location,event_date,event_time,image_path) VALUES(?,?,?,?,?,?,?,?,?)',(session['uid'],typ,*vals,image));iid=cur.lastrowid
        find_matches(iid);flash('Report submitted. FindBack AI is checking for matches.','success');return redirect(url_for('dashboard'))
    return render_template('report.html')
@app.route('/search')
def search():
    q=request.args.get('q','');cat=request.args.get('category','');loc=request.args.get('location','');typ=request.args.get('item_type','');sql='SELECT items.*,users.name reporter FROM items JOIN users ON users.id=items.user_id WHERE 1=1';p=[]
    if q:sql+=' AND (items.title LIKE ? OR items.description LIKE ? OR items.category LIKE ?)';p += [f'%{q}%']*3
    if cat:sql+=' AND items.category=?';p.append(cat)
    if loc:sql+=' AND items.location LIKE ?';p.append(f'%{loc}%')
    if typ:sql+=' AND items.item_type=?';p.append(typ)
    with db() as c:items=c.execute(sql+' ORDER BY items.id DESC',p).fetchall()
    return render_template('search.html',items=items,q=q,category=cat,location=loc,item_type=typ)
@app.route('/item/<int:iid>')
def item(iid):
    with db() as c:x=c.execute('SELECT items.*,users.name reporter FROM items JOIN users ON users.id=items.user_id WHERE items.id=?',(iid,)).fetchone();cs=c.execute("SELECT * FROM items WHERE item_type=? AND status='open' AND id!=?",('found' if x and x['item_type']=='lost' else 'lost',iid)).fetchall() if x else []
    if not x:return 'Item not found',404
    ms=[]
    for y in cs:
        l,f=(x,y) if x['item_type']=='lost' else (y,x);s=score(l,f)
        if s>=35:ms.append((s,y,slabel(s)))
    return render_template('item.html',item=x,matches=sorted(ms,key=lambda z:z[0],reverse=True)[:8])
@app.post('/claim/<int:iid>')
def claim(iid):
    if not current():return redirect(url_for('login'))
    with db() as c:
        x=c.execute('SELECT * FROM items WHERE id=?',(iid,)).fetchone()
        if not x:return 'Item not found',404
        if x['user_id']==session['uid']:flash('You cannot claim your own report.','error');return redirect(url_for('item',iid=iid))
        c.execute('INSERT INTO claims(item_id,claimant_id,message) VALUES(?,?,?)',(iid,session['uid'],request.form.get('message','')));c.execute('INSERT INTO notifications(user_id,title,message,item_id) VALUES(?,?,?,?)',(x['user_id'],'New claim request',f'Someone submitted a claim for “{x["title"]}”.',iid))
    flash('Claim submitted for owner verification.','success');return redirect(url_for('item',iid=iid))
@app.post('/claims/<int:cid>/status')
def claim_status(cid):
    if not current():return redirect(url_for('login'))
    st=request.form.get('status','pending')
    with db() as c:
        x=c.execute('SELECT claims.*,items.user_id owner_id,items.title FROM claims JOIN items ON items.id=claims.item_id WHERE claims.id=?',(cid,)).fetchone()
        if not x or x['owner_id']!=session['uid']:return 'Not allowed',403
        c.execute('UPDATE claims SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(st,cid))
        if st=='approved':c.execute("UPDATE items SET status='recovered' WHERE id=?",(x['item_id'],));msg='was approved.'
        else:msg='was not verified.'
        c.execute('INSERT INTO notifications(user_id,title,message,item_id) VALUES(?,?,?,?)',(x['claimant_id'],'Claim update',f'Your claim for “{x["title"]}” {msg}',x['item_id']))
    return redirect(url_for('dashboard'))
@app.post('/api/assistant')
def assistant():
    m=(request.json or {}).get('message','').lower()
    with db() as c:st={'items':c.execute('SELECT COUNT(*) n FROM items').fetchone()['n'],'claims':c.execute('SELECT COUNT(*) n FROM claims').fetchone()['n']}
    if any(x in m for x in ['hello','hi','hey']):r='Hi! I’m FindBack AI. I can help with reporting, search, matching, claims and verification.'
    elif 'report' in m:r='Open Report Item, choose Lost or Found, then add category, location, date/time, description and a photo if available.'
    elif 'match' in m:r='I compare category, location, title/description, date and time. Higher scores mean stronger similarity, but the owner still verifies.'
    elif 'claim' in m or 'verify' in m:r='Open a possible match and submit a claim with a detail only the genuine owner is likely to know. The reporter can verify it.'
    elif 'privacy' in m or 'safe' in m:r='Share only information needed for recovery. Never post passwords or bank details.'
    elif 'how many' in m or 'stats' in m:r=f'There are currently {st["items"]} item reports and {st["claims"]} claims in the demo database.'
    else:r='Try asking: How do I report an item? How does matching work? How do I claim an item?'
    return jsonify(reply=r)

if __name__=='__main__':init();app.run(debug=True)
else:init()
