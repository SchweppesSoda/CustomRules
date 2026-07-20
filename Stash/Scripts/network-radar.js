function getGeo(proxy) {
  return new Promise((resolve) => {
    const started = Date.now();
    $httpClient.get({
      url: "https://api.ip.sb/geoip",
      headers: { "User-Agent": "ProxyConfig-Stash-NetworkRadar/1.0", "X-Stash-Selected-Proxy": encodeURIComponent(proxy) },
      timeout: 6,
    }, (error, _response, data) => {
      if (error) return resolve({ proxy, error: String(error) });
      try {
        const value = JSON.parse(data);
        resolve({ proxy, ip: value.ip, country: value.country || value.country_code || "-", isp: value.isp || value.organization || "-", ms: Date.now() - started });
      } catch (parseError) { resolve({ proxy, error: String(parseError) }); }
    });
  });
}

Promise.all([getGeo("DIRECT"), getGeo("Proxy")]).then(([direct, proxy]) => {
  const line = (label, value) => value.error ? `${label}: 失败` : `${label}: ${value.ip} · ${value.country} · ${value.ms}ms`;
  const ok = !direct.error && !proxy.error;
  $done({
    title: ok ? "Network Radar" : "Network Radar 异常",
    content: `${line("直连", direct)}\n${line("代理", proxy)}${proxy.isp ? `\n${proxy.isp}` : ""}`,
    icon: "radar",
    backgroundColor: ok ? "#2563eb" : "#b45309",
  });
});
