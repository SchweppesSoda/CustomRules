import test from 'node:test';
import assert from 'node:assert/strict';
import { radar, fixture, texts, walk, serviceCalls } from './fixtures.mjs';

function setup(t, opts) {
  const f = fixture(opts);
  t.mock.method(Date, 'now', () => f.state.now);
  return f;
}
test('one IPPure response supplies all exit fields; direct and selected policies stay separate', async t => {
  const f = setup(t), result = await radar.collectRadar(f.ctx);
  assert.equal(result.proxy.ip, f.state.ip);
  assert.equal(result.proxy.asn, 'AS64496');
  assert.equal(result.proxy.score, 18);
  assert.equal(result.proxy.organization, 'Example Network');
  assert.equal(f.calls.some(c => c.url.includes('ip-api.com')), false);
  assert.equal(f.calls.length, 11);
  for (const call of f.calls) {
    assert.equal(call.policy, /ipip.net|baidu.com/.test(call.url) ? 'DIRECT' : 'Proxy');
    assert.equal(call.redirect, 'manual');
    assert.equal(call.credentials, 'omit');
    assert.equal('followRedirect' in call, false);
  }
  assert.equal(result.checks.GPT.cc, 'JP');
  assert.equal(result.checks.DP.cc, ''); // Never substitute proxy country for service evidence.
});
test('GPT timeout is unknown even when exit lookup succeeds', async t => {
  const f = setup(t); f.state.replies.set('chatgpt', new Error('timeout'));
  const result = await radar.collectRadar(f.ctx);
  assert.equal(result.checks.GPT.state, 'unknown');
  const tree = radar.renderRadar(result, f.ctx);
  assert.equal(texts(tree.children[3].children[1].children[2]).at(-1), '?');
});
test('all requests failing returns valid widget without any successful check', async t => {
  const f = setup(t, { allFail: true });
  const tree = await radar.default(f.ctx);
  assert.equal(tree.type, 'widget');
  assert.equal(texts(tree).some(s => s.includes('✓')), false);
  assert.equal(serviceCalls(f.calls).length, 0);
  assert.equal(texts(tree).includes('IPPure 无数据'), true);
});
test('challenge pages, empty success, redirects and 500 errors cannot become reachable', async t => {
  const f = setup(t);
  f.state.replies.set('claude', { status: 403, body: '<html>Just a moment cf-turnstile</html>' });
  f.state.replies.set('disney', { status: 200, body: '' });
  f.state.replies.set('gemini', { status: 302, location: '/login' });
  f.state.replies.set('chatgpt', { status: 500, body: 'loc=JP\nApp unavailable' });
  const r = await radar.collectRadar(f.ctx);
  for (const id of ['CL', 'DP', 'GM', 'GPT']) assert.equal(r.checks[id].state, 'unknown', id);
});
test('explicit restriction and partial Netflix reachability are distinct', async t => {
  const f = setup(t);
  f.state.replies.set('70143836', { status: 403, body: 'not available in your country' });
  f.state.replies.set('disney', { status: 302, location: 'https://www.disneyplus.com/unavailable' });
  f.state.replies.set('gemini', { status: 302, location: 'https://gemini.google.com/faq/' });
  const r = await radar.collectRadar(f.ctx);
  assert.equal(r.checks.NF.state, 'limited');
  assert.equal(r.checks.DP.state, 'restricted');
  assert.equal(r.checks.GM.state, 'restricted');
});
test('fallback has its own exit IP and never inherits the previous IPPure score', async t => {
  const f = setup(t);
  await radar.collectRadar(f.ctx);
  f.state.pureFails = true; f.calls.length = 0;
  const r = await radar.collectRadar(f.ctx);
  assert.equal(r.proxy.ip, '198.51.100.88');
  assert.equal(r.proxy.asn, 'AS64497');
  assert.equal(r.proxy.score, null);
  assert.equal(r.proxy.residential, null);
  assert.equal(r.cached, false);
  assert.equal(serviceCalls(f.calls).length, 7);
});
test('invalid score types and bounds display no data; zero remains a score', async t => {
  const f = setup(t);
  for (const score of [null, '', '18', false, -1, 101]) {
    f.state.score = score;
    assert.equal((await radar.collectRadar(f.ctx)).proxy.score, null);
  }
  f.state.score = 0;
  assert.equal((await radar.collectRadar(f.ctx)).proxy.score, 0);
});
test('invalid IP and malformed JSON fall back instead of accepting unbound scores', async t => {
  const f = setup(t);
  for (const bad of ['999.1.1.1', 'abcd', '1:2:3', '1::2::3', ':1::2', '1:2:3:4:5:6:7:8:']) {
    f.state.ip = bad;
    assert.equal((await radar.collectRadar(f.ctx)).proxy.source, 'ip-api');
  }
  f.state.replies.set('ippure.com', { status: 200, body: '{invalid' });
  assert.equal((await radar.collectRadar(f.ctx)).proxy.score, null);
});
test('normal refresh rechecks actual exit, while warm local and service caches suppress duplicate requests', async t => {
  const f = setup(t);
  await radar.collectRadar(f.ctx); f.calls.length = 0; f.state.now += 1000;
  const r = await radar.collectRadar(f.ctx);
  assert.equal(f.calls.length, 2);
  assert.equal(r.cached, true);
  assert.equal(serviceCalls(f.calls).length, 0);
  f.state.ip = '203.0.113.43'; f.calls.length = 0;
  assert.equal((await radar.collectRadar(f.ctx)).cached, false);
  assert.equal(serviceCalls(f.calls).length, 7);
});
test('unknown items retry independently without re-requesting successful services', async t => {
  const f = setup(t); f.state.replies.set('chatgpt', new Error('timeout'));
  await radar.collectRadar(f.ctx); f.calls.length = 0; f.state.now += 31_000;
  f.state.replies.delete('chatgpt');
  const r = await radar.collectRadar(f.ctx);
  assert.equal(serviceCalls(f.calls).length, 1);
  assert.equal(r.checks.GPT.state, 'reachable');
  assert.equal(r.cached, true);
});
test('network and selected policy changes invalidate caches even at the same exit IP', async t => {
  const f = setup(t);
  await radar.collectRadar(f.ctx); f.calls.length = 0;
  f.ctx.device.wifi.ssid = 'Other Wi-Fi';
  await radar.collectRadar(f.ctx);
  assert.equal(f.calls.length, 11);
  f.ctx.env.RADAR_POLICY = 'MyProxy'; f.calls.length = 0;
  await radar.collectRadar(f.ctx);
  assert.equal(serviceCalls(f.calls).every(c => c.policy === 'MyProxy'), true);
  assert.equal(f.calls.length, 11);
});
test('manual force bypasses caches, disable makes zero service requests', async t => {
  const f = setup(t);
  await radar.collectRadar(f.ctx); f.calls.length = 0;
  f.ctx.script.name = '网络诊断雷达 · 立即检测';
  await radar.collectRadar(f.ctx);
  assert.equal(f.calls.length, 11);
  f.ctx.env.RADAR_SERVICES_ENABLED = 'false'; f.calls.length = 0;
  const tree = await radar.default(f.ctx);
  assert.equal(serviceCalls(f.calls).length, 0);
  assert.equal(texts(tree).filter(v => v === '—').length, 6);
});
test('cache expiry and explicit zero TTL request fresh data', async t => {
  const f = setup(t);
  await radar.collectRadar(f.ctx); f.calls.length = 0; f.state.now += 601_000;
  assert.equal((await radar.collectRadar(f.ctx)).cached, false);
  assert.equal(f.calls.length, 11);
  f.ctx.env.RADAR_LOCAL_CACHE_SECONDS = '0'; f.ctx.env.RADAR_SERVICE_CACHE_SECONDS = '0'; f.calls.length = 0;
  await radar.collectRadar(f.ctx);
  assert.equal(f.calls.length, 11);
});
test('storage failures do not prevent rendering or leak raw errors', async t => {
  const f = setup(t);
  f.ctx.storage = { get: () => { throw new Error('PRIVATE raw failure'); }, set: () => { throw new Error('PRIVATE raw failure'); } };
  const tree = await radar.default(f.ctx);
  assert.equal(tree.type, 'widget');
  assert.equal(JSON.stringify(tree).includes('PRIVATE'), false);
});
test('accepted medium layout has six rows per column and icons, ASN, organization and services', async t => {
  const f = setup(t), tree = await radar.default(f.ctx);
  const columns = tree.children[1];
  for (const index of [0, 2]) {
    assert.equal(columns.children[index].children.length, 6);
    assert.equal(columns.children[index].children.every(row => row.children[0].type === 'image'), true);
  }
  for (const value of ['内网', '组织', 'ASN', '策略', '中国电信', 'AS64496', ...['NF', 'DP', 'TK', 'GPT', 'CL', 'GM']]) assert.equal(texts(tree).includes(value), true, value);
  assert.equal(walk(tree).filter(n => n.type === 'image').every(n => n.src.startsWith('sf-symbol:')), true);
});
test('large layout does not duplicate quality or AI and keeps IPv6 readable', async t => {
  const f = setup(t, { ip: '2001:db8:85a3:8d3:1319:8a2e:370:7348' });
  f.ctx.env.RADAR_LAYOUT = 'large';
  const tree = await radar.default(f.ctx), values = texts(tree);
  assert.equal(values.filter(v => v === 'IPPure 风险').length, 1);
  assert.equal(values.filter(v => v === '机房 / 商业').length, 1);
  assert.equal(values.filter(v => v === 'GPT').length, 1);
  assert.equal(values.includes('网关'), true);
  const ip = walk(tree).find(n => n.text === f.state.ip);
  assert.equal(ip.maxLines, 2);
  assert.ok(ip.minScale >= 0.9);
  f.ctx.env.RADAR_LAYOUT = 'medium';
  assert.equal(texts(await radar.default(f.ctx)).some(v => v.includes('…') && v.startsWith('2001:db8:')), true);
});
test('masking hides all displayed address values without changing detection', async t => {
  const f = setup(t); f.ctx.env.RADAR_MASK_IP = 'true'; f.ctx.env.RADAR_LAYOUT = 'large';
  const tree = await radar.default(f.ctx), content = JSON.stringify(tree);
  for (const ip of [f.state.ip, '192.0.2.18', '192.168.50.128', '192.168.50.1']) assert.equal(content.includes(ip), false, ip);
  assert.equal(texts(tree).includes('203.0.*.*'), true);
});

