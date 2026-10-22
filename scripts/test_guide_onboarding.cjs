/* State/interaction checks using a small DOM stub; no browser or dependencies. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../static/guide-onboarding.js"), "utf8");
const VISITED = "kflow:guide:visited:v1", WELCOME = "kflow:guide:welcome:v1";
const user = { username: "alice", role: "user" };
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.classes = new Set(); this.classList = { add: value => this.classes.add(value), remove: value => this.classes.delete(value), contains: value => this.classes.has(value) }; }
  setAttribute(key, value) { this[key] = value; }
  append(...children) { this.children.push(...children); }
  addEventListener(event, handler) { this.events[event] = handler; }
  contains(target) { return this === target || this.children.some(child => child.contains?.(target)); }
  remove() { this.removed = true; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  getBoundingClientRect() { return { left: 100, right: 560, top: 100, bottom: 580 }; }
}
function findClass(node, name) {
  if (node?.className === name) return node;
  for (const child of node?.children || []) { const match = findClass(child, name); if (match) return match; }
  return null;
}
function storage(map, unavailable) {
  return { getItem(key) { if (unavailable) throw Error("Unavailable"); return map.get(key) ?? null; }, setItem(key, value) { if (unavailable) throw Error("Unavailable"); map.set(key, value); } };
}
function run({ pathname = "/", auth = null, local = new Map(), session = new Map(), server = { state: null }, brokenStorage = false, failedAPI = false } = {}) {
  const header = new Element("header"), fixedLink = new Element("a"), calls = [];
  header.querySelector = () => fixedLink;
  const body = new Element("body");
  body.append = modal => { header.banner = modal; };
  const document = {
    readyState: "complete", cookie: "other=x; csrftoken=test-csrf", activeElement: null, body,
    createElement: tag => new Element(tag),
    querySelector(selector) { return selector === "header" ? header : header.banner && !header.banner.removed ? header.banner : null; },
  };
  const fetch = async (url, options) => {
    calls.push({ url, options });
    if (failedAPI) throw Error("Offline");
    let claimed = false;
    if (options.method === "POST") {
      assert.equal(options.headers["X-CSRFToken"], "test-csrf");
      const { action } = JSON.parse(options.body);
      if (action === "visited") server.state = "visited";
      else if (action === "shown" && server.state === "pending") { server.state = "shown"; claimed = true; }
      else if (action === "dismissed" && ["pending", "shown"].includes(server.state)) server.state = "dismissed";
    }
    const result = { state: server.state, should_prompt: server.state === "pending", claimed };
    return { ok: true, json: async () => result };
  };
  const window = { localStorage: storage(local, brokenStorage), sessionStorage: storage(session, false), kflowAuthReady: Promise.resolve(auth) };
  vm.runInNewContext(source, { window, document, location: { pathname }, fetch });
  return { header, fixedLink, document, window, local, session, calls, server, banner() { return header.banner && !header.banner.removed ? header.banner : null; } };
}

(async () => {
  const guest = run(); await flush();
  assert(guest.banner()); assert.equal(guest.calls.length, 0);
  assert.equal(guest.banner().tag, "dialog"); assert(guest.banner().open);
  assert(guest.document.body.classList.contains("guide-welcome-open"));
  assert.equal(guest.banner()["aria-describedby"], "guideWelcomeDescription");
  assert(findClass(guest.banner(), "guide-welcome-read").autofocus);
  assert.equal(findClass(guest.banner(), "guide-welcome-figure").children[0].src, "/static/xiaok/chibi-welcome-v2.png");
  const skip = findClass(guest.banner(), "guide-welcome-skip");
  guest.document.activeElement = skip; skip.events.click();
  assert(!guest.banner()); assert(guest.fixedLink.focused);
  assert(!guest.document.body.classList.contains("guide-welcome-open"));
  const repeat = run({ local: guest.local }); await flush(); assert(!repeat.banner());
  const away = run({ pathname: "/forum" }); await flush(); assert(!away.banner());

  const reader = run({ pathname: "/guide" }); await flush();
  assert.equal(reader.local.get(VISITED), "1"); assert(!reader.banner());
  const readAgain = run({ local: reader.local }); await flush(); assert(!readAgain.banner());
  const oldProgress = run({ local: new Map([["kflow:guide:progress:v1", JSON.stringify({ current: "learning", completed: ["community"] })]]) });
  await flush(); assert(!oldProgress.banner());

  // A guest dismissal does not suppress the distinct new-account welcome.
  const registered = run({ auth: user, local: guest.local, server: { state: "pending" } }); await flush();
  assert(registered.banner()); assert.equal(registered.server.state, "shown");
  findClass(registered.banner(), "guide-welcome-skip").events.click(); await flush();
  assert.equal(registered.server.state, "dismissed");
  const otherDevice = run({ auth: user, server: registered.server }); await flush(); assert(!otherDevice.banner());

  const visitedNewUser = run({ auth: user, local: reader.local, server: { state: "pending" } }); await flush();
  assert.equal(visitedNewUser.server.state, "visited"); assert(!visitedNewUser.banner());
  const noRepeatedWrite = run({ auth: user, local: reader.local, server: visitedNewUser.server }); await flush();
  assert.equal(noRepeatedWrite.calls.length, 0);
  const existing = run({ auth: user }); await flush(); assert(!existing.banner());
  await existing.window.KflowGuide.openWelcome(); assert(existing.banner(), "Existing users may explicitly reopen the guide welcome");
  findClass(existing.banner(), "guide-welcome-close").events.click(); await flush();
  assert(!existing.banner()); assert.equal(existing.server.state, null);
  const offline = run({ auth: user, failedAPI: true }); await flush(); assert(!offline.banner());
  const admin = run({ auth: { ...user, role: "admin" } }); await flush(); assert.equal(admin.calls.length, 0);
  const consolePage = run({ pathname: "/admin" }); await flush(); assert(!consolePage.banner());

  const fallback = run({ brokenStorage: true }); await flush(); assert(fallback.banner());
  const fallbackRepeat = run({ brokenStorage: true, session: fallback.session }); await flush(); assert(!fallbackRepeat.banner());
  let resolveAuth;
  const waiting = run({ auth: new Promise(resolve => { resolveAuth = resolve; }) });
  await flush(); assert(!waiting.banner()); resolveAuth(user); await flush(); assert(!waiting.banner());

  const shared = { state: "pending" };
  const tab1 = run({ auth: user, server: shared }), tab2 = run({ auth: user, server: shared });
  await flush(); assert.equal(Number(!!tab1.banner()) + Number(!!tab2.banner()), 1);
  for (const way of ["close", "escape", "backdrop", "read"]) {
    const modalCase = run(); await flush();
    const modal = modalCase.banner();
    if (way === "close") findClass(modal, "guide-welcome-close").events.click();
    if (way === "escape") { let prevented = false; modal.events.cancel({ preventDefault() { prevented = true; } }); assert(prevented); }
    if (way === "backdrop") {
      modal.events.click({ target: modal, clientX: 150, clientY: 150 }); assert(modalCase.banner(), "Inside padding must not dismiss");
      modal.events.click({ target: modal, clientX: 50, clientY: 50 });
    }
    if (way === "read") { const read = findClass(modal, "guide-welcome-read"); assert.equal(read.href, "/guide"); read.events.click(); assert(!modalCase.local.has(VISITED)); }
    assert(!modalCase.banner()); assert(!modal.open);
    assert(!modalCase.document.body.classList.contains("guide-welcome-open"));
  }
  console.log("PASS: welcome state, registration handoff, account persistence, storage fallback, auth wait, tab claim; modal open, close button, Escape, backdrop, read link, scroll unlock and focus return");
})().catch(error => { console.error(error); process.exitCode = 1; });
