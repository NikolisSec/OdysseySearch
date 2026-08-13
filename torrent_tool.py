#!/usr/bin/env python3
"""Torrent Tool - TUI + CLI torrent search + Real-Debrid downloader"""
import os, sys, sqlite3, json, re, hashlib, base64, urllib.parse
import requests, time, shutil, argparse, threading, math
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

APP_DIR = Path.home() / ".torrent_tool"; APP_DIR.mkdir(exist_ok=True)
DB_PATH = APP_DIR / "settings.db"
DL_DIR  = Path.home() / "Downloads" / "TorrentTool"; DL_DIR.mkdir(exist_ok=True)
SALT_FILE = APP_DIR / ".salt"; KEY_FILE = APP_DIR / ".key"
HEADERS = {"User-Agent": "Mozilla/5.0 Gecko Firefox/128.0"}
TIMEOUT = 25

def _dk():
    if KEY_FILE.exists(): return KEY_FILE.read_bytes()
    mid = hashlib.sha256(os.environ.get('COMPUTERNAME','').encode()).digest()
    if not SALT_FILE.exists(): SALT_FILE.write_bytes(os.urandom(16))
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT_FILE.read_bytes(), iterations=600_000)
    key = base64.urlsafe_b64encode(kdf.derive(mid)); KEY_FILE.write_bytes(key); return key

class DB:
    """One hidden sqlite database for everything local: config (encrypted secrets),
    search history, a downloads log, a blacklist, and a tiny TTL cache.
    Lives in ~/.torrent_tool so it never leaks into the repo."""
    def __init__(self):
        self._lock = threading.Lock()
        self.c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, v TEXT, enc INTEGER DEFAULT 0)")
        self.c.execute("CREATE TABLE IF NOT EXISTS history (q TEXT PRIMARY KEY, ts REAL)")
        self.c.execute("CREATE TABLE IF NOT EXISTS downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, title TEXT, path TEXT, size INTEGER, status TEXT)")
        self.c.execute("CREATE TABLE IF NOT EXISTS blacklist (ih TEXT PRIMARY KEY, reason TEXT, ts REAL)")
        self.c.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, expires REAL)")
        self.c.commit()
        self._migrate_history()
        self._rearm_secrets()
    def _rearm_secrets(self):
        # if a plaintext token survived from before we added encryption, lock it up.
        # one-time, invisible, and the whole point of a hidden db is not leaking it.
        try:
            r = self.c.execute("SELECT v,enc FROM config WHERE k='rd_api_token'").fetchone()
            if r and not r[1]:
                self.c.execute("INSERT OR REPLACE INTO config(k,v,enc) VALUES(?,?,?)",
                               ("rd_api_token", Fernet(_dk()).encrypt(r[0].encode()).decode(), 1))
                self.c.commit()
        except Exception:
            pass
    def _migrate_history(self):
        # history used to be a JSON blob in config; fold it into the real table once
        try:
            raw = self.c.execute("SELECT v FROM config WHERE k='history'").fetchone()
            if raw:
                now = time.time()
                for i, q in enumerate(json.loads(raw[0])):
                    self.c.execute("INSERT OR REPLACE INTO history(q,ts) VALUES(?,?)", (q, now - i))
                self.c.execute("DELETE FROM config WHERE k='history'")
                self.c.commit()
        except Exception:
            pass
    def get(self,k,d=None):
        with self._lock: r=self.c.execute("SELECT v,enc FROM config WHERE k=?",(k,)).fetchone()
        return Fernet(_dk()).decrypt(r[0].encode()).decode() if (r and r[1]) else (r[0] if r else d)
    def set(self,k,v,e=True):
        with self._lock: self.c.execute("INSERT OR REPLACE INTO config(k,v,enc) VALUES(?,?,?)",(k,Fernet(_dk()).encrypt(v.encode()).decode() if e else v,1 if e else 0)); self.c.commit()
    def rmv(self,k):
        with self._lock: self.c.execute("DELETE FROM config WHERE k=?",(k,)); self.c.commit()
    def query(self,sql,params=()):
        with self._lock: return self.c.execute(sql,params).fetchall()
    def execute(self,sql,params=()):
        with self._lock: self.c.execute(sql,params); self.c.commit()

db = DB()

def hist_get():
    """Search history, newest first (max 50)."""
    try: return [r[0] for r in db.query("SELECT q FROM history ORDER BY ts DESC LIMIT 50")]
    except Exception: return []

def hist_add(q):
    if not q: return
    try: db.execute("INSERT OR REPLACE INTO history(q,ts) VALUES(?,?)", (q, time.time()))
    except Exception: pass

def hist_clear():
    try: db.execute("DELETE FROM history")
    except Exception: pass

# ── local db extras: blacklist / prefs / downloads log / ttl cache ──
def blk_add(ih, reason="manual"):
    try: db.execute("INSERT OR REPLACE INTO blacklist(ih,reason,ts) VALUES(?,?,?)", (ih, reason, time.time()))
    except Exception: pass
def blk_get():
    try: return {r[0] for r in db.query("SELECT ih FROM blacklist")}
    except Exception: return set()
def blk_list():
    try: return db.query("SELECT ih,reason,ts FROM blacklist ORDER BY ts DESC")
    except Exception: return []
def blk_wipe():
    try: db.execute("DELETE FROM blacklist")
    except Exception: pass

def pref_get(k, d=None):
    try: return db.get("pref:"+k, d)
    except Exception: return d
def pref_set(k, v):
    try: db.set("pref:"+k, str(v), e=False)
    except Exception: pass
def apply_prefs():
    """Re-read persistent prefs into module globals (call once at startup)."""
    global DL_DIR
    d = pref_get("dl_dir")
    if d:
        DL_DIR = Path(d); DL_DIR.mkdir(exist_ok=True)

def dl_log(title, path=None, size=None, status="ok"):
    try: db.execute("INSERT INTO downloads(ts,title,path,size,status) VALUES(?,?,?,?,?)",
                    (time.time(), str(title)[:300], path, size, status))
    except Exception: pass
def dl_history(limit=20):
    try: return db.query("SELECT ts,title,path,size,status FROM downloads ORDER BY id DESC LIMIT ?", (max(1,limit),))
    except Exception: return []

def cache_get(k):
    try:
        r = db.query("SELECT v,expires FROM cache WHERE k=?", (k,))
        if not r: return None
        if r[0][1] and time.time() > r[0][1]:
            db.execute("DELETE FROM cache WHERE k=?", (k,)); return None
        return r[0][0]
    except Exception: return None
def cache_set(k, v, ttl=43200):  # 12h default: what's cached today might change tomorrow
    try: db.execute("INSERT OR REPLACE INTO cache(k,v,expires) VALUES(?,?,?)", (k, v, time.time()+ttl))
    except Exception: pass

def fs(b):
    for u in ['B','KB','MB','GB','TB']:
        if b<1024: return f"{b:.1f} {u}"
        b/=1024
    return f"{b:.1f} PB"

def tr(s,n): return (str(s or ''))[:n]+('...' if len(str(s or ''))>n else '')

SIZE_RE = re.compile(r'([\d.]+)\s*([KMGT]i?B|B)', re.I)
def parse_size(s):
    """'624.0 MiB' -> bytes (0 if unparseable)."""
    m=SIZE_RE.search(str(s or ''))
    if not m: return 0
    u=m.group(2).upper().replace('I','')
    return int(float(m.group(1))*{'B':1,'KB':1024,'MB':1024**2,'GB':1024**3,'TB':1024**4}.get(u,1))

def intx(s):
    """'3,205' -> 3205 (0 if no digits)."""
    d=re.sub(r'[^\d]','',str(s or ''))
    return int(d) if d else 0

BTIH_RE = re.compile(r'xt=urn:btih:([a-zA-Z0-9]{32,40})', re.I)
TRACKERS = ("&tr=udp://tracker.opentrackr.org:1337/announce"
            "&tr=udp://open.stealth.si:80/announce"
            "&tr=udp://exodus.desync.com:6969/announce"
            "&tr=udp://tracker.torrent.eu.org:451/announce")
def magnet_for(ih): return f"magnet:?xt=urn:btih:{ih}{TRACKERS}" if ih else ""

