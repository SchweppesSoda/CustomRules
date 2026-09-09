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
  assert.equal(result.checks.DP.cc, 'JP'); // Parsed from the Disney page, not the proxy IP.
});
test('GPT timeout is unknown even when exit lookup succeeds', async t => {
  const f = setup(t); f.state.replies.set('chatgpt', new Error('timeout'));
  const result = await radar.collectRadar(f.ctx);
  assert.equal(result.checks.GPT.state, 'unknown');
  const tree = radar.renderRadar(result, f.ctx);
  assert.ok(texts(tree).includes('GPT 连接'));
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
  f.state.replies.set('70143836', { status: 404, body: '<html><title>Not found</title></html>' });
  f.state.replies.set('disney', { status: 302, location: 'https://www.disneyplus.com/unavailable' });
  f.state.replies.set('gemini', { status: 302, location: 'https://gemini.google.com/faq/' });
  const r = await radar.collectRadar(f.ctx);
  assert.equal(r.checks.NF.state, 'limited');
  assert.equal(r.checks.DP.state, 'restricted');
  assert.equal(r.checks.GM.state, 'unknown'); // A generic FAQ redirect is not a geo denial.
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
  assert.equal(r.checks.GPT.state, 'region');
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
  assert.equal(texts(tree).filter(v => v.endsWith(' —')).length, 6);
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
  assert.equal(columns.children.length, 6);
  for (const row of columns.children) {
    assert.equal(row.children.length, 2);
    assert.ok(row.children.every(cell => cell.children[0].type === 'image'));
  }
  for (const value of ['内网', '组织', 'ASN', '策略', '中国电信', 'AS64496']) assert.equal(texts(tree).includes(value), true, value);
  for (const id of ['NF', 'DP', 'TK', 'GPT', 'CL', 'GM']) assert.ok(texts(tree).some(v => v.startsWith(id + ' ')), id);
  assert.equal(walk(tree).filter(n => n.type === 'image').every(n => n.src.startsWith('sf-symbol:')), true);
});
test('both layouts keep every data value on one line, including organization and unexpected IPv6', async t => {
  const f = setup(t);
  f.ctx.env.RADAR_LAYOUT = 'large';
  const model = await radar.collectRadar(f.ctx);
  model.proxy.ip = '2001:db8:85a3:8d3:1319:8a2e:370:7348';
  model.proxy.organization = 'Very Long International Organization Name';
  const tree = radar.renderRadar(model, f.ctx), values = texts(tree);
  assert.equal(values.filter(v => v.startsWith('IPPure ')).length, 1);
  assert.equal(values.filter(v => v === '机房 / 商业').length, 1);
  assert.equal(values.filter(v => v.startsWith('GPT ')).length, 1);
  assert.equal(values.includes('网关'), true);
  const ip = walk(tree).find(n => n.text === model.proxy.ip);
  assert.equal(ip.maxLines, 1);
  assert.equal(ip.minScale, 1);
  assert.ok(walk(tree).filter(n => n.type === 'text').every(n => n.maxLines === 1));
  f.ctx.env.RADAR_LAYOUT = 'medium';
  const medium = radar.renderRadar(model, f.ctx);
  assert.equal(texts(medium).some(v => v.includes('…') && v.startsWith('2001:db8:')), true);
  assert.ok(walk(medium).filter(n => n.type === 'text').every(n => n.maxLines === 1));
});

test('IPv4 IPPure endpoint is preferred and IPv6 responses never populate IPv4 quality', async t => {
  const f = setup(t);
  let model = await radar.collectRadar(f.ctx);
  assert.ok(f.calls.some(c => c.url === 'https://my.123169.xyz/v1/info'));
  assert.ok(!f.calls.some(c => c.url.includes('my.ippure.com')));
  assert.equal(model.proxy.score, 18);
  f.state.ip = '2001:db8::1234';
  model = await radar.collectRadar(f.ctx);
  assert.equal(model.proxy.ip, '198.51.100.88');
  assert.equal(model.proxy.score, null);
  assert.equal(model.proxy.residential, null);
  f.state.replies.set('ip-api.com', { status: 200, body: { status: 'success', query: '2001:db8::5678', countryCode: 'JP', org: 'Wrong family' } });
  f.calls.length = 0;
  model = await radar.collectRadar(f.ctx);
  assert.equal(model.proxy.ip, '');
  assert.equal(model.proxy.organization, '');
  assert.equal(serviceCalls(f.calls).length, 0);
});

