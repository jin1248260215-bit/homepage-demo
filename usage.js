'use strict';
(() => {
  const codexCards = document.getElementById('codex-cards');
  const deepseekCards = document.getElementById('deepseek-cards');
  const update = document.getElementById('usage-update');
  const refresh = document.getElementById('usage-refresh');
  const defaultWindows = [{id: 'primary', label: '5 小时额度'}, {id: 'secondary', label: '每周额度'}];
  const colors = {teal: '#177e73', mint: '#77c7b6', track: '#eaf0f1'};
  let lastData = null;
  let loading = false;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const timestamp = value => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? Date.parse(value) : null;
  const number = value => new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 1}).format(value);
  const money = (value, currency) => new Intl.NumberFormat('zh-CN', {style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 4}).format(value);
  const date = value => new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false}) + '（北京时间）';
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function card(title, badgeText, badgeClass = '') {
    const article = el('article', 'usage-card');
    const heading = el('div', 'usage-card-head');
    heading.append(el('h3', '', title), el('span', 'usage-badge ' + badgeClass, badgeText));
    article.append(heading);
    return article;
  }
  function chart(value, caption, label, percent = null, alternate = colors.track) {
    const figure = el('figure', 'usage-chart');
    figure.setAttribute('role', 'img');
    figure.setAttribute('aria-label', label);
    if (finite(percent)) figure.style.background = 'conic-gradient(' + colors.teal + ' 0% ' + Math.max(0, Math.min(100, percent)) + '%, ' + alternate + ' ' + Math.max(0, Math.min(100, percent)) + '% 100%)';
    const center = el('div', 'usage-chart-center');
    center.setAttribute('aria-hidden', 'true');
    center.append(el('div', 'usage-chart-value' + (percent === null ? ' is-label' : ''), value), el('div', 'usage-chart-caption', caption));
    figure.append(center);
    return figure;
  }
  function legend(entries) {
    const list = el('ul', 'usage-legend');
    for (const entry of entries) {
      const item = el('li');
      const swatch = el('span', 'usage-swatch ' + entry.color);
      swatch.setAttribute('aria-hidden', 'true');
      item.append(swatch, el('span', 'usage-legend-name', entry.label), el('strong', '', entry.value));
      list.append(item);
    }
    return list;
  }
  function emptyCard(title, badgeText, center, explanation, note) {
    const article = card(title, badgeText, 'is-muted');
    const row = el('div', 'usage-chart-row');
    const copy = el('div', 'usage-empty-copy');
    copy.append(el('strong', '', center), el('p', '', explanation));
    row.append(chart('—', '暂无数据', title + '：' + center + '，当前没有可展示的数值。'), copy);
    article.append(row);
    if (note) article.append(el('p', 'usage-card-note', note));
    return article;
  }
  function renderCodex(data) {
    codexCards.replaceChildren();
    const updated = timestamp(data?.updatedAt);
    const snapshot = data?.status === 'snapshot' && updated !== null;
    const old = snapshot && Date.now() - updated > 30 * 60 * 1000;
    for (const fallback of defaultWindows) {
      const windowData = Array.isArray(data?.windows) ? data.windows.find(item => item?.id === fallback.id) : null;
      const used = windowData?.usedPercent;
      const reset = finite(windowData?.resetsAt) ? windowData.resetsAt * 1000 : null;
      const expired = reset !== null && reset <= Date.now();
      const valid = snapshot && finite(used) && used >= 0 && used <= 100;
      if (!valid || expired) {
        codexCards.append(emptyCard(fallback.label, expired ? '待同步' : '暂无快照', expired ? '等待新快照' : '尚无可用数据', expired ? '上次记录的窗口重置时间已过，当前额度需要重新同步。' : '同步账户额度后，这里会显示剩余与已用的比例。', expired ? '上次记录的重置时间：' + date(reset) + '。不会自动假定额度已恢复。' : '未知额度不会显示为 0% 或 100%。'));
        continue;
      }
      const remaining = 100 - used;
      const article = card(fallback.label, old ? '快照较旧' : '已同步快照', old ? 'is-warning' : '');
      const row = el('div', 'usage-chart-row');
      row.append(chart(number(remaining) + '%', '快照中的剩余', fallback.label + '：剩余 ' + number(remaining) + '%，已用 ' + number(used) + '%。数据同步于 ' + date(updated) + '。', remaining), legend([{color: 'teal', label: '剩余', value: number(remaining) + '%'}, {color: '', label: '已用', value: number(used) + '%'}]));
      article.append(row, el('p', 'usage-card-note' + (old ? ' is-warning' : ''), (reset !== null ? '记录的重置时间：' + date(reset) + '。' : '暂未提供重置时间。') + (old ? ' 快照已超过 30 分钟，当前额度可能不同。' : '')));
      codexCards.append(article);
    }
    document.getElementById('codex-source').textContent = snapshot ? '来源：Codex 账户额度快照 · 同步于 ' + date(updated) + '。刷新仅加载最新已同步快照。' : '来源：Codex 账户额度快照 · 尚未取得可展示的快照。';
    codexCards.setAttribute('aria-busy', 'false');
  }
  function renderDeepSeek(data) {
    deepseekCards.replaceChildren();
    const updated = timestamp(data?.updatedAt);
    const balances = Array.isArray(data?.balances) ? data.balances.filter(item => item && ['CNY', 'USD'].includes(item.currency) && finite(item.total) && finite(item.granted) && finite(item.toppedUp)) : [];
    const live = data?.status === 'live';
    if (!live || !balances.length) {
      const pending = data?.status === 'not_configured';
      const noDetails = live && Array.isArray(data.balances) && data.balances.length === 0;
      deepseekCards.append(emptyCard('DeepSeek API', pending ? '待连接' : noDetails ? '暂无明细' : '暂不可用', pending ? '等待连接账户' : noDetails ? '暂无余额明细' : '暂时无法读取', pending ? '账户连接完成后，这里会展示官方返回的可用余额。' : noDetails ? '已连接账户，开放平台本次没有返回余额明细。' : '本次没有取得有效余额，请稍后刷新。', '当前没有余额数据；灰色空环不表示账户余额为零。'));
    } else {
      for (const balance of balances) {
        const total = balance.total;
        const partsTotal = balance.granted + balance.toppedUp;
        const partsValid = balance.granted >= 0 && balance.toppedUp >= 0 && partsTotal > 0 && total > 0 && Math.abs(partsTotal - total) <= Math.max(.01, total * .001);
        const percent = partsValid ? balance.granted / partsTotal * 100 : null;
        const currencyLabel = balance.currency === 'CNY' ? '人民币' : '美元';
        const badge = data.isAvailable === false ? '账户暂不可用' : total <= 0 ? '余额不足' : '最新读取';
        const article = card(currencyLabel + '余额', badge, data.isAvailable === false || total <= 0 ? 'is-warning' : '');
        const row = el('div', 'usage-chart-row');
        const figure = chart(money(total, balance.currency), '可用余额', 'DeepSeek API ' + currencyLabel + '余额：合计 ' + money(total, balance.currency) + '，赠送余额 ' + money(balance.granted, balance.currency) + '，充值余额 ' + money(balance.toppedUp, balance.currency) + '。', percent, colors.mint);
        figure.querySelector('.usage-chart-value').classList.remove('is-label');
        row.append(figure, legend([{color: 'teal', label: '赠送余额', value: money(balance.granted, balance.currency)}, {color: 'mint', label: '充值余额', value: money(balance.toppedUp, balance.currency)}]));
        article.append(row, el('p', 'usage-card-note', partsValid ? '环图表示余额构成，不是已消耗比例。实际可用 Token 数随模型与调用方式变化。' : total <= 0 ? '当前可用余额不足；未绘制余额占比。' : '余额明细暂不支持绘制占比，保留官方返回的金额。'));
        deepseekCards.append(article);
      }
    }
    document.getElementById('deepseek-source').textContent = live ? '来源：DeepSeek API 开放平台 · ' + (updated !== null ? '更新于 ' + date(updated) : '更新时间暂不可用') + '。' : '来源：DeepSeek API 开放平台 · ' + (data?.status === 'not_configured' ? '尚未连接。' : '本次未取得有效余额。');
    deepseekCards.setAttribute('aria-busy', 'false');
  }
  function render(data) { renderCodex(data?.codex); renderDeepSeek(data?.deepseek); }
  async function load() {
    if (loading) return;
    loading = true;
    refresh.disabled = true;
    update.classList.remove('is-error');
    update.textContent = '正在读取数据…';
    codexCards.setAttribute('aria-busy', 'true');
    deepseekCards.setAttribute('aria-busy', 'true');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/api/usage', {cache: 'no-store', signal: controller.signal, credentials: 'same-origin', headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('request-failed');
      const data = await response.json();
      if (!data || typeof data !== 'object' || !data.codex || !data.deepseek) throw new Error('invalid-response');
      lastData = data;
      render(data);
      update.textContent = '页面读取于 ' + date(Date.now()) + ' · 各账户数据时间见下方。';
    } catch {
      render(lastData);
      update.classList.add('is-error');
      update.textContent = lastData ? '刷新失败，保留上次读取的数据；请留意各项的更新时间，稍后重试。' : '暂时无法读取用量数据，请稍后点击刷新。当前没有展示任何估算额度。';
    } finally {
      clearTimeout(timeout);
      loading = false;
      refresh.disabled = false;
      codexCards.setAttribute('aria-busy', 'false');
      deepseekCards.setAttribute('aria-busy', 'false');
    }
  }
  render(null);
  refresh.addEventListener('click', load);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && lastData) render(lastData); });
  setInterval(() => { if (!document.hidden && lastData && !loading) renderCodex(lastData.codex); }, 60000);
  load();
})();