# ── Category badges (name heuristics; first match wins) ──
CAT_RULES = [
    ("🌸", re.compile(r'^\[(erai|subsplease|.*raws|.*subs)\]', re.I)),                      # weebs get their own badge. you're welcome.
    ("📺", re.compile(r'\bs\d{1,2}e\d{1,2}\b|\bseason\s*\d+\b|hdtv|\bcomplete\s+series\b', re.I)),
    ("🎬", re.compile(r'\b(1080p|2160p|720p|480p|blu[\- ]?ray|bdrip|web[\- ]?dl|webrip|dvdrip|hdrip|remux|x264|x265|hevc)\b', re.I)),
    ("🎮", re.compile(r'\b(fitgirl|reloaded|codex|razor1911|skidrow|repack|steamrip|elamigos|dodi)\b', re.I)),
    ("🎵", re.compile(r'\b(flac|mp3|320kbps|discography|soundtrack|vinyl)\b|\bost\b', re.I)),
    ("📚", re.compile(r'\b(epub|mobi|azw3|ebook|audiobook|m4b)\b', re.I)),
    ("💾", re.compile(r'\b(crack|keygen|portable|activated|iso)\b', re.I)),
]
def cat_badge(name):
    """Emoji badge guessed from the release name ('·' if unknown)."""
    for b, rx in CAT_RULES:
        if rx.search(str(name or '')): return b
    return "·"

# ── Search ──
def search_solidtorrents(q,n=30):
    r=[]
    try:
        u=f"https://solidtorrents.to/api/v1/search?q={urllib.parse.quote(q)}&sort=seeders&order=desc&limit={n}"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code==429: time.sleep(3); resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        for h in resp.json().get('results',[]):
            ih=h.get('infohash','')
            r.append({'n':h.get('title','?'),'s':int(h.get('seeders',0)),'l':int(h.get('leechers',0)),
                      'sz':fs(int(h.get('size',0))),'szr':int(h.get('size',0)),'src':'SolidTorrents',
                      'mag':f"magnet:?xt=urn:btih:{ih}" if ih else'',
                      'web':f"https://solidtorrents.to/torrents/{h.get('id','')}"})
    except: pass
    return r

def search_tpb(q,n=30):
    """ThePirateBay via the official apibay.org JSON API (info_hash, seeders, size)."""
    r=[]
    try:
        u=f"https://apibay.org/q.php?q={urllib.parse.quote(q)}"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        data=resp.json()
        if not isinstance(data,list): return r
        for h in data[:n]:
            name=h.get('name','')
            if not name or name=='No results returned': continue
            sz=int(h.get('size',0) or 0)
            r.append({'n':name,'s':intx(h.get('seeders')),'l':intx(h.get('leechers')),
                      'sz':fs(sz),'szr':sz,'src':'TPB',
                      'mag':magnet_for(h.get('info_hash','')),
                      'web':f"https://thepiratebay.org/description.php?id={h.get('id','')}"})
    except: pass
    return r

def search_1337x(q,n=30):
    r=[]
    try:
        u=f"https://1377x.to/search/{urllib.parse.quote(q)}/1/"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
        if resp.status_code!=200: return r
        import bs4
        for row in bs4.BeautifulSoup(resp.text,'html.parser').select('tbody tr')[:n]:
            cols=row.select('td')
            if len(cols)<5: continue
            ne=cols[0].select_one('a:nth-of-type(2)')
            if not ne: continue
            s=int(cols[1].text.strip()) if cols[1].text.strip().isdigit() else 0
            l=int(cols[2].text.strip()) if cols[2].text.strip().isdigit() else 0
            r.append({'n':ne.text.strip(),'s':s,'l':l,'sz':cols[4].text.strip(),'szr':0,'src':'1337x','web':'https://1377x.to'+ne['href']})
    except: pass
    return r

def search_torrentscsv(q,n=30):
    """torrents-csv.com JSON API (infohash, seeders, size)."""
    r=[]
    try:
        u=f"https://torrents-csv.com/service/search?q={urllib.parse.quote(q)}"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        for h in resp.json().get('torrents',[])[:n]:
            sz=int(h.get('size_bytes',0) or 0)
            r.append({'n':h.get('name','?'),'s':int(h.get('seeders',0)),'l':int(h.get('leechers',0)),
                      'sz':fs(sz),'szr':sz,'src':'TorrentsCSV',
                      'mag':magnet_for(h.get('infohash','')),'web':''})
    except: pass
    return r

def search_nyaa(q,n=30):
    """Nyaa.si scrape (anime/general; magnets inline)."""
    r=[]
    try:
        u=f"https://nyaa.si/?f=0&c=0_0&q={urllib.parse.quote(q)}&s=seeders&o=desc"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        import bs4
        for row in bs4.BeautifulSoup(resp.text,'html.parser').select('table.torrent-list tbody tr')[:n]:
            tds=row.select('td')
            if len(tds)<7: continue
            links=tds[1].select('a')
            if not links: continue
            ne=links[-1]; me=row.select_one('a[href^="magnet:"]')
            sz=tds[3].text.strip()
            r.append({'n':ne.text.strip(),'s':intx(tds[5].text),'l':intx(tds[6].text),
                      'sz':sz,'szr':parse_size(sz),'src':'Nyaa',
                      'mag':me['href'] if me else '',
                      'web':'https://nyaa.si'+ne.get('href','')})
    except: pass
    return r

def search_bitsearch(q,n=30):
    """BitSearch scrape (magnets inline; stats parsed from card text)."""
    r=[]
    try:
        u=f"https://bitsearch.to/search?q={urllib.parse.quote(q)}&sort=seeders"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
        if resp.status_code!=200: return r
        import bs4
        soup=bs4.BeautifulSoup(resp.text,'html.parser')
        base=resp.url.split('/search')[0]
        for a in soup.select('h3 a[href^="/torrent/"]')[:n]:
            card=a.find_parent('div',class_='p-6')
            if not card: continue
            me=card.select_one('a[href^="magnet:"]')
            txts=list(card.stripped_strings)
            def stat(label):
                try: return intx(txts[txts.index(label)-1])
                except: return 0
            szm=re.search(r'([\d.]+\s*[KMGT]i?B)',' '.join(txts))
            sz=szm.group(1) if szm else '?'
            r.append({'n':a.text.strip(),'s':stat('seeders'),'l':stat('leechers'),
                      'sz':sz,'szr':parse_size(sz),'src':'BitSearch',
                      'mag':me['href'] if me else '','web':base+a.get('href','')})
    except: pass
    return r

def search_torlock(q,n=30):
    """Torlock scrape (no inline magnets; details page has them -> lazy fetch)."""
    r=[]
    try:
        u=f"https://www.torlock.com/all/torrents/{urllib.parse.quote(q)}.html?sort=seeds"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        import bs4
        cnt=0
        for row in bs4.BeautifulSoup(resp.text,'html.parser').select('table.tl-list tr'):
            if cnt>=n: break
            tds=row.select('td')
            if len(tds)<5: continue
            ne=tds[0].select_one('a')
            if not ne: continue
            idm=re.search(r'/torrent/(\d+)/',ne.get('href',''))
            sz=tds[2].text.strip()
            r.append({'n':ne.text.strip(),'s':intx(tds[3].text),'l':intx(tds[4].text),
                      'sz':sz,'szr':parse_size(sz),'src':'Torlock','mag':'',
                      'web':f"https://www.torlock.com/torrent/{idm.group(1)}/x.html" if idm else ''})
            cnt+=1
    except: pass
    return r

def search_lime(q,n=30):
    """LimeTorrents scrape (no inline magnets; details page has them -> lazy fetch)."""
    r=[]
    try:
        u=f"https://www.limetorrents.lol/search/all/{urllib.parse.quote(q)}/seeds/1/"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
        if resp.status_code!=200: return r
        import bs4
        soup=bs4.BeautifulSoup(resp.text,'html.parser')
        base=resp.url.split('/search')[0]
        cnt=0
        for row in soup.select('table.table2 tr'):
            if cnt>=n: break
            tds=row.select('td')
            if len(tds)<5: continue
            ne=tds[0].select_one('a[href$=".html"]')
            if not ne: continue
            sz=tds[2].text.strip()
            web=ne.get('href','')
            r.append({'n':ne.text.strip(),'s':intx(tds[3].text),'l':intx(tds[4].text),
                      'sz':sz,'szr':parse_size(sz),'src':'Lime','mag':'',
                      'web':web if web.startswith('http') else base+web})
            cnt+=1
    except: pass
    return r

