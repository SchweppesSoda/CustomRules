/**
 * ProxyConfig -> Stash provider transformer for Sub-Store.
 *
 * Attach this script to each source/collection used by Stash/AutoStash.yaml.
 * The provider URL passes: mode=proxyconfig-stash-v1&profile=<profile>&strict=1
 */

const PROFILES = {
  bitznet: { prefix: "BZ | " },
  sntp: { prefix: "SN | " },
  linkcube: { prefix: "LC | " },
  flower: { prefix: "FL | " },
  mesl: { prefix: "MS | " },
  ctc02: { prefix: "C2 | " },
  liangxin: { prefix: "LX | " },
  dmit_pro: { prefix: "" },
  dmit_eb: { prefix: "" },
  custom_jp: { prefix: "" },
  po0_jp: { prefix: "" },
  po0_hk: { prefix: "" },
  po0_tw: { prefix: "" },
  po0_us: { prefix: "" },
  residential_us: { prefix: "Res-US | ", dialer: "🔗 Dialer-Res-US" },
  residential_global: { prefix: "Res-G | ", dialer: "🔗 Dialer-Res-Global" },
  landed_daily: { prefix: "Land-D | ", dialer: "🔗 Dialer-Landed-Daily" },
  landed_heavy: { prefix: "Land-H | ", dialer: "🔗 Dialer-Landed-Heavy" },
};

const JUNK = /(剩余|到期|官网|用户|问题|临时|续费|回国|过期|游戏|流量|Gamer|Play|Traffic|Expire)/i;
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

function stableObject(value) {
  if (Array.isArray(value)) return value.map(stableObject);
  if (!value || typeof value !== "object") return value;
  const out = {};
  Object.keys(value).sort().forEach((key) => {
    if (key !== "name") out[key] = stableObject(value[key]);
  });
  return out;
}

function shortHash(value) {
  const text = JSON.stringify(stableObject(value));
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36).slice(0, 6).padStart(6, "0");
}

function operator(proxies = [], targetPlatform) {
  const options = parseOptions(optionBag());
  const strict = String(options.strict || "1") !== "0";
  const target = String(targetPlatform || "").toLowerCase();
  if (options.mode !== "proxyconfig-stash-v1") return proxies;
  if (target && target !== "stash") throw new Error(`stash transform refuses target: ${targetPlatform}`);

  const profile = PROFILES[String(options.profile || "")];
  if (!profile) throw new Error(`unknown stash profile: ${options.profile || "(empty)"}`);

  const cleaned = [];
  const fingerprints = new Set();
  for (const original of proxies) {
    if (!original || typeof original !== "object") continue;
    const rawName = String(original.name || "").trim();
    if (!rawName || JUNK.test(rawName)) continue;
    const existingChain = CHAIN_KEYS.find((key) => original[key] != null && original[key] !== "");
    if (existingChain && strict) throw new Error(`${rawName}: existing chain field ${existingChain}`);

    const node = {
      ...original,
      udp: true,
      "benchmark-url": "http://www.gstatic.com/generate_204",
      "benchmark-timeout": 5,
    };
    CHAIN_KEYS.forEach((key) => { delete node[key]; });
    node.name = profile.prefix && !rawName.startsWith(profile.prefix)
      ? `${profile.prefix}${rawName}`
      : rawName;
    if (profile.dialer) node["underlying-proxy"] = profile.dialer;

    const fingerprint = shortHash(node);
    if (fingerprints.has(fingerprint)) continue;
    fingerprints.add(fingerprint);
    cleaned.push({ node, fingerprint });
  }

  const byName = new Map();
  cleaned.forEach((entry) => {
    const list = byName.get(entry.node.name) || [];
    list.push(entry);
    byName.set(entry.node.name, list);
  });
  for (const [name, entries] of byName.entries()) {
    if (entries.length < 2) continue;
    if (!profile.prefix && strict) {
      throw new Error(`${options.profile}: duplicate unprefixed node name: ${name}`);
    }
    entries.forEach((entry) => { entry.node.name = `${name} #${entry.fingerprint}`; });
  }

  const result = cleaned.map((entry) => entry.node);
  if (!result.length) throw new Error(`${options.profile}: empty Stash provider output`);
  console.log(`[stash-provider-transform] ${options.profile}: ${proxies.length} -> ${result.length}`);
  return result;
}

if (typeof module !== "undefined") module.exports = { operator, PROFILES, shortHash };
