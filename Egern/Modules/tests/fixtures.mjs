import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../NetworkRadar.js', import.meta.url), 'utf8');
export const radar = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
export function fixture(options = {}) {
  const calls = [], store = new Map();
  const state = {
    ip: '203.0.113.42', score: 18, residential: false, pureFails: false, allFail: false,
    now: Date.parse('2026-09-09T10:42:00+08:00'), replies: new Map(),
    ...options,
  };
  const ctx = {
    env: { RADAR_POLICY: 'Proxy', RADAR_LAYOUT: 'medium' },
    widgetFamily: 'systemMedium', script: { name: '网络诊断雷达' },
    device: { wifi: { ssid: 'Home Wi-Fi', bssid: '00:00:5e:00:53:01' }, ipv4: { address: '192.168.50.128', gateway: '192.168.50.1', interface: 'en0' } },
    storage: { get: key => store.get(key) ?? null, set: (key, value) => store.set(key, value) },
    http: { get: async (url, opts) => {
      calls.push({ url, ...opts });
      if (state.allFail) throw new Error('Mock offline; never expose raw request details');
      const custom = [...state.replies].find(([pattern]) => url.includes(pattern));
      if (custom && custom[1] instanceof Error) throw custom[1];
      let status = 200, body = '<!doctype html><html><body>Service page</body></html>', location = '';
      if (url.includes('ipip.net')) body = { data: { ip: '192.0.2.18', location: ['中国', '广东', '广州', '', '中国电信'] } };
      else if (url.includes('ippure.com')) {
        if (state.pureFails) throw new Error('Mock IPPure offline');
        body = { ip: state.ip, countryCode: 'JP', country: '日本', city: '东京', asn: 64496, asOrganization: 'Example Network', isResidential: state.residential, fraudScore: state.score };
      } else if (url.includes('ip-api.com')) body = { status: 'success', query: '198.51.100.88', countryCode: 'US', country: '美国', city: '洛杉矶', org: 'Fallback Network', as: 'AS64497 Fallback Network' };
      else if (url.includes('tiktok')) body = '<html>{"region":"JP"}</html>';
      else if (url.includes('cdn-cgi/trace')) body = 'fl=demo\nloc=JP\n';
      else if (url.includes('generate_204')) { status = 204; body = ''; }
      if (custom) ({ status = 200, body = '', location = '' } = custom[1]);
      return { status, headers: { get: name => name.toLowerCase() === 'location' ? location : null }, text: async () => typeof body === 'object' ? JSON.stringify(body) : body };
    } },
  };
  return { state, ctx, calls, store };
}
export function walk(node) { return [node, ...(node.children || []).flatMap(walk)]; }
export function texts(node) { return walk(node).filter(n => n.type === 'text').map(n => n.text); }
export function serviceCalls(calls) { return calls.filter(c => /netflix|disneyplus|tiktok|chatgpt|claude|gemini/.test(c.url)); }
