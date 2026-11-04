/* pyworker.js: the command-line tools (psx-mufap/scripts/*.py), run in the browser.
 *
 * A Web Worker, so long jobs (backtests for a proposal) never freeze the page. It loads Pyodide
 * (Python compiled to WebAssembly) from jsDelivr on first use, copies the scripts and brokers.json
 * from this site into Python's in-memory file system, and builds a data folder from the prices the
 * page has already decrypted (webrun.py). Nothing is sent anywhere: the only downloads are Python
 * itself and this site's own scripts.
 *
 * Messages in:  {id, cmd: "init"|"setup"|"run"|"paper"|"config", ...}
 * Messages out: {id, ok: true, result} or {id, ok: false, error}
 */
/* global importScripts, loadPyodide */
var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
// Every script the tools import. tests/test_all.py checks this list against psx-mufap/scripts/.
var SCRIPTS = ["advice", "alerts", "analyst", "backtest", "broker", "budget", "common", "daily", "dashboard", "desk", "entry",
  "exitplan", "freshness", "funds", "insiders", "intraday", "news", "paper", "pkdata", "pkm", "portfolio", "profiles", "propose",
  "psxinfo", "rank", "risk", "scanner", "signals", "sip", "timemachine", "watchlist", "webhome", "webrun"];
var ROOT = "/pkm/psx-mufap", HOME = "/pkm/home";
var py = null, ready = null;

// ssl isn't in the browser's Python (there is no network for it anyway): a stand-in so the tools import.
var SSL_SHIM = [
  "import sys, types",
  "try:",
  "    import ssl",
  "except ImportError:",
  "    m = types.ModuleType('ssl')",
  "    class _Ctx:",
  "        post_handshake_auth = None",
  "        check_hostname = False",
  "        verify_mode = 0",
  "        def set_alpn_protocols(self, *a): pass",
  "        def load_verify_locations(self, *a, **k): pass",
  "        def wrap_socket(self, *a, **k): raise OSError('no network in the browser')",
  "    m.SSLError = type('SSLError', (OSError,), {})",
  "    m.CertificateError = type('CertificateError', (ValueError,), {})",
  "    m.SSLContext = _Ctx",
  "    m.create_default_context = lambda *a, **k: _Ctx()",
  "    m._create_default_https_context = m.create_default_context",
  "    m.PROTOCOL_TLS_CLIENT = 16",
  "    m.HAS_SNI = True",
  "    sys.modules['ssl'] = m",
  "sys.path.insert(0, '" + ROOT + "/scripts')",
  "import os",
  "os.environ['PKM_HOME'] = '" + HOME + "'",
  "os.environ['PKM_VIEW'] = 'table'",
  "os.environ['HOME'] = '/pkm'"
].join("\n");

function init(base) {
  if (ready) return ready;
  ready = (function () {
    importScripts(PYODIDE + "pyodide.js");
    return loadPyodide({ indexURL: PYODIDE });
  })().then(function (p) {
    py = p;
    py.FS.mkdirTree(ROOT + "/scripts");
    py.FS.mkdirTree(HOME);
    var get = function (url) { return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url + ": " + r.status); return r.text(); }); };
    return Promise.all(SCRIPTS.map(function (s) {
      return get(base + "../scripts/" + s + ".py").then(function (t) { py.FS.writeFile(ROOT + "/scripts/" + s + ".py", t); });
    }).concat([get(base + "../brokers.json").then(function (t) { py.FS.writeFile(ROOT + "/brokers.json", t); })]));
  }).then(function () {
    py.runPython(SSL_SHIM);
    py.runPython("import webrun");
    return { python: py.version };
  });
  ready.catch(function () { ready = null; });   // a failed load can be retried
  return ready;
}

function call(fn, args) {
  var mod = py.pyimport("webrun");
  var r = mod[fn].apply(null, args || []);
  var out = (r && typeof r.toJs === "function") ? r.toJs({ dict_converter: Object.fromEntries }) : r;
  if (r && typeof r.destroy === "function") r.destroy();
  mod.destroy();
  return out;
}

// Before each run: your ledger and your risk profile from the page, so the tools see what the page shows.
function sync(m) {
  if (m.ledger) {
    py.FS.mkdirTree(HOME + "/portfolio");
    py.FS.writeFile(HOME + "/portfolio/ledger.json", JSON.stringify(m.ledger, null, 1));
  }
  Object.keys(m.put || {}).forEach(function (path) { py.FS.writeFile(path, m.put[path]); });   // a page you uploaded
  if (m.profile) py.runPython("import common as C\nC.write_user_config('" + HOME + "', {'risk_profile': " + JSON.stringify(m.profile) + "})");
}

self.onmessage = function (ev) {
  var m = ev.data || {}, reply = function (ok, x) { self.postMessage(ok ? { id: m.id, ok: true, result: x } : { id: m.id, ok: false, error: String((x && x.message) || x) }); };
  var job;
  try {
    if (m.cmd === "init") job = init(m.base);
    else if (m.cmd === "setup") job = init(m.base).then(function () {
      return call("setup", [HOME, m.months || "{}", m.meta || "{}", m.files || "{}", m.config || "{}"]);
    });
    else if (m.cmd === "run") job = init(m.base).then(function () {
      sync(m);
      var r = call("run", [m.tool, py.toPy(m.args || [])]);
      return { out: r.out, code: r.code, files: call("user_files", []) };
    });
    else if (m.cmd === "paper") job = init(m.base).then(function () { sync(m); return JSON.parse(call("paper_data", [])); });
    else if (m.cmd === "config") job = init(m.base).then(function () { return JSON.parse(call("config", [])); });
    else throw new Error("unknown command " + m.cmd);
  } catch (e) { reply(false, e); return; }
  Promise.resolve(job).then(function (x) { reply(true, x); }, function (e) { reply(false, e); });
};
