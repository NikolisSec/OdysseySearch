import os, sys, sqlite3, json, re, hashlib, base64, urllib.parse
import requests, time, shutil, argparse, threading, math
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def _legacy_conhost():
    if os.name != "nt": return False
    return not (os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") or os.environ.get("TERM"))
_LEGACY_CONHOST = _legacy_conhost()

_EMO_ASCII = {
    "📦 Queue": "Queue", "📋 Magnet": "Magnet", "🔑 Real-Debrid": "Real-Debrid",
    "⚡ ODYSSEY SEARCHER": "ODYSSEY SEARCHER", "⚡": "*", "✓": "+", "✗": "-", "⚠": "!", "☁": "~", "⊘": "-",
    "🔍": ">", "🔗": "→", "⬇": "↓", "📦": "", "📋": "", "🔑": "",
    "🥁": "pr", "🌸": "an", "📺": "tv", "🎬": "mv", "🎮": "gm", "🎵": "mu", "📚": "bk", "💾": "sw",
}
def g(s):

    if not _LEGACY_CONHOST or not isinstance(s, str): return s
    for k, v in _EMO_ASCII.items(): s = s.replace(k, v)
    return s

APP_DIR = Path.home() / ".odyssey"; APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "settings.db"
DL_DIR  = Path.home() / "Downloads" / "Odyssey"; DL_DIR.mkdir(parents=True, exist_ok=True)
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

        try:
            r = self.c.execute("SELECT v,enc FROM config WHERE k='rd_api_token'").fetchone()
            if r and not r[1]:
                self.c.execute("INSERT OR REPLACE INTO config(k,v,enc) VALUES(?,?,?)",
                               ("rd_api_token", Fernet(_dk()).encrypt(r[0].encode()).decode(), 1))
                self.c.commit()
        except Exception:
            pass
    def _migrate_history(self):
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

    try: return [r[0] for r in db.query("SELECT q FROM history ORDER BY ts DESC LIMIT 50")]
    except Exception: return []

def hist_add(q):
    if not q: return
    try: db.execute("INSERT OR REPLACE INTO history(q,ts) VALUES(?,?)", (q, time.time()))
    except Exception: pass

def hist_clear():
    try: db.execute("DELETE FROM history")
    except Exception: pass

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
    global DL_DIR
    d = pref_get("dl_dir")
    if d:
        DL_DIR = Path(d); DL_DIR.mkdir(parents=True, exist_ok=True)

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
def cache_set(k, v, ttl=43200):
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

    m=SIZE_RE.search(str(s or ''))
    if not m: return 0
    u=m.group(2).upper().replace('I','')
    return int(float(m.group(1))*{'B':1,'KB':1024,'MB':1024**2,'GB':1024**3,'TB':1024**4}.get(u,1))

def intx(s):

    d=re.sub(r'[^\d]','',str(s or ''))
    return int(d) if d else 0

BTIH_RE = re.compile(r'xt=urn:btih:([a-zA-Z0-9]{32,40})', re.I)
TRACKERS = ("&tr=udp://tracker.opentrackr.org:1337/announce"
            "&tr=udp://open.stealth.si:80/announce"
            "&tr=udp://exodus.desync.com:6969/announce"
            "&tr=udp://tracker.torrent.eu.org:451/announce")
def magnet_for(ih): return f"magnet:?xt=urn:btih:{ih}{TRACKERS}" if ih else ""

def btih_from_torrent(data):

    i=data.find(b"4:info")
    if i<0: return None
    i+=6; pos=i
    def _skip(p):
        e=data.find(b":",p)
        if e<0: return None
        return e+1+int(data[p:e])
    stack=[]
    while pos<len(data):
        c=data[pos:pos+1]
        if c in (b"d",b"l"):
            stack.append(c); pos+=1
        elif c==b"i":
            e=data.find(b"e",pos)
            if e<0: return None
            pos=e+1
        elif c==b"e":
            stack.pop(); pos+=1
            if not stack: return hashlib.sha1(data[i:pos]).hexdigest()
        else:
            n=_skip(pos)
            if n is None: return None
            pos=n
    return None

def fetch_archive_magnet(x):

    m=re.search(r'/details/([^/\s]+)', x.get('web','') or '')
    if not m: return None
    iid=m.group(1)
    try:
        resp=requests.get(f"https://archive.org/download/{iid}/{iid}_archive.torrent",
                          headers=HEADERS, timeout=60)
        if resp.status_code!=200: return None
        btih=btih_from_torrent(resp.content)
        return f"magnet:?xt=urn:btih:{btih}" if btih else None
    except: return None

CAT_RULES = [
    ("🥁", re.compile(r'\b(drum\s?kit|drum\s?pack|drum\s?loop|drum\s?sample|drum\s?midi|boom\s?bap|one\s?shots?|sample\s?pack|sample\s?kit|midi\s?kit|melody\s?pack|vocal\s?pack|break\s?kit|trap\s?kit|beat\s?pack|wav\s?pack|ableton\s?pack|serum\s?pack|kontakt\s?kit|lo[\- ]?fi\s?kit)\b', re.I)),
    ("🌸", re.compile(r'^\[(erai|subsplease|.*raws|.*subs)\]', re.I)),
    ("📺", re.compile(r'\bs\d{1,2}e\d{1,2}\b|\bseason\s*\d+\b|hdtv|\bcomplete\s+series\b', re.I)),
    ("🎬", re.compile(r'\b(1080p|2160p|720p|480p|blu[\- ]?ray|bdrip|web[\- ]?dl|webrip|dvdrip|hdrip|remux|x264|x265|hevc)\b', re.I)),
    ("🎮", re.compile(r'\b(fitgirl|reloaded|codex|razor1911|skidrow|repack|steamrip|elamigos|dodi)\b', re.I)),
    ("🎵", re.compile(r'\b(flac|mp3|320kbps|discography|soundtrack|vinyl)\b|\bost\b', re.I)),
    ("📚", re.compile(r'\b(epub|mobi|azw3|ebook|audiobook|m4b)\b', re.I)),
    ("💾", re.compile(r'\b(crack|keygen|portable|activated|iso)\b', re.I)),
]
def cat_badge(name):
    for b, rx in CAT_RULES:
        if rx.search(str(name or '')): return g(b)
    return "·"

def _sz_bytes(s):
    m = re.match(r'(\d+(?:\.\d+)?)\s*(b|kb|kib|mb|mib|gb|gib|tb|tib)?$', str(s or '').strip(), re.I)
    if not m: return None
    unit = (m.group(2) or 'b').lower().replace('i', '')
    return int(float(m.group(1)) * {'b': 1, 'kb': 1024, 'mb': 1024 ** 2, 'gb': 1024 ** 3, 'tb': 1024 ** 4}[unit])

S1E_RE    = re.compile(r'\bs(\d{1,2})-?e(\d{1,3})(?:\s*[-–to]\s*(?:e)?(\d{1,3}))?\b', re.I)
SRANGE_RE = re.compile(r'\bs(\d{1,2})\s*(?:-|–|to)\s*s?(\d{1,2})\b', re.I)
SEAS_RE   = re.compile(r'\bs(\d{1,2})\b', re.I)
SEASW_RE  = re.compile(r'\bseason\s*(\d{1,2})\b', re.I)
SEASW2_RE = re.compile(r'(\bseason\s+)(\d{1,2})\b', re.I)
EPW_RE    = re.compile(r'\bep(?:isode)?\.?\s*(\d{1,3})\b', re.I)
XN_RE     = re.compile(r'\b(\d{1,2})x(\d{1,3})(?:\s*(?:-|–|to)\s*(\d{1,3}))?\b', re.I)
YEAR_RE   = re.compile(r'\b(?:19|20)\d{2}\b')
IMDB_RE   = re.compile(r'\b(?:imdb[-_ ]?)?(tt\d{7,8})\b', re.I)
SERIES_RE = re.compile(r'\b(complete\s*series|full\s*series|series\s*pack|boxset|\[all\]|the\s*complete)\b', re.I)

QUALITY_RE = [
    ("2160p", re.compile(r'\b(2160p|4k|uhd|uhdbluray)\b', re.I)),
    ("1080p", re.compile(r'\b1080p\b', re.I)),
    ("720p",  re.compile(r'\b720p\b', re.I)),
    ("480p",  re.compile(r'\b480p\b', re.I)),
]
CODEC_RE = [
    ("h265", re.compile(r'\b(x265|h265|hevc)\b', re.I)),
    ("h264", re.compile(r'\b(x264|h264|avc1?)\b', re.I)),
    ("av1",  re.compile(r'\bav1\b', re.I)),
]
HDR_RE  = re.compile(r'\bhdr10\+?\b|\bdolby\s?vision\b|\bdovi\b|\bhdr\b', re.I)
DV_RE   = re.compile(r'\bdolby\s?vision\b|\bdovi\b|\bhdr10\+?\b', re.I)
AUDIO_RE = [
    ("atmos", re.compile(r'\batmos\b|\bdd\+?\s?atmos\b', re.I)),
    ("truehd", re.compile(r'\btrue[- ]?hd\b', re.I)),
    ("dtsx",  re.compile(r'\bdts[- ]?x\b', re.I)),
    ("dtshd", re.compile(r'\bdts[- ]?hd(?:[- ]?(?:ma|hr))?\b', re.I)),
    ("dts",   re.compile(r'\bdts\b', re.I)),
    ("ac3",   re.compile(r'\bac3\b|\bdolby\s?digital\b', re.I)),
    ("aac",   re.compile(r'\baac\b', re.I)),
    ("flac",  re.compile(r'\bflac\b', re.I)),
    ("mp3",   re.compile(r'\bmp3\b', re.I)),
]
LANG_RE = [
    ("multi", re.compile(r'\b(multi|dua?l(?:[- ]?audio)?)\b', re.I)),
    ("eng",   re.compile(r'\b(english|engl|\[eng\])\b', re.I)),
    ("jap",   re.compile(r'\bjap(?:anese)?\b|\b日本\b', re.I)),
    ("esp",   re.compile(r'\b(s?panish|español|\[es\]|latino)\b', re.I)),
    ("fre",   re.compile(r'\bfre(?:nch)?\b|\bfr\b', re.I)),
    ("ger",   re.compile(r'\bger(?:man)?\b|\bdeutsch\b', re.I)),
    ("sub",   re.compile(r'\bsub(?:s|title)?(?:ed|s)?\b', re.I)),
]
TV_RE     = re.compile(r'\bhdtv\b|\bcomplete\s*series\b|\bmini[- ]?series\b', re.I)
GAME_RE   = re.compile(r'\b(fitgirl|dodi|elamigos|reloaded|codex|razor1911|skidrow|steamrip|repack|gog)\b|\bpc[\s-]?game\b|\bgame[\s-]?pc\b|\b(cracked|full[\s-]?version|nsz|xci|rom)\b', re.I)
ANIME_TAG = re.compile(r'^\[(?:erai|subsplease|.*raws|.*subs)\]', re.I)
KIND_ANIME_MARK = re.compile(r'\b(?:sub|dub|s\d{1,2}e\d{1,2})\b', re.I)

def _norm(s):

    s = ''.join(ch for ch in s.lower() if ch.isalnum() or ch.isspace())
    return s

def media_parse(title, cached=None):

    t = str(title or '')
    tl = t.lower()
    m = {"text": _norm(t), "raw": t}

    mo = S1E_RE.search(tl)
    if mo:
        m["season"], m["episode"] = int(mo.group(1)), int(mo.group(2))
        if mo.group(3): m["episode_max"] = int(mo.group(3))
    else:
        mo = SRANGE_RE.search(tl)
        if mo:
            m["season"], m["season_max"] = int(mo.group(1)), int(mo.group(2))
        else:
            mo = XN_RE.search(tl)
            if mo:
                m["season"], m["episode"] = int(mo.group(1)), int(mo.group(2))
                if mo.group(3): m["episode_max"] = int(mo.group(3))
            else:
                mo = SEASW_RE.search(tl)
                if not mo: mo = SEASW2_RE.search(tl)
                if mo: m["season"] = int(mo.group(1))
                else:
                    mo = SEAS_RE.search(tl)
                    if mo and not re.search(r'\bsi\b', tl): m["season"] = int(mo.group(1))
                mo = EPW_RE.search(tl)
                if mo: m["episode"] = int(mo.group(1))

    for q, rx in QUALITY_RE:
        if rx.search(tl): m["quality"] = q; break
    for c, rx in CODEC_RE:
        if rx.search(tl): m["codec"] = c; break
    if HDR_RE.search(tl): m["hdr"] = True
    if DV_RE.search(tl):  m["dv"] = True
    for a, rx in AUDIO_RE:
        if rx.search(tl): m.setdefault("audio", []).append(a)
    for l, rx in LANG_RE:
        if rx.search(tl): m.setdefault("lang", []).append(l)

    mo = IMDB_RE.search(tl)
    if mo: m["imdb"] = mo.group(1)
    mo = YEAR_RE.search(tl)
    if mo: m["year"] = int(mo.group(0))
    if ANIME_TAG.search(tl):
        m["kind"] = "anime"
    elif S1E_RE.search(tl) or SRANGE_RE.search(tl) or XN_RE.search(tl) or SEASW_RE.search(tl) or SEAS_RE.search(tl) or TV_RE.search(tl):
        m["kind"] = "tv"
    elif re.search(r'\bmovie\b|\bcinema\b|\btheatrical\b', tl):
        m["kind"] = "movie"
    elif QUALITY_RE[0][1].search(tl) and mo:
        m["kind"] = "movie"
    if GAME_RE.search(tl):
        m["kind"] = "game"
    if SERIES_RE.search(tl):
        m["series_pack"] = True

    m["badge"] = cat_badge(t) or "·"
    return m

class Query:
    __slots__ = ("title", "season", "episode", "year", "kind", "quality", "codec",
                 "hdr", "dv", "audio", "lang", "min_seeds", "min_size", "max_size",
                 "imdb", "tmdb", "idname", "raw")
    def __init__(self, raw=""):
        self.title = ""; self.season = self.episode = self.year = None
        self.kind = None; self.quality = None; self.codec = None
        self.hdr = self.dv = None; self.audio = None; self.lang = None
        self.min_seeds = 0; self.min_size = self.max_size = None
        self.imdb = self.tmdb = None; self.idname = None; self.raw = raw
    @property
    def title_tokens(self): return [t for t in re.split(r'\s+', self.title.lower().strip()) if t]
    def __repr__(self): return f"<Query {self.raw!r} → {self.__dict__}>"

QC_QUAL = {"1080p": "1080p", "2160p": "2160p", "720p": "720p", "480p": "480p", "4k": "2160p", "uhd": "2160p"}
QC_CODEC = {"h264": "h264", "x264": "h264", "avc": "h264", "h265": "h265", "hevc": "h265", "x265": "h265", "av1": "av1"}
QC_AUDIO = {"truehd": "truehd", "dts": "dts", "dtshd": "dtshd", "dtsx": "dtsx", "ac3": "ac3", "dd": "ac3", "aac": "aac", "atmos": "atmos", "flac": "flac", "mp3": "mp3"}
QC_LANG = {"en":"eng","eng":"eng","english":"eng","de":"ger","ger":"ger","jap":"jap","ja":"jap","japanese":"jap","es":"esp","esp":"esp","fr":"fre","fre":"fre","multi":"multi","sub":"sub","subs":"sub"}
QC_KIND = {"tv":"tv","show":"tv","series":"tv","movie":"movie","film":"movie","anime":"anime","game":"game","games":"game","pc":"game"}

def build_query(raw):

    q = Query(raw)
    if not raw: return q
    toks = raw.split()
    title = []
    i = 0
    while i < len(toks):
        t = toks[i]
        tl = t.lower()
        if tl == "season" and i + 1 < len(toks) and toks[i + 1].isdigit() and len(toks[i + 1]) <= 2:
            q.season = int(toks[i + 1]); i += 2; continue
        elif tl.startswith("season") and tl[6:].isdigit() and 1 <= len(tl) - 6 <= 2:
            q.season = int(tl[6:]); i += 1; continue
        m = re.match(r'min(?:imum)?:?(\d+)$', tl)
        if m: q.min_seeds = int(m.group(1)); i += 1; continue
        m = re.match(r'(min|minsize|min_size|size):(\d+(?:\.\d+)?)\s*(kb|mb|gb|tb)?$', t, re.I)
        if m:
            q.min_size = _sz_bytes(f"{m.group(2)}{m.group(3)}") if m.group(3) else int(float(m.group(2)))
            i += 1; continue
        m = re.match(r'(max|maxsize|max_size):(\d+(?:\.\d+)?)\s*(kb|mb|gb|tb)?$', t, re.I)
        if m:
            q.max_size = _sz_bytes(f"{m.group(2)}{m.group(3)}") if m.group(3) else int(float(m.group(2)))
            i += 1; continue
        m = re.match(r'(q|quality|res):(.+)$', t, re.I)
        if m:
            v = m.group(2).lower().strip('[]')
            if v in QC_QUAL and v != "": q.quality = QC_QUAL[v]
            i += 1; continue
        m = re.match(r'(c|codec):(.+)$', t, re.I)
        if m:
            v = m.group(2).lower().strip('[]')
            if v in QC_CODEC: q.codec = QC_CODEC[v]
            i += 1; continue
        m = re.match(r'(a|audio):(.+)$', t, re.I)
        if m:
            v = m.group(2).lower().strip('[]')
            if v in QC_AUDIO: q.audio = QC_AUDIO[v]
            i += 1; continue
        m = re.match(r'(l|lang|language):(.+)$', t, re.I)
        if m:
            v = m.group(2).lower().strip('[]')
            if v in QC_LANG: q.lang = QC_LANG[v]
            i += 1; continue
        m = re.match(r'(t|type):(.+)$', t, re.I)
        if m:
            v = m.group(2).lower().strip('[]')
            if v in QC_KIND: q.kind = QC_KIND[v]
            i += 1; continue
        if tl in ("hdr", "hdr10", "hdr10+", "dv", "dolby", "dolbyvision", "4kdcp"):
            q.hdr = True
            if tl in ("dv", "dolby", "dolbyvision", "hdr10+"): q.dv = True
            i += 1; continue
        if tl in ("no-hdr", "nohdr"):
            q.hdr = False; i += 1; continue

        if tl in QC_QUAL:
            q.quality = QC_QUAL[tl]; i += 1; continue
        if tl in QC_CODEC:
            q.codec = QC_CODEC[tl]; i += 1; continue
        if tl in QC_AUDIO and tl not in QC_CODEC:
            q.audio = QC_AUDIO[tl]; i += 1; continue
        if tl in QC_KIND and len(tl) <= 6:
            q.kind = QC_KIND[tl]; i += 1; continue
        m = re.match(r'(?:imdb[:_-]?)?(tt\d{7,8})$', tl)
        if m: q.imdb = m.group(1); i += 1; continue
        m = re.match(r'tmdb[:_-]?(\d+)$', tl)
        if m: q.tmdb = m.group(1); i += 1; continue
        m = re.match(r's(\d{1,2})e(\d{1,3})$', tl)
        if m:
            q.season, q.episode = int(m.group(1)), int(m.group(2)); i += 1; continue
        m = re.match(r's(\d{1,2})$', tl)
        if m and len(tl) < 5:
            q.season = int(m.group(1)); i += 1; continue
        m = re.match(r'e(\d{1,3})$', tl)
        if m:
            q.episode = int(m.group(1)); i += 1; continue
        m = re.match(r'(\d{1,2})x(\d{1,3})$', tl)
        if m:
            q.season, q.episode = int(m.group(1)), int(m.group(2)); i += 1; continue
        m = re.match(r'(?:19|20)\d{2}$', tl)
        if m:
            q.year = int(m.group(0)); i += 1; continue
        title.append(t)
        i += 1
    q.title = " ".join(title).strip()
    if q.imdb:
        q.idname = classify_lookup(q.imdb)
        if q.idname and not q.title: q.title = q.idname
    elif q.tmdb:
        q.idname = tmdb_lookup(q.tmdb, q.kind)
        if q.idname and not q.title: q.title = q.idname
    return q

def classify_lookup(imdb_id):

    ck = "id:" + imdb_id.lower()
    v = cache_get(ck)
    if v == "!": return None
    if v: return v
    name = None
    try:
        r = requests.get(f"https://v2.sg.media-imdb.com/suggestion/x/{imdb_id}.json",
                         headers=HEADERS, timeout=12)
        if r.status_code == 200:
            d = r.json().get("d", [])
            for it in d:
                if it.get("id", "").lower() == imdb_id.lower():
                    name = it.get("l"); break
            if name is None and d: name = d[0].get("l")
    except Exception:
        pass
    cache_set(ck, name or "!", ttl=2592000)
    return name

def tmdb_lookup(tmdb_id, kind=None):

    ck = "tmdb:" + str(tmdb_id) + ":" + (kind or "?")
    v = cache_get(ck)
    if v == "!": return None
    if v: return v
    import html as _html
    name = None
    for k in ([kind] if kind else ["tv", "movie"]):
        if not k: continue
        try:
            r = requests.get(f"https://www.themoviedb.org/{k}/{tmdb_id}", headers=HEADERS, timeout=12)
            if r.status_code != 200: continue
            mo = re.search(r'<title>(.*?)</title>', r.text, re.I | re.S)
            if mo:
                raw = _html.unescape(mo.group(1)).strip()
                raw = re.split(r'\s*[—–\-]\s*The Movie Database', raw, flags=re.I)[0].strip()

                raw = re.sub(r'\s*\(\d{4}.*?\)\s*$', '', raw).strip()
                raw = re.sub(r'\s+\(\d{4}\)', '', raw).strip()
                if raw: name = raw; break
        except Exception:
            continue
    cache_set(ck, name or "!", ttl=2592000)
    return name

def _tok_match(qtoks, rtok_letters):

    return sum(1 for t in qtoks if t in rtok_letters or any(
        len(rt) >= 4 and rt[:4] == t[:4] and len(t) >= 4 for rt in rtok_letters))

def smart_score(r, q):

    m = r.get("media") or media_parse(r["n"])
    r["media"] = m
    s = 0.0
    qts = q.title_tokens
    r_text = m["text"]
    if qts:
        hit = _tok_match(qts, [w for w in r_text.split()])
        s += 55 * hit / len(qts)
        if q.title.lower() == " ".join(r_text.split()[:len(qts)]):
            s += 18
    k = m.get("kind")
    if q.kind:
        if k == q.kind: s += 22
        elif k and k != q.kind: s -= 60
    rs, rex = m.get("season"), m.get("episode")
    if q.season:
        if rs == q.season: s += 45
        elif rs is None:
            if q.episode and k != "tv": s -= 25
            elif m.get("series_pack") and k == "tv": s += 8
            else: s -= 5
        elif q.season is not None and m.get("season_max") is not None and q.season <= m["season_max"]: s += 28
        else: s -= 60
    if q.episode:
        if rex == q.episode: s += 55
        elif rex is None and not (m.get("season") == q.season and m.get("episode_max") and q.episode <= m["episode_max"]):
            s -= 18
        else: s -= 80
    if q.year and m.get("year"):
        s += 14 if m["year"] == q.year else -22
    if q.quality and m.get("quality") == q.quality: s += 12
    if q.codec and m.get("codec") == q.codec: s += 10
    if q.hdr and m.get("hdr"): s += 8
    if q.lang and q.lang in (m.get("lang") or []): s += 8
    if q.audio and q.audio in (m.get("audio") or []): s += 7
    s += math.log10(1 + r["s"]) * 8
    return s

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

def search_bitsearch(q,n=30,category=None,tag="BitSearch"):

    r=[]
    try:
        u=f"https://bitsearch.to/search?q={urllib.parse.quote(q)}&sort=seeders"+(f"&category={category}" if category else "")
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
        if resp.status_code in (429, 500):
            time.sleep(2); resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT,allow_redirects=True)
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
                      'sz':sz,'szr':parse_size(sz),'src':tag,
                      'mag':me['href'] if me else '','web':base+a.get('href','')})
    except: pass
    return r

