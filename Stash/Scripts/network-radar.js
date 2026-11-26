const STORE_KEY = "proxyconfig.network-radar.v1";
const DETAIL = "http://network-radar.invalid/";
const PROBE = "https://cp.cloudflare.com/generate_204";
const TRACE = "https://www.cloudflare.com/cdn-cgi/trace";
const UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1";
const SERVICES = [
  { id: "nf", name: "Netflix", policy: "Netflix", domain: "netflix.com" },
  { id: "dp", name: "Disney+", policy: "Disney", domain: "disneyplus.com", url: "https://www.disneyplus.com/" },
  { id: "tk", name: "TikTok", policy: "TikTok", domain: "tiktok.com", url: "https://www.tiktok.com/" },
  { id: "gpt", name: "ChatGPT", policy: "OpenAI", domain: "chatgpt.com", url: "https://chatgpt.com/cdn-cgi/trace" },
  { id: "cl", name: "Claude", policy: "Anthropic", domain: "claude.ai", url: "https://claude.ai/cdn-cgi/trace" },
  { id: "gm", name: "Gemini", policy: "Gemini", domain: "gemini.google.com", url: "https://gemini.google.com/" },
  { id: "bili", name: "哔哩哔哩", policy: "CN Mainland TV", domain: "bilibili.com", url: "https://api.bilibili.com/x/web-interface/zone" },
  { id: "yt", name: "YouTube", policy: "YouTube", domain: "youtube.com", url: "https://www.youtube.com/generate_204" },
  { id: "icloud", name: "iCloud", policy: "Apple", domain: "icloud.com", url: "https://www.icloud.com/" },
];

function clean(value, max = 120) {
  return typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max) : '';
}
function ipAddress(value) {
  const ip = clean(value, 64);
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) return ip.split('.').every(p => Number(p) <= 255) ? ip : '';
  if (!/^[\da-f:]+$/i.test(ip) || !ip.includes(':') || ip.includes(':::')) return '';
  const halves = ip.split('::'), parts = ip.split(':').filter(Boolean);
  if (halves.length > 2 || halves.some(h => h && !/^[\da-f]{1,4}(:[\da-f]{1,4})*$/i.test(h))) return '';
  if (halves.length === 1 ? parts.length !== 8 || ip.startsWith(':') || ip.endsWith(':') : parts.length >= 8) return '';
  return ip.toLowerCase();
}
function country(value) { return /^[A-Z]{2}$/.test(String(value || '').toUpperCase()) ? String(value).toUpperCase() : ''; }
function asn(value) { const s = String(value || '').replace(/^AS/i, ''); return /^\d{1,10}$/.test(s) ? `AS${s}` : ''; }
function carrier(value) {
  const s = clean(value);
  if (/cmcc|cmnet|china mobile|移动/i.test(s)) return '中国移动';
  if (/chinanet|china telecom|电信/i.test(s)) return '中国电信';
  if (/unicom|cncgroup|联通/i.test(s)) return '中国联通';
  if (/china broadnet|广电/i.test(s)) return '中国广电';
  return s || '未知';
}

