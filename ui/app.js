/* 岛·壁纸 · 前端逻辑
   与本地应用通讯走 WKWebView 的 messageHandlers：JS 发请求，Python 回结果。 */

const pending = new Map();
let seq = 1;
let STATE = null;
let CFG = null;
let currentView = 'today';

const $ = (id) => document.getElementById(id);

/* ------------------------------ 桥接 ------------------------------ */
function hasBridge() {
  return !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.native);
}

function call(action, payload = {}) {
  return new Promise((resolve, reject) => {
    if (!hasBridge()) {
      reject(new Error('未连接到本地应用（请通过菜单栏启动本窗口）'));
      return;
    }
    const id = 'r' + seq++;
    pending.set(id, { resolve, reject });
    window.webkit.messageHandlers.native.postMessage({ id, action, payload });
  });
}

window.__resolve = (id, ok, data) => {
  const p = pending.get(id);
  if (!p) return;
  pending.delete(id);
  if (ok) p.resolve(data);
  else p.reject(new Error((data && data.error) || '操作失败'));
};

window.__push = (event, data) => {
  if (event === 'state') {
    STATE = data;
    render();
  } else if (event === 'navigate') {
    switchView(data.view || 'today');
  }
};

async function safe(action, payload) {
  try {
    return await call(action, payload);
  } catch (err) {
    toast(err.message || String(err));
    return null;
  }
}

/* ------------------------------ 工具 ------------------------------ */
function urlFor(absPath) {
  if (!absPath) return '';
  const root = (STATE && STATE.root) || (CFG && CFG.root) || '';
  let p = String(absPath);
  // root 不带结尾斜杠，slice 后需去掉开头的 / 再统一补一个，
  // 否则会拼出 //cache/... 这种协议相对 URL（被解析成 http://cache/... 而全部加载失败）
  if (root && p.startsWith(root)) p = p.slice(root.length).replace(/^\/+/, '');
  if (!p.startsWith('/')) p = '/' + p;
  return encodeURI(p);
}

function humanBytes(n) {
  if (!n) return '0 MB';
  const mb = n / 1024 / 1024;
  return mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : mb.toFixed(0) + ' MB';
}

let toastTimer = null;
function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

/* ------------------------------ 视图切换 ------------------------------ */
function switchView(view) {
  currentView = view;
  document.querySelectorAll('.tab').forEach((t) => {
    t.classList.toggle('is-active', t.dataset.view === view);
  });
  document.querySelectorAll('.view').forEach((v) => {
    v.classList.toggle('is-active', v.id === 'view-' + view);
  });
  if (view === 'favorites') renderFavorites();
  if (view === 'settings') loadConfig();
}

/* ------------------------------ 渲染 ------------------------------ */
function render() {
  if (!STATE) return;
  const cur = STATE.current;

  if (cur) {
    const img = $('heroImg');
    const src = urlFor(cur.file);
    if (img.getAttribute('src') !== src) img.setAttribute('src', src);
    img.hidden = false;
    $('heroEmpty').hidden = true;
    $('heroTitle').textContent = cur.title || '未命名';
    $('heroSource').textContent = cur.source_label || cur.source || '';
    $('heroAuthor').textContent = cur.author ? '© ' + cur.author : '';
    $('btnOpenSource').hidden = !cur.page_url;

    $('infoTitle').textContent = cur.title || '—';
    $('infoSource').textContent = cur.source_label || cur.source || '—';
    $('infoAuthor').textContent = cur.author || '—';
    $('infoSize').textContent =
      cur.width && cur.height ? `${cur.width} × ${cur.height}` : '—';
    const tags = $('infoTags');
    tags.innerHTML = '';
    if (cur.tags && cur.tags.length) {
      cur.tags.slice(0, 8).forEach((t) => {
        const s = document.createElement('span');
        s.textContent = t;
        tags.appendChild(s);
      });
    } else {
      tags.textContent = '—';
    }

    const fav = $('btnFav');
    fav.classList.toggle('is-on', !!cur.favorite);
    $('btnFavText').textContent = cur.favorite ? '已收藏' : '收藏';
  } else {
    $('heroImg').hidden = true;
    $('heroEmpty').hidden = false;
    $('heroEmpty').textContent = '还没有壁纸，点「换一张新图」开始。';
  }

  $('btnPrev').disabled = !STATE.can_prev;

  // 显示器
  const sl = $('screenList');
  sl.innerHTML = '';
  (STATE.screens || []).forEach((s) => {
    const li = document.createElement('li');
    const left = document.createElement('span');
    left.textContent = `显示器 ${s.index + 1}`;
    const right = document.createElement('span');
    right.textContent = `${s.width} × ${s.height}`;
    li.appendChild(left);
    li.appendChild(right);
    if (s.main) {
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = '主屏';
      li.appendChild(tag);
    }
    sl.appendChild(li);
  });

  // 状态
  $('infoLast').textContent = (STATE.status && STATE.status.last_change) || '—';
  $('infoCache').textContent =
    `${STATE.total || 0} 张 · ${humanBytes(STATE.status ? STATE.status.cache_bytes : 0)}`;
  $('infoBlocked').textContent =
    `${(STATE.blocked && STATE.blocked.ids) || 0} 张` +
    (((STATE.blocked && STATE.blocked.authors) || 0) ? ` · ${STATE.blocked.authors} 位作者` : '');
  $('infoSources').textContent = ((STATE.status && STATE.status.sources) || [])
    .map((s) => (STATE.status.source_labels || {})[s] || s)
    .join('、') || '无';

  const warn = $('warnBox');
  if (STATE.status && STATE.status.last_error) {
    warn.textContent = STATE.status.last_error;
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }

  renderDeck();
  if (currentView === 'favorites') renderFavorites();
}