def search_torlock(q,n=30):

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

def search_fitgirl(q,n=30):

    r=[]
    try:
        u=f"https://fitgirl-repacks.site/?s={urllib.parse.quote(q)}"
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        import bs4
        soup=bs4.BeautifulSoup(resp.text,'html.parser')
        for a in soup.select('article h1 a, article h2 a, article h3 a, .entry-title a')[:n]:
            href=a.get('href','')
            if not href: continue
            name=a.get_text(' ',strip=True) or '?'
            r.append({'n':name,'s':0,'l':0,'sz':'?','szr':0,
                      'src':'FitGirl','mag':'','web':href})
    except: pass
    return r

def search_archive(q,n=30):

    r=[]
    try:
        fl="&fl[]=identifier&fl[]=title&fl[]=mediatype&fl[]=item_size&fl[]=downloads"
        u=(f"https://archive.org/advancedsearch.php?q={urllib.parse.quote(f'({q}) AND (mediatype:(audio) OR mediatype:(software) OR mediatype:(movies))')}"
           f"&rows={n}&sort[]=downloads+desc{fl}&output=json")
        resp=requests.get(u,headers=HEADERS,timeout=TIMEOUT)
        if resp.status_code!=200: return r
        for d in resp.json().get('response',{}).get('docs',[]):
            iid=d.get('identifier','')
            if not iid: continue
            sz=int(d.get('item_size',0) or 0)
            r.append({'n':d.get('title',iid),'s':0,'l':0,
                      'sz':fs(sz) if sz else '?','szr':sz,
                      'src':'Archive','mag':'',
                      'web':f'https://archive.org/details/{iid}'})
    except: pass
    return r

