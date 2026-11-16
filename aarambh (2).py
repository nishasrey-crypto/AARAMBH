"""
AARAMBH v3 - Search . Explore . Grow   (Made in India)
ONE file: Flask + SQLite + Claude/ChatGPT/Gemini + 11 image engines + live search
          + self-learning + PRIVACY FIREWALL

INSTALL
    pip install flask requests

KEYS  (put them in a file called  .env  next to this file, one per line, e.g.  GEMINI_API_KEY=xxxx )
  Chat brains (any you have; Auto-fallback between them):
      ANTHROPIC_API_KEY   OPENAI_API_KEY   GEMINI_API_KEY
  Web search (optional, else Wikipedia only):  TAVILY_API_KEY   BRAVE_API_KEY
  Image engines  -- FREE first:
      pollinations   : no key needed (free, slow limit ~1 image / 15 s)
      cloudflare     : CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN   (free daily allowance, FLUX)
      huggingface    : HF_TOKEN                                        (small free monthly credit, FLUX)
      together       : TOGETHER_API_KEY                                (free FLUX model if still offered)
      gemini         : GEMINI_API_KEY                                  (free quota is small / may need billing)
    PAID (only used if you pick them, or untick "Free engines only"):
      openai: OPENAI_API_KEY   stability: STABILITY_API_KEY   leonardo: LEONARDO_API_KEY
      ideogram: IDEOGRAM_API_KEY   recraft: RECRAFT_API_KEY   flux_bfl: BFL_API_KEY
  Extra: AARAMBH_PIN=1234  -> asks for a password (username anything) before opening the app.

RUN
    python aarambh.py     then open  http://127.0.0.1:5000
    Put your artwork as  background.jpg  next to this file to use it as the background.

PRIVACY (see the 🔒 Privacy button)
    - Image engines receive ONLY the picture prompt (after personal data is removed). Never your chat
      history, database, lessons, other API keys or files.
    - Outbound firewall: the app can only talk to a fixed allow-list of hosts. Anything else is blocked.
    - Personal data (emails, phones, Aadhaar/PAN/card numbers, API keys, IPs) is removed from image
      prompts and search queries ALWAYS, and from chat when "Private mode" is on.
    - Every outside call is written to a local Audit Log you can read. You can switch any service OFF,
      or turn on LOCAL-ONLY mode (nothing leaves your computer).
    - Keys stay on the server; they are never sent to the browser. Server listens on 127.0.0.1 only.
"""
import os, re, uuid, base64, sqlite3, time, datetime, socket, ipaddress, hmac, secrets
from urllib.parse import urlparse, urljoin, quote
import requests
from flask import Flask, request, jsonify, Response, g, send_from_directory, abort

BASE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    p = os.path.join(BASE, ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
DB_PATH = os.environ.get("AARAMBH_DB", os.path.join(BASE, "aarambh.db"))
IMG_DIR = os.path.join(BASE, "generated")
os.makedirs(IMG_DIR, exist_ok=True)
try:
    os.chmod(IMG_DIR, 0o700)
except OSError:
    pass
MAX_IMG = 15 * 1024 * 1024

# ----------------------------------------------------------------- PROVIDERS
CHAT_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
CHAT_ORDER = list(CHAT_KEYS.items())
CHAT_LABEL = {"anthropic": "Claude", "openai": "ChatGPT", "gemini": "Gemini"}
MODELS = {
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
    "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "gemini": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
}
SEARCH_FORCED = os.environ.get("SEARCH_PROVIDER", "").lower()

# id: (label, group, required env vars)
IMAGE_PROVIDERS = {
    "pollinations": ("Pollinations FLUX", "free", []),
    "cloudflare": ("Cloudflare FLUX", "free", ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]),
    "huggingface": ("Hugging Face FLUX", "free", ["HF_TOKEN"]),
    "together": ("Together FLUX", "free", ["TOGETHER_API_KEY"]),
    "gemini": ("Google Gemini", "free", ["GEMINI_API_KEY"]),
    "openai": ("OpenAI Images", "paid", ["OPENAI_API_KEY"]),
    "stability": ("Stability AI", "paid", ["STABILITY_API_KEY"]),
    "flux_bfl": ("FLUX (Black Forest Labs)", "paid", ["BFL_API_KEY"]),
    "recraft": ("Recraft", "paid", ["RECRAFT_API_KEY"]),
    "ideogram": ("Ideogram", "paid", ["IDEOGRAM_API_KEY"]),
    "leonardo": ("Leonardo AI", "paid", ["LEONARDO_API_KEY"]),
}
IMAGE_ORDER = ["pollinations", "cloudflare", "huggingface", "together", "gemini",
               "openai", "stability", "flux_bfl", "recraft", "ideogram", "leonardo"]

# Services with no official public image API that I could confirm: open the website instead.
LINKOUTS = [
    ("Midjourney", "https://www.midjourney.com/"), ("Adobe Firefly", "https://firefly.adobe.com/"),
    ("Krea AI", "https://www.krea.ai/"), ("OpenArt", "https://openart.ai/"),
    ("Playground", "https://playground.com/"), ("Reve", "https://reve.com/"),
    ("Runway", "https://runwayml.com/"), ("Ideogram (website)", "https://ideogram.ai/"),
    ("Recraft (website)", "https://www.recraft.ai/"), ("Canva AI", "https://www.canva.com/ai-image-generator/"),
    ("Microsoft Designer", "https://designer.microsoft.com/"), ("NightCafe", "https://creator.nightcafe.studio/"),
    ("Craiyon", "https://www.craiyon.com/"), ("Fotor AI", "https://www.fotor.com/features/ai-image-generator/"),
    ("Picsart", "https://picsart.com/ai-image-generator/"), ("Bing Image Creator", "https://www.bing.com/images/create"),
    ("Meta AI", "https://www.meta.ai/"), ("Dream by WOMBO", "https://dream.ai/"),
    ("Tensor.Art", "https://tensor.art/"), ("Perchance", "https://perchance.org/ai-text-to-image-generator"),
    ("Leonardo AI (website)", "https://app.leonardo.ai/"), ("Google Gemini (website)", "https://gemini.google.com/"),
]

# ---------------------------------------------------------- OUTBOUND FIREWALL
ALLOWED_HOSTS = {
    "api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
    "api.tavily.com", "api.search.brave.com", "en.wikipedia.org",
    "image.pollinations.ai", "api.cloudflare.com", "router.huggingface.co", "api.together.xyz",
    "api.stability.ai", "cloud.leonardo.ai", "api.ideogram.ai", "external.api.recraft.ai",
}
ALLOWED_SUFFIXES = (".bfl.ai",)  # api.bfl.ai, api.eu.bfl.ai, api.us.bfl.ai


