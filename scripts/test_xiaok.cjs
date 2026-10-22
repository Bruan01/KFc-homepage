/* Shared entry behavior, using DOM stubs rather than a browser. */
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm"), assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname, "../static/xiaok.js"), "utf8");
const flush = async () => { for (let i = 0; i < 5; i++) await new Promise(setImmediate); };
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.events = {}; this.value = ""; this.classes = new Set(); this.classList = { add: value => this.classes.add(value), toggle: (value, enabled) => { if (enabled) this.classes.add(value); else this.classes.delete(value); } }; }
  set textContent(value) { this.value = value; this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent || "").join(""); }
  setAttribute(key, value) { this[key] = value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.value = ""; this.children = children; }
  addEventListener(event, handler) { this.events[event] = handler; }
  remove() { this.removed = true; }
  focus() { this.focused = true; }
  querySelector(selector) { return this.children.find(child => child.tag === selector) || null; }
}
function tree(root) { return [root, ...root.children.flatMap(tree)]; }
function run({ account = null, failed = false, saved = new Map(), pathname = "/" } = {}) {
  const body = new Element("body"), header = new Element("header"), guideLink = new Element("a"), heroLink = new Element("a"), calls = [];
  guideLink.href = "/guide";
  header.querySelector = () => guideLink;
  heroLink.dataset.xiaokOfficial = ""; heroLink.href = "/guide"; heroLink.textContent = "认识社区";
  body.append(header, heroLink);
  const document = {
    readyState: "complete", body,
    createElement: tag => new Element(tag),
    querySelector: selector => selector === "header" ? header : null,
    querySelectorAll: () => tree(body).filter(node => !node.removed && Object.hasOwn(node.dataset, "xiaokOfficial")),
    getElementById: id => tree(body).find(node => node.id === id && !node.removed),
  };
  let manualCount = 0;
  const window = { KflowGuide: { openWelcome() { manualCount++; } } };
  const fetch = async (url, options) => { calls.push({ url, options }); if (failed) throw Error("Offline"); return { ok: true, json: async () => ({ account }) }; };
  const sessionStorage = { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  vm.runInNewContext(source, { window, document, sessionStorage, location: { pathname }, fetch });
  return { window, body, heroLink, guideLink, saved, calls, get manualCount() { return manualCount; }, companion() { return document.getElementById("xiaokCompanion"); } };
}
(async () => {
  const guest = run(); await flush();
  assert(guest.companion());
  const [close, profile, guide, restore] = guest.companion().children;
  assert.equal(profile.href, "/guide"); assert.equal(guest.heroLink.href, "/guide");
  assert.equal(profile.children[0].src, "/static/xiaok/chibi-welcome-v2.png");
  guide.events.click(); assert.equal(guest.manualCount, 1);
  assert(restore.hidden); assert(!profile.hidden);
  close.events.click(); assert(guest.companion()); assert(restore.focused);
  assert(!restore.hidden); assert(profile.hidden); assert(guide.hidden); assert(close.hidden);
  const nextPage = run({ saved: guest.saved }); await flush(); assert(nextPage.companion());
  const [nextClose, nextProfile, nextGuide, nextRestore] = nextPage.companion().children;
  assert(nextProfile.hidden); assert(!nextRestore.hidden);
  nextRestore.events.click(); assert(!nextProfile.hidden); assert(!nextGuide.hidden); assert(!nextClose.hidden);
  assert(nextRestore.hidden); assert(nextProfile.focused); assert.equal(nextPage.saved.get("kflow:xiaok:hidden:v1"), "0");
  const restoredPage = run({ saved: nextPage.saved }); await flush(); assert(!restoredPage.companion().children[1].hidden);

  const account = { username: "小k & friends", display_name: "<img onerror=alert(1)>", profile_url: "https://untrusted.example" };
  const configured = run({ account }); await flush();
  const official = configured.companion().children[1];
  const expected = "/forum/user/" + encodeURIComponent(account.username);
  assert.equal(official.href, expected); assert.equal(configured.heroLink.href, expected);
  assert.equal(official.children[1].textContent, "官方主页");
  assert.equal(official.children[0].tag, "img", "Identity update must preserve character artwork");
  assert.equal(official["aria-label"], "小 K 官方主页：" + account.display_name);
  assert.equal(configured.calls.length, 1); assert.equal(configured.calls[0].url, "/api/community/official");
  const offline = run({ failed: true }); await flush(); assert.equal(offline.companion().children[1].href, "/guide");
  const admin = run({ pathname: "/admin/users" }); await flush(); assert(!admin.companion()); assert.equal(admin.calls.length, 0);

  const helpers = configured.window.KflowXiaok;
  const empty = helpers.empty("<script>title</script>", "plain description");
  assert.equal(empty.children[1].textContent, "<script>title</script>");
  const toast = new Element("div"); toast.textContent = "发布成功"; helpers.decorateToast(toast);
  assert.equal(toast.children[0].src, "/static/xiaok/chibi-done-v2.png");
  assert.equal(toast.textContent, "发布成功"); assert(toast.classes.has("xiaok-toast"));
  toast.children[0].events.error(); assert(toast.children[0].removed);
  console.log("PASS: official identity, safe profile paths, guide fallback, manual welcome, collapse/restore and reload persistence, image fallback and plain-text feedback");
})().catch(error => { console.error(error); process.exitCode = 1; });