test('IPv4 mirror failure can fall back to a validated IPv4 official response', async t => {
  const f = setup(t);
  f.state.replies.set('my.123169.xyz', new Error('mirror timeout'));
  const model = await radar.collectRadar(f.ctx);
  assert.equal(model.proxy.ip, f.state.ip);
  assert.equal(model.proxy.score, 18);
  assert.equal(model.proxy.source, 'IPPure');
});

test('service names and results stay in the same text block in aligned cells', async t => {
  const f = setup(t);
  for (const layout of ['medium', 'large']) {
    f.ctx.env.RADAR_LAYOUT = layout;
    const tree = await radar.default(f.ctx);
    const panel = tree.children[3];
    if (layout === 'medium') {
      assert.equal(panel.children.length, 6);
      assert.equal(panel.height, 14);
      assert.ok(panel.children.every(cell => cell.flex === 1 && cell.children[0].type === 'text'));
      continue;
    }
    const rows = panel.children;
    assert.equal(rows.length, 2);
    assert.equal(panel.height, 38);
    assert.equal(rows[0].children[0].width, rows[1].children[0].width);
    for (const row of rows) {
      assert.equal(row.children.length, 4);
      for (const cell of row.children.slice(1)) {
        assert.equal(cell.flex, 1);
        assert.equal(cell.children[0].type, 'image');
        assert.match(cell.children[1].text, /^(NF|DP|TK|GPT|CL|GM) (?:(?:[A-Z]{2} )?[✓×◐?—]|[A-Z]{2,3})$/);
        assert.equal(cell.children[1].textAlign, 'left');
      }
    }
  }
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

function checkAllocation(node, allocatedHeight) {
  if (!node.children) return;
  const p = node.padding || 0;
  const padding = Array.isArray(p) ? p[0] + (p.length === 2 ? p[0] : p[2]) : p * 2;
  const inner = allocatedHeight - padding;
  if (node.direction === 'row') {
    for (const c of node.children) {
      assert.ok(reservedHeight(c) <= inner + 0.01, `row content exceeds allocation: ${texts(c)}`);
      checkAllocation(c, c.height || inner);
    }
  } else {
    const fixed = node.children.filter(c => !c.flex).reduce((sum, c) => sum + reservedHeight(c), 0);
    const flex = node.children.reduce((sum, c) => sum + (c.flex || 0), 0);
    const remaining = inner - fixed - Math.max(0, node.children.length - 1) * (node.gap || 0);
    for (const c of node.children) {
      const height = c.flex ? remaining * c.flex / flex : reservedHeight(c);
      assert.ok(height + 0.01 >= reservedHeight(c), `flex row is compressed below readable height: ${texts(c)}`);
      checkAllocation(c, height);
    }
  }
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
    for (const height of [budget, budget + 15, budget + 47]) checkAllocation(tree, height);
    const title = walk(tree).find(n => n.text === '网络诊断雷达');
    assert.equal(title.flex, 1); assert.equal(title.maxLines, 1);
    const location = walk(tree).find(n => n.text === model.local.location);
    assert.equal(location.flex, 1); assert.equal(location.maxLines, 1);
    // Only the main table absorbs surplus root height. Footer rows stay compact.
    assert.deepEqual(tree.children.filter(c => c.flex), [tree.children[1]]);
    assert.ok(walk(tree).filter(n => n.type === 'stack' && !n.height).every(n => n.flex === 1));
  }
});