# Engine registry — the gang's all here. order = display order of per-engine counts.
ENGINES = [("SolidTorrents", search_solidtorrents),
           ("TPB",          search_tpb),
           ("1337x",        search_1337x),
           ("TorrentsCSV",  search_torrentscsv),
           ("Nyaa",         search_nyaa),
           ("BitSearch",    search_bitsearch),
           ("Torlock",      search_torlock),
           ("Lime",         search_lime)]
# Engines whose results carry no magnet (fetched lazily from the details page).
NO_MAGNET_ENGINES = {"1337x", "Torlock", "Lime"}

def dedupe_sort(all_r):
    """Same hash, different trenchcoat -> one row, many sources ('TPB+1337x').
    Dedupes by infohash (fallback: name hash), keeps the highest-seeded copy,
    backfills magnet/web/size. Sorted by seeders desc."""
    best={}
    for r in all_r:
        m=BTIH_RE.search(r.get('mag') or '')
        key='ih:'+m.group(1).lower() if m else 'n:'+hashlib.md5(r['n'][:80].lower().encode()).hexdigest()
        r['_id']=key
        cur=best.get(key)
        if cur is None:
            best[key]=r; continue
        keep,drop=(r,cur) if r['s']>cur['s'] else (cur,r)
        if drop['src'] not in keep['src'].split('+'): keep['src']=keep['src']+'+'+drop['src']
        if not keep.get('mag') and drop.get('mag'): keep['mag']=drop['mag']
        if not keep.get('web') and drop.get('web'): keep['web']=drop['web']
        if not keep.get('szr') and drop.get('szr'): keep['sz'],keep['szr']=drop['sz'],drop['szr']
        best[key]=keep
    return sorted(best.values(), key=lambda x: x['s'], reverse=True)

def parse_query(q):
    """Extract filter tokens from a query. Supports: min:SEEDS. Returns (clean_query, min_seeds)."""
    min_seeds=0; toks=[]
    for t in q.split():
        m=re.match(r'min:(\d+)$',t,re.I)
        if m: min_seeds=int(m.group(1))
        else: toks.append(t)
    return ' '.join(toks), min_seeds

def smart_score(r, qtokens, qfull):
    """Relevance + seeders. spam farms hate this one weird trick."""
    tl=r['n'].lower()
    matched=sum(1 for t in qtokens if t in tl)
    rel=matched/max(len(qtokens),1)
    if qfull and qfull in tl: rel+=0.5
    return rel*100 + math.log10(1+r['s'])*25

# SEO-bait titles ([REAL]! Full Version!! Direct Download!!1). torlock, we're looking at you.
JUNK_RE = re.compile(r'(\[real\]|\bfull version\b|\bhigh-definition\b|\blatest top release\b|\bdirect download\b)', re.I)

def rank_filter(results, query='', sort='smart', min_seeds=0, src=None, cached=None):
    """Filter (bait titles / blacklisted / min seeders / source / cached-only) and sort
    (smart|seeds|size|name) a result list."""
    blk = blk_get()
    out=[r for r in results if r['s']>=min_seeds and (not src or src in r['src'])
         and not JUNK_RE.search(r['n']) and r.get('_id') not in blk
         and (not cached or r.get('rd_cached'))]
    if sort=='seeds': out.sort(key=lambda x: x['s'], reverse=True)
    elif sort=='size': out.sort(key=lambda x: x['szr'], reverse=True)
    elif sort=='name': out.sort(key=lambda x: x['n'].lower())
    else:
        qt=[t for t in re.split(r'\s+',query.lower().strip()) if t]; qf=query.lower().strip()
        out.sort(key=lambda x: smart_score(x,qt,qf), reverse=True)
    return out

