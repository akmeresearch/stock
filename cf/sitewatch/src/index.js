/* AKME 게시판 감시 워커 — 1분마다 data/site_watch.json 의 사이트를 확인해 새 글을 텔레그램으로 보낸다.
   설정·수신자는 사이트(GitHub Pages)에서 읽고, 상태(본 글)는 KV 에 둔다. */

const UA = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36', 'Accept-Language': 'ko-KR,ko;q=0.9' };

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const textOf = html => html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ')
  .replace(/<br\s*\/?>|<\/p>|<\/div>|<\/tr>|<\/li>/gi, '\n').replace(/<[^>]+>/g, ' ')
  .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
  .replace(/[ \t ]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
const ws = s => s.replace(/\s+/g, ' ').trim();
const kst = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16).replace('T', ' ');

async function fetchText(url) {
  const r = await fetch(url, { headers: UA, cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  const buf = await r.arrayBuffer();
  const ct = r.headers.get('content-type') || '';
  const m = /charset=([\w-]+)/i.exec(ct);
  let enc = m ? m[1].toLowerCase() : 'utf-8';
  if (enc === 'iso-8859-1' || enc === 'ascii') enc = 'utf-8';
  try { return new TextDecoder(enc).decode(buf); } catch { return new TextDecoder('utf-8').decode(buf); }
}

async function sha1(s) {
  const d = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/* 링크형 게시판: link_re 의 첫 괄호 = 글 id */
function linkPosts(site, html) {
  const re = new RegExp(`<a[^>]+href=['"]([^'"]*${site.link_re}[^'"]*)['"][^>]*>([\\s\\S]*?)<\\/a>`, 'gi');
  const out = [], seen = new Set(); let m;
  while ((m = re.exec(html))) {
    const href = m[1], pid = m[2], title = ws(m[3].replace(/<[^>]+>/g, ' '));
    if (!title || seen.has(pid)) continue;
    seen.add(pid);
    const link = href.startsWith('http') ? href : href.startsWith('?') ? site.url + href : (site.base || '') + href;
    const row = html.slice(m.index + m[0].length, m.index + m[0].length + 1500);
    const dm = /(20\d\d[-./]\d\d[-./]\d\d)/.exec(row);
    out.push({ id: pid, title, link: link.replace(/&amp;/g, '&'), date: dm ? dm[1] : '' });
  }
  return out;
}

/* irupsite FAQ: 날짜 + 본문 해시 */
async function faqPosts(site, html) {
  const re = /<button class="trigger"[\s\S]*?<strong class="tit">([\s\S]*?)<\/strong>[\s\S]*?<div class="date">\s*([\d.-]+)\s*<\/div>[\s\S]*?<p class="desc">([\s\S]*?)<\/p>/g;
  const out = []; let m;
  while ((m = re.exec(html))) {
    const title = ws(m[1].replace(/<[^>]+>/g, ' ')), date = m[2].trim(), body = textOf(m[3]);
    const pid = `${date}-${(await sha1(body.replace(/\s+/g, ''))).slice(0, 8)}`;
    const qs = [...body.matchAll(/(Q\d+\.[^\n]{3,140})/g)].map(x => ws(x[1]));
    const intro = ws(body.split('Q1.')[0]).slice(0, 300);
    const ex = (intro + (intro ? '\n\n' : '') + qs.slice(0, 8).map(q => `• ${q.slice(0, 110)}`).join('\n') + (qs.length > 8 ? `\n… 외 ${qs.length - 8}개` : '')).trim() || body.slice(0, 600);
    out.push({ id: pid, title: qs.length ? `${title} (${qs.length}문항)` : title, link: site.url + (site.anchor || ''), date, excerpt: ex });
  }
  return out;
}

async function excerpt(link, title) {
  try {
    const t = textOf(await fetchText(link));
    const i = t.indexOf(title.slice(0, 20));
    let body = i >= 0 ? t.slice(i + title.length) : t;
    body = body.trim().replace(/^(최고관리자|관리자|작성자|작성일자?|조회|첨부|목록|이전글|다음글|[\d\-.: ]+)\s*/, '');
    for (const cut of ['이전글', '다음글', '목록보기', 'Copyright', 'COPYRIGHT']) { const j = body.indexOf(cut); if (j > 200) body = body.slice(0, j); }
    return ws(body).slice(0, 600);
  } catch { return ''; }
}

async function recipients(env) {
  const r = await fetch(env.SITE + 'data/notify.json?t=' + Math.floor(Date.now() / 600e3), { cf: { cacheTtl: 600 } });
  const j = r.ok ? await r.json() : {};
  const ids = (j.chat_ids || []).map(c => (typeof c === 'object' ? c.id : c));
  if (j.chat_id && !ids.includes(j.chat_id)) ids.unshift(j.chat_id);
  return ids;
}

async function tg(env, text) {
  const ids = await recipients(env); let ok = false;
  for (const cid of ids) {
    const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: cid, text, parse_mode: 'HTML', disable_web_page_preview: false }) });
    ok = ok || r.ok;
  }
  return ok;
}