def _is_public(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def fetch(method, url, public_only=False, **kw):
    """The ONLY way this app talks to the internet.
    public_only=True is used for downloading result images (no keys are ever sent there)."""
    kw.setdefault("timeout", 60)
    for _ in range(4):
        u = urlparse(url)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not host:
            raise PermissionError("Blocked: only HTTPS addresses are allowed")
        if public_only:
            if not _is_public(host):
                raise PermissionError("Blocked: address is not a public internet address")
        elif host not in ALLOWED_HOSTS and not host.endswith(ALLOWED_SUFFIXES):
            raise PermissionError("Blocked by privacy firewall: %s is not on the allow-list" % host)
        r = requests.request(method, url, allow_redirects=False, **kw)
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", ""))
            if r.status_code == 303:
                method = "GET"
                for k in ("json", "data", "files"):
                    kw.pop(k, None)
            continue
        return r
    raise RuntimeError("Too many redirects")


def download_image(url):
    r = fetch("GET", url, public_only=True, stream=True, timeout=60)
    if not r.ok:
        raise RuntimeError("Image download failed (%s)" % r.status_code)
    buf = bytearray()
    for chunk in r.iter_content(65536):
        buf += chunk
        if len(buf) > MAX_IMG:
            raise RuntimeError("Image too large")
    return bytes(buf)


def secret_values():
    names = set(CHAT_KEYS.values()) | {"TAVILY_API_KEY", "BRAVE_API_KEY", "AARAMBH_PIN"}
    for v in IMAGE_PROVIDERS.values():
        names |= set(v[2])
    return [os.environ[n] for n in names if os.environ.get(n) and len(os.environ[n]) > 5]


def redact(text):
    text = str(text)
    for s in secret_values():
        text = text.replace(s, "***")
    return text


def check(r, name):
    if not r.ok:
        raise RuntimeError(redact("%s error %s: %s" % (name, r.status_code, r.text[:250])))
    return r


# ----------------------------------------------------------- PERSONAL-DATA SCRUBBER
SECRET_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{20,}|hf_[A-Za-z0-9]{20,}|"
                       r"tvly-[A-Za-z0-9\-]{16,}|gsk_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}|"
                       r"ghp_[A-Za-z0-9]{20,}|bfl_[A-Za-z0-9\-]{10,}|Bearer\s+[A-Za-z0-9._\-]{20,})")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
NUM_RE = re.compile(r"(?<![\w])\+?\d[\d\s\-()]{8,}\d(?![\w])")


def scrub(text):
    """returns (clean_text, number_of_items_removed)"""
    count = [0]

    def sub(rx, label, t):
        t, c = rx.subn(label, t)
        count[0] += c
        return t

    def num(m):
        d = len(re.sub(r"\D", "", m.group(0)))
        if d == 12:
            lab = "[id-number]"
        elif 13 <= d <= 19:
            lab = "[card-number]"
        elif 10 <= d <= 11:
            lab = "[phone]"
        else:
            return m.group(0)
        count[0] += 1
        return lab

    text = sub(SECRET_RE, "[secret]", text)
    text = sub(EMAIL_RE, "[email]", text)
    text = sub(PAN_RE, "[id-number]", text)
    text = sub(IP_RE, "[ip]", text)
    text = NUM_RE.sub(num, text)
    return text, count[0]


