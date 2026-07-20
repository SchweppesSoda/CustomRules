/**
 * ProxyConfig -> Stash chained-provider transformer for Sub-Store.
 *
 * Attach this script only to the Residential/Landed sources used by
 * Stash/AutoStash.yaml. Ordinary airport and self-hosted providers use
 * Sub-Store's native target=Stash conversion without this script.
 * The provider URL passes: mode=proxyconfig-stash-v1&profile=<profile>&strict=1
 */

const PROFILES = {
  residential_us: { prefix: "Res-US | ", dialer: "🔗 Dialer-Res-US" },
  residential_global: { prefix: "Res-G | ", dialer: "🔗 Dialer-Res-Global" },
  landed_daily: { prefix: "Land-D | ", dialer: "🔗 Dialer-Landed-Daily" },
  landed_heavy: { prefix: "Land-H | ", dialer: "🔗 Dialer-Landed-Heavy" },
};

const CHAIN_KEYS = ["dialer-proxy", "underlying-proxy", "prev_hop", "chain", "detour"];

function optionBag() {
  if (typeof $options !== "undefined" && $options) return $options;
  if (typeof $arguments !== "undefined" && $arguments) return $arguments;
  return {};
}

function parseOptions(value) {
  if (typeof value === "object") return value;
  const out = {};
  String(value || "").split("&").forEach((part) => {
    const pos = part.indexOf("=");
    const key = decodeURIComponent(pos < 0 ? part : part.slice(0, pos));
    const val = decodeURIComponent(pos < 0 ? "" : part.slice(pos + 1));
    if (key) out[key] = val;
  });
  return out;
}

function operator(proxies = [], targetPlatform) {
  const options = parseOptions(optionBag());
  if (options.mode !== "proxyconfig-stash-v1") return proxies;

  const target = String(targetPlatform || "").toLowerCase();
  if (target && target !== "stash") throw new Error(`stash transform refuses target: ${targetPlatform}`);

  const profileName = String(options.profile || "");
  const profile = PROFILES[profileName];
  if (!profile) throw new Error(`unknown stash profile: ${profileName || "(empty)"}`);

  const strict = String(options.strict || "1") !== "0";
  const names = new Set();
  const result = [];

  for (const original of proxies) {
    if (!original || typeof original !== "object") continue;
    const rawName = String(original.name || "").trim();
    if (!rawName) continue;

    const existingChain = CHAIN_KEYS.find((key) => original[key] != null && original[key] !== "");
    if (existingChain && strict) throw new Error(`${rawName}: existing chain field ${existingChain}`);

    const node = { ...original };
    CHAIN_KEYS.forEach((key) => { delete node[key]; });
    node.name = rawName.startsWith(profile.prefix) ? rawName : `${profile.prefix}${rawName}`;
    node["underlying-proxy"] = profile.dialer;

    if (names.has(node.name) && strict) {
      throw new Error(`${profileName}: duplicate node name: ${node.name}`);
    }
    names.add(node.name);
    result.push(node);
  }

  if (!result.length) throw new Error(`${profileName}: empty Stash provider output`);
  console.log(`[stash-provider-transform] ${profileName}: ${proxies.length} -> ${result.length}`);
  return result;
}

if (typeof module !== "undefined") module.exports = { operator, PROFILES };