async function check(env) {
  const conf = await (await fetch(env.SITE + 'data/site_watch.json?t=' + Math.floor(Date.now() / 600e3), { cf: { cacheTtl: 600 } })).json();
  const log = [];
  for (const site of conf.sites || []) {
    const key = 'site:' + site.id;
    const st = (await env.STATE.get(key, 'json')) || { seen: [], init: false };
    let html;
    try { html = await fetchText(site.url); } catch (e) { log.push(`${site.name}: fetch FAIL ${e.message}`); continue; }
    const ps = site.mode === 'irup_faq' ? await faqPosts(site, html) : linkPosts(site, html);
    if (!ps.length) { log.push(`${site.name}: 글 목록 없음`); continue; }
    const seen = new Set(st.seen);
    const fresh = ps.filter(p => !seen.has(p.id));
    if (!st.init) {
      st.seen = ps.map(p => p.id); st.init = true; st.initAt = kst();
      await env.STATE.put(key, JSON.stringify(st)); log.push(`${site.name}: init ${ps.length}`); continue;
    }
    for (const p of fresh.sort((a, b) => (+a.id || 0) - (+b.id || 0) || a.id.localeCompare(b.id))) {
      const ex = p.excerpt || await excerpt(p.link, p.title);
      const kind = site.mode === 'irup_faq' && st.seen.some(x => x.startsWith(p.date + '-')) ? '수정' : '새 글';
      const msg = `📢 <b>${esc(site.name)} ${kind}</b>\n<b>${esc(p.title)}</b>${p.date ? ' · ' + esc(p.date) : ''}\n\n${esc(ex)}\n\n<a href="${esc(p.link)}">원문 보기</a>`;
      const ok = await tg(env, msg);
      if (ok) { st.seen.push(p.id); st.alerts = [...(st.alerts || []).slice(-50), { id: p.id, title: p.title, at: kst() }]; }
      log.push(`${site.name}: ALERT ${p.id} ${p.title.slice(0, 40)} sent=${ok}`);
    }
    st.seen = st.seen.slice(-500); st.checkedAt = kst(); st.count = ps.length;
    await env.STATE.put(key, JSON.stringify(st));
    if (!fresh.length) log.push(`${site.name}: ${ps.length} posts, 0 new`);
  }
  await env.STATE.put('lastRun', JSON.stringify({ at: kst(), log }));
  return log;
}

async function safeCheck(env) {
  try { return await check(env); }
  catch (e) { await env.STATE.put('lastRun', JSON.stringify({ at: kst(), error: String(e && e.stack || e) })); return [String(e)]; }
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(safeCheck(env)); },
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === '/run' && url.searchParams.get('key') === (env.RUN_KEY || '')) return Response.json({ log: await safeCheck(env) });
    const last = await env.STATE.get('lastRun', 'json');
    const sites = [];
    for (const k of (await env.STATE.list({ prefix: 'site:' })).keys) { const s = await env.STATE.get(k.name, 'json'); sites.push({ id: k.name.slice(5), init: s?.init, initAt: s?.initAt, checkedAt: s?.checkedAt, count: s?.count, seen: s?.seen?.length, alerts: s?.alerts?.slice(-5) }); }
    return Response.json({ worker: 'akme-sitewatch', lastRun: last, sites }, { headers: { 'cache-control': 'no-store' } });
  },
};