test('normal pages containing CAPTCHA resources remain usable, real interstitials do not', async t => {
  const f = setup(t), r = await radar.collectRadar(f.ctx);
  for (const id of ['NF', 'DP', 'TK']) assert.equal(r.checks[id].state, 'reachable', id);
  for (const id of ['GPT', 'CL', 'GM']) assert.equal(r.checks[id].state, 'region', id);
  assert.ok(texts(radar.renderRadar(r, f.ctx)).includes('CL JP'));
  f.ctx.script.name = '网络诊断雷达 · 立即检测';
  f.state.replies.set('disney', { status: 403, body: '<html><title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x"></script></html>' });
  assert.equal((await radar.collectRadar(f.ctx)).checks.DP.reason, 'challenge');
});

test('normal HTTPS redirects follow within the same service with the original policy and no cookies', async t => {
  const f = setup(t);
  f.state.replies.set('=https://www.disneyplus.com/', { status: 302, location: '/welcome' });
  f.state.replies.set('=https://www.netflix.com/title/70143836', { status: 301, location: 'https://www.netflix.com/jp/title/70143836' });
  const r = await radar.collectRadar(f.ctx);
  assert.equal(r.checks.DP.state, 'reachable');
  assert.equal(r.checks.NF.state, 'reachable');
  assert.equal(r.checks.NF.cc, 'JP');
  for (const c of serviceCalls(f.calls)) { assert.equal(c.policy, 'Proxy'); assert.equal(c.credentials, 'omit'); }
});

test('redirect loops, foreign hosts and HTTP downgrades remain bounded unknown results', async t => {
  const f = setup(t); f.ctx.script.name = '网络诊断雷达 · 立即检测';
  for (const location of ['/', 'https://www.disneyplus.com.example.org/', 'http://www.disneyplus.com/', 'https://user@www.disneyplus.com/', 'https://127.0.0.1/']) {
    f.state.replies.set('disney', { status: 302, location }); f.calls.length = 0;
    const r = await radar.collectRadar(f.ctx);
    assert.equal(r.checks.DP.reason, 'redirect');
    assert.equal(f.calls.filter(c => c.url.includes('disney')).length, 1);
  }
});

test('plain HTTP failures and unexpected content retain diagnostic reasons, not a green check', async t => {
  const f = setup(t);
  f.state.replies.set('disney', { status: 403, body: '<html><title>Forbidden</title></html>' });
  f.state.replies.set('tiktok', { status: 429, body: '' });
  f.state.replies.set('gemini', { status: 200, body: '<html><title>Sign in</title></html>' });
  const r = await radar.collectRadar(f.ctx);
  assert.equal(r.checks.DP.reason, 'http_403');
  assert.equal(r.checks.TK.reason, 'rate_limit');
  assert.equal(r.checks.GM.reason, 'unrecognized');
  const values = texts(radar.renderRadar(r, f.ctx));
  for (const expected of ['DP 403', 'TK 限流', 'GM 解析']) assert.ok(values.includes(expected));
});

test('large columns have seven aligned rows with latency last; medium reserves title breathing room', async t => {
  const f = setup(t), model = await radar.collectRadar(f.ctx);
  const medium = radar.renderRadar(model, f.ctx);
  assert.ok(medium.children[0].padding[2] + medium.gap >= 9);
  assert.equal(walk(medium).find(n => n.text === '网络诊断雷达').font.size, 17);
  f.ctx.env.RADAR_LAYOUT = 'large';
  const large = radar.renderRadar(model, f.ctx);
  const rows = large.children[1].children.slice(1);
  assert.equal(rows.length, 7);
  for (const row of rows) assert.equal(row.children[0].height, row.children[1].height);
  assert.ok(rows.at(-1).children.every(cell => texts(cell).includes('延迟')));
  assert.ok(texts(rows.at(-2).children[1]).includes('来源'));
  assert.equal(walk(large).find(n => n.text === '网络诊断雷达').font.size, 20);
});
