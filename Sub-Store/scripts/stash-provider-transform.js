/**
 * ProxyConfig residential naming and Stash chained-provider transformer.
 *
 * Attach this script to the three independent US sources and the existing
 * Residential/Landed collections used by Stash. Ordinary providers use
 * Sub-Store's native target=Stash conversion without this script.
 * Legacy Stash requests use mode=proxyconfig-stash-v1 with emoji front names.
 * Opt-in mode=proxyconfig-stash-text-v1 uses compact names and text-only fronts.
 * Independent US Egern/Loon/Mihomo requests use
 * mode=proxyconfig-residential-name-v1; Egern/Mihomo receive compact names,
 * while retired Loon and legacy Stash requests retain their original names.
 * Bind each independent source via fixed Script Operator link arguments:
 * #kind=subscription&source=<source>&profile=<profile>
 * A different requested profile passes through, so collection members do not
 * inject a chain or prefix before Residential_US_All's legacy transformer.
 */

const PROFILES = {
  residential_us: { prefix: "Res-US | ", dialer: "🔗 Dialer-Res-US" },
  residential_us_txpool: { prefix: "US-TXPOOL | ", dialer: "🔗 Dialer-Res-US", source: "TX_Carpool_Residential_US" },
  residential_us_frontier: { prefix: "US-Frontier | ", dialer: "🔗 Dialer-Res-US", source: "LAND_TX" },
  residential_us_charter: { prefix: "US-Charter | ", dialer: "🔗 Dialer-Res-US", source: "Charter_LA" },
  residential_global: { prefix: "Res-G | ", dialer: "🔗 Dialer-Res-Global" },
  landed_daily: { prefix: "Land-D | ", dialer: "🔗 Dialer-Landed-Daily" },
  landed_heavy: { prefix: "Land-H | ", dialer: "🔗 Dialer-Landed-Heavy" },
};

const CHAIN_KEYS = ["dialer-proxy", "underlying-proxy", "prev_hop", "chain", "detour"];

function compactName(rawName, profileName) {
  const prefix = PROFILES[profileName].prefix;
  const name = rawName.startsWith(prefix) ? rawName.slice(prefix.length) : rawName;
  if (profileName === "residential_us_txpool") {
    const match = name.match(/^🇺🇸 【1\.0x美国】(AT&T|Verizon)(家宽|商宽)落地 · 线路(\d+) \[(\d+)(?:st|nd|rd|th)\]$/);
    // The line and ordinal describe the same route in the reviewed source.
    // Keep unfamiliar rates, labels or mismatched ordinals intact.
    if (match && match[3] === match[4]) {
      const kind = match[1] === "Verizon" && match[2] === "家宽" ? "" : ` ${match[2]}`;
      return `🇺🇸 ${match[1]}${kind} ${match[3]}`;
    }
    if (/^🇺🇸 (?:AT&T (?:家宽|商宽)|Verizon(?: 商宽)?) \d+$/.test(name)) return name;
  }
  if (profileName === "residential_us_frontier" && ["US-FRONTIER-AAITR", "🇺🇸 Frontier"].includes(name)) {
    return "🇺🇸 Frontier";
  }
  if (profileName === "residential_us_charter" && ["[SS] 🇺🇸 Spectrum-CA", "🇺🇸 Spectrum CA"].includes(name)) {
    return "🇺🇸 Spectrum CA";
  }
  if (profileName === "landed_daily" || profileName === "landed_heavy") {
    // Both providers contain the same leaves but use different front hops.
    const suffix = profileName === "landed_daily" ? " · 日常" : " · 大流量";
    return name.endsWith(suffix) ? name : name + suffix;
  }
  // Unknown upstream names keep their source identity until reviewed.
  return rawName.startsWith(prefix) ? rawName : prefix + rawName;
}

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

function operator(proxies = [], targetPlatform, context) {
  const binding = parseOptions(typeof $arguments !== "undefined" ? $arguments : {});
  // Sub-Store passes child subscriptions a source map plus _collection. The
  // collection's own transformer owns its legacy naming and single front hop.
  if (binding.kind === "subscription" && context && context.source && context.source._collection) {
    return proxies;
  }
  const options = parseOptions(optionBag());
  // Appended adapters for NoUS/Landed must stay transparent to old consumers.
  if (binding.onlyMode && binding.onlyMode !== options.mode) return proxies;
  const textChained = options.mode === "proxyconfig-stash-text-v1";
  const chained = options.mode === "proxyconfig-stash-v1" || textChained;
  const namesOnly = options.mode === "proxyconfig-residential-name-v1";
  if (!chained && !namesOnly) return proxies;

  const target = String(targetPlatform || "").toLowerCase();
  if (chained && target && target !== "stash") throw new Error(`stash transform refuses target: ${targetPlatform}`);

  const profileName = String(options.profile || "");
  const profile = PROFILES[profileName];
  if (!profile) throw new Error(`unknown stash profile: ${profileName || "(empty)"}`);

  if (binding.profile && String(binding.profile) !== profileName) return proxies;
  if (textChained) {
    const source = profile.source || {
      residential_global: "TX_Carpool_Residential_NoUS",
      landed_daily: "Landed", landed_heavy: "Landed",
    }[profileName];
    if (!source || binding.kind !== "subscription" || binding.source !== source
        || binding.profile !== profileName) {
      throw new Error(`${profileName}: missing or invalid text source binding`);
    }
    if (context && context.source && (!context.source[source] || context.source[source].name !== source)) {
      throw new Error(`${profileName}: fixed source identity mismatch`);
    }
  }
  if (profile.source && (binding.profile !== profileName || binding.source !== profile.source
      || binding.kind !== "subscription")) {
    throw new Error(`${profileName}: missing or invalid fixed source binding`);
  }
  if (profile.source && context && context.source
      && (!context.source[profile.source] || context.source[profile.source].name !== profile.source)) {
    throw new Error(`${profileName}: fixed source identity mismatch`);
  }
  if (namesOnly && (!profile.source || !["egern", "loon", "clashmeta", "mihomo"].includes(target))) {
    throw new Error(`${profileName}: invalid residential naming target`);
  }

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
    // The published NoUS provider uses native names without a legacy prefix.
    // Its opt-in text variant adds only the front hop to those exact leaves.
    node.name = textChained && profileName === "residential_global" ? original.name
      : textChained || (namesOnly && target !== "loon") ? compactName(rawName, profileName)
      : rawName.startsWith(profile.prefix) ? rawName : `${profile.prefix}${rawName}`;
    if (chained) node["underlying-proxy"] = textChained ? profile.dialer.replace(/^🔗\s+/, "") : profile.dialer;

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