# ------------------------------------------------------------------ DATABASE
app = Flask(__name__)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, title TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT, role TEXT, content TEXT,
        rating TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS mistakes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, wrong_answer TEXT,
        correction TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS outbound_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, provider TEXT,
        purpose TEXT, preview TEXT, redactions INTEGER);
    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge USING fts5(title, body);
    CREATE VIRTUAL TABLE IF NOT EXISTS lessons USING fts5(question, answer, kind UNINDEXED);
    """)
    if c.execute("SELECT count(*) FROM knowledge").fetchone()[0] == 0:
        c.executemany("INSERT INTO knowledge(title, body) VALUES(?,?)", [
            ("Aarambh", "Aarambh is an Indian AI search and assistant. Tagline: Search, Explore, Grow. Made in India."),
            ("India capital", "The capital of India is New Delhi. India Gate is a war memorial in New Delhi."),
        ])
    c.commit()
    c.close()
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def get_setting(key, default="0"):
    r = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key, value):
    d = db()
    d.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, value))
    d.commit()


def local_only():
    return get_setting("local_only") == "1"


def enabled(kind, pid):
    return get_setting("off:%s:%s" % (kind, pid)) != "1"


def chat_ready(k):
    return bool(os.environ.get(CHAT_KEYS[k])) and enabled("chat", k)


def image_ready(k):
    return all(os.environ.get(e) for e in IMAGE_PROVIDERS[k][2]) and enabled("image", k)


def log_out(kind, provider, purpose, preview="", redactions=0):
    d = db()
    d.execute("INSERT INTO outbound_log(ts,kind,provider,purpose,preview,redactions) VALUES(?,?,?,?,?,?)",
              (time.time(), kind, provider, purpose, (preview or "")[:80], redactions))
    d.execute("DELETE FROM outbound_log WHERE id NOT IN (SELECT id FROM outbound_log ORDER BY id DESC LIMIT 500)")
    d.commit()


def fts_query(text):
    words = [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2][:8]
    return " OR ".join('"%s"' % w for w in words)


def local_knowledge(question, limit=3):
    q = fts_query(question)
    if not q:
        return []
    try:
        rows = db().execute("SELECT title, body FROM knowledge WHERE knowledge MATCH ? ORDER BY rank LIMIT ?",
                            (q, limit)).fetchall()
        return ["%s: %s" % (r["title"], r["body"]) for r in rows]
    except sqlite3.Error:
        return []


def find_lessons(question, limit=3):
    q = fts_query(question)
    if not q:
        return []
    try:
        rows = db().execute("SELECT question, answer, kind FROM lessons WHERE lessons MATCH ? ORDER BY rank LIMIT ?",
                            (q, limit)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for r in rows:
        label = "VERIFIED CORRECTION" if r["kind"] == "correction" else "APPROVED ANSWER"
        out.append("[%s] Q: %s | A: %s" % (label, r["question"][:200], r["answer"][:1200]))
    return out


# -------------------------------------------------------------- WEB SEARCH
def search_provider():
    if SEARCH_FORCED in ("tavily", "brave"):
        want = [SEARCH_FORCED]
    else:
        want = ["tavily", "brave"]
    for p in want:
        if os.environ.get(p.upper() + "_API_KEY") and enabled("search", p):
            return p
    return None


def wikipedia_facts(question, limit=2):
    out = []
    if not enabled("search", "wikipedia"):
        return out
    q, n = scrub(question)
    try:
        log_out("search", "wikipedia", "search", q, n)
        h = {"User-Agent": "Aarambh/3.0"}
        r = fetch("GET", "https://en.wikipedia.org/w/api.php", timeout=8, headers=h, params={
            "action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": limit})
        for hit in r.json().get("query", {}).get("search", []):
            t = hit["title"]
            s = fetch("GET", "https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(t, safe=""),
                      timeout=8, headers=h)
            if s.ok and s.json().get("extract"):
                out.append("Wikipedia - %s: %s" % (t, s.json()["extract"][:900]))
    except Exception:
        pass
    return out


def web_search(question, news=False):
    """returns (snippets, sources[{title,url}])"""
    snips, srcs = [], []
    q, n = scrub(question)
    prov = search_provider()
    try:
        if prov == "tavily":
            log_out("search", "tavily", "news" if news else "search", q, n)
            body = {"query": q, "max_results": 5, "include_answer": True, "search_depth": "basic"}
            if news:
                body["topic"] = "news"
            r = check(fetch("POST", "https://api.tavily.com/search", timeout=25,
                            headers={"Authorization": "Bearer " + os.environ["TAVILY_API_KEY"]}, json=body), "Tavily")
            j = r.json()
            if j.get("answer"):
                snips.append("Search summary: " + j["answer"])
            for x in j.get("results", []):
                snips.append("%s (%s): %s" % (x.get("title"), x.get("url"), (x.get("content") or "")[:700]))
                srcs.append({"title": x.get("title") or x.get("url"), "url": x.get("url")})
        elif prov == "brave":
            log_out("search", "brave", "news" if news else "search", q, n)
            url = "https://api.search.brave.com/res/v1/%s/search" % ("news" if news else "web")
            r = check(fetch("GET", url, timeout=20, params={"q": q, "count": 5},
                            headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"],
                                     "Accept": "application/json"}), "Brave")
            j = r.json()
            items = j.get("results", []) if news else j.get("web", {}).get("results", [])
            for x in items:
                snips.append("%s (%s): %s" % (x.get("title"), x.get("url"), (x.get("description") or "")[:700]))
                srcs.append({"title": x.get("title") or x.get("url"), "url": x.get("url")})
    except Exception as e:
        snips.append("(Live search failed: %s)" % redact(e)[:150])
    if not srcs:
        snips += wikipedia_facts(question)
    return snips, srcs


# ------------------------------------------------------------------ CHAT LLM
def _chat_call(provider, system, history, lang):
    if lang == "hi":
        system += " Reply in Hindi (Devanagari) unless the user writes in another language."
    while history and history[0]["role"] != "user":
        history = history[1:]
    if provider == "anthropic":
        r = check(fetch("POST", "https://api.anthropic.com/v1/messages", timeout=120, headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
            "content-type": "application/json"},
            json={"model": MODELS["anthropic"], "max_tokens": 2048, "system": system, "messages": history}),
            "Claude")
        return "".join(b.get("text", "") for b in r.json()["content"])
    if provider == "openai":
        r = check(fetch("POST", "https://api.openai.com/v1/chat/completions", timeout=120,
                        headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
                        json={"model": MODELS["openai"],
                              "messages": [{"role": "system", "content": system}] + history}), "ChatGPT")
        return r.json()["choices"][0]["message"]["content"]
    if provider == "gemini":
        contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
                    for m in history]
        r = check(fetch(
            "POST", "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % MODELS["gemini"],
            timeout=120, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={"system_instruction": {"parts": [{"text": system}]}, "contents": contents}), "Gemini")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("Unknown chat provider")


def call_chat(system, history, lang, brain="auto"):
    order = [k for k, _ in CHAT_ORDER if chat_ready(k)]
    if brain != "auto":
        order = [k for k in order if k == brain]
    if not order:
        raise RuntimeError("No chat brain available. Add ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY "
                           "to your .env file (and check it is switched ON in Privacy).")
    errs = []
    for k in order:
        try:
            log_out("chat", k, "answer", history[-1]["content"] if history else "", g.get("redactions", 0))
            return _chat_call(k, system, history, lang)
        except Exception as e:
            errs.append("%s: %s" % (CHAT_LABEL[k], redact(e)[:200]))
    raise RuntimeError(" | ".join(errs))


# ------------------------------------------------------------- IMAGE ENGINES
def img_pollinations(p):
    url = "https://image.pollinations.ai/prompt/%s?width=1024&height=1024&model=flux&nologo=true&seed=%d" % (
        quote(p[:800], safe=""), secrets.randbelow(10 ** 6))
    r = check(fetch("GET", url, timeout=120, stream=True), "Pollinations")
    buf = bytearray()
    for chunk in r.iter_content(65536):
        buf += chunk
        if len(buf) > MAX_IMG:
            raise RuntimeError("Image too large")
    return bytes(buf)


def img_cloudflare(p):
    url = "https://api.cloudflare.com/client/v4/accounts/%s/ai/run/@cf/black-forest-labs/flux-1-schnell" % quote(
        os.environ["CLOUDFLARE_ACCOUNT_ID"], safe="")
    r = check(fetch("POST", url, timeout=120, headers={"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"]},
                    json={"prompt": p, "steps": 4}), "Cloudflare")
    if r.headers.get("content-type", "").startswith("image/"):
        return r.content
    j = r.json()
    img = (j.get("result") or {}).get("image")
    if not img:
        raise RuntimeError("Cloudflare returned no image: " + str(j.get("errors"))[:200])
    return base64.b64decode(img)


def img_huggingface(p):
    model = os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    r = check(fetch("POST", "https://router.huggingface.co/hf-inference/models/" + model, timeout=180,
                    headers={"Authorization": "Bearer " + os.environ["HF_TOKEN"]}, json={"inputs": p}),
              "Hugging Face")
    return r.content


def img_together(p):
    r = check(fetch("POST", "https://api.together.xyz/v1/images/generations", timeout=120,
                    headers={"Authorization": "Bearer " + os.environ["TOGETHER_API_KEY"]},
                    json={"model": os.environ.get("TOGETHER_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell-Free"),
                          "prompt": p, "width": 1024, "height": 768, "steps": 4, "n": 1,
                          "response_format": "b64_json"}), "Together")
    d = r.json()["data"][0]
    return base64.b64decode(d["b64_json"]) if d.get("b64_json") else download_image(d["url"])


def img_gemini(p):
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    r = check(fetch("POST", "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
                    timeout=180, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                    json={"contents": [{"parts": [{"text": "Generate an image: " + p}]}],
                          "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}), "Gemini Images")
    for c in r.json().get("candidates", []):
        for part in (c.get("content") or {}).get("parts", []):
            d = part.get("inlineData") or part.get("inline_data")
            if d and d.get("data"):
                return base64.b64decode(d["data"])
    raise RuntimeError("Gemini returned no image (quota may be 0 on the free tier, or the prompt was refused)")


def img_openai(p):
    r = check(fetch("POST", "https://api.openai.com/v1/images/generations", timeout=180,
                    headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
                    json={"model": os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                          "prompt": p, "size": "1024x1024"}), "OpenAI Images")
    item = r.json()["data"][0]
    return base64.b64decode(item["b64_json"]) if item.get("b64_json") else download_image(item["url"])


def img_stability(p):
    r = check(fetch("POST", "https://api.stability.ai/v2beta/stable-image/generate/core", timeout=180,
                    headers={"Authorization": "Bearer " + os.environ["STABILITY_API_KEY"], "Accept": "image/*"},
                    files={"none": ""}, data={"prompt": p, "output_format": "png"}), "Stability")
    return r.content


def img_recraft(p):
    r = check(fetch("POST", "https://external.api.recraft.ai/v1/images/generations", timeout=180,
                    headers={"Authorization": "Bearer " + os.environ["RECRAFT_API_KEY"]},
                    json={"prompt": p, "model": os.environ.get("RECRAFT_MODEL", "recraftv3"),
                          "size": "1024x1024"}), "Recraft")
    d = r.json()["data"][0]
    return base64.b64decode(d["b64_json"]) if d.get("b64_json") else download_image(d["url"])


def img_ideogram(p):
    r = check(fetch("POST", "https://api.ideogram.ai/v1/ideogram-v3/generate", timeout=180,
                    headers={"Api-Key": os.environ["IDEOGRAM_API_KEY"]},
                    files={"prompt": (None, p), "rendering_speed": (None, "TURBO")}), "Ideogram")
    return download_image(r.json()["data"][0]["url"])


def img_flux_bfl(p):
    model = os.environ.get("BFL_MODEL", "flux-pro-1.1")
    h = {"x-key": os.environ["BFL_API_KEY"], "accept": "application/json"}
    r = check(fetch("POST", "https://api.bfl.ai/v1/" + quote(model, safe="-."), timeout=60, headers=h,
                    json={"prompt": p, "width": 1024, "height": 1024}), "FLUX")
    poll = r.json()["polling_url"]
    for _ in range(40):
        time.sleep(2.5)
        j = check(fetch("GET", poll, timeout=30, headers=h), "FLUX poll").json()
        if j.get("status") == "Ready":
            return download_image(j["result"]["sample"])
        if j.get("status") in ("Error", "Failed", "Request Moderated", "Content Moderated"):
            raise RuntimeError("FLUX: " + str(j.get("status")))
    raise RuntimeError("FLUX timed out")


def img_leonardo(p):
    h = {"accept": "application/json", "authorization": "Bearer " + os.environ["LEONARDO_API_KEY"]}
    body = {"prompt": p, "width": 1024, "height": 1024, "num_images": 1}
    if os.environ.get("LEONARDO_MODEL_ID"):
        body["modelId"] = os.environ["LEONARDO_MODEL_ID"]
    r = check(fetch("POST", "https://cloud.leonardo.ai/api/rest/v1/generations", timeout=60, headers=h, json=body),
              "Leonardo")
    gid = r.json()["sdGenerationJob"]["generationId"]
    for _ in range(40):
        time.sleep(3)
        j = check(fetch("GET", "https://cloud.leonardo.ai/api/rest/v1/generations/" + quote(gid, safe=""),
                        timeout=30, headers=h), "Leonardo poll").json().get("generations_by_pk") or {}
        if j.get("status") == "COMPLETE" and j.get("generated_images"):
            return download_image(j["generated_images"][0]["url"])
        if j.get("status") == "FAILED":
            raise RuntimeError("Leonardo generation failed")
    raise RuntimeError("Leonardo timed out")


IMG_FUNCS = {"pollinations": img_pollinations, "cloudflare": img_cloudflare, "huggingface": img_huggingface,
             "together": img_together, "gemini": img_gemini, "openai": img_openai, "stability": img_stability,
             "flux_bfl": img_flux_bfl, "recraft": img_recraft, "ideogram": img_ideogram, "leonardo": img_leonardo}
IMG_EXT = r"(?:png|jpg|webp)"
IMG_TOKEN = r"\[\[image:[a-f0-9]{32}\.%s\]\]" % IMG_EXT
IMG_RE = re.compile(r"\b(make|generate|create|draw|paint|design|show|produce)\b.{0,30}?"
                    r"\b(picture|image|photo|illustration|painting|logo|wallpaper|poster|drawing|artwork)\b", re.I)


def save_image(raw):
    if raw[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif raw[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise RuntimeError("Provider did not return a picture: " + redact(raw[:100].decode("utf-8", "replace")))
    name = uuid.uuid4().hex + "." + ext
    path = os.path.join(IMG_DIR, name)
    with open(path, "wb") as f:
        f.write(raw)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return name


def make_image(prompt, engine="auto", free_only=True):
    if local_only():
        raise RuntimeError("Local-only mode is ON, so images cannot be made. Turn it off in Privacy.")
    clean, n = scrub(prompt)
    ready = [k for k in IMAGE_ORDER if image_ready(k)]
    if engine != "auto":
        order = [k for k in ready if k == engine]
    else:
        order = [k for k in ready if IMAGE_PROVIDERS[k][1] == "free"] if free_only else ready
    if not order:
        raise RuntimeError("No image engine is ready. Free options: Pollinations needs no key; or add "
                           "CLOUDFLARE_*, HF_TOKEN, TOGETHER_API_KEY or GEMINI_API_KEY to .env. "
                           "Also check the engine is switched ON in Privacy.")
    errs = []
    for k in order:
        label = IMAGE_PROVIDERS[k][0]
        try:
            log_out("image", k, "image", clean, n)
            return save_image(IMG_FUNCS[k](clean[:1500])), label
        except Exception as e:
            errs.append("%s: %s" % (label, redact(e)[:160]))
    raise RuntimeError(" | ".join(errs))


# ------------------------------------------------------------------- GUARDS
_hits = {}


def rate_ok(ip, limit=30, window=60):
    now = time.time()
    q = _hits.setdefault(ip, [])
    q[:] = [t for t in q if now - t < window]
    if len(q) >= limit:
        return False
    q.append(now)
    return True


@app.before_request
def guard():
    pin = os.environ.get("AARAMBH_PIN")
    if pin:
        a = request.authorization
        if not a or not hmac.compare_digest((a.password or "").encode(), pin.encode()):
            return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Aarambh"'})
    if request.method == "POST":
        o = request.headers.get("Origin")
        if o and urlparse(o).netloc != request.host:
            abort(403)
        if not request.is_json:
            abort(415)


@app.after_request
def secure_headers(resp):
    n = g.get("nonce")
    script = "script-src 'self' 'nonce-%s'" % n if n else "script-src 'none'"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; %s; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'" % script)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# -------------------------------------------------------------------- API
def today():
    return datetime.date.today().strftime("%A, %d %B %Y")


SYSTEM = (
    "You are Aarambh, a helpful, accurate AI assistant made in India. Today's date is {date}. "
    "Answer clearly and completely. Use the CONTEXT when relevant and prefer it over guesses. "
    "VERIFIED CORRECTION items come from the user and must be followed over everything else. "
    "For live facts (news, scores, prices) rely only on the search context and mention the source; "
    "if you do not have reliable information, say so honestly instead of inventing. "
    "Put code in triple-backtick blocks."
)


def history_for_llm(conv_id, private, limit=20):
    rows = db().execute("SELECT role, content FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?",
                        (conv_id, limit)).fetchall()[::-1]
    out, total = [], 0
    for r in rows:
        c = re.sub(IMG_TOKEN, "(an image was generated here)", r["content"])
        if private:
            c, n = scrub(c)
            total += n
        out.append({"role": r["role"], "content": c})
    g.redactions = total
    return out


@app.post("/api/chat")
def chat():
    if not rate_ok(request.remote_addr):
        return jsonify(error="Too many requests. Please wait a minute."), 429
    data = request.get_json(silent=True) or {}
    text = (data.get("message") or "").strip()[:4000]
    lang = data.get("lang", "en")
    mode = data.get("mode", "ask")
    use_web = bool(data.get("web", True))
    verify = bool(data.get("verify", False))
    private = bool(data.get("private", True))
    engine = data.get("engine", "auto")
    free_only = bool(data.get("free_only", True))
    brain = data.get("brain", "auto")
    if not text:
        return jsonify(error="Empty message"), 400
    conv_id = data.get("conv_id") or uuid.uuid4().hex
    d = db()
    if not d.execute("SELECT 1 FROM conversations WHERE id=?", (conv_id,)).fetchone():
        d.execute("INSERT INTO conversations VALUES(?,?,?)", (conv_id, text[:60], time.time()))
    d.execute("INSERT INTO messages(conv_id,role,content,created) VALUES(?,?,?,?)",
              (conv_id, "user", text, time.time()))
    d.commit()

    def save_answer(content):
        cur = d.execute("INSERT INTO messages(conv_id,role,content,created) VALUES(?,?,?,?)",
                        (conv_id, "assistant", content, time.time()))
        d.commit()
        return cur.lastrowid

    # ---- image request
    if mode == "image" or IMG_RE.search(text):
        try:
            name, label = make_image(text, engine, free_only)
            content = "[[image:%s]]Here is your image (made with %s)." % (name, label)
        except Exception as e:
            content = "Sorry, I could not make the image. " + redact(e)[:600]
        return jsonify(answer=content, conv_id=conv_id, id=save_answer(content))

    # ---- text answer
    lessons = find_lessons(text)
    local = local_knowledge(text)
    web, sources = [], []
    if (use_web or mode == "news") and not local_only():
        web, sources = web_search(text, news=(mode == "news"))
    ctx = lessons + local + web

    if local_only():
        answer = ("🔒 Local-only mode is ON, so nothing was sent outside. From your saved data:\n- " +
                  "\n- ".join(lessons + local)) if (lessons + local) else (
            "🔒 Local-only mode is ON and I have nothing saved about this. Teach me, or turn it off in Privacy.")
        return jsonify(answer=answer, conv_id=conv_id, id=save_answer(answer), sources=[], learned_used=len(lessons))

    system = SYSTEM.format(date=today())
    if ctx:
        system += "\n\nCONTEXT:\n- " + "\n- ".join(ctx)
    history = history_for_llm(conv_id, private)
    if private:
        system, n = scrub(system)
        g.redactions = g.get("redactions", 0) + n
    try:
        answer = call_chat(system, history, lang, brain)
        if verify:
            answer = call_chat(
                "You are a strict fact-checker. Compare the DRAFT with the CONTEXT and your own knowledge. "
                "Fix errors, remove unsupported claims, keep the useful parts. Output ONLY the final answer. "
                "Today is %s." % today(),
                [{"role": "user", "content": "QUESTION:\n%s\n\nCONTEXT:\n%s\n\nDRAFT:\n%s" % (
                    history[-1]["content"], "\n".join(ctx) or "(none)", answer)}], lang, brain)
    except Exception as e:
        return jsonify(error=redact(e), conv_id=conv_id), 500
    return jsonify(answer=answer, conv_id=conv_id, id=save_answer(answer), sources=sources,
                   learned_used=len(lessons))


@app.post("/api/feedback")
def feedback():
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    correction = (data.get("correction") or "").strip()[:3000]
    d = db()
    msg = d.execute("SELECT * FROM messages WHERE id=? AND role='assistant'", (data.get("id"),)).fetchone()
    if not msg or rating not in ("up", "down"):
        return jsonify(error="bad request"), 400
    q = d.execute("SELECT content FROM messages WHERE conv_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1",
                  (msg["conv_id"], msg["id"])).fetchone()
    question = q["content"] if q else ""
    d.execute("UPDATE messages SET rating=? WHERE id=?", (rating, msg["id"]))
    if "[[image:" not in msg["content"] and question:
        if rating == "up":
            d.execute("INSERT INTO lessons(question, answer, kind) VALUES(?,?,?)",
                      (question, msg["content"][:1500], "approved"))
        else:
            d.execute("INSERT INTO mistakes(question, wrong_answer, correction, created) VALUES(?,?,?,?)",
                      (question, msg["content"], correction, time.time()))
            if correction:
                d.execute("INSERT INTO lessons(question, answer, kind) VALUES(?,?,?)",
                          (question, correction, "correction"))
    d.commit()
    return jsonify(ok=True)


@app.post("/api/teach")
def teach():
    data = request.get_json(silent=True) or {}
    title, body = (data.get("title") or "").strip()[:200], (data.get("body") or "").strip()[:4000]
    if not title or not body:
        return jsonify(error="title and body required"), 400
    d = db()
    d.execute("INSERT INTO knowledge(title, body) VALUES(?,?)", (title, body))
    d.commit()
    return jsonify(ok=True)


@app.get("/api/privacy")
def privacy_get():
    d = db()
    items = []
    for k, _ in CHAT_ORDER:
        items.append({"kind": "chat", "id": k, "label": CHAT_LABEL[k] + " (chat)",
                      "has_key": bool(os.environ.get(CHAT_KEYS[k])), "on": enabled("chat", k)})
    for k in ("tavily", "brave"):
        items.append({"kind": "search", "id": k, "label": k.capitalize() + " (web search)",
                      "has_key": bool(os.environ.get(k.upper() + "_API_KEY")), "on": enabled("search", k)})
    items.append({"kind": "search", "id": "wikipedia", "label": "Wikipedia (facts)", "has_key": True,
                  "on": enabled("search", "wikipedia")})
    for k in IMAGE_ORDER:
        v = IMAGE_PROVIDERS[k]
        items.append({"kind": "image", "id": k, "label": "%s (image, %s)" % (v[0], v[1]),
                      "has_key": all(os.environ.get(e) for e in v[2]), "on": enabled("image", k)})
    rows = d.execute("SELECT ts, kind, provider, purpose, preview, redactions FROM outbound_log "
                     "ORDER BY id DESC LIMIT 40").fetchall()
    return jsonify(local_only=local_only(), items=items, log=[dict(r) for r in rows])


@app.post("/api/privacy")
def privacy_set():
    data = request.get_json(silent=True) or {}
    if "local_only" in data:
        set_setting("local_only", "1" if data["local_only"] else "0")
    if data.get("kind") in ("chat", "search", "image") and isinstance(data.get("id"), str) \
            and re.fullmatch(r"[a-z_]{3,20}", data["id"]):
        set_setting("off:%s:%s" % (data["kind"], data["id"]), "0" if data.get("enabled") else "1")
    if data.get("clear_log"):
        db().execute("DELETE FROM outbound_log")
        db().commit()
    return jsonify(ok=True)


@app.get("/api/history")
def history():
    rows = db().execute("SELECT id, title FROM conversations ORDER BY created DESC LIMIT 40").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/conversation/<cid>")
def conversation(cid):
    rows = db().execute("SELECT id, role, content, rating FROM messages WHERE conv_id=? ORDER BY id",
                        (cid,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/status")
def status():
    d = db()
    return jsonify(
        chat=[{"id": k, "label": CHAT_LABEL[k]} for k, _ in CHAT_ORDER if chat_ready(k)],
        search=search_provider() or "wikipedia",
        images=[{"id": k, "label": IMAGE_PROVIDERS[k][0], "group": IMAGE_PROVIDERS[k][1]}
                for k in IMAGE_ORDER if image_ready(k)],
        sites=[{"name": n, "url": u} for n, u in LINKOUTS],
        local_only=local_only(),
        lessons=d.execute("SELECT count(*) FROM lessons").fetchone()[0],
        facts=d.execute("SELECT count(*) FROM knowledge").fetchone()[0],
        mistakes=d.execute("SELECT count(*) FROM mistakes").fetchone()[0])


@app.get("/img/<name>")
def img(name):
    if not re.fullmatch(r"[a-f0-9]{32}\.%s" % IMG_EXT, name):
        abort(404)
    return send_from_directory(IMG_DIR, name)


@app.get("/bg")
def bg():
    if not os.path.exists(os.path.join(BASE, "background.jpg")):
        abort(404)
    return send_from_directory(BASE, "background.jpg")


# -------------------------------------------------------------------- UI
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Aarambh</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Segoe UI,system-ui,sans-serif;min-height:100vh;color:#222;
background:url(/bg) center/cover fixed,linear-gradient(180deg,#3a4a8a 0%,#e9a36b 45%,#f6d9a8 70%,#2f6b4a 100%)}
.wrap{max-width:880px;margin:0 auto;padding:16px}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.badges{font-size:11px;color:#fff;text-shadow:0 1px 3px #0008}
.top button{border:0;border-radius:20px;padding:6px 14px;background:rgba(255,255,255,.88);cursor:pointer;margin-left:6px}
.logo{text-align:center;margin:18px 0 2px;font-size:44px;font-weight:700;letter-spacing:3px;color:#fff;text-shadow:0 2px 10px #0007}
.logo span{color:#ff8a1f}.tag{text-align:center;color:#fff;letter-spacing:4px;font-size:12px;margin-bottom:16px;text-shadow:0 1px 4px #0008}
.bar{display:flex;align-items:center;background:#fff;border-radius:40px;padding:8px 10px;box-shadow:0 6px 22px #0004}
.bar input{flex:1;border:0;outline:0;font-size:16px;padding:8px 12px;background:transparent;min-width:0}
.go,.mic{border:0;border-radius:50%;width:42px;height:42px;font-size:18px;cursor:pointer}
.go{background:#ff8a1f;color:#fff}.mic{background:#f1f1f1;margin-right:6px}
.chips{display:flex;gap:8px;justify-content:center;margin:14px 0 6px;flex-wrap:wrap}
.chip{background:rgba(255,255,255,.85);border:2px solid transparent;padding:7px 14px;border-radius:18px;font-size:13px;cursor:pointer}
.chip.on{border-color:#ff8a1f;background:#fff;font-weight:600}
.opts{text-align:center;color:#fff;font-size:13px;text-shadow:0 1px 3px #0008;line-height:2}
.opts label{margin:0 8px;cursor:pointer}.opts select{padding:3px 6px;border-radius:8px;border:0}
#imgopts{display:none}
#chat{margin-top:10px}
.m{margin:10px 0;padding:12px 16px;border-radius:16px;line-height:1.55;word-wrap:break-word;white-space:pre-wrap}
.u{background:#ff8a1f;color:#fff;margin-left:18%}.a{background:rgba(255,255,255,.96);margin-right:8%}
.a img{max-width:100%;border-radius:12px;display:block;margin-bottom:8px}
pre{background:#1e1e2e;color:#eee;padding:10px;border-radius:8px;overflow:auto;white-space:pre}
code{background:#eee;padding:1px 5px;border-radius:4px}pre code{background:none;padding:0}
.src{font-size:12px;color:#555;margin-top:8px;white-space:normal}.src a{color:#0a5bd6}
.fb{margin-top:8px;white-space:normal}.fb button{border:1px solid #ddd;background:#fff;border-radius:14px;padding:3px 10px;cursor:pointer;margin-right:6px}
.fb .done{color:#2a7;font-size:12px}
.panel{margin-top:14px;background:rgba(255,255,255,.94);border-radius:12px;padding:12px;display:none;font-size:14px}
.panel input[type=text],.panel textarea,.panel input:not([type]){width:100%;margin:4px 0;padding:8px;border:1px solid #ccc;border-radius:6px;font:inherit}
.panel button{padding:6px 14px;border:0;border-radius:8px;background:#ff8a1f;color:#fff;cursor:pointer;margin-top:4px}
.panel h4{margin:10px 0 4px}.row{display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-bottom:1px solid #eee}
.row small{color:#777}.log{font-size:12px;color:#444;border-bottom:1px solid #eee;padding:3px 0;word-break:break-word}
.hist div{padding:6px 4px;border-bottom:1px solid #eee;cursor:pointer}.hist div:hover{background:#fff4e8}
.foot{text-align:center;color:#fff;margin:22px 0 8px;font-style:italic;text-shadow:0 1px 4px #0008}
.stat{text-align:center;color:#fff;font-size:12px;text-shadow:0 1px 3px #0008}
</style></head><body><div class="wrap">
<div class="top"><div class="badges" id="badges"></div>
<div><button id="lang">English | हिन्दी</button><button id="btnPriv">🔒 Privacy</button><button id="hist">History</button><button id="new">New chat</button></div></div>
<div class="logo"><span>A</span>ARAMBH</div><div class="tag">SEARCH · EXPLORE · GROW</div>
<form class="bar" id="f"><input id="q" placeholder="Search anything..." autocomplete="off">
<button type="button" class="mic" id="mic" title="Speak">🎤</button><button class="go" type="submit">➤</button></form>
<div class="chips" id="chips">
<div class="chip on" data-m="ask">🌐 Web</div><div class="chip" data-m="image">🖼 Images</div>
<div class="chip" data-m="video">▶ Videos</div><div class="chip" data-m="news">📰 News</div>
<div class="chip" data-m="map">📍 Maps</div><div class="chip" data-m="teach">⋯ Teach</div></div>
<div class="opts">
<label><input type="checkbox" id="web" checked> Live web search</label>
<label><input type="checkbox" id="verify"> Double-check answer</label>
<label><input type="checkbox" id="private" checked> Private mode (hide personal data)</label>
<label>Brain: <select id="brain"></select></label>
<div id="imgopts"><label>Image engine: <select id="engine"></select></label>
<label><input type="checkbox" id="free" checked> Free engines only</label>
<label>Other sites: <select id="sites"></select></label></div></div>
<div class="panel" id="pTeach"><b>Teach Aarambh</b> (saved permanently in your database)
<input id="tt" placeholder="Topic"><textarea id="tb" rows="3" placeholder="Correct facts"></textarea>
<button id="ts">Save</button></div>
<div class="panel" id="pPriv"></div>
<div class="panel hist" id="pHist"></div>
<div id="chat"></div>
<div class="stat" id="stat"></div><div class="foot">Made in India 🇮🇳</div></div>
<script nonce="__NONCE__">
let conv=null,lang="en",mode="ask";
const $=id=>document.getElementById(id),chat=$("chat");
const esc=s=>s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const post=(u,o)=>fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)});
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function opt(sel,v,l){const o=document.createElement("option");o.value=v;o.textContent=l;sel.appendChild(o)}
function fmt(t){
 return t.split("```").map((p,i)=>{
  if(i%2){return "<pre><code>"+esc(p.replace(/^[\w+-]*\n/,""))+"</code></pre>"}
  let s=esc(p);
  s=s.replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g,"<b>$1</b>");
  s=s.replace(/(https?:\/\/[^\s<)]+)/g,'<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  return s}).join("")}
function body(t){
 const m=t.match(/^\[\[image:([a-f0-9]{32}\.(?:png|jpg|webp))\]\]([\s\S]*)$/);
 if(m)return '<img src="/img/'+m[1]+'" alt="generated image">'+fmt(m[2]);
 return fmt(t)}
function add(cls,html){const d=document.createElement("div");d.className="m "+cls;d.innerHTML=html;chat.appendChild(d);d.scrollIntoView({block:"end"});return d}
function addAnswer(e,j){
 let h=body(j.answer);
 if(j.sources&&j.sources.length){h+='<div class="src">Sources: '+j.sources.map(s=>'<a href="'+encodeURI(s.url)+'" target="_blank" rel="noopener noreferrer">'+esc(s.title||s.url)+'</a>').join(" · ")+'</div>'}
 if(j.learned_used){h+='<div class="src">🧠 Used '+j.learned_used+' thing(s) I learned from you</div>'}
 if(j.id){h+='<div class="fb" data-id="'+j.id+'"><button data-r="up">👍 Good</button><button data-r="down">👎 Wrong</button></div>'}
 e.innerHTML=h}
chat.onclick=async e=>{
 const b=e.target.closest("button[data-r]");if(!b)return;
 const box=b.parentNode,id=box.dataset.id,r=b.dataset.r;let c="";
 if(r==="down"){c=prompt("What is the correct answer? (Aarambh will remember it. Leave blank to just flag it.)")||""}
 const res=await post("/api/feedback",{id:+id,rating:r,correction:c});
 box.innerHTML=res.ok?'<span class="done">'+(r==="up"?"Thanks! Saved as approved.":"Thanks! I will learn from this.")+'</span>':"Could not save";
 loadStatus()};
$("chips").onclick=e=>{const c=e.target.closest(".chip");if(!c)return;
 mode=c.dataset.m;document.querySelectorAll(".chip").forEach(x=>x.classList.toggle("on",x===c));
 $("pTeach").style.display=mode==="teach"?"block":"none";
 $("imgopts").style.display=mode==="image"?"block":"none";
 $("q").placeholder={image:"Describe the picture to create...",video:"Search videos on YouTube...",news:"Search latest news...",map:"Search a place..."}[mode]||"Search anything...";
 if(mode==="teach")mode="ask";$("q").focus()};
$("lang").onclick=()=>{lang=lang==="en"?"hi":"en";alert("Reply language: "+(lang==="en"?"English":"हिन्दी"))};
$("new").onclick=()=>{conv=null;chat.innerHTML="";$("pHist").style.display="none"};
$("hist").onclick=async()=>{const p=$("pHist");if(p.style.display==="block"){p.style.display="none";return}
 const r=await (await fetch("/api/history")).json();p.textContent="";
 if(!r.length)p.textContent="No chats yet";
 r.forEach(x=>{const d=el("div",x.title||"Chat");d.dataset.id=x.id;p.appendChild(d)});p.style.display="block"};
$("pHist").onclick=async e=>{const d=e.target.closest("div[data-id]");if(!d)return;
 conv=d.dataset.id;chat.innerHTML="";
 const ms=await (await fetch("/api/conversation/"+encodeURIComponent(conv))).json();
 ms.forEach(m=>{if(m.role==="user")add("u",esc(m.content));else{const x=add("a","");addAnswer(x,{answer:m.content,id:m.rating?null:m.id})}});
 $("pHist").style.display="none"};
$("ts").onclick=async()=>{const r=await post("/api/teach",{title:$("tt").value,body:$("tb").value});
 alert(r.ok?"Saved":"Please fill both boxes");if(r.ok){$("tt").value=$("tb").value=""}loadStatus()};
$("sites").onchange=async()=>{const u=$("sites").value;if(!u)return;const t=$("q").value.trim();
 try{await navigator.clipboard.writeText(t)}catch(e){}
 window.open(u,"_blank","noopener,noreferrer");$("sites").value="";
 if(t)alert("Your prompt was copied to the clipboard. Paste it on the site.")};
$("f").onsubmit=async e=>{e.preventDefault();const t=$("q").value.trim();if(!t)return;
 if(mode==="video"){window.open("https://www.youtube.com/results?search_query="+encodeURIComponent(t),"_blank","noopener,noreferrer");return}
 if(mode==="map"){window.open("https://www.google.com/maps/search/"+encodeURIComponent(t),"_blank","noopener,noreferrer");return}
 $("q").value="";add("u",esc(t));const w=add("a",mode==="image"?"Creating your image... (can take up to a minute)":"Thinking...");
 try{const r=await post("/api/chat",{message:t,conv_id:conv,lang:lang,mode:mode,web:$("web").checked,verify:$("verify").checked,
  private:$("private").checked,brain:$("brain").value,engine:$("engine").value,free_only:$("free").checked});
  const j=await r.json();if(j.conv_id)conv=j.conv_id;
  if(j.error){w.textContent="Error: "+j.error;return}
  addAnswer(w,j);loadStatus()}catch(err){w.textContent="Network error - is the server running?"}};
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
$("mic").onclick=()=>{if(!SR){alert("Voice input is not supported in this browser (try Chrome).");return}
 const r=new SR();r.lang=lang==="hi"?"hi-IN":"en-IN";r.onresult=e=>{$("q").value=e.results[0][0].transcript;$("q").focus()};r.start()};
async function loadStatus(){try{const s=await (await fetch("/api/status")).json();
 $("badges").textContent="Brain: "+(s.chat.length?s.chat.map(x=>x.label).join(" / "):"NOT SET")+" · Search: "+s.search+" · Image engines: "+s.images.length+(s.local_only?" · 🔒 LOCAL-ONLY ON":"");
 const b=$("brain"),bv=b.value;b.textContent="";opt(b,"auto","Auto (with fallback)");s.chat.forEach(x=>opt(b,x.id,x.label));b.value=bv||"auto";
 const g=$("engine"),gv=g.value;g.textContent="";opt(g,"auto","Auto (free first)");s.images.forEach(x=>opt(g,x.id,x.label+" ("+x.group+")"));g.value=gv||"auto";
 const st=$("sites");if(!st.options.length){opt(st,"","Open another site...");s.sites.forEach(x=>opt(st,x.url,x.name))}
 $("stat").textContent="🧠 Learned: "+s.lessons+" lessons · "+s.facts+" saved facts · "+s.mistakes+" mistakes reviewed"}catch(e){}}
$("btnPriv").onclick=async()=>{const p=$("pPriv");if(p.style.display==="block"){p.style.display="none";return}await renderPriv();p.style.display="block"};
async function renderPriv(){
 const j=await (await fetch("/api/privacy")).json(),p=$("pPriv");p.textContent="";
 p.appendChild(el("b","🔒 Privacy area"));
 p.appendChild(el("div","Outside services only get what the app sends them: the question, or just the picture prompt for image engines. They never get your database, chat history, lessons or API keys. Personal data (email, phone, ID numbers, keys) is removed from image prompts and search queries. Every outside call is listed below."));
 const lo=el("label","");const cb=document.createElement("input");cb.type="checkbox";cb.checked=j.local_only;
 cb.onchange=async()=>{await post("/api/privacy",{local_only:cb.checked});await renderPriv();loadStatus()};
 lo.appendChild(cb);lo.appendChild(document.createTextNode(" LOCAL-ONLY mode: nothing leaves this computer (answers only from your saved data)"));
 p.appendChild(el("h4","Mode"));p.appendChild(lo);
 p.appendChild(el("h4","Services (untick to block completely)"));
 j.items.forEach(it=>{const r=el("div","","row");const l=document.createElement("label");const c=document.createElement("input");
  c.type="checkbox";c.checked=it.on;c.onchange=async()=>{await post("/api/privacy",{kind:it.kind,id:it.id,enabled:c.checked});loadStatus()};
  l.appendChild(c);l.appendChild(document.createTextNode(" "+it.label));r.appendChild(l);
  r.appendChild(el("small",it.has_key?"key set":"no key"));p.appendChild(r)});
 p.appendChild(el("h4","Audit log: last outside calls"));
 if(!j.log.length)p.appendChild(el("div","Nothing has left this computer yet."));
 j.log.forEach(x=>p.appendChild(el("div",new Date(x.ts*1000).toLocaleTimeString()+" · "+x.kind+" · "+x.provider+" · removed "+x.redactions+" personal item(s) · \""+x.preview+"\"","log")));
 const cl=el("button","Clear log");cl.onclick=async()=>{await post("/api/privacy",{clear_log:true});renderPriv()};p.appendChild(cl)}
loadStatus();
</script></body></html>"""


@app.get("/")
def index():
    g.nonce = secrets.token_urlsafe(16)
    return Response(PAGE.replace("__NONCE__", g.nonce), mimetype="text/html")


if __name__ == "__main__":
    init_db()
    print("Chat brains :", ", ".join(k for k, e in CHAT_KEYS.items() if os.environ.get(e)) or "NONE - add a key to .env")
    print("Image engines ready:", ", ".join(k for k in IMAGE_ORDER if all(os.environ.get(e) for e in IMAGE_PROVIDERS[k][2])))
    print("Open http://127.0.0.1:5000   (listening on this computer only)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
