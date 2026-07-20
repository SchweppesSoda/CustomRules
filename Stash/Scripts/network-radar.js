const STORE_KEY = "proxyconfig.network-radar.v1";

let finished = false;
let watchdog = null;

function doneOnce(value) {
  if (finished) return;
  finished = true;
  if (watchdog) clearTimeout(watchdog);
  $done(value);
}

function parseArgument() {
  try { return JSON.parse($argument || "{}"); }
  catch (_) { return {}; }
}

function readState() {
  try { return JSON.parse($persistentStore.read(STORE_KEY) || "null") || {}; }
  catch (_) { return {}; }
}

function writeState(state) {
  return $persistentStore.write(JSON.stringify(state), STORE_KEY);
}

function line(label, value) {
  return !value || value.error
    ? `${label}: 失败`
    : `${label}: ${value.ip} · ${value.country} · ${value.ms}ms`;
}

function tile(state) {
  if (!state.checked_at) {
    return {
      title: "Network Radar",
      content: "等待首次后台检测",
      icon: "radar",
      backgroundColor: "#6b7280",
    };
  }
  const ok = state.direct && !state.direct.error && state.proxy && !state.proxy.error;
  const age = Math.max(0, Math.floor((Date.now() - Number(state.checked_at)) / 60000));
  return {
    title: ok ? "Network Radar" : "Network Radar 异常",
    content: `${line("直连", state.direct)}\n${line("代理", state.proxy)}${state.proxy && state.proxy.isp ? `\n${state.proxy.isp}` : ""}\n${age} 分钟前`,
    icon: "radar",
    backgroundColor: ok ? "#2563eb" : "#b45309",
  };
}

function getGeo(proxy) {
  return new Promise((resolve) => {
    const started = Date.now();
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    try {
      $httpClient.get({
        url: "https://api.ip.sb/geoip",
        headers: {
          "User-Agent": "ProxyConfig-Stash-NetworkRadar/1.0",
          "X-Stash-Selected-Proxy": encodeURIComponent(proxy),
        },
        timeout: 6,
      }, (error, _response, data) => {
        if (error) return finish({ proxy, error: String(error) });
        try {
          const value = JSON.parse(data);
          finish({
            proxy,
            ip: value.ip,
            country: value.country || value.country_code || "-",
            isp: value.isp || value.organization || "-",
            ms: Date.now() - started,
          });
        } catch (parseError) {
          finish({ proxy, error: String(parseError) });
        }
      });
    } catch (error) {
      finish({ proxy, error: String(error) });
    }
  });
}

async function refresh() {
  const [direct, proxy] = await Promise.all([getGeo("DIRECT"), getGeo("Proxy")]);
  writeState({ checked_at: Date.now(), direct, proxy });
  doneOnce();
}

function run() {
  const args = parseArgument();
  const type = typeof $script === "object" && $script ? $script.type : "";
  const mode = type === "tile" ? "status" : String(args.mode || "refresh");
  if (mode === "status") return doneOnce(tile(readState()));

  watchdog = setTimeout(() => doneOnce(), 13000);
  return refresh().catch((error) => {
    console.log(`[NetworkRadar] ${String(error && error.message || error)}`);
    doneOnce();
  });
}

try {
  run();
} catch (error) {
  console.log(`[NetworkRadar] ${String(error && error.message || error)}`);
  doneOnce();
}