ENGINES = [("SolidTorrents", search_solidtorrents),
           ("TPB",          search_tpb),
           ("1337x",        search_1337x),
           ("TorrentsCSV",  search_torrentscsv),
           ("Nyaa",         search_nyaa),
           ("BitSearch",    search_bitsearch),
           ("BitMusic",     lambda q, n=30: search_bitsearch(q, n, category="music", tag="BitMusic")),
           ("Torlock",      search_torlock),
           ("Lime",         search_lime),
           ("FitGirl",      search_fitgirl),
           ("Archive",      search_archive)]

NO_MAGNET_ENGINES = {"1337x", "Torlock", "Lime", "Archive", "FitGirl"}

CUSTOM_MAGNET = {"Archive": fetch_archive_magnet}

def dedupe_sort(all_r):
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

    bq = build_query(q)
    return bq.title, bq.min_seeds

JUNK_RE = re.compile(r'(\[real\]|\bfull version\b|\bhigh-definition\b|\blatest top release\b|\bdirect download\b)', re.I)

def engine_query(q, raw):

    def _local(t):
        tl = t.lower()
        return bool(re.match(r'^(min|min_size|minsize|size|max|max_size|maxsize'
                             r'|lang|language|l|audio|a|tmdb|q|quality|res|c|codec|t|type):', tl)) or tl == 'no-hdr'
    have = []
    for t in raw.split():
        tl = t.lower()
        if re.match(r'^tt\d{7,8}$', tl):
            if q.idname: have.append(q.idname)
            continue
        if re.match(r'^tmdb[:_-]?\d+$', tl):
            if q.idname: have.append(q.idname)
            continue
        m = re.match(r'^(q|quality|res|c|codec):(.+)$', t, re.I)
        if m and ':' in t: have.append(m.group(2)); continue
        if _local(t): continue
        have.append(t)

    if q.idname:
        want = {re.sub(r'[^a-z0-9]', '', w) for w in q.idname.lower().split()}
        dropped_id = any(re.sub(r'[^a-z0-9]', '', t.lower()) in want for t in have)
        if dropped_id:
            have = [t for t in have if re.sub(r'[^a-z0-9]', '', t.lower()) not in want]
            have.append(q.idname)
    return ' '.join([k for k in have if k])