function renderDeck() {
  const list = $('deckList');
  const deck = STATE.deck || [];
  $('deckCount').textContent = `${STATE.total || 0} 张`;
  list.innerHTML = '';
  deck.slice().reverse().forEach((item) => {
    const btn = document.createElement('button');
    btn.className = 'strip-item' + (STATE.current && item.key === STATE.current.key ? ' is-current' : '');
    btn.title = item.title || '';
    const img = document.createElement('img');
    img.src = urlFor(item.file);
    img.alt = item.title || '';
    img.loading = 'lazy';
    btn.appendChild(img);
    btn.addEventListener('click', () => call('show_key', { key: item.key }));
    list.appendChild(btn);
  });
}

function renderFavorites() {
  const grid = $('favGrid');
  const favs = STATE.favorites || [];
  grid.innerHTML = '';
  $('favCount').textContent = `${favs.length} 张`;
  $('favEmpty').hidden = favs.length > 0;
  favs.forEach((f) => {
    const card = document.createElement('div');
    card.className = 'card';

    const imgWrap = document.createElement('div');
    imgWrap.className = 'card-img';
    const img = document.createElement('img');
    img.src = urlFor(f.file);
    img.alt = f.title || '';
    img.loading = 'lazy';
    imgWrap.appendChild(img);

    const body = document.createElement('div');
    body.className = 'card-body';
    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = f.title || '未命名';
    const sub = document.createElement('div');
    sub.className = 'card-sub';
    sub.textContent = f.source_label || f.source || '';
    const actions = document.createElement('div');
    actions.className = 'card-actions';

    const b1 = document.createElement('button');
    b1.className = 'btn btn-sm btn-primary';
    b1.textContent = '设为壁纸';
    b1.addEventListener('click', () => call('apply_favorite', { key: f.key }));

    const b2 = document.createElement('button');
    b2.className = 'btn btn-sm';
    b2.textContent = '在访达中显示';
    b2.addEventListener('click', () => call('reveal', { path: f.file }));

    const b3 = document.createElement('button');
    b3.className = 'btn btn-sm btn-quiet';
    b3.textContent = '移除';
    b3.addEventListener('click', () => call('remove_favorite', { key: f.key }));

    actions.append(b1, b2, b3);
    body.append(title, sub, actions);
    card.append(imgWrap, body);
    grid.appendChild(card);
  });
}

/* ------------------------------ 设置 ------------------------------ */
async function loadConfig() {
  CFG = await safe('get_config');
  if (!CFG) return;
  const s = (path, dflt) => {
    const v = path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), CFG);
    return v === undefined || v === null ? dflt : v;
  };
  $('setLaunch').checked = !!s('app.change_on_launch', true);
  $('setTimes').value = (s('app.schedule_times', []) || []).join(', ');
  $('setInterval').value = s('app.interval_minutes', 0);
  $('setFill').value = s('display.fill_mode', 'fill');
  $('setBg').value = s('display.background_color', '#15171a');
  $('setMulti').value = s('display.multi_screen', 'independent');
  $('setMinW').value = s('content.min_width', 1920);
  $('setMinH').value = s('content.min_height', 1080);

  $('srcBing').checked = !!s('sources.bing.enabled', false);
  $('srcBingMarket').value = s('sources.bing.market', 'zh-CN');
  $('srcUnsplash').checked = !!s('sources.unsplash.enabled', false);
  $('srcUnsplashKey').value = s('sources.unsplash.api_key', '');
  $('srcUnsplashMode').value = s('sources.unsplash.mode', 'query');
  $('srcWallhaven').checked = !!s('sources.wallhaven.enabled', false);
  $('srcWallhavenKey').value = s('sources.wallhaven.api_key', '');
  $('srcWhCategories').value = s('sources.wallhaven.categories', '100');
  $('srcPicsum').checked = !!s('sources.picsum.enabled', false);
  $('srcLocal').checked = !!s('sources.local.enabled', false);
  $('srcLocalFolder').value = s('sources.local.folder', '');
  $('setSaveDir').value = s('storage.save_dir', '');
  $('setMaxCache').value = s('storage.max_cached_files', 200);

  $('nextFire').textContent = '下次更新：' + (CFG.next_fire || '—');
  $('blockedNote').textContent = STATE
    ? `已屏蔽 ${(STATE.blocked && STATE.blocked.ids) || 0} 张图片、` +
      `${(STATE.blocked && STATE.blocked.authors) || 0} 位作者。`
    : '—';
}