const unknown = (reason = 'unrecognized') => ({ state: 'unknown', cc: '', reason });
function challengePage(body) {
  const title = body.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] || '';
  const visible = body.length < 1000 ? body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<[^>]+>/g, ' ').trim() : '';
  // Normal Netflix/Disney/TikTok pages include CAPTCHA libraries/translations.
  // A bare substring is not evidence that the response is a challenge page.
  return /just a moment|attention required|access denied|verify.*human|security check|captcha/i.test(title) ||
    /<form[^>]+id=["']challenge-form["']|window\._cf_chl_opt\s*=/i.test(body) ||
    /just a moment|checking your browser|^captcha$|access denied/i.test(visible);
}
function serviceURL(location, base, domains) {
  const origin = base.match(/^https:\/\/[^/]+/i)?.[0];
  if (!origin || !location || /[\s\\]/.test(location)) return '';
  const target = location.startsWith('//') ? `https:${location}` : location.startsWith('/') ? origin + location
    : /^https:\/\//i.test(location) ? location : /^[a-z][a-z\d+.-]*:/i.test(location) ? ''
    : location.startsWith('?') ? base.split('?')[0] + location : base.replace(/[^/]*$/, '') + location;
  const host = target.match(/^https:\/\/([a-z\d.-]+)(?=\/|\?|#|$)/i)?.[1]?.toLowerCase();
  return host && domains.some(d => host === d || host.endsWith('.' + d)) ? target.split('#')[0] : '';
}
function serviceResult(r, id) {
  if (!r) return unknown('connection');
  if (r.reason) return unknown(r.reason);
  const body = (r.body || '').replace(/\\"/g, '"'), location = r.location || '';
  if (r.status === 429) return unknown('rate_limit');
  if (r.status >= 500) return unknown(`http_${r.status}`);
  if (challengePage(body)) return unknown('challenge');
  const title = body.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] || '';
  if (/\/(?:unavailable|unsupported-country)(?:[/?#]|$)|unsupported.country/i.test(location) ||
    /app unavailable|not available in your (country|region)/i.test(title) ||
    body.length < 2000 && /app unavailable|not available in your (country|region)|not available in certain regions|forbidden-location/i.test(body)) return { state: 'restricted', cc: '' };
  if (r.status !== 200) return unknown(`http_${r.status}`);
  if (!body.trim()) return unknown('empty');
  if (id === 'GPT' || id === 'CL') {
    const cc = country(body.match(/^loc=([A-Z]{2})\s*$/m)?.[1]);
    // Cloudflare trace is regional evidence, not a product unlock test.
    return cc ? { state: 'region', cc } : unknown();
  }
  if (id === 'TK') {
    const cc = country(body.match(/"region"\s*:\s*"([A-Z]{2})(?:-[A-Z\d]+)?"/i)?.[1]);
    return cc ? { state: 'reachable', cc } : unknown();
  }
  if (id === 'DP') {
    const supported = body.match(/"inSupportedLocation"\s*:\s*(true|false)/i)?.[1];
    const cc = country(body.match(/"(?:countryCode|region)"\s*:\s*"([A-Z]{2})"/i)?.[1]);
    if (supported === 'false') return { state: 'restricted', cc };
    if (supported === 'true' || /Disney\+/i.test(title) && cc) return { state: 'reachable', cc };
  }
  if (id === 'GM') {
    const cc = body.match(/,\s*2,\s*1,\s*200,\s*"([A-Z]{3})"/)?.[1];
    if (cc) return { state: 'region', cc };
    if (/BardChatUi|boq_assistant-bard/i.test(body)) return { state: 'reachable', cc: '' };
  }
  if (id === 'NF') {
    const titleID = r.url?.match(/\/title\/(\d+)/)?.[1];
    if (/Netflix/i.test(title) && titleID && body.includes(titleID)) {
      const cc = country(r.url.match(/netflix\.com\/([a-z]{2})(?:-[a-z]{2})?\/title\//i)?.[1]);
      return { state: 'reachable', cc };
    }
  }
  return unknown();
}

function readJSON(raw) {
  try {
    const value = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function readState() {
  return readJSON($persistentStore.read(STORE_KEY));
}

// Keep a missing callback from delaying the other path or the next service.
function bounded(promise, ms, fallback) {
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(fallback), ms);
    Promise.resolve(promise).then(value => {
      clearTimeout(timer);
      resolve(value);
    }, () => {
      clearTimeout(timer);
      resolve(fallback);
    });
  });
}

async function request(url, policy, timeout = 4000) {
  const clockMs = typeof performance !== "undefined" && typeof performance.now === "function" ? () => performance.now() : Date.now;
  const started = clockMs();
  const response = new Promise((resolve, reject) => {
    $httpClient.get({
      url, timeout: Math.ceil(timeout / 1000), "auto-cookie": false, "auto-redirect": false,
      headers: { "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Cache-Control": "no-cache",
        "X-Stash-Selected-Proxy": encodeURIComponent(policy) },
    }, (error, r, body) => {
      if (error || !r) return reject();
      const elapsed = clockMs() - started;
      resolve({ status: Number(r.status ?? r.statusCode), body: typeof body === "string" ? body : "",
        location: clean(r.headers?.location || r.headers?.Location, 1000), url, ms: elapsed >= 0 ? Math.round(elapsed) : null });
    });
  });
  return bounded(response, timeout, null);
}

async function fetchGeo(policy) {
  for (const [source, url] of [["IPPure", "https://my.ippure.com/v1/info"], ["IP.SB", "https://api.ip.sb/geoip"]]) {
    const r = await request(url, policy);
    const j = r?.status === 200 ? readJSON(r.body) : {};
    const ip = ipAddress(j.ip);
    if (!ip) continue;
    const pure = source === "IPPure";
    const score = pure && Number.isFinite(j.fraudScore) && j.fraudScore >= 0 && j.fraudScore <= 100 ? j.fraudScore : null;
    const org = clean(pure ? j.asOrganization : j.asn_organization || j.organization);
    return { ip, source, country: clean(j.country), cc: country(j.countryCode || j.country_code),
      region: clean(j.region), city: clean(j.city), asn: asn(j.asn), org, isp: carrier(j.isp || org),
      score, residential: pure && typeof j.isResidential === "boolean" ? j.isResidential : null };
  }
  return { error: true };
}

async function measureExit(policy) {
  const [geo, probe] = await Promise.all([fetchGeo(policy), request(PROBE, policy)]);
  return { ...geo, policy, ms: probe?.status === 204 ? probe.ms : null };
}

function visibleName(value) {
  const text = clean(value, 80);
  return /^(?:<redacted>|redacted|<unknown ssid>|unknown|null)$/i.test(text) ? "" : text;
}

async function deviceNetwork() {
  let info = {};
  if (typeof $httpAPI === "function") {
    try { info = await bounded($httpAPI("GET", "/diagnosis/network"), 1800, {}) || {}; } catch {}
  }
  const runtime = typeof $network === "object" && $network ? $network : {};
  const iface = clean(info.interface || runtime.v4?.primaryInterface, 32).toLowerCase();
  const ssid = visibleName(info.ssid ?? runtime.wifi?.ssid);
  const radio = clean(info.radioAccessTechnology || info.cellular?.radio || info.radio || runtime.cellular?.radio, 64);
  const tech = radio.replace(/^CTRadioAccessTechnology/i, "").replace(/[-_ ]/g, "").toUpperCase();
  let kind = "网络未知";
  if (/^wi-?fi$/.test(iface) || ((!iface || /^en\d+$/.test(iface)) && ssid)) kind = "Wi-Fi";
  else if (/^(cellular|wwan|pdp_ip\d+)$/.test(iface) || (!iface && !ssid && tech)) kind = "蜂窝";
  else if (iface === "ethernet") kind = "以太网";
  const generation = /^(NR|NRSA|NRNSA|5G)$/.test(tech) ? "5G" : /^(LTE|4G)$/.test(tech) ? "4G" :
    /^(WCDMA|HSDPA|HSUPA|CDMAEVDOREVA|3G)$/.test(tech) ? "3G" : "";
  return { kind, ssid: kind === "Wi-Fi" ? ssid : "", generation: kind === "蜂窝" ? generation : "",
    carrier: kind === "蜂窝" ? visibleName(info.cellular?.carrier || info.carrier || runtime.cellular?.carrier) : "",
    local: ipAddress(info.ipv4?.address || info.address || runtime.v4?.primaryAddress),
    gateway: ipAddress(info.ipv4?.gateway || info.gateway || runtime.v4?.primaryRouter) };
}

async function serviceRequest(url, policy, domain) {
  const deadline = Date.now() + 6000;
  const seen = new Set();
  for (let hop = 0; hop < 4; hop++) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) return { reason: "timeout" };
    if (seen.has(url)) break;
    seen.add(url);
    const r = await request(url, policy, Math.min(remaining, 3500));
    if (!r) return { reason: "connection" };
    if (![301, 302, 303, 307, 308].includes(r.status) || /\/(unavailable|unsupported-country)\b/i.test(r.location)) return r;
    url = serviceURL(r.location, url, [domain]);
    if (!url) break;
  }
  return { reason: "redirect" };
}

function traceExit(response) {
  if (response?.status !== 200) return {};
  return { ip: ipAddress(response.body.match(/^ip=([^\s]+)\s*$/m)?.[1]), cc: country(response.body.match(/^loc=([A-Z]{2})\s*$/m)?.[1]) };
}

async function serviceCheck(service, policy) {
  if (service.id === "nf") {
    const responses = await Promise.all(["70143836", "81280792"].map(id =>
      serviceRequest("https://www.netflix.com/title/" + id, policy, service.domain)));
    const [a, b] = responses.map(r => serviceResult(r, "NF"));
    if (a.state === "reachable" && b.state === "reachable") return a;
    if (responses[0].status === 404 && b.state === "reachable" || responses[1].status === 404 && a.state === "reachable") {
      return { state: "limited", cc: a.cc || b.cc };
    }
    if (a.state === "restricted" || b.state === "restricted") return a.state === "restricted" ? a : b;
    return a.state === "unknown" ? a : b;
  }
  const r = await serviceRequest(service.url, policy, service.domain);
  if (service.id === "yt" && r.status === 204) return { state: "reachable", cc: "" };
  if (r.status === 200 && service.id === "bili") {
    const j = readJSON(r.body);
    if (j.code === 0 && ipAddress(j.data?.addr)) return { state: "reachable", cc: "", exit: { ip: ipAddress(j.data.addr), place: clean(j.data.country) } };
  }
  if (r.status === 200 && service.id === "icloud" && !challengePage(r.body) && /<title[^>]*>[^<]*icloud[^<]*<\/title>/i.test(r.body)) {
    return { state: "reachable", cc: "" };
  }
  const result = serviceResult(r, service.id.toUpperCase());
  if (service.id === "gpt" || service.id === "cl") {
    const exit = traceExit(r);
    if (exit.ip) result.exit = exit;
  }
  return result;
}

// Process three services at a time to limit large response bodies in the VPN extension.
async function collectServices(options, active) {
  const results = {};
  const traces = new Map();
  let next = 0;
  async function consume() {
    while (next < SERVICES.length && active()) {
      const service = SERVICES[next++];
      const policy = clean(options.servicePolicies?.[service.id], 100) || service.policy;
      const result = await serviceCheck(service, policy);
      let exitSource = "业务响应";
      if (!result.exit?.ip && active()) {
        if (!traces.has(policy)) traces.set(policy, request(TRACE, policy, 3000).then(traceExit));
        result.exit = await traces.get(policy);
        exitSource = "同策略 Cloudflare 回显";
      }
      results[service.id] = { ...result, exitSource: result.exit?.ip ? exitSource : "", policy, at: Date.now() };
    }
  }
  await Promise.all([consume(), consume(), consume()]);
  return results;
}

function validMs(ms) { return Number.isFinite(ms) && ms >= 0; }
function historyOf(route) {
  return Array.isArray(route?.history) ? route.history.filter(p => p?.at > 0 && validMs(p.ms)).slice(-7) : [];
}

function withHistory(measured, previous, at, oldState) {
  const history = historyOf(previous);
  if (validMs(measured.ms)) history.push({ at, ms: measured.ms });
  const route = { ...measured, history: history.slice(-7) };
  // The old worker timed its IP.SB lookup. Keep the genuine reading, labelled with its own target.
  const legacy = oldState.version === 4 ? previous?.legacy :
    !previous?.error && ipAddress(previous?.ip) && validMs(previous?.ms) && oldState.checked_at > 0
      ? { at: oldState.checked_at, ms: previous.ms } : null;
  if (legacy) route.legacy = legacy;
  return route;
}

function clock(at) {
  if (!Number.isFinite(at) || at <= 0) return "未检测";
  const d = new Date(at);
  const pad = value => String(value).padStart(2, "0");
  return pad(d.getMonth() + 1) + "/" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
}

function displayIP(ip, mask) {
  if (!ipAddress(ip)) return "未取得";
  if (!mask) return ip;
  return ip.includes(":") ? ip.split(":").slice(0, 2).join(":") + ":…" : ip.split(".").slice(0, 2).join(".") + ".*.*";
}
function locationOf(route) {
  return [...new Set([route?.country || route?.cc, route?.region, route?.city].filter(Boolean))].join(" · ");
}
function quality(route) {
  if (!Number.isFinite(route?.score)) return "风险分未提供";
  const level = route.score >= 70 ? "高风险" : route.score >= 40 ? "中风险" : "低风险";
  return level + " " + route.score + "/100";
}
function property(route) {
  return route?.residential === true ? "住宅" : route?.residential === false ? "机房 / 商业" : "属性未知";
}
function access(net = {}) {
  if (net.kind === "Wi-Fi") return "Wi-Fi · " + (net.ssid || "SSID 未提供");
  if (net.kind === "蜂窝") return [net.generation || "蜂窝（制式未知）", net.carrier].filter(Boolean).join(" · ");
  return net.kind || "网络未知";
}
function statusText(s) {
  const labels = { reachable: "可达", region: "服务地区", limited: "部分片目", restricted: "地区受限" };
  if (labels[s?.state]) return [labels[s.state], s.cc].filter(Boolean).join(" ");
  const reasons = { rate_limit: "限流", challenge: "需验证", connection: "连接失败", timeout: "超时", redirect: "未确认跳转",
    empty: "空响应", unrecognized: "未识别响应" };
  if (/^http_\d{3}$/.test(s?.reason || "")) return "HTTP " + s.reason.slice(5);
  return reasons[s?.reason] || "待检测";
}
function bars(history) {
  const levels = "▁▂▃▄▅▆▇█";
  return history.map(p => levels[Math.max(0, Math.min(7, Math.ceil(p.ms / 20) - 1))]).join("");
}

function exitCard(key, state) {
  const route = state[key], direct = key === "direct", history = historyOf(route);
  const place = clean(route?.city || route?.region || route?.cc || route?.country, 22);
  const title = [direct ? "直连" : "代理", place].filter(Boolean).join(" · ");
  const current = validMs(route?.ms) ? route.ms + " ms" : "本次 HTTP 失败";
  const lines = [
    route?.ip ? displayIP(route.ip, state.maskIP) + " · " + (clean(route.isp, 42) || "运营商未知") : "出口 IP 未取得",
    [bars(history), current].filter(Boolean).join("  "),
    [route?.asn, quality(route)].filter(Boolean).join(" · "),
    direct ? access(state.network) : property(route),
  ];
  return { title, content: lines.join("\n"), backgroundColor: !route?.ip || !validMs(route.ms) ? "#975821" : direct ? "#21605a" : "#345586" };
}
function serviceCard(service, state) {
  const result = state.services?.[service.id];
  const base = { title: service.name, backgroundColor: "#6b7280" };
  if (!state.servicesEnabled) return { ...base, content: "业务探测已关闭" };
  if (!result) return { ...base, content: "等待业务检测" };
  const colors = { reachable: "#21605a", region: "#345586", restricted: "#9d403a", limited: "#975821" };
  const place = result.exit?.cc || result.exit?.place;
  return { title: [service.name, place].filter(Boolean).join(" · "), backgroundColor: colors[result.state] || "#975821",
    content: [statusText(result), result.policy + " · " + displayIP(result.exit?.ip, state.maskIP)].join("\n") };
}
function save(state) {
  state.cards = { direct: exitCard("direct", state), proxy: exitCard("proxy", state) };
  for (const service of SERVICES) state.cards[service.id] = serviceCard(service, state);
  if (!$persistentStore.write(JSON.stringify(state), STORE_KEY)) throw new Error("storage");
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function rows(values) {
  return "<dl>" + values.map(([label, value]) => "<dt>" + escapeHTML(label) + "</dt><dd>" + escapeHTML(value || "未提供") + "</dd>").join("") + "</dl>";
}
function exitDetails(key, state) {
  const route = state[key] || {}, history = historyOf(route);
  const fields = [["策略", route.policy || (key === "direct" ? "DIRECT" : "Proxy")],
    ["出口 IP", displayIP(route.ip, state.maskIP)], ["地区", locationOf(route)], ["运营商", route.isp],
    ["ASN", route.asn], ["AS 组织", route.org], ["IP 属性", property(route)], ["IPPure 风险分", quality(route)],
    ["位置与属性来源", route.source || (route.ip && "IP.SB")], ["最近检测", clock(state.checked_at)]];
  const recent = history.map(p => "<li><time>" + clock(p.at) + "</time><strong>" + p.ms + " ms</strong></li>").join("");
  const legacy = route.legacy || (state.version !== 4 && route.ip && validMs(route.ms) ? { at: state.checked_at, ms: route.ms } : null);
  return '<section id="' + key + '"><h2>' + (key === "direct" ? "直连" : "代理") + "出口</h2>" + rows(fields) +
    "<h3>最近 " + history.length + " 次成功的 HTTP 采样</h3>" +
    (recent ? "<ol>" + recent + "</ol>" : "<p>等待首次成功采样。</p>") +
    (state.version === 4 && !validMs(route.ms) ? "<p>本次 HTTP 探测失败，保留此前的实测值。</p>" : "") +
    (legacy ? "<p>旧版 IP.SB 查询 · " + clock(legacy.at) + " · " + Number(legacy.ms) + " ms</p>" : "") + "</section>";
}

function details(state, note = "") {
  const net = state.network || {};
  const device = rows([["网络", net.kind], ["Wi-Fi SSID", net.kind === "蜂窝" ? "蜂窝接入" : net.ssid],
    ["蜂窝制式", net.kind === "Wi-Fi" ? "Wi-Fi 接入" : net.generation], ["蜂窝运营商", net.carrier],
    ["内网 IP", displayIP(net.local, state.maskIP)], ["网关", displayIP(net.gateway, state.maskIP)]]);
  const services = SERVICES.map(service => {
    const r = state.services?.[service.id];
    return '<article id="' + service.id + '"><h3>' + service.name + "</h3>" +
      rows([["策略", r?.policy || state.servicePolicies?.[service.id] || service.policy],
        ["探测结果", state.servicesEnabled === false ? "已关闭" : statusText(r)],
        ["策略出口 IP", displayIP(r?.exit?.ip, state.maskIP)], ["出口地区", r?.exit?.cc || r?.exit?.place], ["出口来源", r?.exitSource],
        ["检查时间", clock(r?.at)]]) + "</article>";
  }).join("");
  const style = ":root{color-scheme:light dark}*{box-sizing:border-box}body{font:16px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;margin:0 auto;max-width:38rem;padding:1rem;color:#172839;background:#f2f5f6}h1{font-size:1.6rem}h2{font-size:1.2rem}h3{font-size:1rem}section{background:#fff;border-radius:14px;padding:.4rem 1rem 1rem;margin:1rem 0}#direct{border-top:4px solid #21605a}#proxy{border-top:4px solid #345586}article+article{border-top:1px solid #8997a755}dl{display:grid;grid-template-columns:auto 1fr;gap:.35rem .8rem}dt,time{color:#52606b}dd{margin:0;text-align:right;overflow-wrap:anywhere}ol{padding:0}li{display:flex;justify-content:space-between;font-variant-numeric:tabular-nums}button{font:inherit;padding:.6rem 1rem;border-radius:.6rem;cursor:pointer}p{font-size:.9rem}@media(prefers-color-scheme:dark){body{background:#131a21;color:#e4edf1}section{background:#1f2b35}dt,time{color:#b6c5cf}}";
  const html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>网络雷达</title><style>' + style +
    '</style><main><h1>网络雷达</h1><p>' + escapeHTML(note || ("最近采样 · " + clock(state.checked_at))) +
    '</p><form method="post" action="/"><button type="submit">立即检测</button></form><section><h2>本机接入网络</h2>' +
    device + "</section>" + exitDetails("direct", state) + exitDetails("proxy", state) +
    "<p>两条路径访问相同的 Cloudflare 204 端点。每级 20 ms，柱子从左到右由早到晚。IPPure 风险分越高，风险越高。</p>" +
    "<section><h2>业务出口</h2><p>出口由业务响应或同策略的 IP 回显取得。服务地区和页面可达性分别记录，播放与账号权限需在服务内确认。</p>" +
    services + "</section></main></html>";
  return { response: { status: 200, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'" }, body: html } };
}

async function refresh(options, event) {
  const lockKey = STORE_KEY + ".run";
  const now = Date.now(), last = readJSON($persistentStore.read(lockKey));
  if (!event && last.id && now >= last.at && now - last.at < 45000) return "检测进行中";
  const id = String(now) + "-" + Math.random();
  const claim = JSON.stringify({ id, at: now });
  if (!$persistentStore.write(claim, lockKey)) throw new Error("storage");
  const active = () => $persistentStore.read(lockKey) === claim;
  try {
    const proxyPolicy = clean(options.proxyPolicy, 100) || "Proxy";
    const [network, direct, proxy] = await Promise.all([deviceNetwork(), measureExit("DIRECT"), measureExit(proxyPolicy)]);
    if (!active()) return "网络已切换，新的检测正在进行";
    const old = readState(), at = Date.now();
    const state = { version: 4, checked_at: at, network, maskIP: options.maskIP === true, servicesEnabled: options.servicesEnabled !== false,
      servicePolicies: options.servicePolicies || {}, direct: withHistory(direct, old.direct, at, old),
      proxy: withHistory(proxy, old.proxy, at, old), services: {} };
    save(state);
    if (state.servicesEnabled) {
      state.services = await collectServices(options, active);
      if (active()) save(state);
    }
    return active() ? "检测完成 · " + clock(at) : "网络已切换，新的检测正在进行";
  } finally {
    if (active()) $persistentStore.write("", lockKey);
  }
}

async function run() {
  const options = readJSON(typeof $argument === "string" ? $argument : "");
  const type = typeof $script === "object" && $script ? $script.type : "";
  // Old providers can still call the public script directly as a Tile.
  if (type === "tile" || options.mode === "status") {
    const state = readState(), key = options.route === "direct" ? "direct" : "proxy";
    return state.cards?.[key] || { title: "网络雷达", content: state[key]?.ip || "等待首次后台检测" };
  }
  if (typeof $request !== "undefined" && $request) {
    const headers = $request.headers || {};
    const origin = headers.Origin || headers.origin;
    const referer = headers.Referer || headers.referer || "";
    const sameOrigin = origin ? origin === DETAIL.slice(0, -1) : referer.startsWith(DETAIL);
    let note = "";
    if ($request.method === "POST" && sameOrigin) note = await refresh(options, false);
    return details(readState(), note);
  }
  await refresh(options, type === "event" || options.trigger === "network");
}

run().then(value => $done(value), () => {
  console.log("[NetworkRadar] 本次检测未能保存");
  $done(typeof $request !== "undefined" && $request ? details(readState(), "本次检测未完成") : undefined);
});