def fetch_magnet(url):
    """Scrape a details page for its magnet. Some trackers hide it there like
    it's a treasure hunt. it's not fun treasure. it's just an extra request."""
    if not url: return None
    try:
        resp=requests.get(url,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
        m=re.search(r'href="(magnet:\?xt=urn:btih:[^"]+)"',resp.text)
        return m.group(1) if m else None
    except: return None

def search_all(query):
    results_q=[]
    def _run(name,fn):
        res=fn(query)
        if name in NO_MAGNET_ENGINES:  # prefetch magnets for top results (details-page scrape)
            s=requests.Session(); s.headers.update(HEADERS)
            for x in res[:6]:
                if not x.get('mag') and x.get('web'):
                    try:
                        resp=s.get(x['web'],timeout=TIMEOUT,allow_redirects=True)
                        m=re.search(r'href="(magnet:\?xt=urn:btih:[^"]+)"',resp.text)
                        if m: x['mag']=m.group(1)
                    except: pass
                    time.sleep(0.25)
        results_q.append((name,len(res),res))

    threads=[threading.Thread(target=_run,args=e,daemon=True) for e in ENGINES]
    for t in threads: t.start()
    si=0
    while any(t.is_alive() for t in threads):
        done=len(results_q); dots='.'*(si%3+1)
        sys.stderr.write(f"\rSearching{dots}{' '*(3-len(dots))} {done}/{len(ENGINES)} engines  "); sys.stderr.flush()
        si+=1; time.sleep(0.2)
    sys.stderr.write(f"\r{' '*40}\r"); sys.stderr.flush()
    for t in threads: t.join()

    all_r=[]; counts={}
    for name,cnt,res in results_q: counts[name]=cnt; all_r.extend(res)
    return dedupe_sort(all_r),counts

# ── RD ──
def rd_request(method, path, data=None):
    """Call the Real-Debrid API. Never raises: returns {} for empty bodies (204),
    or {"error": ...} on HTTP/network/JSON failures."""
    token = db.get("rd_api_token")
    if not token: return {"error": "RD token not configured. Run: torrent_tool.py token <your-token>"}
    h = {"Authorization": f"Bearer {token}"}
    u = f"https://api.real-debrid.com/rest/1.0{path}"
    try:
        if method == "GET": r = requests.get(u, headers=h, timeout=TIMEOUT)
        elif method == "POST": r = requests.post(u, data=data, headers=h, timeout=TIMEOUT)
        elif method == "DELETE": r = requests.delete(u, headers=h, timeout=TIMEOUT)
        else: return {"error": f"bad method {method}"}
    except requests.RequestException as e:
        return {"error": f"network: {e}"}
    if r.status_code not in (200, 201, 204): return {"error": r.text}
    if not r.content: return {}  # 204 No Content
    try: return r.json()
    except ValueError: return {}

def rd_stats():
    """Normalized RD account stats. fun fact: 'premium' comes back in SECONDS,
    because days would be too easy. /traffic is a per-hoster dict, so we sum
    'left' over gigabytes-type hosters. Returns None on error."""
    u = rd_request("GET", "/user")
    if "error" in u: return None
    traf = rd_request("GET", "/traffic")
    gb = 0.0
    if isinstance(traf, dict) and "error" not in traf:
        for h in traf.values():
            if isinstance(h, dict) and h.get("type") == "gigabytes":
                gb += h.get("left", 0) / 1073741824
    tor = rd_request("GET", "/torrents")
    return {"username": u.get("username", "?"),
            "premium_days": int(u.get("premium", 0)) // 86400,
            "points": u.get("points", u.get("fidelityPoints", 0)),
            "traffic_gb": gb,
            "torrents": len(tor) if isinstance(tor, list) else 0,
            "expiration": u.get("expiration", "")}

def rd_user():
    s = rd_stats()
    if not s: return {"error": "could not reach RD"}
    return (f"User: {s['username']} | Premium: {s['premium_days']}d | Points: {s['points']} "
            f"| Traffic: {s['traffic_gb']:.0f}GB | Torrents: {s['torrents']}")

def rd_add_magnet(m):
    r = rd_request("POST", "/torrents/addMagnet", {"magnet": m})
    tid = r.get("id")
    if not tid: return None, r.get("error","unknown")
    rd_request("POST", f"/torrents/selectFiles/{tid}", {"files": "all"})
    return tid, None

def rd_wait(tid, timeout=600):
    start=time.time(); errs=0
    while time.time()-start<timeout:
        info=rd_request("GET",f"/torrents/info/{tid}")
        if "error" in info:
            errs+=1
            if errs>=5: return None
            time.sleep(2); continue
        errs=0
        s=info.get("status","")
        if s=="downloaded":
            links=[]
            for lu in info.get("links",[]):
                ur=rd_request("POST","/unrestrict/link",{"link":lu})
                if "download" in ur: links.append({"f":ur.get("filename","?"),"sz":ur.get("filesize",0),"u":ur["download"]})
            return links
        if s in("magnet_error","error","virus","dead"): return None
        pct=info.get("progress",0)
        spd=info.get("speed",0)/1048576
        sys.stderr.write(f"\rCaching... {pct:.0f}% @ {spd:.1f} MB/s  "); sys.stderr.flush()
        time.sleep(1.5)
    return None

def rd_instant(hashes):
    """Which of these infohashes are already sitting in RD's cache?
    One batched GET, hashes comma-separated (the API allows ~50). Returns a
    set of cached hashes (lowercased). Never raises."""
    token = db.get("rd_api_token")
    if not token or not hashes: return set()
    h = {"Authorization": f"Bearer {token}"}
    u = f"https://api.real-debrid.com/rest/1.0/torrents/instantAvailability/{','.join(x.lower() for x in hashes)}"
    try:
        r = requests.get(u, headers=h, timeout=TIMEOUT)
        if r.status_code != 200: return set()
        return {hs.lower() for hs, v in r.json().items() if v}
    except (requests.RequestException, ValueError):
        return set()

def stamp_cached(results, maxn=40):
    """Best-effort: mark rows that are instant-available on RD with rd_cached=True.
    Checks the top maxn rows (the ones worth clicking), batches 50 hashes/call,
    and remembers each hash in the local cache for 12h so repeat searches are free.
    Never raises — if RD is missing or grumpy, the ⚡ badges just don't show up."""
    token = db.get("rd_api_token")
    if not token or not results: return
    want = {}
    for r in results[:maxn]:
        m = BTIH_RE.search(r.get("mag") or "")
        if m and r.get("_id"): want[r["_id"]] = m.group(1).lower()
    if not want: return
    rowmap = {r.get("_id"): r for r in results if r.get("_id")}
    miss = []
    for rid, hsh in want.items():
        c = cache_get("inst:" + hsh)
        if c == "1": rowmap[rid]["rd_cached"] = True
        elif c is None: miss.append((rid, hsh))   # "0" = known-not-cached, skip
    for i in range(0, len(miss), 50):
        got = rd_instant([h for _, h in miss[i:i+50]])
        for rid, hsh in miss[i:i+50]:
            hit = hsh in got
            cache_set("inst:" + hsh, "1" if hit else "0", ttl=43200)
            if hit and rid in rowmap: rowmap[rid]["rd_cached"] = True

def rd_list():
    tor=rd_request("GET","/torrents")
    if "error" in tor: print(f"Error: {tor['error']}"); return
    tbs=rd_request("GET","/traffic")
    left=tbs.get("left",0)/1073741824 if "left" in tbs else 0
    print(f"Traffic remaining: {left:.0f} GB")
    print(f"Cached torrents: {len(tor)}")
    for i,t in enumerate(tor):
        print(f"  [{i}] {tr(t.get('filename','?'),60)}  {t.get('status','?')}  {t.get('progress',0)}%  {fs(t.get('bytes',0))}")

def rd_delete(idx):
    tor=rd_request("GET","/torrents")
    if "error" in tor: print(f"Error: {tor['error']}"); return
    if 0<=idx<len(tor):
        rd_request("DELETE",f"/torrents/delete/{tor[idx]['id']}")
        print(f"Deleted: {tor[idx].get('filename','?')[:60]}")

# ── Download ──
def download_file(url, fn, cb=None):
    """Download url to DL_DIR (atomic: .part -> rename). cb(dl_bytes, total_bytes, speed_mbps)
    is called on progress; when cb is None, a CLI progress bar goes to stderr instead.
    Returns saved path. Raises on HTTP/network errors (no more error-pages-saved-as-movies)."""
    dest=DL_DIR
    fn=re.sub(r'[<>:"/\\|?*]','_',fn).strip() or "download.bin"
    # windows still thinks 260 chars is plenty of path. it is not. trim the novel.
    if len(fn)>150:
        stem,_,ext=fn.rpartition('.')
        fn=(stem[:150]+'.'+ext) if ext and len(ext)<=10 else fn[:150]
    stem0,_,ext0=fn.rpartition('.')
    ext0=('.'+ext0) if ext0 else ''
    last=None
    for attempt in (1,2):  # one retry, because CDNs have moods
        tmp=None
        try:
            r=requests.get(url,stream=True,timeout=60)
            r.raise_for_status()
            total=int(r.headers.get('content-length',0))
            fp=dest/fn
            if fp.exists() and total and fp.stat().st_size==total:
                if cb: cb(total,total,0)
                else: print(f"Already complete: {fn}")
                dl_log(fn, str(fp), total, "ok")
                return str(fp)
            n=1
            while fp.exists():  # same name, different file -> don't clobber
                n+=1; fp=dest/f"{stem0} ({n}){ext0}"
            if not cb: print(f"Downloading: {fp.name}")
            dl=0; t0=time.time(); tmp=fp.with_name(fp.name+'.part')
            with open(tmp,'wb') as f:
                for c in r.iter_content(65536):
                    if c: f.write(c); dl+=len(c)
                    elapsed=max(time.time()-t0,0.001); speed=dl/elapsed/1048576
                    if cb: cb(dl,total,speed)
                    elif total:
                        pct=dl/total*100; bar_w=30; fw=int(bar_w*dl/total)
                        bar='#'*fw+'-'*(bar_w-fw)
                        sys.stderr.write(f"\r[{bar}] {pct:.0f}%  {dl/1048576:.0f}/{total/1048576:.0f}MB  {speed:.1f}MB/s  "); sys.stderr.flush()
            if total and dl<total: raise IOError(f"incomplete download ({dl}/{total} bytes)")
            tmp.replace(fp)  # atomic: no half-downloaded files cosplaying as complete ones
            dl_log(fp.name, str(fp), total, "ok")
            if cb: return str(fp)
            print(f"\nSaved: {fp}")
            return str(fp)
        except (requests.RequestException, IOError) as e:
            last=e
            if tmp: 
                try: tmp.unlink()
                except OSError: pass
            if attempt==1: time.sleep(2)
    raise last

# ── CLI ──
def cmd_search(args):
    if not args.query:
        print("Usage: torrent_tool.py search <query> [--sort smart|seeds|size|name] [--min-seeds N] [--cached]"); return
    query,ms=parse_query(args.query)
    min_seeds=args.min_seeds or ms
    print(f"Searching for: {query}")
    results,counts=search_all(query)
    stamp_cached(results)  # ⚡ instant on RD?
    if args.cached and not db.get("rd_api_token"):
        print("(cached filter needs an RD token: torrent_tool.py token <token>)")
    results=rank_filter(results,query,sort=args.sort,min_seeds=min_seeds,cached=args.cached)
    if not results: print("No results."); return
    srcs=" | ".join(f"{k}: {v}" for k,v in counts.items())
    print(f"\n{len(results)} results ({srcs}) sort={args.sort} min_seeds={min_seeds}{' cached-only' if args.cached else ''}\n")
    hist_add(query)
    for i,r in enumerate(results[:args.limit]):
        badge="⚡" if r.get("rd_cached") else " "
        print(f"[{i:>3}] {badge} {cat_badge(r['n'])} {r['s']:>5}S {r['l']:>5}L  {r['sz']:>10}  {r['src']:<20}  {tr(r['n'],60)}")
        if args.detail:
            if r.get('mag'): print(f"      magnet: {r['mag'][:70]}...")
            if r.get('web'): print(f"      web: {r['web']}")
    if args.download is not None:
        idx=args.download
        if 0<=idx<len(results): cmd_download_from_result(results[idx])

def cmd_download_from_result(r):
    token=db.get("rd_api_token")
    if not token:
        print("Error: RD token not set. Run: torrent_tool.py token <your-token>")
        if r.get('mag'): print(f"Magnet: {r['mag']}")
        return
    if not r.get('mag') and r.get('web'):
        print("Fetching magnet from details page...")
        r['mag']=fetch_magnet(r['web']) or ''
    if not r.get('mag'): print("No magnet link available."); return
    print(f"Adding to RD: {tr(r['n'],60)}")
    tid,err=rd_add_magnet(r['mag'])
    if not tid: print(f"Error: {err}"); return
    print(f"ID: {tid} | Caching...")
    links=rd_wait(tid)
    if links is None: print("Failed: torrent could not be downloaded"); return
    print(f"\nReady! {len(links)} file(s):")
    for i,lk in enumerate(links):
        sz=f"({lk['sz']/1048576:.0f}MB)" if lk['sz'] else ""
        print(f"  [{i}] {tr(lk['f'],55)} {sz}")
    print()

def cmd_download(args):
    if not args.url:
        print("Usage: torrent_tool.py download <magnet-link>"); return
    print(f"Adding to RD...")
    tid,err=rd_add_magnet(args.url)
    if not tid: print(f"Error: {err}"); return
    print(f"ID: {tid} | Caching...")
    links=rd_wait(tid)
    if links is None: print("Failed"); return
    print(f"\nReady! {len(links)} file(s):")
    for i,lk in enumerate(links):
        sz=f"({lk['sz']/1048576:.0f}MB)" if lk['sz'] else ""
        print(f"  [{i}] {tr(lk['f'],55)} {sz}")
    if args.get:
        all_links=links
        if args.get!="all":
            try:
                indices=[int(x) for x in args.get.split(",")]
                all_links=[links[i] for i in indices if 0<=i<len(links)]
            except: pass
        for lk in all_links:
            try:
                download_file(lk['u'],lk['f'])
            except Exception as e:
                dl_log(lk['f'], None, None, f"error: {str(e)[:120]}")
                print(f"Failed: {lk['f']} ({e})")

def cmd_token(args):
    if not args.token:
        print("Usage: torrent_tool.py token <api-token>")
        current=db.get("rd_api_token")
        if current: print(f"Current token: {current[:12]}...{current[-4:]}")
        return
    db.set("rd_api_token",args.token)
    r=rd_request("GET","/user")
    if "error" in r: print(f"Invalid token: {r['error']}"); db.rmv("rd_api_token")
    else: print(f"Token saved. User: {r['username']} | Premium: {r['premium']}d")

def cmd_status(args):
    s=rd_stats()
    if not s:
        print("RD: not connected (check token / network)")
        return
    print(f"User:     {s['username']}")
    print(f"Premium:  {s['premium_days']} days (expires {s['expiration'][:10] or '?'})")
    print(f"Points:   {s['points']}")
    print(f"Traffic:  {s['traffic_gb']:.0f} GB remaining (hoster limits)")
    print(f"Torrents: {s['torrents']} cached")

def cmd_rd(args):
    if args.delete is not None:
        rd_delete(args.delete)
    else:
        rd_list()

# ── TUI (textual) ──
try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal
    from textual.screen import ModalScreen
    from textual.widgets import (DataTable, Footer, Input, Label, OptionList,
                                 ProgressBar, Static)
    from textual.widgets.option_list import Option
    from rich.text import Text
    TUI_OK = True
except ImportError:
    TUI_OK = False

if TUI_OK:
    SRC_STYLE = {"SolidTorrents": "#39c5cf", "TPB": "#bc8cff", "1337x": "#f0883e",
                 "TorrentsCSV": "#2ea043", "Nyaa": "#f778ba", "BitSearch": "#58a6ff",
                 "Torlock": "#ff7b72", "Lime": "#7ee787"}
    SORT_MODES = ["smart", "seeds", "size", "name"]

    def _seeds_cell(v):
        st = "bold #3fb950" if v >= 100 else ("#3fb950" if v > 0 else "#f85149")
        return Text(str(v), style=st, justify="right")

    def _leech_cell(v):
        return Text(str(v), style="#d29922" if v else "#6e7681", justify="right")

    class TokenScreen(ModalScreen):
        """Modal for entering / validating the Real-Debrid API token."""
        CSS = """
        TokenScreen { align: center middle; }
        #token-box { width: 74; height: auto; background: #161b22; border: round #58d6eb; padding: 1 3; }
        #token-box Label { margin-bottom: 1; }
        #token-input { border: round #30363d; background: #0d1117; }
        #token-input:focus { border: round #58d6eb; }
        """
        BINDINGS = [Binding("escape", "cancel", "Cancel")]

        def compose(self) -> ComposeResult:
            with Container(id="token-box"):
                yield Label("[bold #7ee787]🔑 Real-Debrid API token[/]")
                yield Label("[#8b949e]Get yours at [u]https://real-debrid.com/apitoken[/u][/]")
                yield Input(placeholder="Paste token, press Enter…", password=True, id="token-input")
                yield Label("", id="token-error")

        def on_mount(self): self.query_one("#token-input", Input).focus()
        def action_cancel(self): self.dismiss(None)

        def on_input_submitted(self, event):
            tok = event.value.strip()
            if not tok: return
            self.query_one("#token-error", Label).update("[#8b949e]Checking…[/]")
            self._validate(tok)

        @work(thread=True, group="token", exclusive=True)
        def _validate(self, tok):
            try:
                r = requests.get("https://api.real-debrid.com/rest/1.0/user",
                                 headers={"Authorization": f"Bearer {tok}"}, timeout=TIMEOUT)
                user = r.json().get("username") if r.status_code == 200 else None
            except Exception:
                user = None
            self.app.call_from_thread(self._done, tok if user else None, user)

        def _done(self, tok, user):
            if tok:
                db.set("rd_api_token", tok)
                self.dismiss(user)
            else:
                self.query_one("#token-error", Label).update("[#f85149]✗ Invalid token — try again.[/]")

    class FilesScreen(ModalScreen):
        """Modal listing unrestricted RD files; pick one or all to download."""
        CSS = """
        FilesScreen { align: center middle; }
        #files-box { width: 90; max-width: 95%; height: auto; background: #161b22; border: round #3fb950; padding: 1 3; }
        #files-list { height: auto; max-height: 18; background: #0d1117; border: round #30363d; margin: 1 0; }
        """
        BINDINGS = [Binding("escape", "cancel", "Close"), Binding("a", "all", "Download all")]

        def __init__(self, links): super().__init__(); self.links = links

        def compose(self) -> ComposeResult:
            with Container(id="files-box"):
                yield Label(f"[bold #3fb950]✓ Cached on Real-Debrid[/]  [#8b949e]— {len(self.links)} file(s) ready[/]")
                yield OptionList(*[Option(f"[#e6edf3]{tr(l['f'], 62)}[/]  [#8b949e]({fs(l['sz'])})[/]") for l in self.links], id="files-list")
                yield Label("[#8b949e]Enter = download file · a = download all · Esc = keep in cloud[/]")

        def on_mount(self): self.query_one("#files-list", OptionList).focus()
        def on_option_list_option_selected(self, event): self.dismiss(event.option_index)
        def action_all(self): self.dismiss("all")
        def action_cancel(self): self.dismiss(None)

    class RDScreen(ModalScreen):
        """Modal listing torrents cached on Real-Debrid (x to delete)."""
        CSS = """
        RDScreen { align: center middle; }
        #rd-box { width: 100; max-width: 95%; height: auto; background: #161b22; border: round #bc8cff; padding: 1 3; }
        #rd-table { height: auto; max-height: 20; background: #0d1117; border: round #30363d; margin: 1 0; }
        """
        BINDINGS = [Binding("escape", "cancel", "Close"), Binding("x", "delete", "Delete")]

        def __init__(self): super().__init__(); self._tor = []

        def compose(self) -> ComposeResult:
            with Container(id="rd-box"):
                yield Label("[bold #bc8cff]☁ Real-Debrid cloud[/]")
                yield DataTable(id="rd-table", cursor_type="row", zebra_stripes=True)
                yield Label("[#8b949e]x = delete selected · Esc = close[/]")

        def on_mount(self):
            self.query_one("#rd-table", DataTable).add_columns("#", "Name", "Status", "%", "Size")
            self._load()

        @work(thread=True, group="rdlist", exclusive=True)
        def _load(self):
            tor = rd_request("GET", "/torrents")
            self.app.call_from_thread(self._fill, tor if isinstance(tor, list) else [])

        def _fill(self, tor):
            self._tor = tor
            t = self.query_one("#rd-table", DataTable)
            t.clear()
            for i, x in enumerate(tor):
                t.add_row(Text(str(i), style="#8b949e"),
                          Text(tr(x.get("filename", "?"), 54)),
                          x.get("status", "?"),
                          Text(f"{x.get('progress', 0)}%", justify="right"),
                          Text(fs(x.get("bytes", 0)), justify="right"),
                          key=str(i))

        def action_cancel(self): self.dismiss(None)

        def action_delete(self):
            idx = self.query_one("#rd-table", DataTable).cursor_row
            if 0 <= idx < len(self._tor):
                self._delete(self._tor[idx]["id"])

        @work(thread=True, group="rdlist", exclusive=True)
        def _delete(self, tid):
            rd_request("DELETE", f"/torrents/delete/{tid}")
            tor = rd_request("GET", "/torrents")
            self.app.call_from_thread(self._fill, tor if isinstance(tor, list) else [])

    HELP_TEXT = """\
[bold #7ee787]⚡ TORRENT TOOL[/]  [#8b949e]— keyboard shortcuts[/]

[bold #79c0ff]SEARCH[/]
  [#58d6eb]/[/]          focus search box
  [#58d6eb]Enter[/]      run search
  [#58d6eb]↑ / ↓[/]      previous searches
  [#58d6eb]min:N[/]      in query → hide below N seeders

[bold #79c0ff]RESULTS[/]
  [#58d6eb]↑ / ↓[/]      navigate
  [#58d6eb]Enter[/]      download this torrent
  [#58d6eb]Space[/]      mark / unmark (multi-download)
  [#58d6eb]Esc[/]        clear marks
  [#58d6eb]o[/]          sort: smart → seeds → size → name
  [#58d6eb]f[/]          filter by source
  [#58d6eb]c[/]          toggle ⚡ cached-only (instant on RD)
  [#58d6eb]C[/]          clear all filters
  [#58d6eb]x[/]          hide this result (persisted)
  [#58d6eb]m[/]          copy magnet link
  [#8b949e]⚡ in the table = already in RD's cache → instant download[/]

[bold #79c0ff]REAL-DEBRID[/]
  [#58d6eb]t[/]          set API token
  [#58d6eb]r[/]          cloud contents (x = delete)
  [#58d6eb]s[/]          refresh account info

[bold #79c0ff]APP[/]
  [#58d6eb]?[/]          this help
  [#58d6eb]q[/]          quit

[#8b949e]Esc closes this window[/]"""

    class HelpScreen(ModalScreen):
        """Keybinding cheat-sheet (? to open, Esc to close)."""
        CSS = """
        HelpScreen { align: center middle; }
        #help-box { width: 62; height: auto; background: #161b22; border: round #f778ba; padding: 1 3; }
        """
        BINDINGS = [Binding("escape", "cancel", "Close"), Binding("question_mark", "cancel", "Close", show=False)]
        def compose(self) -> ComposeResult:
            with Container(id="help-box"):
                yield Static(HELP_TEXT)
        def action_cancel(self): self.dismiss(None)

    class TorrentApp(App):
        """⚡ Torrent Tool — interactive terminal UI."""
        TITLE = "Torrent Tool"
        CSS = """
        Screen { background: #0d1117; }
        #topbar { height: 3; background: #161b22; border-bottom: solid #30363d; padding: 0 2; }
        #app-title { width: 1fr; padding-top: 1; }
        #rd-status { width: auto; padding-top: 1; }
        #search { margin: 1 2 0 2; border: round #30363d; background: #161b22; }
        #search:focus { border: round #58d6eb; }
        #results { margin: 1 2 0 2; border: round #30363d; background: #0d1117; }
        #results:focus { border: round #58d6eb; }
        DataTable > .datatable--header { background: #161b22; color: #79c0ff; text-style: bold; }
        DataTable > .datatable--cursor { background: #16375c; }
        #bottombar { height: 3; padding: 1 2 0 2; }
        #status { width: 1fr; color: #8b949e; padding-top: 1; }
        #pbar { width: 44; padding-top: 1; }
        ProgressBar > .bar--complete { color: #3fb950; }
        ProgressBar > .bar--bar { color: #21262d; }
        Footer { background: #161b22; }
        """
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("question_mark", "help", "Help"),
            Binding("slash", "focus_search", "Search"),
            Binding("space", "mark", "Mark"),
            Binding("d", "download", "Download"),
            Binding("o", "sort", "Sort"),
            Binding("f", "filter_src", "Filter"),
            Binding("c", "toggle_cached", "Cached"),
            Binding("x", "hide", "Hide"),
            Binding("t", "token", "Token"),
            Binding("r", "rd", "RD cloud"),
            Binding("m", "copy_magnet", "Copy magnet", show=False),
            Binding("shift+c", "clear_filters", "Clear", show=False),
            Binding("s", "status", "Refresh", show=False),
            Binding("escape", "clear_marks", show=False),
            Binding("up", "hist_prev", show=False),
            Binding("down", "hist_next", show=False),
        ]

        def __init__(self):
            super().__init__()
            self.results = []      # all deduped results from last search
            self.view = []         # filtered/sorted rows currently shown
            self.query = ""
            self.sort_mode = "smart" if pref_get("sort", "smart") not in SORT_MODES else pref_get("sort", "smart")
            self.src_filter = None
            self.min_seeds = 0
            self.cached_only = False
            self._counts = {}
            self.marked = set()    # _id set of multi-selected rows
            self._queue = []       # pending multi-download rows
            self._hist_i = -1      # -1 = editing, >=0 = browsing history
            self._hist_draft = ""

        def compose(self) -> ComposeResult:
            with Horizontal(id="topbar"):
                yield Static("[bold #7ee787]⚡ TORRENT TOOL[/]  [#8b949e]search · cache · download[/]", id="app-title")
                yield Static("[#8b949e]…[/]", id="rd-status")
            yield Input(placeholder="🔍  Search 8 engines — SolidTorrents · TPB · 1337x · TorrentsCSV · Nyaa · BitSearch · Torlock · Lime", id="search")
            yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="bottombar"):
                yield Static("", id="status")
                yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="pbar")
            yield Footer()

        # ── helpers ──
        def _status(self, txt): self.query_one("#status", Static).update(txt)
        def _rd_label(self, txt): self.query_one("#rd-status", Static).update(txt)
        def _progress(self, pct, txt):
            pb = self.query_one("#pbar", ProgressBar)
            if not pb.display: pb.display = True
            pb.update(progress=max(0, min(100, pct)))
            self._status(txt)
        def _hide_pbar(self): self.query_one("#pbar", ProgressBar).display = False

        def _current(self):
            if not self.view: return None, None
            idx = min(max(self.query_one("#results", DataTable).cursor_row, 0), len(self.view) - 1)
            return idx, self.view[idx]

        # ── lifecycle ──
        def on_mount(self):
            self.query_one("#results", DataTable).add_columns("#", "⚡", "Cat", "Seeds", "Leech", "Size", "Source", "Name")
            self._hide_pbar()
            self.query_one("#search", Input).focus()
            self._status(f"[#8b949e]Type a query, hit Enter — {len(ENGINES)} engines · try[/] min:10 [#8b949e]to filter seeders[/]")
            self._refresh_rd()

        def action_focus_search(self): self.query_one("#search", Input).focus()
        def action_status(self): self._refresh_rd()
        def action_help(self): self.push_screen(HelpScreen())

        # ── multi-select ──
        def action_mark(self):
            idx, r = self._current()
            if r is None: return
            rid = r.get("_id")
            if rid in self.marked: self.marked.discard(rid)
            else: self.marked.add(rid)
            self._apply_view(cursor_to=idx + 1)  # move down, lazygit-style

        def action_clear_marks(self):
            if self.marked:
                self.marked.clear()
                self._apply_view()

        # ── search history (↑/↓ inside the search box) ──
        def action_hist_prev(self):
            inp = self.query_one("#search", Input)
            if self.focused is not inp: return
            h = hist_get()
            if not h: return
            if self._hist_i == -1: self._hist_draft = inp.value
            self._hist_i = min(self._hist_i + 1, len(h) - 1)
            inp.value = h[self._hist_i]
            inp.cursor_position = len(inp.value)

        def action_hist_next(self):
            inp = self.query_one("#search", Input)
            if self.focused is not inp or self._hist_i == -1: return
            self._hist_i -= 1
            inp.value = self._hist_draft if self._hist_i == -1 else hist_get()[self._hist_i]
            inp.cursor_position = len(inp.value)

        # ── sort / filter ──
        def _view_label(self):
            parts = [f"sort:{self.sort_mode}"]
            if self.src_filter: parts.append(f"src:{self.src_filter}")
            if self.min_seeds: parts.append(f"min:{self.min_seeds}")
            if self.cached_only: parts.append("⚡cached")
            return " · ".join(parts)

        def _apply_view(self, cursor_to=None):
            if not self.results and not self._counts:
                self._status(f"[#8b949e]Type a query, hit Enter — {len(ENGINES)} engines · try[/] min:10 [#8b949e]to filter seeders[/]")
                return
            self.view = rank_filter(self.results, self.query, self.sort_mode, self.min_seeds, self.src_filter, self.cached_only)
            t = self.query_one("#results", DataTable)
            t.clear()
            for i, r in enumerate(self.view):
                marked = r.get("_id") in self.marked
                t.add_row(Text(("✓" if marked else " ") + str(i),
                               style="bold #3fb950" if marked else "#8b949e"),
                          Text("⚡" if r.get("rd_cached") else "", style="#f0c674" if r.get("rd_cached") else ""),
                          Text(cat_badge(r["n"])),
                          _seeds_cell(r["s"]),
                          _leech_cell(r["l"]),
                          Text(r["sz"], justify="right"),
                          Text(r["src"], style=SRC_STYLE.get(r["src"].split("+")[0], "#8b949e")),
                          Text(tr(r["n"], 68)),
                          key=str(i))
            if cursor_to is not None and self.view:
                t.move_cursor(row=max(0, min(cursor_to, len(self.view) - 1)), animate=False)
            srcs = " · ".join(f"{k}: {v}" for k, v in self._counts.items())
            marks = f" · [#3fb950]{len(self.marked)} marked[/]" if self.marked else ""
            if self.view:
                self._status(f"[#3fb950]✓[/] {len(self.view)} shown / {len(self.results)} found · [#79c0ff]{self._view_label()}[/]{marks}  ({srcs})")
            else:
                hint = ("cached-only — press c to show everything again" if self.cached_only
                        else "press C to clear filters")
                self._status(f"[#f85149]✗ Nothing matches[/] · {self._view_label()} · {hint}")

        def action_sort(self):
            self.sort_mode = SORT_MODES[(SORT_MODES.index(self.sort_mode) + 1) % len(SORT_MODES)]
            pref_set("sort", self.sort_mode)  # remember your favorite
            self._apply_view()

        def action_hide(self):
            idx, r = self._current()
            if r is None: return
            rid = r.get("_id") or r["n"]
            blk_add(rid, "manual")
            self.marked.discard(rid)
            self.results = [x for x in self.results if x.get("_id") != rid]
            self._apply_view()
            self.notify(f"⊘ hidden: {tr(r['n'], 40)} — undo: torrent_tool.py blacklist --wipe", timeout=5)

        def action_filter_src(self):
            srcs = sorted({p for r in self.results for p in r["src"].split("+")})
            opts = [None] + srcs
            try: i = opts.index(self.src_filter)
            except ValueError: i = -1
            self.src_filter = opts[(i + 1) % len(opts)]
            self._apply_view()

        def action_toggle_cached(self):
            self.cached_only = not self.cached_only
            if self.cached_only and not db.get("rd_api_token"):
                self.notify("⚠ Cached-only needs an RD token — press t to set one", severity="warning")
            self._apply_view()

        def action_clear_filters(self):
            self.src_filter = None; self.min_seeds = 0; self.cached_only = False
            self._apply_view()

        # ── search ──
        def on_input_submitted(self, event):
            q = event.value.strip()
            if q:
                hist_add(q)
                self._hist_i = -1
                self.marked.clear()
                self._search(q)

        @work(thread=True, group="search", exclusive=True)
        def _search(self, q):
            clean, ms = parse_query(q)
            self.query = clean or q
            self.min_seeds = ms
            self.call_from_thread(self._status, f"🔍 Searching [#79c0ff]{self.query}[/] on {len(ENGINES)} engines…")
            bag, counts = [], {}
            def run(name, fn):
                try: res = fn(self.query)
                except Exception: res = []
                counts[name] = len(res); bag.extend(res)
                self.call_from_thread(self._status,
                    "🔍 " + " · ".join(f"{k}: {counts[k]}" for k in counts) + "…")
            ts = [threading.Thread(target=run, args=e, daemon=True) for e in ENGINES]
            for t in ts: t.start()
            for t in ts: t.join()
            results = dedupe_sort(bag)
            stamp_cached(results)  # ⚡ which of these are instant on RD?
            self.call_from_thread(self._search_done, results, counts)

        def _search_done(self, results, counts):
            self.results = results
            self._counts = counts
            self._apply_view()
            if self.view:
                self.query_one("#results", DataTable).focus()
            elif not results:
                srcs = " · ".join(f"{k}: {v}" for k, v in counts.items())
                self._status(f"[#f85149]✗ No results[/] for {self.query}  ({srcs})")

        # ── download pipeline ──
        def on_data_table_row_selected(self, event):
            # Enter acts on the current row only (marks are for d)
            r = self.view[int(event.row_key.value)]
            self._start_pipeline(r)

        def action_download(self):
            idx, r = self._current()
            if r is None and not self.marked:
                self.notify("Search first — press /", severity="warning"); return
            if not db.get("rd_api_token"):
                self.notify("⚠ Set your Real-Debrid token first — press t", severity="warning")
                self.action_token()
                return
            if self.marked:
                targets = [x for x in self.view if x.get("_id") in self.marked]
                self.marked.clear()
                self._queue = list(targets)
                self._apply_view()
                self._drain_queue()
            else:
                self._start_pipeline(r)

        def _drain_queue(self):
            if not self._queue: return
            r = self._queue.pop(0)
            left = len(self._queue)
            self._status(f"📦 Queue — {tr(r['n'], 44)}" + (f" [#8b949e]({left} more after this)[/]" if left else ""))
            self._pipeline(r)

        def _start_pipeline(self, r):
            if r is None: return
            if not db.get("rd_api_token"):
                self.notify("⚠ Set your Real-Debrid token first — press t", severity="warning")
                self.action_token()
                return
            self._pipeline(r)

        @work(thread=True, group="rd", exclusive=True)
        def _pipeline(self, r):
            name = r["n"]
            mag = r.get("mag")
            if not mag:
                self.call_from_thread(self._status, f"🔗 Fetching magnet — {tr(name, 46)}")
                mag = fetch_magnet(r.get("web", ""))
                if not mag:
                    self.call_from_thread(self.notify, "✗ No magnet found for this result", severity="error")
                    self.call_from_thread(self._status, "[#8b949e]Ready.[/]")
                    return
                r["mag"] = mag
            self.call_from_thread(self._status, f"⚡ Sending to Real-Debrid — {tr(name, 46)}")
            tid, err = rd_add_magnet(mag)
            if not tid:
                self.call_from_thread(self.notify, f"✗ RD error: {tr(err, 80)}", severity="error")
                self.call_from_thread(self._status, "[#8b949e]Ready.[/]")
                return
            start = time.time(); errs = 0
            while time.time() - start < 600:
                info = rd_request("GET", f"/torrents/info/{tid}")
                if "error" in info:
                    errs += 1
                    if errs >= 5:
                        self.call_from_thread(self.notify, f"✗ RD unreachable: {tr(info['error'], 60)}", severity="error")
                        self.call_from_thread(self._hide_pbar)
                        self.call_from_thread(self._status, "[#8b949e]Ready.[/]")
                        return
                    time.sleep(2); continue
                errs = 0
                st = info.get("status", "")
                if st == "downloaded":
                    links = []
                    for lu in info.get("links", []):
                        ur = rd_request("POST", "/unrestrict/link", {"link": lu})
                        if "download" in ur:
                            links.append({"f": ur.get("filename", "?"), "sz": ur.get("filesize", 0), "u": ur["download"]})
                    self.call_from_thread(self._hide_pbar)
                    self.call_from_thread(self._show_files, links)
                    return
                if st in ("magnet_error", "error", "virus", "dead"):
                    self.call_from_thread(self.notify, f"✗ Torrent {st}", severity="error")
                    self.call_from_thread(self._hide_pbar)
                    self.call_from_thread(self._status, "[#8b949e]Ready.[/]")
                    return
                pct = info.get("progress", 0); spd = info.get("speed", 0) / 1048576
                self.call_from_thread(self._progress, pct,
                    f"☁ Caching on RD — {tr(name, 34)}  [#3fb950]{pct:.0f}%[/] @ {spd:.1f} MB/s")
                time.sleep(1.5)
            self.call_from_thread(self.notify, "✗ Timed out waiting for RD", severity="error")
            self.call_from_thread(self._hide_pbar)

        def _show_files(self, links):
            if not links:
                self.notify("✗ RD returned no files", severity="error")
                self._status("[#8b949e]Ready.[/]")
                return
            def pick(choice):
                if choice is None:
                    if self._queue: self._drain_queue()
                    else: self._status("[#8b949e]Kept in RD cloud — press r to manage.[/]")
                    return
                self._dl_worker(links if choice == "all" else [links[choice]])
            self.push_screen(FilesScreen(links), pick)

        @work(thread=True, group="dl", exclusive=True)
        def _dl_worker(self, links):
            # the conveyor belt: cache -> pick files -> download -> next in queue
            n = len(links); saved = 0
            for i, lk in enumerate(links, 1):
                def cb(dl, total, speed, i=i, f=lk["f"]):
                    pct = dl / total * 100 if total else 0
                    self.call_from_thread(self._progress, pct,
                        f"⬇ [{i}/{n}] {tr(f, 34)}  [#3fb950]{pct:.0f}%[/] @ {speed:.1f} MB/s")
                try:
                    fp = download_file(lk["u"], lk["f"], cb=cb)
                    saved += 1
                    self.call_from_thread(self.notify, f"✓ Saved {Path(fp).name}", timeout=4)
                except Exception as e:
                    dl_log(lk["f"], None, None, f"error: {str(e)[:120]}")
                    self.call_from_thread(self.notify, f"✗ Failed: {tr(lk['f'], 40)} ({e})", severity="error")
            self.call_from_thread(self._hide_pbar)
            self.call_from_thread(self._after_downloads, saved, n)

        def _after_downloads(self, saved, n):
            if self._queue:
                self._drain_queue()  # next marked torrent
            else:
                self._status(f"[#3fb950]✓ {saved}/{n} file(s)[/] saved to [#79c0ff]{DL_DIR}[/]")
                self._refresh_rd()

        # ── copy magnet ──
        def action_copy_magnet(self):
            idx, r = self._current()
            if r is None: return
            if r.get("mag"):
                self._clip(r["mag"])
            else:
                self._status(f"🔗 Fetching magnet — {tr(r['n'], 46)}")
                self._magnet_then_copy(idx)

        @work(thread=True, group="mag", exclusive=True)
        def _magnet_then_copy(self, idx):
            mag = fetch_magnet(self.view[idx].get("web", ""))
            if mag: self.view[idx]["mag"] = mag
            self.call_from_thread(self._clip, mag)

        def _clip(self, mag):
            if not mag:
                self.notify("✗ No magnet found for this result", severity="error")
                self._status("[#8b949e]Ready.[/]")
                return
            try:
                self.copy_to_clipboard(mag)
                self.notify("📋 Magnet copied to clipboard")
                self._status("[#3fb950]✓ Magnet copied.[/]")
            except Exception:
                self.notify("✗ Clipboard unavailable in this terminal", severity="error")

        # ── token / RD cloud / status ──
        def action_token(self):
            self.push_screen(TokenScreen(), self._token_done)

        def _token_done(self, user):
            if user:
                self.notify(f"✓ Connected to Real-Debrid as [b]{user}[/]")
                self._refresh_rd()

        def action_rd(self):
            self.push_screen(RDScreen(), lambda *_: self._refresh_rd())

        @work(thread=True, group="status", exclusive=True)
        def _refresh_rd(self):
            try:
                if not db.get("rd_api_token"):
                    self.call_from_thread(self._rd_label, "[#f85149]○ no token[/] [#8b949e]— press t[/]")
                    return
                s = rd_stats()
                if not s:
                    self.call_from_thread(self._rd_label, "[#f85149]● RD error[/]")
                    return
                self.call_from_thread(self._rd_label,
                    f"[#3fb950]●[/] {s['username']}  [#8b949e]·[/]  {s['premium_days']}d  [#8b949e]·[/]  {s['traffic_gb']:.0f} GB  [#8b949e]·[/]  {s['torrents']} cached")
            except Exception:
                self.call_from_thread(self._rd_label, "[#f85149]● RD unreachable[/]")