// Geometry contract, not a claim to emulate iOS font rendering. Reserve 1.2x
// numeric font size per line and check descendants against each explicit box.
function reservedHeight(node) {
  if (node.type === 'text') return node.font.size * 1.2 * node.maxLines;
  if (node.type === 'image') return node.height;
  assert.notEqual(node.type, 'spacer', 'unbounded spacer can consume native row space');
  const heights = (node.children || []).map(reservedHeight);
  const p = node.padding || 0;
  const verticalPadding = Array.isArray(p) ? p[0] + (p.length === 2 ? p[0] : p[2]) : p * 2;
  const needed = verticalPadding + (node.direction === 'row' ? Math.max(0, ...heights)
    : heights.reduce((a, b) => a + b, 0) + Math.max(0, heights.length - 1) * (node.gap || 0));
  if (node.height) assert.ok(needed <= node.height + 0.01, `content ${needed} exceeds reserved ${node.height}: ${texts(node).join('/')}`);
  return node.height || needed;
}

test('native layout reserves every row, bounds title and values, and fits medium/large height budgets', async t => {
  const f = setup(t, { ip: '2001:db8:85a3:8d3:1319:8a2e:370:7348' });
  const model = await radar.collectRadar(f.ctx);
  model.net.label = 'Very long wireless network name '.repeat(5);
  model.proxy.organization = 'Very long organization name '.repeat(5);
  model.local.location = '很长的地区名称'.repeat(10);
  for (const [family, budget] of [['systemMedium', 155], ['systemLarge', 329]]) {
    f.ctx.env.RADAR_LAYOUT = 'auto'; f.ctx.widgetFamily = family;
    const tree = radar.renderRadar(model, f.ctx);
    assert.ok(reservedHeight(tree) <= budget);
    assert.ok(walk(tree).filter(n => n.type === 'stack').every(n => n.height > 0));
    const title = walk(tree).find(n => n.text === '网络诊断雷达');
    assert.equal(title.flex, 1); assert.equal(title.maxLines, 1);
    const location = walk(tree).find(n => n.text === model.local.location);
    assert.equal(location.flex, 1); assert.equal(location.maxLines, 1);
    // Vertical flex would compete for section height instead of reserving it.
    for (const n of walk(tree).filter(n => n.direction === 'column' || n.type === 'widget')) {
      assert.ok((n.children || []).every(child => !child.flex));
    }
  }
});