def kind_badge(k):
    return {"tv": g("📺"), "movie": g("🎬"), "anime": g("🌸"), "game": g("🎮")}.get(k, "·")

def _merge_over(q, over):

    n = Query(q.raw)
    n.title, n.season, n.episode, n.year, n.kind = q.title, q.season, q.episode, q.year, q.kind
    n.imdb, n.tmdb, n.min_seeds, n.max_size = q.imdb, q.tmdb, q.min_seeds, q.max_size
    n.quality = over.get("quality", q.quality)
    n.codec = over.get("codec", q.codec)
    n.hdr = over.get("hdr", q.hdr)
    n.dv = over.get("dv", q.dv)
    n.audio = over.get("audio", q.audio)
    n.lang = over.get("lang", q.lang)
    n.min_size = over.get("min_size", q.min_size)
    return n

def q_label(q):

    p = []
    if q.title: p.append(f"[#79c0ff]{q.title}[/]")
    if q.imdb: p.append(f"imdb:{q.imdb}")
    if q.tmdb: p.append(f"tmdb:{q.tmdb}")
    if q.kind: p.append(q.kind)
    if q.season is not None:
        s = f"S{q.season:02d}"
        if q.episode is not None: s += f"E{q.episode:02d}"
        p.append(s)
    if q.year: p.append(str(q.year))
    for label, val in (("q", q.quality), ("codec", q.codec), ("audio", q.audio), ("lang", q.lang)):
        if val: p.append(f"{label}:{val}")
    if q.hdr is True: p.append("hdr")
    if q.hdr is False: p.append("no-hdr")
    if q.dv: p.append("dv")
    if q.min_seeds: p.append(f"min:{q.min_seeds}")
    if q.min_size: p.append(f"size>={fs(q.min_size)}")
    if q.max_size: p.append(f"size<={fs(q.max_size)}")
    return " · ".join(p) if p else ""