def cmd_ui():
    if not TUI_OK:
        print("The TUI requires 'textual'.\nInstall it first:  pip install textual")
        return
    TorrentApp().run()

def cmd_history(args):
    if args.clear: hist_clear(); print("History cleared."); return
    h = hist_get()
    if not h: print("No history yet — run a search."); return
    for i, q in enumerate(h, 1): print(f"{i:>3}. {q}")

def cmd_blacklist(args):
    if args.wipe: blk_wipe(); print("Blacklist cleared — they're back on the menu."); return
    rows = blk_list()
    if not rows: print("Blacklist is empty — nothing has hurt you yet."); return
    for ih, reason, ts in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        print(f"  {ih[:24]:<26} {reason:<8} {when}")
    print(f"\n{len(rows)} hidden. Undo everything: torrent_tool.py blacklist --wipe")

def cmd_prefs(args):
    if args.sort: pref_set("sort", args.sort); print(f"default sort → {args.sort}")
    if args.dl_dir: pref_set("dl_dir", str(Path(args.dl_dir))); print(f"download dir → {args.dl_dir}")
    if args.show or not (args.sort or args.dl_dir):
        print(f"sort:    {pref_get('sort','smart')}")
        print(f"dl_dir:  {pref_get('dl_dir', str(Path.home()/'Downloads'/'TorrentTool'))}")