function parseTimes(text) {
  return String(text || '')
    .split(/[,，\s]+/)
    .map((t) => t.trim())
    .filter((t) => /^\d{1,2}:\d{2}$/.test(t))
    .map((t) => (t.length === 4 ? '0' + t : t));
}

async function saveSettings() {
  const num = (v, dflt) => {
    const n = parseInt(v, 10);
    return isNaN(n) ? dflt : n;
  };
  const updates = {
    'app.change_on_launch': $('setLaunch').checked,
    'app.schedule_times': parseTimes($('setTimes').value),
    'app.interval_minutes': num($('setInterval').value, 0),
    'display.fill_mode': $('setFill').value,
    'display.background_color': $('setBg').value.trim() || '#15171a',
    'display.multi_screen': $('setMulti').value,
    'content.min_width': num($('setMinW').value, 1920),
    'content.min_height': num($('setMinH').value, 1080),
    'sources.bing.enabled': $('srcBing').checked,
    'sources.bing.market': $('srcBingMarket').value.trim() || 'zh-CN',
    'sources.unsplash.enabled': $('srcUnsplash').checked,
    'sources.unsplash.api_key': $('srcUnsplashKey').value.trim(),
    'sources.unsplash.mode': $('srcUnsplashMode').value,
    'sources.wallhaven.enabled': $('srcWallhaven').checked,
    'sources.wallhaven.api_key': $('srcWallhavenKey').value.trim(),
    'sources.wallhaven.categories': $('srcWhCategories').value.trim() || '100',
    'sources.picsum.enabled': $('srcPicsum').checked,
    'sources.local.enabled': $('srcLocal').checked,
    'sources.local.folder': $('srcLocalFolder').value.trim(),
    'storage.save_dir': $('setSaveDir').value.trim(),
    'storage.max_cached_files': num($('setMaxCache').value, 200),
  };
  const res = await safe('save_config', updates);
  if (res && res.ok) {
    toast('设置已保存');
    $('saveHint').textContent = '已更新 ' + res.updated.length + ' 项';
    await refreshState();
  } else if (res) {
    toast('保存失败：' + (res.reason || '未知原因'));
  }
}

/* ------------------------------ 事件绑定 ------------------------------ */
function bind() {
  document.querySelectorAll('.tab').forEach((t) => {
    t.addEventListener('click', () => switchView(t.dataset.view));
  });

  $('btnPrev').addEventListener('click', () => call('prev'));
  $('btnNext').addEventListener('click', () => call('next'));
  $('btnNew').addEventListener('click', () => call('refresh'));
  $('btnRefreshTop').addEventListener('click', () => call('refresh'));

  $('btnFav').addEventListener('click', () => call('toggle_favorite'));

  $('btnSave').addEventListener('click', async () => {
    const res = await safe('save');
    if (res && res.ok) toast('已保存到 ' + res.path);
  });

  $('btnBlock').addEventListener('click', async () => {
    if (!window.confirm('不再显示这张图？')) return;
    const alsoAuthor = window.confirm('是否同时屏蔽该作者的全部作品？');
    await safe('block', { block_author: alsoAuthor });
    toast('已屏蔽，后续不再出现');
  });

  $('btnOpenSource').addEventListener('click', () => {
    if (STATE && STATE.current) call('open_source', { url: STATE.current.page_url });
  });

  $('btnOpenConfig').addEventListener('click', () => call('open_config_file'));
  $('btnSaveSettings').addEventListener('click', saveSettings);
  $('btnClearBlocked').addEventListener('click', async () => {
    await safe('clear_blocked');
    toast('屏蔽列表已清空');
    await refreshState();
    loadConfig();
  });

  document.addEventListener('keydown', (e) => {
    if (currentView !== 'today') return;
    if (e.key === 'ArrowLeft') call('prev');
    if (e.key === 'ArrowRight') call('next');
    if (e.key === ' ' && e.target === document.body) { e.preventDefault(); call('refresh'); }
  });
}

async function refreshState() {
  const s = await safe('get_state');
  if (s) { STATE = s; render(); }
}

/* ------------------------------ 启动 ------------------------------ */
(async function boot() {
  bind();
  if (!hasBridge()) {
    $('heroEmpty').textContent = '请在菜单栏点击壁纸图标打开本窗口（直接用浏览器打开无法控制本地壁纸）。';
    $('heroEmpty').hidden = false;
    return;
  }
  await refreshState();
  await loadConfig();
  setInterval(refreshState, 60000);
})();
