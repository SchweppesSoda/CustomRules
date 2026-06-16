/**
 * 📌 桌面小组件: 🛡️ 网络诊断雷达 (全栈解锁 Pro 版 - 终极美化版)
 * 🎨 采用全新 System UI 规范色系 | 纯色背景解决暗黑圆角
 */
export default async function(ctx) {
  // 1. 统一 UI 规范颜色 (全局 C 对象)
  const C = {
    bg: { light: '#FFFFFF', dark: '#121212' },       
    barBg: { light: '#0000001A', dark: '#FFFFFF22' },
    text: { light: '#1C1C1E', dark: '#FFFFFF' },     
    dim: { light: '#8E8E93', dark: '#8E8E93' },      
    
    cpu: { light: '#007AFF', dark: '#0A84FF' },      // 用于左侧本地列
    mem: { light: '#AF52DE', dark: '#BF5AF2' },      // 用于右侧代理列
    disk: { light: '#FF9500', dark: '#FF9F0A' },     // 用于中危/机房
    netRx: { light: '#34C759', dark: '#30D158' },    // 用于纯净/原生住宅
    netTx: { light: '#5856D6', dark: '#5E5CE6' },    
    
    // 补充：用于网络雷达极危状态的衍生色
    yellow: { light: '#FFCC00', dark: '#FFD60A' },
    red: { light: '#FF3B30', dark: '#FF453A' }
  };

  // --- 辅助与解析函数 ---
  const fmtCarrier = (isp) => {
    if (!isp) return "未知运营商";
    const raw = String(isp).replace(/\s*\(中国\)\s*/g, "").replace(/\s+/g, " ").trim();
    const s = raw.toLowerCase();
    if (/(^|[\s-])(cmcc|cmnet|cmi|mobile)\b|移动/.test(s)) return "中国移动";
    if (/(^|[\s-])(chinanet|telecom|ctcc|ct)\b|电信/.test(s)) return "中国电信";
    if (/(^|[\s-])(unicom|cncgroup|netcom|link)\b|联通/.test(s)) return "中国联通";
    if (/(^|[\s-])(cbn|broadcast)\b|广电/.test(s)) return "中国广电";
    return raw || "未知运营商";
  };

  const fmtProxyISP = (isp) => {
    if (!isp) return "未知";
    let s = String(isp);
    const knownCarriers = new Set(["中国移动", "中国电信", "中国联通", "中国广电"]);
    const carrier = fmtCarrier(s);
    if (knownCarriers.has(carrier)) return carrier;
    if (/it7/i.test(s)) return "IT7 Network";
    if (/dmit/i.test(s)) return "DMIT Network";
    if (/cloudflare/i.test(s)) return "Cloudflare";
    if (/akamai/i.test(s)) return "Akamai";
    if (/amazon|aws/i.test(s)) return "AWS";
    if (/google/i.test(s)) return "Google Cloud";
    if (/microsoft|azure/i.test(s)) return "Azure";
    if (/alibaba|aliyun/i.test(s)) return "阿里云";
    if (/tencent/i.test(s)) return "腾讯云";
    if (/oracle/i.test(s)) return "Oracle Cloud";
    return s.length > 11 ? s.substring(0, 11) + "..." : s; 
  };

  const getFlag = (code) => {
    if (!code || code.toUpperCase() === 'TW') return '🇨🇳'; 
    if (code.toUpperCase() === 'XX' || code === 'OK') return '✅';
    return String.fromCodePoint(...code.toUpperCase().split('').map(c => 127397 + c.charCodeAt()));
  };

  const BASE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36";
  const commonHeaders = { "User-Agent": BASE_UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8" };
  const readBody = async (r) => {
    if (!r) return "";
    if (typeof r.body === "string" && r.body.length) return r.body;
    if (typeof r.text === "function") {
      try { const t = await r.text(); return typeof t === "string" ? t : ""; } catch { return ""; }
    }
    return "";
  };

  // 2. 获取本地网络数据
  const d = ctx.device || {};
  const isWifi = !!d.wifi?.ssid;
  let netName = "未连接", netIcon = "antenna.radiowaves.left.and.right";
  
  const netInfo = (typeof $network !== 'undefined') ? $network : (ctx.network || {});
  let localIp = netInfo.v4?.primaryAddress || d.ipv4?.address || "获取失败";
  let gateway = netInfo.v4?.primaryRouter || d.ipv4?.gateway || "无网关";

  if (isWifi) { netName = d.wifi.ssid; netIcon = "wifi"; }
  else if (d.cellular?.radio) {
    const radioMap = { "GPRS": "2.5G", "EDGE": "2.75G", "WCDMA": "3G", "LTE": "4G", "NR": "5G", "NRNSA": "5G" };
    netName = `${radioMap[d.cellular.radio.toUpperCase().replace(/\s+/g, "")] || d.cellular.radio}`;
    gateway = "蜂窝内网";
  }

  // 3. 基础网络请求
  const fetchLocal = async () => {
    try {
      const res = await ctx.http.get('https://myip.ipip.net/json', { headers: commonHeaders, timeout: 4000 });
      const body = JSON.parse(await res.text());
      const location = Array.isArray(body?.data?.location) ? body.data.location : [];
      if (body?.data?.ip) return {
        ip: body.data.ip,
        loc: `${location[1] || ""} ${location[2] || ""}`.trim() || "未知",
        isp: fmtCarrier(location[location.length - 1])
      };
    } catch (e) {}
    return { ip: "获取失败", loc: "未知", isp: "未知运营商" };
  };

  const fetchProxy = async () => {
    try {
      const res = await ctx.http.get('http://ip-api.com/json/?lang=zh-CN', { timeout: 4000 });
      const data = JSON.parse(await res.text());
      const flag = getFlag(data.countryCode);
      return { ip: data.query || "获取失败", loc: `${flag} ${data.city || data.country || ""}`.trim(), isp: fmtProxyISP(data.isp || data.org), cc: data.countryCode || "XX" };
    } catch (e) { return { ip: "获取失败", loc: "未知", isp: "未知", cc: "XX" }; }
  };

  const fetchPurity = async () => {
    try {
      const res = await ctx.http.get('https://my.ippure.com/v1/info', { timeout: 4000 });
      return JSON.parse(await res.text());
    } catch (e) { return {}; }
  };

  const fetchLocalDelay = async () => {
    const start = Date.now();
    try { await ctx.http.get('http://www.baidu.com', { timeout: 2000 }); return `${Date.now() - start} ms`; } catch (e) { return "超时"; }
  };

  const fetchProxyDelay = async () => {
    const start = Date.now();
    try { await ctx.http.get('http://cp.cloudflare.com/generate_204', { timeout: 2000 }); return `${Date.now() - start} ms`; } catch (e) { return "超时"; }
  };

  // 🎬 流媒体解锁测试 
  async function checkNetflix() {
    try {
      const checkStatus = async (id) => {
        const r = await ctx.http.get(`https://www.netflix.com/title/${id}`, { timeout: 4000, headers: commonHeaders, followRedirect: false }).catch(() => null);
        return r ? r.status : 0;
      };
      const sFull = await checkStatus(70143836); 
      const sOrig = await checkStatus(81280792); 
      if (sFull === 200) return "OK"; 
      if (sOrig === 200) return "🍿"; 
      return "❌"; 
    } catch { return "❌"; }
  }

  async function checkDisney() {
    try {
      const res = await ctx.http.get("https://www.disneyplus.com", { timeout: 4000, headers: commonHeaders, followRedirect: false }).catch(() => null);
      if (!res || res.status === 403) return "❌";
      const loc = res.headers?.location || res.headers?.Location || "";
      if (loc.includes("unavailable")) return "❌";
      return "OK"; 
    } catch { return "❌"; }
  }

  async function checkTikTok() {
    try {
      const r = await ctx.http.get("https://www.tiktok.com/explore", { timeout: 4000, headers: commonHeaders, followRedirect: false }).catch(() => null);
      if (!r || r.status === 403 || r.status === 401) return "❌";
      const body = await readBody(r);
      if (body.includes("Access Denied") || body.includes("Please wait...")) return "❌";
      const m = body.match(/"region":"([A-Z]{2})"/i);
      return m?.[1] ? m[1].toUpperCase() : "OK";
    } catch { return "❌"; }
  }

  // 🤖 AI 解锁测试
  async function checkChatGPT() {
    try {
      const traceRes = await ctx.http.get("https://chatgpt.com/cdn-cgi/trace", { timeout: 3000 }).catch(() => null);
      const tb = await readBody(traceRes);
      const m = tb?.match(/loc=([A-Z]{2})/);
      return m?.[1] ? m[1].toUpperCase() : "OK";
    } catch { return "❌"; }
  }

  async function checkClaude() {
    try {
      const res = await ctx.http.get("https://claude.ai/login", { 
        timeout: 5000, 
        headers: {
          "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
      }).catch(() => null);
      if (!res) return "❌";
      const status = res.status;
      const body = await readBody(res);
      if (body.includes("App unavailable") || body.includes("certain regions")) return "❌";
      if (status === 403 && body.includes("1020")) return "❌";
      if (status === 403 && (body.includes("cf-turnstile") || body.includes("Just a moment") || body.includes("Challenge"))) return "OK";
      if (status === 200 || status === 301 || status === 302) return "OK";
      return "❌";
    } catch { return "❌"; }
  }

  async function checkGemini() {
    try {
      const res = await ctx.http.get("https://gemini.google.com/app", { timeout: 4000, headers: commonHeaders, followRedirect: false }).catch(() => null);
      if (!res) return "❌";
      const loc = res.headers?.location || res.headers?.Location || "";
      if (loc.includes("faq")) return "❌";
      return "OK";
    } catch { return "❌"; }
  }

  // 🚦 并发执行所有核心网络请求
  const [localData, proxyData, purityData, localDelay, proxyDelay, rNF, rDP, rTK, rGPT, rCL, rGM] = await Promise.all([
    fetchLocal(), fetchProxy(), fetchPurity(), fetchLocalDelay(), fetchProxyDelay(),
    checkNetflix(), checkDisney(), checkTikTok(), 
    checkChatGPT(), checkClaude(), checkGemini()
  ]);

  // 4. 数据清洗与渲染逻辑
  const isRes = purityData.isResidential;
  let nativeText = "未知属性", nativeIc = "questionmark.building.fill", nativeCol = C.dim;
  if (isRes === true) { nativeText = "原生住宅"; nativeIc = "house.fill"; nativeCol = C.netRx; } 
  else if (isRes === false) { nativeText = "商业机房"; nativeIc = "building.2.fill"; nativeCol = C.disk; }

  const risk = purityData.fraudScore;
  let riskTxt = "无数据", riskCol = C.dim, riskIc = "questionmark.circle.fill";
  if (risk !== undefined) {
    if (risk >= 70) { riskTxt = `高危 (${risk})`; riskCol = C.red; riskIc = "xmark.shield.fill"; } 
    else if (risk >= 30) { riskTxt = `中危 (${risk})`; riskCol = C.disk; riskIc = "exclamationmark.triangle.fill"; } 
    else { riskTxt = `纯净 (${risk})`; riskCol = C.netRx; riskIc = "checkmark.shield.fill"; }
  }

  const fmtUnlock = (name, res, cc) => {
    let flag = "🚫";
    if (res === "🍿" || res === "APP") flag = res;
    else if (res !== "❌") flag = getFlag(res === "OK" || res === "XX" ? cc : res);
    return `${name} ${flag}`; 
  };
  
  const textVideo = `${fmtUnlock('NF', rNF, proxyData.cc)}   ${fmtUnlock('DP', rDP, proxyData.cc)}   ${fmtUnlock('TK', rTK, proxyData.cc)}`;
  const textAI = `${fmtUnlock('GPT', rGPT, proxyData.cc)}   ${fmtUnlock('CL', rCL, proxyData.cc)}   ${fmtUnlock('GM', rGM, proxyData.cc)}`;

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const TIME_COL = { light: 'rgba(0,0,0,0.3)', dark: 'rgba(255,255,255,0.3)' };
  const layoutHint = String(ctx.env?.RADAR_LAYOUT || ctx.env?.WIDGET_SIZE || "").toLowerCase();
  const familyValue = [
    ctx.widgetFamily,
    ctx.family,
    ctx.widget?.family,
    ctx.widget?.widgetFamily,
    ctx.widgetSize,
    ctx.size,
    ctx.env?.widgetFamily,
    ctx.env?.WIDGET_FAMILY
  ].find((v) => v !== undefined && v !== null && String(v).trim());
  const family = String(familyValue || "systemMedium").toLowerCase();
  const isLarge = /large|extra|大/.test(layoutHint) || (!/medium|中/.test(layoutHint) && /large|extra|大/.test(family));
  const S = isLarge
    ? { padding: [12, 13, 10, 13], title: 15, icon: 17, rowFont: 10.5, labelFont: 10, rowIcon: 12, rowGap: 4, headerSpacer: 8, panelPadding: [8, 9] }
    : { padding: 14, title: 14, icon: 16, rowFont: 10, labelFont: 10, rowIcon: 11, rowGap: 4.5, headerSpacer: 12, panelPadding: [8, 10] };

  // 5. 网格行组件 (采用 C.dim 和 C.text)
  const Row = (ic, icCol, label, val, valCol) => ({
    type: 'stack', direction: 'row', alignItems: 'center', gap: 5,
    children: [
      { type: 'image', src: `sf-symbol:${ic}`, color: icCol, width: S.rowIcon, height: S.rowIcon },
      { type: 'text', text: label, font: { size: S.labelFont, weight: 'regular' }, textColor: C.dim, maxLines: 1 }, 
      { type: 'spacer' },
      { type: 'text', text: val, font: { size: S.rowFont, weight: 'medium' }, textColor: valCol, maxLines: 1, minScale: 0.4 }
    ]
  });

  const FullRow = (ic, icCol, label, val, valCol = C.text) => ({
    type: 'stack',
    direction: 'column',
    gap: 3,
    children: [
      { type: 'stack', direction: 'row', alignItems: 'center', gap: 5, children: [
        { type: 'image', src: `sf-symbol:${ic}`, color: icCol, width: S.rowIcon, height: S.rowIcon },
        { type: 'text', text: label, font: { size: S.labelFont, weight: 'regular' }, textColor: C.dim, maxLines: 1 },
        { type: 'spacer' }
      ]},
      { type: 'text', text: val, font: { size: S.rowFont, weight: 'medium' }, textColor: valCol, maxLines: 1, minScale: 0.35 }
    ]
  });

  const LargeCard = (ic, icCol, title, rows) => ({
    type: 'stack',
    direction: 'column',
    gap: 4,
    flex: 1,
    padding: [8, 9],
    backgroundColor: C.barBg,
    borderRadius: 10,
    children: [
      { type: 'stack', direction: 'row', alignItems: 'center', gap: 6, children: [
        { type: 'image', src: `sf-symbol:${ic}`, color: icCol, width: 13, height: 13 },
        { type: 'text', text: title, font: { size: 11, weight: 'semibold' }, textColor: C.text, maxLines: 1 },
        { type: 'spacer' }
      ]},
      ...rows
    ]
  });

  const Metric = (ic, icCol, label, val, valCol = C.text) => ({
    type: 'stack',
    direction: 'column',
    gap: 4,
    flex: 1,
    padding: [7, 8],
    backgroundColor: C.barBg,
    borderRadius: 10,
    children: [
      { type: 'stack', direction: 'row', alignItems: 'center', gap: 5, children: [
        { type: 'image', src: `sf-symbol:${ic}`, color: icCol, width: 12, height: 12 },
        { type: 'text', text: label, font: { size: 10, weight: 'regular' }, textColor: C.dim, maxLines: 1 },
        { type: 'spacer' }
      ]},
      { type: 'text', text: val, font: { size: 12, weight: 'semibold' }, textColor: valCol, maxLines: 1, minScale: 0.35 }
    ]
  });

  const unlockMark = (res, cc) => {
    if (res === "🍿" || res === "APP") return res;
    if (res === "❌") return "🚫";
    return getFlag(res === "OK" || res === "XX" ? cc : res);
  };

  const UnlockBadge = (name, res, cc, ic, icCol) => ({
    type: 'stack',
    direction: 'row',
    alignItems: 'center',
    gap: 5,
    flex: 1,
    children: [
      { type: 'image', src: `sf-symbol:${ic}`, color: icCol, width: 11, height: 11 },
      { type: 'text', text: name, font: { size: 10, weight: 'regular' }, textColor: C.dim, maxLines: 1 },
      { type: 'spacer' },
      { type: 'text', text: unlockMark(res, cc), font: { size: 12, weight: 'semibold' }, textColor: C.text, maxLines: 1, minScale: 0.5 }
    ]
  });

  const UnlockPanel = {
    type: 'stack',
    direction: 'column',
    gap: 6,
    padding: [8, 9],
    backgroundColor: C.barBg,
    borderRadius: 10,
    children: [
      { type: 'stack', direction: 'row', alignItems: 'center', gap: 8, children: [
        { type: 'image', src: 'sf-symbol:play.tv.fill', color: C.cpu, width: 12, height: 12 },
        { type: 'text', text: '影视', font: { size: 11, weight: 'semibold' }, textColor: C.text, maxLines: 1 },
        UnlockBadge('NF', rNF, proxyData.cc, 'n.circle.fill', C.cpu),
        UnlockBadge('DP', rDP, proxyData.cc, 'd.circle.fill', C.cpu),
        UnlockBadge('TK', rTK, proxyData.cc, 't.circle.fill', C.cpu)
      ]},
      { type: 'stack', direction: 'row', alignItems: 'center', gap: 8, children: [
        { type: 'image', src: 'sf-symbol:cpu', color: C.mem, width: 12, height: 12 },
        { type: 'text', text: 'AI', font: { size: 11, weight: 'semibold' }, textColor: C.text, maxLines: 1 },
        UnlockBadge('GPT', rGPT, proxyData.cc, 'g.circle.fill', C.mem),
        UnlockBadge('CL', rCL, proxyData.cc, 'c.circle.fill', C.mem),
        UnlockBadge('GM', rGM, proxyData.cc, 'sparkles', C.mem)
      ]}
    ]
  };

  const Header = {
    type: 'stack', direction: 'row', alignItems: 'center', gap: 6, children: [
      { type: 'image', src: 'sf-symbol:waveform.path.ecg', color: C.text, width: S.icon, height: S.icon },
      { type: 'text', text: '网络诊断雷达', font: { size: S.title, weight: 'bold' }, textColor: C.text },
      { type: 'spacer' },
      { type: 'text', text: timeStr, font: { size: 10, weight: 'medium' }, textColor: TIME_COL }
    ]
  };

  if (isLarge) {
    return {
      type: 'widget',
      padding: S.padding,
      backgroundColor: C.bg,
      gap: 6,
      children: [
        Header,
        { type: 'stack', direction: 'row', alignItems: 'stretch', gap: 8, children: [
          LargeCard(netIcon, C.cpu, "本地网络", [
            Row(netIcon, C.cpu, "环境", netName, C.text),
            Row("iphone", C.cpu, "内网", localIp, C.text),
            Row("globe.asia.australia.fill", C.cpu, "公网", localData.ip, C.text),
            FullRow("map.fill", C.cpu, "位置", localData.loc, C.text),
            Row("antenna.radiowaves.left.and.right", C.cpu, "运营", localData.isp, C.text),
            Row("wifi.router.fill", C.cpu, "网关", gateway, C.text),
            Row("timer", C.cpu, "延迟", localDelay, C.text)
          ]),
          LargeCard("paperplane.fill", C.mem, "代理出口", [
            Row("paperplane.fill", C.mem, "出口", proxyData.ip, C.text),
            Row("mappin.and.ellipse", C.mem, "落地", proxyData.loc, C.text),
            FullRow("server.rack", C.mem, "厂商", proxyData.isp, C.text),
            Row(nativeIc, nativeCol, "属性", nativeText, C.text),
            Row(riskIc, riskCol, "纯净", riskTxt, riskCol),
            Row("timer", C.mem, "延迟", proxyDelay, C.text),
            Row("cpu", C.mem, "AI", textAI, C.text)
          ])
        ]},
        { type: 'stack', direction: 'row', alignItems: 'stretch', gap: 8, children: [
          Metric("antenna.radiowaves.left.and.right", C.cpu, "本地运营", localData.isp),
          Metric(nativeIc, nativeCol, "出口属性", nativeText),
          Metric(riskIc, riskCol, "风险评分", riskTxt, riskCol)
        ]},
        UnlockPanel
      ]
    };
  }

  // 6. 最终渲染
  return {
    type: 'widget', 
    padding: S.padding,
    backgroundColor: C.bg, // 完美融合暗黑圆角
    children: [
      // 顶部 Header
      Header,
      { type: 'spacer', length: S.headerSpacer }, 
      
      // 双列网格
      { type: 'stack', direction: 'row', gap: 10, children: [
          
          // 【左列】：本地与影视 (使用 C.cpu 科技蓝)
          { type: 'stack', direction: 'column', gap: S.rowGap, flex: 1, children: [
              Row(netIcon, C.cpu, "环境", netName, C.text),
              Row("iphone", C.cpu, "内网", localIp, C.text),
              Row("globe.asia.australia.fill", C.cpu, "公网", localData.ip, C.text),
              Row("map.fill", C.cpu, "位置", localData.loc, C.text),
              Row("antenna.radiowaves.left.and.right", C.cpu, "运营", localData.isp, C.text),
              Row("timer", C.cpu, "延迟", localDelay, C.text), 
              Row("play.tv.fill", C.cpu, "影视", textVideo, C.text) 
          ]},

          // ✂️ 【中轴线】：使用 C.barBg 分割
          { type: 'stack', width: 0.5, backgroundColor: C.barBg },
          
          // 【右列】：代理与 AI (使用 C.mem 高贵紫)
          { type: 'stack', direction: 'column', gap: S.rowGap, flex: 1, children: [
              Row("paperplane.fill", C.mem, "出口", proxyData.ip, C.text),
              Row("mappin.and.ellipse", C.mem, "落地", proxyData.loc, C.text),
              Row("server.rack", C.mem, "厂商", proxyData.isp, C.text),
              Row(nativeIc, nativeCol, "属性", nativeText, C.text), 
              Row(riskIc, riskCol, "纯净", riskTxt, riskCol),
              Row("timer", C.mem, "延迟", proxyDelay, C.text), 
              Row("cpu", C.mem, "AI", textAI, C.text) 
          ]}
      ]},
      { type: 'spacer' }
    ]
  };
}