def cmd_dl_history(args):
    rows = dl_history(args.limit)
    if not rows: print("No downloads logged yet."); return
    for ts, title, path, size, status in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        mark = "✓" if status == "ok" else "✗"
        sz = fs(size) if size else "?"
        print(f"{mark} {when}  {sz:>8}  {tr(title, 70)}  {status}")

# ── Main ──
def main():
    try:  # never crash on emoji when stdout is piped through a legacy codepage
        sys.stdout.reconfigure(errors="replace"); sys.stderr.reconfigure(errors="replace")
    except Exception: pass
    parser=argparse.ArgumentParser(description="Torrent Tool - Search + Real-Debrid (run with no arguments for the TUI)")
    sub=parser.add_subparsers(dest="cmd")

    sub.add_parser("ui",help="Launch the interactive TUI (default)")

    srch=sub.add_parser("search",help="Search torrents (supports 'min:N' in query)")
    srch.add_argument("query",nargs="?",help="Search query")
    srch.add_argument("-n","--limit",type=int,default=30,help="Max results")
    srch.add_argument("-d","--detail",action="store_true",help="Show magnet/URL")
    srch.add_argument("--sort",choices=["smart","seeds","size","name"],default="seeds",help="Sort order (default: seeds)")
    srch.add_argument("--min-seeds",type=int,default=0,metavar="N",help="Only show results with >= N seeders")
    srch.add_argument("--cached",action="store_true",help="Only show results already cached on RD (⚡)")
    srch.add_argument("--download",type=int,metavar="IDX",help="Download result by index")

    dl=sub.add_parser("download",help="Download via RD")
    dl.add_argument("url",nargs="?",help="Magnet link")
    dl.add_argument("--get",default="all",help="Files to download (all or 0,1,2)")

    tok=sub.add_parser("token",help="Set RD API token")
    tok.add_argument("token",nargs="?",help="API token from real-debrid.com/apitoken")

    sub.add_parser("status",help="Show RD status")

    rd=sub.add_parser("rd",help="Manage RD torrents")
    rd.add_argument("--delete",type=int,metavar="IDX",help="Delete cached torrent by index")

    hist=sub.add_parser("history",help="Show search history (local db)")
    hist.add_argument("--clear",action="store_true",help="Wipe history")

    bl=sub.add_parser("blacklist",help="Hidden results (local db)")
    bl.add_argument("--wipe",action="store_true",help="Unhide everything")

    pr=sub.add_parser("prefs",help="Persistent preferences")
    pr.add_argument("--sort",choices=["smart","seeds","size","name"],help="Default sort in the TUI")
    pr.add_argument("--dl-dir",metavar="PATH",help="Download folder")
    pr.add_argument("--show",action="store_true",help="Show current prefs")

    dl2=sub.add_parser("downloads",help="Local download history")
    dl2.add_argument("-n","--limit",type=int,default=15,help="Rows")

    args=parser.parse_args()

    apply_prefs()  # pick up dl_dir & friends from the local db

    if args.cmd=="ui": cmd_ui()
    elif args.cmd=="search": cmd_search(args)
    elif args.cmd=="download": cmd_download(args)
    elif args.cmd=="token": cmd_token(args)
    elif args.cmd=="status": cmd_status(args)
    elif args.cmd=="rd": cmd_rd(args)
    elif args.cmd=="history": cmd_history(args)
    elif args.cmd=="blacklist": cmd_blacklist(args)
    elif args.cmd=="prefs": cmd_prefs(args)
    elif args.cmd=="downloads": cmd_dl_history(args)
    elif TUI_OK: cmd_ui()
    else:
        print("Tip: pip install textual  →  then run with no arguments for the TUI.\n")
        parser.print_help()

if __name__=="__main__":
    main()
