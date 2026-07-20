$httpClient.get({
  url: "https://api.ip.sb/geoip",
  headers: { "User-Agent": "ProxyConfig-Stash-IPPanel/1.0", "X-Stash-Selected-Proxy": encodeURIComponent("DIRECT") },
  timeout: 6,
}, (error, _response, data) => {
  if (error) return $done({ title: "IP 信息失败", content: String(error), icon: "exclamationmark.triangle.fill", backgroundColor: "#b45309" });
  try {
    const value = JSON.parse(data);
    $done({ title: value.ip || "IP 信息", content: `${value.country || value.country_code || "-"} · ${value.isp || value.organization || "-"}`, icon: "network", backgroundColor: "#2563eb" });
  } catch (parseError) {
    $done({ title: "IP 信息失败", content: String(parseError), icon: "exclamationmark.triangle.fill", backgroundColor: "#b45309" });
  }
});