def rank_filter(results, query='', sort='smart', min_seeds=0, src=None, cached=None,
                q=None, over=None):

    blk = blk_get()
    qo = _merge_over(q or build_query(query), over or {})
    ms = max(min_seeds, qo.min_seeds)
    out = []
    for r in results:
        m = r.get("media") or media_parse(r["n"]); r["media"] = m
        if r['s'] < ms: continue
        if src and src not in r['src']: continue
        if JUNK_RE.search(r['n']) or r.get('_id') in blk: continue
        if cached and not r.get('rd_cached'): continue
        if qo.min_size and r.get("szr") and r['szr'] < qo.min_size: continue
        if qo.max_size and r.get("szr") and r['szr'] > qo.max_size: continue
        if qo.quality and m.get("quality") and m['quality'] != qo.quality: continue
        if qo.codec and m.get("codec") and m['codec'] != qo.codec: continue
        if qo.hdr is not None and m.get("hdr") is not None and m['hdr'] != qo.hdr: continue
        if qo.dv and m.get("dv") is None: continue
        if qo.audio and m.get("audio") and qo.audio not in m['audio']: continue
        if qo.lang and m.get("lang") and qo.lang not in m['lang']: continue
        if qo.kind and m.get("kind") and m['kind'] != qo.kind: continue
        if qo.season and m.get("season") is not None and m['season'] != qo.season and not (
                m.get("season_max") and qo.season <= m['season_max']): continue
        if qo.episode and m.get("episode") is not None and m['episode'] != qo.episode and not (
                m.get("episode_max") and qo.episode <= m['episode_max']): continue
        out.append(r)
    if sort == 'seeds': out.sort(key=lambda x: x['s'], reverse=True)
    elif sort == 'size': out.sort(key=lambda x: x['szr'], reverse=True)
    elif sort == 'name': out.sort(key=lambda x: x['n'].lower())
    else: out.sort(key=lambda x: smart_score(x, qo), reverse=True)
    return out

def fetch_magnet(url):

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
        if name in CUSTOM_MAGNET:
            for x in res[:6]:
                if not x.get('mag'):
                    try: x['mag']=CUSTOM_MAGNET[name](x) or ''
                    except: pass
        elif name in NO_MAGNET_ENGINES:
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

def rd_request(method, path, data=None):
    token = db.get("rd_api_token")
    if not token: return {"error": "RD token not configured. Run: odyssey.py token <your-token>"}
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
    if not r.content: return {}
    try: return r.json()
    except ValueError: return {}

def rd_stats():
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
        elif c is None: miss.append((rid, hsh))
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

def download_file(url, fn, cb=None):
    dest=DL_DIR
    fn=re.sub(r'[<>:"/\\|?*]','_',fn).strip() or "download.bin"
    if len(fn)>150:
        stem,_,ext=fn.rpartition('.')
        fn=(stem[:150]+'.'+ext) if ext and len(ext)<=10 else fn[:150]
    stem0,_,ext0=fn.rpartition('.')
    ext0=('.'+ext0) if ext0 else ''
    last=None
    for attempt in (1,2):
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
            while fp.exists():
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
            tmp.replace(fp)
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

def cmd_search(args):
    if not args.query:
        print("Usage: odyssey.py search <query> [--sort smart|seeds|size|name] [--min-seeds N] [--cached]\n"
              "  query filters: s02 | s02e05 | 1080p | 2160p | 720p | h265 | hevc | hdr | dv\n"
              "                | no-hdr | audio:truehd | lang:en | type:tv | min:20 | size:2gb | max:10gb | tt1234567")
        return
    bq = build_query(args.query)
    eq = engine_query(bq, args.query)
    min_seeds = args.min_seeds or bq.min_seeds
    print(f"Searching for: {eq}")
    results, counts = search_all(eq)
    stamp_cached(results)
    if args.cached and not db.get("rd_api_token"):
        print("(cached filter needs an RD token: odyssey.py token <token>)")
    results = rank_filter(results, sort=args.sort, min_seeds=min_seeds, cached=args.cached, q=bq)
    if not results: print("No results."); return
    srcs = " | ".join(f"{k}: {v}" for k, v in counts.items())
    intent = q_label(bq)
    print(f"\n{len(results)} results ({srcs}) sort={args.sort}{' cached-only' if args.cached else ''} {intent}\n")
    hist_add(eq or args.query)
    for i, r in enumerate(results[:args.limit]):
        badge = g("⚡") if r.get("rd_cached") else " "
        m = r.get("media")
        tags = (m.get("quality") or "    ") + " " + (m.get("codec") or "") + (" HDR" if m.get("hdr") else "")
        print(f"[{i:>3}] {badge} {cat_badge(r['n'])} {r['s']:>5}S {r['l']:>5}L  {r['sz']:>9} {tags:<16} {r['src']:<20} {tr(r['n'],52)}")
        if args.detail:
            if r.get('mag'): print(f"      magnet: {r['mag'][:70]}...")
            if r.get('web'): print(f"      web: {r['web']}")
    if args.download is not None:
        idx = args.download
        if 0 <= idx < len(results): cmd_download_from_result(results[idx])

