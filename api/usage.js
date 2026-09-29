'use strict';
let cached = null;
let inFlight = null;
let expiresAt = 0;
const blank = (status, message) => ({ status, updatedAt: null, isAvailable: null, balances: [], message });

function money(value) {
  if (typeof value !== 'string' || !/^-?\d+(\.\d+)?$/.test(value)) throw Error('invalid balance');
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) throw Error('invalid balance');
  return n;
}
function parseBalances(data) {
  if (typeof data?.is_available !== 'boolean' || !Array.isArray(data.balance_infos)) throw Error('invalid response');
  const currencies = new Set();
  const balances = data.balance_infos.map(item => {
    if (!['CNY', 'USD'].includes(item.currency) || currencies.has(item.currency)) throw Error('invalid currency');
    currencies.add(item.currency);
    const total = money(item.total_balance), granted = money(item.granted_balance), toppedUp = money(item.topped_up_balance);
    if (Math.abs(total - granted - toppedUp) > 0.011) throw Error('inconsistent balance');
    return { currency: item.currency, total, granted, toppedUp };
  });
  return { status: 'live', updatedAt: new Date().toISOString(), isAvailable: data.is_available, balances };
}
async function queryDeepseek() {
  const key = process.env.DEEPSEEK_API_KEY;
  if (!key || !key.trim()) return blank('not_configured', '尚未连接 DeepSeek API 账户。');
  if (cached && Date.now() < expiresAt) return cached;
  if (inFlight) return inFlight;
  inFlight = (async () => {
    let result;
    try {
      const response = await fetch('https://api.deepseek.com/user/balance', {
        method: 'GET', headers: { Authorization: 'Bearer ' + key.trim(), Accept: 'application/json' },
        redirect: 'error', signal: AbortSignal.timeout(10000)
      });
      if (!response.ok) {
        result = blank('error', response.status === 401 || response.status === 403 ? 'DeepSeek 账户连接失效，需更新授权。' : '暂时无法查询 DeepSeek 余额，请稍后刷新。');
      } else result = parseBalances(await response.json());
    } catch {
      result = blank('error', '暂时无法确认 DeepSeek 余额，请稍后刷新。');
    }
    cached = result;
    expiresAt = Date.now() + (result.status === 'live' ? 60000 : 15000);
    return result;
  })();
  try { return await inFlight; } finally { inFlight = null; }
}
function codexSnapshot() {
  let snapshot;
  try { snapshot = JSON.parse(process.env.CODEX_USAGE_SNAPSHOT || 'null'); } catch { snapshot = null; }
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  if (!snapshot || !Number.isFinite(Date.parse(snapshot.updatedAt))) return { status: 'unavailable', windows: [], updatedAt: null };
  return {
    status: 'snapshot', source: 'Codex 应用账户用量查询', updatedAt: snapshot.updatedAt,
    windows: ['primary', 'secondary'].map(id => {
      const w = snapshot.windows?.find(item => item.id === id);
      return { id, label: id === 'primary' ? '5 小时额度' : '每周额度',
        usedPercent: finite(w?.usedPercent) && w.usedPercent >= 0 && w.usedPercent <= 100 ? w.usedPercent : null,
        windowDurationMins: id === 'primary' ? 300 : 10080,
        resetsAt: finite(w?.resetsAt) && w.resetsAt > 0 ? w.resetsAt : null };
    })
  };
}
async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD'); res.statusCode = 405;
    return res.end(JSON.stringify({ error: 'Method not allowed' }));
  }
  const result = { codex: codexSnapshot(), deepseek: await queryDeepseek() };
  res.statusCode = 200;
  res.end(req.method === 'HEAD' ? '' : JSON.stringify(result));
}
module.exports = handler;
module.exports.parseBalances = parseBalances;