def cmd_download_from_result(r):
    token=db.get("rd_api_token")
    if not token:
        print("Error: RD token not set. Run: odyssey.py token <your-token>")
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
        print("Usage: odyssey.py download <magnet-link>"); return
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
        print("Usage: odyssey.py token <api-token>")
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
                yield Label(g("[bold #7ee787]🔑 Real-Debrid API token[/]"))
                yield Label("[#8b949e]Get yours at [u]https://real-debrid.com/apitoken[/u][/]")
                yield Input(placeholder=g("Paste token, press Enter…"), password=True, id="token-input")
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
                self.query_one("#token-error", Label).update(g("[#f85149]✗ Invalid token — try again.[/]"))

    class FilesScreen(ModalScreen):

        CSS = """
        FilesScreen { align: center middle; }
        #files-box { width: 90; max-width: 95%; height: auto; background: #161b22; border: round #3fb950; padding: 1 3; }
        #files-list { height: auto; max-height: 18; background: #0d1117; border: round #30363d; margin: 1 0; }
        """
        BINDINGS = [Binding("escape", "cancel", "Close"), Binding("a", "all", "Download all")]

        def __init__(self, links): super().__init__(); self.links = links

        def compose(self) -> ComposeResult:
            with Container(id="files-box"):
                yield Label(g(f"[bold #3fb950]✓ Cached on Real-Debrid[/]  [#8b949e]— {len(self.links)} file(s) ready[/]"))
                yield OptionList(*[Option(f"[#e6edf3]{tr(l['f'], 62)}[/]  [#8b949e]({fs(l['sz'])})[/]") for l in self.links], id="files-list")
                yield Label("[#8b949e]Enter = download file · a = download all · Esc = keep in cloud[/]")

        def on_mount(self): self.query_one("#files-list", OptionList).focus()
        def on_option_list_option_selected(self, event): self.dismiss(event.option_index)
        def action_all(self): self.dismiss("all")
        def action_cancel(self): self.dismiss(None)

    class RDScreen(ModalScreen):

        CSS = """
        RDScreen { align: center middle; }
        #rd-box { width: 100; max-width: 95%; height: auto; background: #161b22; border: round #bc8cff; padding: 1 3; }
        #rd-table { height: auto; max-height: 20; background: #0d1117; border: round #30363d; margin: 1 0; }
        """
        BINDINGS = [Binding("escape", "cancel", "Close"), Binding("x", "delete", "Delete")]

        def __init__(self): super().__init__(); self._tor = []

        def compose(self) -> ComposeResult:
            with Container(id="rd-box"):
                yield Label(g("[bold #bc8cff]☁ Real-Debrid cloud[/]"))
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
[bold #7ee787]⚡ ODYSSEY SEARCHER[/]  [#8b949e]— keyboard shortcuts[/]

[bold #79c0ff]SEARCH (live — results stream in as you type)[/]
  [#58d6eb]/[/]          focus search box
  [#58d6eb]Enter[/]      run search immediately
  [#58d6eb]↑ / ↓[/]      previous searches
  [#58d6eb]s02[/]        in query → season 2 · s02e05 → that episode
  [#58d6eb]1080p[/]      quality filter (2160p · 720p · 480p)
  [#58d6eb]h265[/]       codec filter (h264 · hevc · av1)
  [#58d6eb]hdr[/]        HDR-only · no-hdr · dv (Dolby Vision)
  [#58d6eb]audio:truehd[/]  audio filter (dts · ac3 · atmos · aac …)
  [#58d6eb]lang:en[/]    language hint · type:tv|movie|anime|game
  [#58d6eb]min:N[/]      hide below N seeders · size:2gb · max:10gb
  [#58d6eb]tt1234567[/]  IMDb id search · tmdb:12345 too

[bold #79c0ff]RESULTS[/]
  [#58d6eb]↑ / ↓[/]      navigate
  [#58d6eb]Enter[/]      download this torrent
  [#58d6eb]Space[/]      mark / unmark (multi-download)
  [#58d6eb]Esc[/]        clear marks
  [#58d6eb]o[/]          sort: smart → seeds → size → name
  [#58d6eb]f[/]          filter by source
  [#58d6eb]Shift+F[/]    ⚙ media filters (quality·codec·HDR·audio·lang·size)
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

        CSS = """
        HelpScreen { align: center middle; }
        #help-box { width: 62; height: auto; background: #161b22; border: round #f778ba; padding: 1 3; }
        """
        BINDINGS = [Binding("escape", "cancel", "Close"), Binding("question_mark", "cancel", "Close", show=False)]
        def compose(self) -> ComposeResult:
            with Container(id="help-box"):
                yield Static(g(HELP_TEXT))
        def action_cancel(self): self.dismiss(None)

    class FilterScreen(ModalScreen):

        QUAL  = [None, "2160p", "1080p", "720p", "480p"]
        CODEC = [None, "h265", "h264", "av1"]
        HDR   = [None, True, False]
        DV    = [None, True]
        AUDIO = [None, "truehd", "dtsx", "dtshd", "dts", "ac3", "aac", "atmos", "flac"]
        LANG  = [None, "eng", "sub", "multi", "jap"]
        SZGB  = [None, 1, 2, 5, 10, 20, 50, 100]
        CSS = """
        FilterScreen { align: center middle; }
        #filter-box { width: 78; height: auto; background: #161b22; border: round #58a6ff; padding: 1 3; }
        #filter-state { width: 100%; height: auto; color: #e6edf3; margin: 1 0 0 0; }
        #filter-hint { width: 100%; height: 3; color: #8b949e; margin-top: 1; }
        """
        BINDINGS = [
            Binding("escape", "cancel", "Close"),
            Binding("q", "cycle_quality", "Quality", show=False),
            Binding("c", "cycle_codec", "Codec", show=False),
            Binding("h", "cycle_hdr", "HDR", show=False),
            Binding("d", "cycle_dv", "Dolby Vision", show=False),
            Binding("a", "cycle_audio", "Audio", show=False),
            Binding("l", "cycle_lang", "Language", show=False),
            Binding("s", "cycle_size", "Min size", show=False),
        ]

        def compose(self) -> ComposeResult:
            with Container(id="filter-box"):
                yield Label(g("[bold #58a6ff]⚙ FILTERS[/]  [#8b949e]cycle each with its key[/]"))
                yield Static("", id="filter-state")
                yield Label("[#8b949e]q:quality  c:codec  h:HDR  d:DolbyVision  a:audio  l:language  s:min-size  ·  Esc close[/]", id="filter-hint")

        def refresh_state(self):
            q = self.app._q_eff()
            parts = [p for p in (q_label(q).split(" · ") if q_label(q) else [])]
            extra = []
            if self.app.src_filter: extra.append(f"src:{self.app.src_filter}")
            if self.app.min_seeds: extra.append(f"min:{self.app.min_seeds}")
            if self.app.cached_only: extra.append(g("⚡") + " cached")
            line = " · ".join(parts + extra) if (parts or extra) else "[#8b949e]no filters — everything qualifies[/]"
            self.query_one("#filter-state", Static).update(line or "[#8b949e]no filters[/]")

        def _cycle(self, key, opts):
            cur = self.app.fover.get(key)
            try: i = opts.index(cur) if cur in opts else 0
            except ValueError: i = 0
            nxt = opts[(i + 1) % len(opts)]
            self.app.fover[key] = nxt
            self.app._apply_view()
            self.refresh_state()

        def action_cycle_quality(self): self._cycle("quality", self.QUAL)
        def action_cycle_codec(self): self._cycle("codec", self.CODEC)
        def action_cycle_hdr(self): self._cycle("hdr", self.HDR)
        def action_cycle_dv(self): self._cycle("dv", self.DV)
        def action_cycle_audio(self): self._cycle("audio", self.AUDIO)
        def action_cycle_lang(self): self._cycle("lang", self.LANG)

        def action_cycle_size(self):
            cur = self.app.fover.get("min_size")
            gb = (round(cur / 1073741824) if cur else None)
            try: i = self.SZGB.index(gb) if gb in self.SZGB else 0
            except ValueError: i = 0
            nxt = self.SZGB[(i + 1) % len(self.SZGB)]
            self.app.fover["min_size"] = nxt * 1073741824 if nxt else None
            self.app._apply_view()
            self.refresh_state()

        def action_cancel(self): self.dismiss(None)

    class TorrentApp(App):
        TITLE = "Odyssey Searcher"
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
            Binding("shift+f", "filters", "Media filters"),
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
            self.results = []
            self.view = []
            self.query = ""
            self.q = Query()
            self.fover = {}
            self.sort_mode = "smart" if pref_get("sort", "smart") not in SORT_MODES else pref_get("sort", "smart")
            self.src_filter = None
            self.min_seeds = 0
            self.cached_only = False
            self._counts = {}
            self.marked = set()
            self._queue = []
            self._hist_i = -1
            self._hist_draft = ""
            self._search_n = 0
            self._want_focus = False
            self._live_timer = None
            self._live_val = None
            self._live_suppress = False

        def compose(self) -> ComposeResult:
            with Horizontal(id="topbar"):
                yield Static(g("[bold #7ee787]⚡ ODYSSEY SEARCHER[/]  [#8b949e]search · cache · download[/]"), id="app-title")
                yield Static("[#8b949e]…[/]", id="rd-status")
            yield Input(placeholder=g("🔍  Search 10 engines — SolidTorrents · TPB · 1337x · TorrentsCSV · Nyaa · BitSearch · BitMusic · Torlock · Lime · Archive"), id="search")
            yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="bottombar"):
                yield Static("", id="status")
                yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="pbar")
            yield Footer()

        def _status(self, txt): self.query_one("#status", Static).update(g(txt))
        def _rd_label(self, txt): self.query_one("#rd-status", Static).update(g(txt))
        def notify(self, message="", *args, **kwargs):
            super().notify(g(message), *args, **kwargs)
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

        def on_mount(self):
            t = self.query_one("#results", DataTable)
            t.add_columns("#", g("⚡"), "Kind", "Seeds", "Leech", "Size", "Media", "Source", "Name")
            self._hide_pbar()
            self.query_one("#search", Input).focus()
            self._live_suppress = True
            self._status(f"[#8b949e]Start typing — search is live · {len(ENGINES)} engines · try:[/] s02 1080p hdr h265 min:20")
            self._live_suppress = False
            self._refresh_rd()

        def action_focus_search(self): self.query_one("#search", Input).focus()
        def action_status(self): self._refresh_rd()
        def action_help(self): self.push_screen(HelpScreen())
        def action_filters(self): self.push_screen(FilterScreen())

        def action_mark(self):
            idx, r = self._current()
            if r is None: return
            rid = r.get("_id")
            if rid in self.marked: self.marked.discard(rid)
            else: self.marked.add(rid)
            self._apply_view(cursor_to=idx + 1)

        def action_clear_marks(self):
            if self.marked:
                self.marked.clear()
                self._apply_view()

        def action_hist_prev(self):
            inp = self.query_one("#search", Input)
            if self.focused is not inp: return
            h = hist_get()
            if not h: return
            self._live_suppress = True
            if self._hist_i == -1: self._hist_draft = inp.value
            self._hist_i = min(self._hist_i + 1, len(h) - 1)
            inp.value = h[self._hist_i]
            inp.cursor_position = len(inp.value)
            self._live_suppress = False

        def action_hist_next(self):
            inp = self.query_one("#search", Input)
            if self.focused is not inp or self._hist_i == -1: return
            self._live_suppress = True
            self._hist_i -= 1
            inp.value = self._hist_draft if self._hist_i == -1 else hist_get()[self._hist_i]
            inp.cursor_position = len(inp.value)
            self._live_suppress = False

        def _q_eff(self):
            return _merge_over(self.q, self.fover)

        def _view_label(self):
            parts = [f"sort:{self.sort_mode}"]
            ql = q_label(self._q_eff())
            if ql: parts.insert(0, ql)
            if self.src_filter: parts.append(f"src:{self.src_filter}")
            if self.min_seeds: parts.append(f"min:{self.min_seeds}")
            if self.cached_only: parts.append(g("⚡") + " cached")
            return " · ".join(parts)

        def on_input_changed(self, event):
            if self._live_suppress: return
            v = event.value.strip()
            if self._live_timer:
                self._live_timer.stop(); self._live_timer = None
            if len(v) < 3 or v == self._live_val: return
            self._live_timer = self.set_timer(0.7, lambda v=v: self._fire_live(v))

        def _fire_live(self, v):
            self._live_timer = None
            if not self.is_running: return
            try: inp = self.query_one("#search", Input)
            except Exception: return
            if v != (inp.value or "").strip(): return
            if v == self._live_val: return
            self._launch_search(v, focus=False)

        def on_input_submitted(self, event):
            q = event.value.strip()
            if not q: return
            hist_add(q)
            self._hist_i = -1
            self._launch_search(q, focus=True)

        def _launch_search(self, q, focus=True):
            if self._live_timer:
                self._live_timer.stop(); self._live_timer = None
            bq = build_query(q)
            eq = engine_query(bq, q)
            self.q = bq
            self.query = eq or q
            self.min_seeds = bq.min_seeds
            self._live_val = q
            self.marked.clear()
            self._search_n += 1
            self._want_focus = focus
            self.results = []
            self._counts = {}
            self._status(f"🔍 Searching [#79c0ff]{self.query}[/] on {len(ENGINES)} engines…")
            t = self.query_one("#results", DataTable); t.clear()
            for entry in ENGINES:
                threading.Thread(target=self._run_engine, args=(entry, eq, self._search_n), daemon=True).start()

        def _run_engine(self, entry, eq, token):
            name, fn = entry
            try: res = fn(eq)
            except Exception: res = []
            if token == self._search_n:
                self.call_from_thread(self._engine_done, name, res, token)

        def _engine_done(self, name, res, token):
            if token != self._search_n: return
            self._counts[name] = len(res)
            if res:
                try: self.results = dedupe_sort(self.results + res)
                except Exception: pass
                stamp_cached(self.results[:60])
            done = len(self._counts)
            self._apply_view()
            if done < len(ENGINES):
                got = " · ".join(f"{k}: {v}" for k, v in self._counts.items())
                self._status(f"🔍 {done}/{len(ENGINES)} engines · [#79c0ff]{self.query}[/]  {got}")
            else:
                self._finalize()

        def _finalize(self):
            srcs = " · ".join(f"{k}: {v}" for k, v in self._counts.items())
            marks = f" · [#3fb950]{len(self.marked)} marked[/]" if self.marked else ""
            if self.view:
                if self._want_focus:
                    self.query_one("#results", DataTable).focus()
                    self._want_focus = False
                self._status(f"[#3fb950]✓[/] {len(self.view)} shown / {len(self.results)} found · [#79c0ff]{self._view_label()}[/]{marks}  ({srcs})")
            else:
                hint = ("cached-only — press c to show everything again" if self.cached_only
                        else "press C to clear filters")
                self._status(f"[#f85149]✗ Nothing matches[/] · {self._view_label()} · {hint}")

        def _media_cell(self, m):
            if not m: return Text("")
            bits = []
            if m.get("quality"): bits.append(m["quality"])
            if m.get("codec"): bits.append(m["codec"])
            if m.get("hdr"): bits.append("HDR")
            if m.get("dv"): bits.append("DV")
            if m.get("audio"): bits.append("/".join(m["audio"][:2]))
            if m.get("lang"): bits.append(m["lang"][0])
            return Text(" ".join(bits), style="#e6edf3" if bits else "#484f58")

        def _apply_view(self, cursor_to=None):
            if not self.results and not self._counts:
                self._status(f"[#8b949e]Start typing — search is live · {len(ENGINES)} engines · try:[/] s02 1080p hdr h265 min:20")
                return
            self.view = rank_filter(self.results, sort=self.sort_mode, min_seeds=self.min_seeds,
                                    src=self.src_filter, cached=self.cached_only, q=self.q, over=self.fover)
            t = self.query_one("#results", DataTable)
            t.clear()
            for i, r in enumerate(self.view):
                m = r.get("media") or r.setdefault("media", media_parse(r["n"]))
                marked = r.get("_id") in self.marked
                t.add_row(Text(g(("✓" if marked else " ") + str(i)),
                               style="bold #3fb950" if marked else "#8b949e"),
                          Text(g("⚡") if r.get("rd_cached") else "", style="#f0c674" if r.get("rd_cached") else ""),
                          Text(kind_badge(m.get("kind"))),
                          _seeds_cell(r["s"]),
                          _leech_cell(r["l"]),
                          Text(r["sz"], justify="right"),
                          self._media_cell(m),
                          Text(r["src"], style=SRC_STYLE.get(r["src"].split("+")[0], "#8b949e")),
                          Text(tr(r["n"], 56)),
                          key=str(i))
            if cursor_to is not None and self.view:
                t.move_cursor(row=max(0, min(cursor_to, len(self.view) - 1)), animate=False)
            if not self._counts: return

        def action_sort(self):
            self.sort_mode = SORT_MODES[(SORT_MODES.index(self.sort_mode) + 1) % len(SORT_MODES)]
            pref_set("sort", self.sort_mode)
            self._apply_view()

        def action_hide(self):
            idx, r = self._current()
            if r is None: return
            rid = r.get("_id") or r["n"]
            blk_add(rid, "manual")
            self.marked.discard(rid)
            self.results = [x for x in self.results if x.get("_id") != rid]
            self._apply_view()
            self.notify(f"⊘ hidden: {tr(r['n'], 40)} — undo: odyssey.py blacklist --wipe", timeout=5)

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
            self.fover = {}
            self._apply_view()

        def on_data_table_row_selected(self, event):
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
                self._drain_queue()
            else:
                self._status(f"[#3fb950]✓ {saved}/{n} file(s)[/] saved to [#79c0ff]{DL_DIR}[/]")
                self._refresh_rd()

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
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetConsoleOutputCP(65001); k32.SetConsoleCP(65001)
            h = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            k32.GetConsoleMode(h, ctypes.byref(mode))
            k32.SetConsoleMode(h, mode.value | 0x0004)
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
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
    print(f"\n{len(rows)} hidden. Undo everything: odyssey.py blacklist --wipe")

def cmd_prefs(args):
    if args.sort: pref_set("sort", args.sort); print(f"default sort → {args.sort}")
    if args.dl_dir: pref_set("dl_dir", str(Path(args.dl_dir))); print(f"download dir → {args.dl_dir}")
    if args.show or not (args.sort or args.dl_dir):
        print(f"sort:    {pref_get('sort','smart')}")
        print(f"dl_dir:  {pref_get('dl_dir', str(Path.home()/'Downloads'/'Odyssey'))}")

def cmd_dl_history(args):
    rows = dl_history(args.limit)
    if not rows: print("No downloads logged yet."); return
    for ts, title, path, size, status in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        mark = g("✓") if status == "ok" else g("✗")
        sz = fs(size) if size else "?"
        print(f"{mark} {when}  {sz:>8}  {tr(title, 70)}  {status}")

def main():
    try:
        sys.stdout.reconfigure(errors="replace"); sys.stderr.reconfigure(errors="replace")
    except Exception: pass
    parser=argparse.ArgumentParser(description="Odyssey Searcher - Search + Real-Debrid (run with no arguments for the TUI)")
    sub=parser.add_subparsers(dest="cmd")

    sub.add_parser("ui",help="Launch the interactive TUI (default)")

    srch=sub.add_parser("search",help="Search torrents (supports 'min:N' in query)")
    srch.add_argument("query",nargs="?",help="Search query")
    srch.add_argument("-n","--limit",type=int,default=30,help="Max results")
    srch.add_argument("-d","--detail",action="store_true",help="Show magnet/URL")
    srch.add_argument("--sort",choices=["smart","seeds","size","name"],default="seeds",help="Sort order (default: seeds)")
    srch.add_argument("--min-seeds",type=int,default=0,metavar="N",help="Only show results with >= N seeders")
    srch.add_argument("--cached",action="store_true",help=f"Only show results already cached on RD ({g('⚡')})")
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

    apply_prefs()

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

# made by NikolisSec
