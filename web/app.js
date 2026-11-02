/* 小伴 · PC 控制台 —— 前端（纯原生 ES6，零依赖）
 *
 * 两个要点：
 *  1. /api/chat 是 POST，EventSource 用不了。SSE 靠 fetch + ReadableStream 手工解帧。
 *  2. content 已经是增量，直接 append 到当前气泡，不再自己做打字机切片。
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'pc_token';
  var IS_MOCK = /[?&]mock=1(?:&|$)/.test(location.search);
  // 自测钩子：?mock=1&decide=approve|deny 会自动点一下确认卡片（走真实的按钮点击路径）
  var AUTO_DECIDE = (function () {
    var m = /[?&]decide=(approve|deny)/.exec(location.search);
    return m ? m[1] : '';
  })();

  /* ================================================================ 状态 */
  var S = {
    sessionId: null,
    streaming: false,
    abortCtrl: null,
    model: '',
    reasoning: 'none',
    provider: '',
    toolCount: 0,
    curThink: null,     // 当前轮的思考条
    curBubble: null,    // 当前正在追加的气泡
    rafId: 0,
    toolCards: {},      // call_id -> DOM
    panelTools: {},     // call_id -> DOM（右栏）
    sessions: [],
    config: null,
    mockCancel: false,
    mockTimers: [],
    mockDecisions: {},  // approval_id -> resolve
    evCount: 0
  };

  /* ================================================================ DOM */
  var $ = function (id) { return document.getElementById(id); };
  var dom = {
    stream: $('stream'),
    sessionList: $('session-list'),
    input: $('input'),
    btnSend: $('btn-send'),
    btnStop: $('btn-stop'),
    btnNew: $('btn-new'),
    btnSettings: $('btn-settings'),
    btnSettingsClose: $('btn-settings-close'),
    settings: $('settings'),
    mask: $('drawer-mask'),
    banner: $('banner'),
    bannerText: $('banner-text'),
    bannerRetry: $('banner-retry'),
    chipBrain: $('chip-brain'),
    chipTools: $('chip-tools'),
    panelTools: $('panel-tools'),
    eventLog: $('event-log'),
    cfgModel: $('cfg-model'),
    cfgToken: $('cfg-token'),
    segReasoning: $('seg-reasoning'),
    cfgProvider: $('cfg-provider'),
    cfgModelCur: $('cfg-model-cur'),
    cfgTools: $('cfg-tools'),
    cfgDb: $('cfg-db'),
    marketList: $('market-list'),
    btnMarketRefresh: $('btn-market-refresh'),
    ghStatus: $('gh-status'),
    ghHint: $('gh-hint'),
    ghSearch: $('gh-search'),
    ghResults: $('gh-results'),
    btnGhSearch: $('btn-gh-search'),
    pluginSpec: $('plugin-spec'),
    pluginList: $('plugin-list'),
    btnPluginInstall: $('btn-plugin-install'),
    kvProvider: $('kv-provider'),
    kvModel: $('kv-model'),
    kvTools: $('kv-tools'),
    kvDb: $('kv-db'),
    kvUptime: $('kv-uptime'),
    sideFoot: $('side-foot'),
    toast: $('toast'),
    btnPanel: $('btn-panel'),
    btnSidebar: $('btn-sidebar'),
    panel: $('panel'),
    sidebar: $('sidebar')
  };

  /* ================================================================ 小工具 */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function esc(v) { return v == null ? '' : String(v); }

  function trunc(s, n) {
    s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }

  var toastTimer = 0;
  function toast(msg) {
    dom.toast.textContent = msg;
    dom.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { dom.toast.hidden = true; }, 2400);
  }

  function showBanner(msg) {
    dom.bannerText.textContent = msg;
    dom.banner.hidden = false;
  }

  /* 网络层失败统一出口：HTTP 404 说明根本没接上 server，别报成「配置读取失败」 */
  function netFail(e) {
    var m = String((e && e.message) || e);
    if (/HTTP 404/.test(m)) {
      showBanner('后端连不上 —— 这个地址没有 /api/*，server 是不是没起？');
    } else {
      showBanner('后端连不上 —— ' + m);
    }
  }
  function hideBanner() { dom.banner.hidden = true; }

  function relTime(ms) {
    if (!ms) return '';
    var d = Date.now() - ms;
    if (d < 60000) return '刚刚';
    if (d < 3600000) return Math.floor(d / 60000) + ' 分钟前';
    if (d < 86400000) return Math.floor(d / 3600000) + ' 小时前';
    if (d < 7 * 86400000) return Math.floor(d / 86400000) + ' 天前';
    var t = new Date(ms);
    return (t.getMonth() + 1) + '/' + t.getDate();
  }

  function dur(ms) {
    if (ms == null) return '';
    if (ms < 1000) return ms + 'ms';
    return (ms / 1000).toFixed(1) + 's';
  }

  /* ================================================================ HTTP */
  function headers(extra) {
    var h = {};
    if (extra) for (var k in extra) h[k] = extra[k];
    var t = '';
    try { t = localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { t = ''; }
    if (t) h['X-PC-Token'] = t;
    return h;
  }

  function api(method, path, body) {
    var opt = { method: method, headers: headers() };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(function (r) {
      return r.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        if (!r.ok) {
          var m = (data && (data.error || data.message)) || ('HTTP ' + r.status);
          throw new Error(m);
        }
        return data;
      });
    });
  }

  /* ================================================================ 滚动 */
  function nearBottom() {
    var s = dom.stream;
    return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  }
  function scrollBottom(force) {
    var s = dom.stream;
    if (force || nearBottom()) s.scrollTop = s.scrollHeight;
  }

  /* ================================================================ 对话区渲染 */
  function clearStream() {
    dom.stream.innerHTML = '';
    S.curThink = null;
    S.curBubble = null;
    S.toolCards = {};
  }

  function showEmpty() {
    clearStream();
    var box = el('div', 'empty');
    box.appendChild(el('div', 'empty-title', '我在呢'));
    box.appendChild(el('div', 'empty-sub',
      IS_MOCK
        ? '这是 mock 模式，不连后端。下面会自动播一段假事件流；想试确认卡片就发一句带「删」的话。'
        : '说句话就行。要我动手的时候我自己会动手，不用特意吩咐。'));
    dom.stream.appendChild(box);
  }

  function ensureNoEmpty() {
    var e = dom.stream.querySelector('.empty');
    if (e) e.remove();
  }

  function userBubble(text) {
    ensureNoEmpty();
    var row = el('div', 'row user');
    var b = el('div', 'bubble', text);
    row.appendChild(b);
    dom.stream.appendChild(row);
    S.curThink = null;
    S.curBubble = null;
    scrollBottom(true);
    return b;
  }

  function botBubble() {
    ensureNoEmpty();
    var row = el('div', 'row bot');
    var b = el('div', 'bubble');
    row.appendChild(b);
    dom.stream.appendChild(row);
    S.curBubble = b;
    b._buf = '';
    scrollBottom(true);
    return b;
  }

  function flushBubble() {
    if (S.rafId) { cancelAnimationFrame(S.rafId); S.rafId = 0; }
    if (S.curBubble) {
      S.curBubble.textContent = S.curBubble._buf;
      scrollBottom(false);
    }
  }

  function appendContent(text) {
    if (!S.curBubble) botBubble();
    var b = S.curBubble;
    b._buf += text;
    if (!S.rafId) {
      S.rafId = requestAnimationFrame(function () {
        S.rafId = 0;
        b.textContent = b._buf;
        scrollBottom(false);
      });
    }
  }

  function thinkBar() {
    ensureNoEmpty();
    var d = el('details', 'think');
    var sum = el('summary', null, '思考中…');
    var body = el('div', 'think-body');
    d.appendChild(sum);
    d.appendChild(body);
    dom.stream.appendChild(d);
    S.curThink = { root: d, body: body, buf: '' };
    scrollBottom(true);
    return S.curThink;
  }

  function appendThinking(text) {
    var t = S.curThink || thinkBar();
    t.buf += text;
    t.body.textContent = t.buf;
    scrollBottom(false);
  }

  function argSummary(args) {
    if (!args || typeof args !== 'object') return '';
    var order = ['path', 'dir', 'file', 'query', 'url', 'text', 'content', 'name', 'cmd', 'command', 'key', 'app', 'device', 'action'];
    var v = '';
    for (var i = 0; i < order.length; i++) {
      var k = order[i];
      if (typeof args[k] === 'string' && args[k]) { v = args[k]; break; }
    }
    if (!v) {
      for (var k2 in args) {
        var av = args[k2];
        if (typeof av === 'string' && av) { v = av; break; }
        if (typeof av === 'number' || typeof av === 'boolean') { v = String(av); break; }
      }
    }
    return v ? trunc(v, 44) : '';
  }

  function argsText(args) {
    try { return JSON.stringify(args || {}, null, 2); } catch (e) { return String(args); }
  }

  /* 工具卡片：call_id 是唯一键，tool_result 靠它回填同一张卡 */
  function toolCard(callId, title, args, done, ok) {
    var card = el('div', 'tool');
    card.dataset.callId = callId || '';
    if (done) card.className = 'tool ' + (ok ? 'done-ok' : 'done-fail');
    else card.className = 'tool pending';

    var head = el('div', 'tool-head');
    head.appendChild(el('span', 'tool-ico', '🔧'));

    var nm = el('span', 'tool-name');
    nm.appendChild(el('b', null, title || '工具'));
    var a = argSummary(args);
    if (a) nm.appendChild(document.createTextNode(' ' + a));
    head.appendChild(nm);

    head.appendChild(el('span', 'tool-status', done ? (ok ? '✓' : '✗') : '…'));
    head.appendChild(el('span', 'tool-meta', ''));
    head.addEventListener('click', function () { card.classList.toggle('open'); });
    card.appendChild(head);

    var body = el('div', 'tool-body');
    var s1 = el('div', 'tool-sec', '参数');
    var p1 = el('pre', 'tool-pre', argsText(args));
    body.appendChild(s1);
    body.appendChild(p1);
    var s2 = el('div', 'tool-sec', '结果');
    var p2 = el('pre', 'tool-pre', done ? '' : '执行中…');
    body.appendChild(s2);
    body.appendChild(p2);
    card.appendChild(body);

    card._out = p2;
    ensureNoEmpty();
    dom.stream.appendChild(card);
    if (callId) S.toolCards[callId] = card;
    scrollBottom(true);
    return card;
  }

  function updateToolCard(p) {
    var card = p.call_id ? S.toolCards[p.call_id] : null;
    if (!card) card = toolCard(p.call_id, p.title || p.name, p.args || {}, false, false);
    card.classList.remove('pending');
    card.classList.add(p.ok ? 'done-ok' : 'done-fail');
    var st = card.querySelector('.tool-status');
    if (st) st.textContent = p.ok ? '✓' : '✗';
    var mt = card.querySelector('.tool-meta');
    if (mt) mt.textContent = p.ms != null ? dur(p.ms) : '';
    if (card._out) card._out.textContent = p.output != null ? String(p.output) : (p.ok ? '完成' : '失败');
    if (!p.ok) card.classList.add('open');
    scrollBottom(false);
  }

  /* 确认卡片：不阻塞流 */
  function approvalCard(p) {
    var box = el('div', 'approval');
    box.dataset.approvalId = p.approval_id || '';
    box.appendChild(el('div', 'approval-say', p.say || '这个要你点个头我才敢动。'));

    if (p.args && Object.keys(p.args).length) {
      box.appendChild(el('div', 'approval-args', argsText(p.args)));
    }

    var acts = el('div', 'approval-acts');
    var yes = el('button', 'btn sm primary', '嗯，删吧');
    var no = el('button', 'btn sm ghost', '算了');
    acts.appendChild(yes);
    acts.appendChild(no);
    box.appendChild(acts);

    var verdict = el('div', 'approval-verdict');
    verdict.hidden = true;
    box.appendChild(verdict);

    function settle(decision) {
      yes.disabled = true;
      no.disabled = true;
      box.classList.add('settled');
      verdict.hidden = false;
      if (decision === 'approve') {
        verdict.className = 'approval-verdict ok';
        verdict.textContent = '已同意';
      } else {
        verdict.className = 'approval-verdict no';
        verdict.textContent = '已拒绝';
      }
    }

    function decide(decision) {
      yes.disabled = true;
      no.disabled = true;
      submitApproval(p.approval_id, decision).then(function () {
        settle(decision);
      }).catch(function (e) {
        yes.disabled = false;
        no.disabled = false;
        showBanner('确认提交失败：' + e.message);
      });
    }

    yes.addEventListener('click', function () { decide('approve'); });
    no.addEventListener('click', function () { decide('deny'); });

    ensureNoEmpty();
    dom.stream.appendChild(box);
    S.curBubble = null;   // 后续 content 另起气泡
    scrollBottom(true);
    return box;
  }

  function submitApproval(id, decision) {
    if (IS_MOCK) {
      var r = S.mockDecisions[id];
      if (r) { delete S.mockDecisions[id]; r(decision); }
      return Promise.resolve({ ok: true, status: decision === 'approve' ? 'approved' : 'denied' });
    }
    return api('POST', '/api/approvals/' + encodeURIComponent(id), { decision: decision });
  }

  function errBar(msg) {
    ensureNoEmpty();
    var b = el('div', 'errbar', msg);
    dom.stream.appendChild(b);
    S.curBubble = null;
    scrollBottom(true);
  }

  function sysLine(text) {
    ensureNoEmpty();
    dom.stream.appendChild(el('div', 'sysline', text));
    scrollBottom(false);
  }

  /* ================================================================ 右栏 */
  function resetPanel() {
    dom.panelTools.innerHTML = '<div class="panel-empty">还没有调用</div>';
    S.panelTools = {};
  }

  function panelTool(p, isCall) {
    var id = p.call_id || ('x' + Math.random());
    var row = S.panelTools[id];
    if (!row) {
      if (dom.panelTools.querySelector('.panel-empty')) dom.panelTools.innerHTML = '';
      row = el('div', 'ptool run');
      row.dataset.callId = id;
      row.appendChild(el('span', 'pi', '…'));
      row.appendChild(el('span', 'pn', p.title || p.name || '工具'));
      row.appendChild(el('span', 'pm', ''));
      dom.panelTools.appendChild(row);
      S.panelTools[id] = row;
    }
    if (!isCall) {
      row.classList.remove('run');
      row.classList.add(p.ok ? 'ok' : 'fail');
      row.querySelector('.pi').textContent = p.ok ? '✓' : '✗';
      row.querySelector('.pm').textContent = p.ms != null ? dur(p.ms) : '';
    }
    dom.panelTools.scrollTop = dom.panelTools.scrollHeight;
  }

  function logEvent(kind, summary) {
    if (dom.eventLog.querySelector('.panel-empty')) dom.eventLog.innerHTML = '';
    var row = el('div', 'ev');
    row.appendChild(el('span', 'ev-k e-' + kind, kind));
    row.appendChild(el('span', 'ev-v', summary));
    dom.eventLog.appendChild(row);
    if (dom.eventLog.children.length > 240) dom.eventLog.removeChild(dom.eventLog.firstChild);
    dom.eventLog.scrollTop = dom.eventLog.scrollHeight;
    S.evCount++;
  }

  function updateStatus(h) {
    if (!h) return;
    S.provider = h.provider || '';
    S.toolCount = h.tools != null ? h.tools : (Array.isArray(h.tools) ? h.tools.length : S.toolCount);
    var model = h.model || S.model || '—';
    dom.chipBrain.textContent = '大脑 ' + (S.provider || '—');
    dom.chipBrain.classList.toggle('ok', !!h.ok);
    dom.chipBrain.classList.toggle('bad', !h.ok);
    dom.chipTools.textContent = '工具 ' + (typeof h.tools === 'number' ? h.tools : (h.tools == null ? '—' : h.tools));
    dom.kvProvider.textContent = S.provider || '—';
    dom.kvModel.textContent = model;
    dom.kvTools.textContent = typeof h.tools === 'number' ? (h.tools + ' 个') : '—';
    dom.kvDb.textContent = h.db == null ? '—' : String(h.db);
    dom.kvUptime.textContent = h.uptime_s != null ? fmtUptime(h.uptime_s) : '—';
    dom.cfgProvider.textContent = S.provider || '—';
    dom.cfgModelCur.textContent = model;
    dom.cfgTools.textContent = typeof h.tools === 'number' ? (h.tools + ' 个') : '—';
    dom.cfgDb.textContent = h.db == null ? '—' : String(h.db);
  }

  function fmtUptime(s) {
    s = Math.floor(s || 0);
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    if (h) return h + ' 小时 ' + m + ' 分';
    if (m) return m + ' 分 ' + (s % 60) + ' 秒';
    return s + ' 秒';
  }

  /* ================================================================ 会话列表 */
  function renderSessions(items) {
    S.sessions = items || [];
    dom.sessionList.innerHTML = '';
    if (!S.sessions.length) {
      dom.sessionList.appendChild(el('div', 'panel-empty', '还没有对话'));
      return;
    }
    S.sessions.forEach(function (s) {
      var row = el('div', 'session-item' + (s.id === S.sessionId ? ' active' : ''));
      row.dataset.sid = s.id;
      row.appendChild(el('span', 'st', s.title || '新对话'));
      row.appendChild(el('span', 'sm', relTime(s.updated_at)));
      var del = el('button', 'del', '×');
      del.title = '删除';
      del.addEventListener('click', function (ev) {
        ev.stopPropagation();
        deleteSession(s.id);
      });
      row.appendChild(del);
      row.addEventListener('click', function () { openSession(s.id); });
      dom.sessionList.appendChild(row);
    });
  }

  function loadSessions() {
    if (IS_MOCK) { renderSessions(MOCK_SESSIONS.slice()); return Promise.resolve(); }
    return api('GET', '/api/sessions?limit=30').then(function (d) {
      renderSessions((d && d.items) || []);
    }).catch(netFail);
  }

  function openSession(sid) {
    if (S.streaming) return;
    S.sessionId = sid;
    Array.prototype.forEach.call(dom.sessionList.children, function (n) {
      n.classList.toggle('active', n.dataset && n.dataset.sid === sid);
    });
    clearStream();
    var p = IS_MOCK ? Promise.resolve(MOCK_HISTORY) : api('GET', '/api/sessions/' + encodeURIComponent(sid) + '/messages?limit=100');
    p.then(function (d) {
      var items = (d && d.items) || [];
      if (!items.length) { showEmpty(); return; }
      items.forEach(renderHistoryMessage);
      scrollBottom(true);
    }).catch(function (e) {
      showBanner('会话读取失败：' + e.message);
    });
  }

  function renderHistoryMessage(m) {
    if (m.role === 'user') { userBubble(m.content || ''); return; }
    // assistant
    if (m.thinking) {
      var t = thinkBar();
      t.buf = m.thinking;
      t.body.textContent = m.thinking;
      t.root.querySelector('summary').textContent = '思考过（点开看）';
    }
    var tcs = m.tool_calls;
    if (tcs && !Array.isArray(tcs)) {
      try { tcs = typeof tcs === 'string' ? JSON.parse(tcs) : null; } catch (e) { tcs = null; }
    }
    (tcs || []).forEach(function (tc) {
      var name = tc.name || (tc.function && tc.function.name) || '工具';
      var args = tc.args || (tc.function && tc.function.arguments) || {};
      if (typeof args === 'string') { try { args = JSON.parse(args); } catch (e) { args = {}; } }
      var id = tc.id || tc.call_id || '';
      // 历史里的工具调用都已完成
      var card = toolCard(id, tc.title || name, args, true, true);
      var mt = card.querySelector('.tool-meta');
      if (mt) mt.textContent = '历史';
      if (card._out) card._out.textContent = '（历史记录，结果未单独保存）';
    });
    if (m.content) {
      var bb = botBubble();
      bb._buf = m.content;
      bb.textContent = m.content;
    }
  }

  function deleteSession(sid) {
    var go = function () {
      api('DELETE', '/api/sessions/' + encodeURIComponent(sid)).then(function () {
        if (S.sessionId === sid) newSession();
        loadSessions();
      }).catch(function (e) { showBanner('删除失败：' + e.message); });
    };
    if (IS_MOCK) {
      var i = MOCK_SESSIONS.findIndex(function (s) { return s.id === sid; });
      if (i >= 0) MOCK_SESSIONS.splice(i, 1);
      if (S.sessionId === sid) newSession();
      loadSessions();
      return;
    }
    go();
  }

  function newSession() {
    S.sessionId = null;
    S.curThink = null;
    S.curBubble = null;
    showEmpty();
    resetPanel();
    Array.prototype.forEach.call(dom.sessionList.children, function (n) {
      if (n.classList) n.classList.remove('active');
    });
    dom.input.focus();
  }

  /* ================================================================ 事件分发 */
  function handleEvent(kind, p) {
    p = p || {};
    switch (kind) {
      case 'session':
        S.sessionId = p.session_id || S.sessionId;
        logEvent('session', trunc(S.sessionId || '', 40));
        break;

      case 'thinking':
        appendThinking(p.text || '');
        logEvent('thinking', trunc(p.text, 60));
        break;

      case 'content':
        appendContent(p.text || '');
        logEvent('content', trunc(p.text, 60));
        break;

      case 'tool_call':
        flushBubble();
        S.curBubble = null;   // 卡片插在两段话之间，后面的 content 另起气泡
        toolCard(p.call_id, p.title || p.name, p.args || {}, false, false);
        panelTool(p, true);
        logEvent('tool_call', trunc((p.title || p.name || '') + ' ' + argSummary(p.args), 60));
        break;

      case 'tool_result':
        updateToolCard(p);
        panelTool(p, false);
        logEvent('tool_result', (p.ok ? 'ok ' : 'fail ') + dur(p.ms));
        break;

      case 'approval': {
        var card = approvalCard(p);
        logEvent('approval', trunc((p.name || '') + ' ' + argSummary(p.args), 60));
        if (AUTO_DECIDE) {
          setTimeout(function () {
            var sel = AUTO_DECIDE === 'approve' ? '.approval-acts .btn.primary' : '.approval-acts .btn.ghost';
            var b = card.querySelector(sel);
            if (b && !b.disabled) b.click();
          }, 600);
        }
        break;
      }

      case 'turn_end':
        flushBubble();
        S.curBubble = null;
        S.curThink = null;
        logEvent('turn_end', 'tools=' + (p.tool_count || 0) + ' ' + dur(p.latency_ms));
        if (p.tool_count || p.latency_ms) {
          var u = p.usage || {};
          sysLine('本轮 ' + (p.tool_count || 0) + ' 次工具 · ' + dur(p.latency_ms) +
            (u.in != null ? ' · in ' + u.in + ' / out ' + (u.out || 0) : ''));
        }
        endTurn();
        break;

      case 'error':
        flushBubble();
        errBar(p.message || '出错了');
        logEvent('error', trunc(p.message, 60));
        endTurn();
        break;

      default:
        logEvent(kind, trunc(JSON.stringify(p), 60));
    }
  }

  /* ================================================================ SSE 解析 */
  function parseFrame(frame) {
    if (!frame) return null;
    var lines = frame.split(/\r?\n/);
    var name = 'message';
    var data = [];
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      if (!ln || ln.charAt(0) === ':') continue;   // 心跳 ": ping"
      if (ln.indexOf('event:') === 0) name = ln.slice(6).trim();
      else if (ln.indexOf('data:') === 0) data.push(ln.slice(5).replace(/^ /, ''));
    }
    if (!data.length) return null;
    var raw = data.join('\n');
    var payload;
    try { payload = JSON.parse(raw); } catch (e) { payload = { message: raw }; }
    return { name: name, payload: payload };
  }

  function readSSE(res) {
    var reader = res.body.getReader();
    var dec = new TextDecoder('utf-8');
    var buf = '';

    function pump() {
      return reader.read().then(function (r) {
        if (r.done) {
          buf += dec.decode();
          var tail = parseFrame(buf.trim());
          if (tail) handleEvent(tail.name, tail.payload);
          return;
        }
        buf += dec.decode(r.value, { stream: true });
        var m;
        while ((m = /\r?\n\r?\n/.exec(buf))) {
          var frame = buf.slice(0, m.index);
          buf = buf.slice(m.index + m[0].length);
          var ev = parseFrame(frame);
          if (ev) handleEvent(ev.name, ev.payload);
        }
        return pump();
      });
    }
    return pump();
  }

  /* ================================================================ 发一轮 */
  function setStreaming(on) {
    S.streaming = on;
    dom.btnSend.disabled = on;
    dom.input.disabled = on;
    dom.btnStop.hidden = !on;
    if (!on) {
      dom.input.focus();
      loadSessions();
    }
  }

  function endTurn() {
    if (S.rafId) { cancelAnimationFrame(S.rafId); S.rafId = 0; }
    S.abortCtrl = null;
    setStreaming(false);
  }

  function send(text) {
    text = (text || '').trim();
    if (!text || S.streaming) return;
    hideBanner();
    userBubble(text);
    S.curThink = null;
    S.curBubble = null;
    S.toolCards = {};     // 每轮独立映射，避免不同轮复用 call_id 时互相改错卡
    resetPanel();
    dom.eventLog.innerHTML = '<div class="panel-empty">等待事件…</div>';
    dom.input.value = '';
    autosize();
    setStreaming(true);

    if (IS_MOCK) { runMockTurn(text); return; }
    runRealTurn(text);
  }

  function runRealTurn(text) {
    var body = { text: text };
    if (S.sessionId) body.session_id = S.sessionId;
    if (S.model) body.model = S.model;
    if (S.reasoning) body.reasoning = S.reasoning;

    var ctrl = new AbortController();
    S.abortCtrl = ctrl;

    fetch('/api/chat', {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json', 'Accept': 'text/event-stream' }),
      body: JSON.stringify(body),
      signal: ctrl.signal
    }).then(function (res) {
      if (!res.ok || !res.body) {
        return res.text().then(function (t) {
          var msg = 'HTTP ' + res.status;
          try {
            var j = JSON.parse(t);
            msg = j.error || j.message || msg;
          } catch (e) {
            // 非 JSON（比如静态服务器回的 HTML 错误页）：别把 HTML 糊到界面上
            msg = 'HTTP ' + res.status + '，返回的不是 SSE 流';
          }
          errBar('这句没发出去：' + msg);
          showBanner('后端没正常响应 /api/chat —— ' + msg);
          endTurn();
        });
      }
      hideBanner();
      return readSSE(res).then(function () {
        if (S.streaming) { flushBubble(); endTurn(); }
      });
    }).catch(function (e) {
      if (e && e.name === 'AbortError') {
        flushBubble();
        sysLine('已停止');
        endTurn();
        return;
      }
      showBanner('后端连不上 —— 检查 server 是否在跑（' + (e.message || e) + '）');
      errBar('后端连不上，这句没发出去。');
      endTurn();
    });
  }

  function stopTurn() {
    if (!S.streaming) return;
    if (IS_MOCK) {
      S.mockCancel = true;
      S.mockTimers.forEach(clearTimeout);
      S.mockTimers = [];
      Object.keys(S.mockDecisions).forEach(function (k) {
        var r = S.mockDecisions[k];
        delete S.mockDecisions[k];
        r('deny');
      });
      flushBubble();
      sysLine('已停止（mock）');
      endTurn();
      return;
    }
    var sid = S.sessionId;
    if (sid) {
      api('POST', '/api/abort/' + encodeURIComponent(sid)).catch(function () { /* 忽略 */ });
    }
    if (S.abortCtrl) S.abortCtrl.abort();
    else { flushBubble(); endTurn(); }
  }

  /* ================================================================ 输入框 */
  function autosize() {
    var t = dom.input;
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 180) + 'px';
  }

  /* ================================================================ 设置 */
  function openSettings() {
    dom.settings.classList.add('open');
    dom.settings.setAttribute('aria-hidden', 'false');
    dom.mask.hidden = false;
    if (!IS_MOCK) { renderPlugins(); renderMarket(); renderGhStatus(); }
  }
  function closeSettings() {
    dom.settings.classList.remove('open');
    dom.settings.setAttribute('aria-hidden', 'true');
    dom.mask.hidden = true;
  }

  function setReasoning(v) {
    S.reasoning = v || 'none';
    Array.prototype.forEach.call(dom.segReasoning.children, function (b) {
      b.classList.toggle('on', b.dataset.reasoning === S.reasoning);
    });
  }

  function applyConfig(cfg) {
    if (!cfg) return;
    // 契约第五节：顶层直接是脱敏配置。容错 server 包成 {ok, config:{...}} 的写法。
    if (cfg.config) cfg = cfg.config;
    S.config = cfg;
    var b = cfg.brain || {};
    S.model = b.model || S.model || '';
    S.provider = b.provider || S.provider || '';
    dom.cfgModel.value = S.model;
    dom.cfgModelCur.textContent = S.model || '—';
    dom.cfgProvider.textContent = S.provider || '—';
    setReasoning(b.reasoning || 'none');
  }

  function loadConfig() {
    if (IS_MOCK) { applyConfig(MOCK_CONFIG); return Promise.resolve(); }
    return api('GET', '/api/config').then(applyConfig).catch(netFail);
  }

  function saveConfig() {
    var model = (dom.cfgModel.value || '').trim();
    var tok = (dom.cfgToken.value || '').trim();
    try {
      if (tok) localStorage.setItem(TOKEN_KEY, tok);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* 忽略 */ }

    var done = function (cfg) {
      if (cfg && cfg.config) cfg = cfg.config;      // 同样兼容 {ok, config:{...}}
      applyConfig(cfg || { brain: { model: model, reasoning: S.reasoning } });
      if (model) S.model = model;
      toast('存好了');
      closeSettings();
      checkHealth();
    };

    if (IS_MOCK) { done({ brain: { provider: S.provider, model: model, reasoning: S.reasoning } }); return; }

    api('POST', '/api/config', { model: model, reasoning: S.reasoning })
      .then(done)
      .catch(function (e) { showBanner('保存失败：' + e.message); });
  }

  /* ================================================================ GitHub 插件口 */
  function renderPlugins() {
    var box = dom.pluginList;
    if (!box) return;
    box.innerHTML = '<div class="muted">读取中…</div>';
    api('GET', '/api/plugins').then(function (res) {
      var items = (res && res.items) || [];
      if (!items.length) { box.innerHTML = '<div class="muted">还没有安装任何插件</div>'; return; }
      box.innerHTML = '';
      items.forEach(function (it) {
        var row = el('div', 'plugin-item');
        row.appendChild(el('span', 'pi-name', it.name || it.id));
        var meta = [it.version || '', it.author || '', it.source || ''].filter(Boolean).join(' · ');
        row.appendChild(el('span', 'pi-meta', meta));
        var x = el('button', 'pi-x', '卸载');
        x.type = 'button';
        x.onclick = function () {
          if (!confirm('确定卸载插件 ' + (it.name || it.id) + ' 吗？')) return;
          api('POST', '/api/plugins/uninstall', { id: it.id })
            .then(function () { toast('已卸载'); renderPlugins(); checkHealth(); })
            .catch(function (e) { showBanner('卸载失败：' + e.message); });
        };
        row.appendChild(x);
        box.appendChild(row);
      });
    }).catch(function (e) { box.innerHTML = '<div class="muted">读取失败</div>'; showBanner('插件列表失败：' + e.message); });
  }

  function renderGhStatus() {
    if (!dom.ghStatus) return;
    api('GET', '/api/github/status').then(function (res) {
      var st = (res && res.status) || {};
      if (st.loggedIn) {
        dom.ghStatus.textContent = '已登录：' + (st.login || '?');
        dom.ghStatus.style.color = '#4ec9b0';
        if (dom.ghHint) dom.ghHint.textContent = '搜索和安装都走这个账户（私有仓库也能装）';
      } else {
        dom.ghStatus.textContent = '未登录';
        dom.ghStatus.style.color = '#e05555';
        if (dom.ghHint) dom.ghHint.textContent = (res && res.login && res.login.hint) || '在终端运行 gh auth login';
      }
    }).catch(function () {
      if (dom.ghStatus) dom.ghStatus.textContent = '读取失败';
    });
  }

  function renderGhResults(items) {
    var box = dom.ghResults;
    if (!box) return;
    if (!items || !items.length) {
      box.innerHTML = '<div class="muted">没搜到，换个关键词试试</div>';
      return;
    }
    box.innerHTML = '';
    items.forEach(function (r) {
      var row = el('div', 'plugin-item');
      var name = el('span', 'pi-name', r.fullName);
      name.style.cursor = 'pointer';
      name.title = r.description || '';
      row.appendChild(name);
      var meta = '⭐' + (r.stars || 0) + (r.language ? ' · ' + r.language : '') + (r.description ? ' · ' + r.description : '');
      row.appendChild(el('span', 'pi-meta', meta));
      var b = el('button', 'btn ghost', '安装');
      b.type = 'button';
      b.style.cssText = 'font-size:11px;padding:2px 8px;flex-shrink:0';
      b.onclick = function () {
        b.disabled = true; b.textContent = '安装中…';
        api('POST', '/api/github/install', { fullName: r.fullName })
          .then(function () { toast('已安装 ' + r.fullName); renderPlugins(); checkHealth(); })
          .catch(function (e) { showBanner('安装失败：' + e.message); })
          .then(function () { b.disabled = false; b.textContent = '安装'; });
      };
      row.appendChild(b);
      box.appendChild(row);
    });
  }

  function searchGithub() {
    var q = (dom.ghSearch && dom.ghSearch.value || '').trim();
    dom.ghResults.innerHTML = '<div class="muted">搜索中…</div>';
    api('GET', '/api/github/search?q=' + encodeURIComponent(q) + '&limit=20&pluginOnly=' + (q ? 'false' : 'true'))
      .then(function (res) {
        if (!res.ok) { dom.ghResults.innerHTML = '<div class="muted">搜索失败：' + (res.error || '') + '</div>'; return; }
        renderGhResults(res.items);
      })
      .catch(function (e) {
        dom.ghResults.innerHTML = '<div class="muted">搜索失败</div>';
        showBanner('GitHub 搜索失败：' + e.message);
      });
  }

  function renderMarket() {
    var box = dom.marketList;
    if (!box) return;
    box.innerHTML = '<div class="muted">加载中…</div>';
    api('GET', '/api/plugins/market').then(function (res) {
      var items = (res && res.plugins) || [];
      if (!items.length) { box.innerHTML = '<div class="muted">市场是空的</div>'; return; }
      box.innerHTML = '';
      items.forEach(function (p) {
        var row = el('div', 'plugin-item');
        row.appendChild(el('span', 'pi-name', p.name || p.id));
        row.appendChild(el('span', 'pi-meta', (p.author || '') + ' · ' + (p.description || '')));
        var b = el('button', 'btn ghost', '安装');
        b.type = 'button';
        b.style.cssText = 'font-size:11px;padding:2px 8px;flex-shrink:0';
        b.onclick = function () {
          var spec = p.tag ? (p.repo + '@' + p.tag) : p.repo;
          b.disabled = true; b.textContent = '安装中…';
          api('POST', '/api/plugins/install', { spec: spec })
            .then(function () { toast('已安装 ' + (p.name || p.id)); renderPlugins(); checkHealth(); })
            .catch(function (e) { showBanner('安装失败：' + e.message); })
            .then(function () { b.disabled = false; b.textContent = '安装'; });
        };
        row.appendChild(b);
        box.appendChild(row);
      });
    }).catch(function (e) {
      box.innerHTML = '<div class="muted">市场加载失败</div>';
      showBanner('市场加载失败：' + e.message);
    });
  }

  function installPlugin() {
    var spec = (dom.pluginSpec && dom.pluginSpec.value || '').trim();
    if (!spec) { toast('先填 owner/repo 或 GitHub 链接'); return; }
    var btn = dom.btnPluginInstall;
    btn.disabled = true; btn.textContent = '安装中…';
    api('POST', '/api/plugins/install', { spec: spec })
      .then(function (res) {
        toast('已安装：' + (res.item && (res.item.name || res.item.id)));
        if (dom.pluginSpec) dom.pluginSpec.value = '';
        renderPlugins();
        checkHealth();
      })
      .catch(function (e) { showBanner('安装失败：' + e.message); })
      .then(function () { btn.disabled = false; btn.textContent = '安装'; });
  }

  function checkHealth() {
    if (IS_MOCK) { updateStatus(MOCK_HEALTH); hideBanner(); return Promise.resolve(); }
    return api('GET', '/api/health').then(function (h) {
      if (h && h.data && typeof h.data === 'object') h = h.data;   // 容错 {ok, data:{...}}
      updateStatus(h);
      hideBanner();
    }).catch(function (e) {
      dom.chipBrain.textContent = '大脑 离线';
      dom.chipBrain.classList.remove('ok');
      dom.chipBrain.classList.add('bad');
      netFail(e);
    });
  }

  /* ================================================================ MOCK */
  var MOCK_SESSIONS = [
    { id: 's_mock0000000001', title: '看看 E:\\WH 里有什么', updated_at: Date.now() - 1000 * 60 * 12, msg_count: 4 },
    { id: 's_mock0000000002', title: '今天有点累', updated_at: Date.now() - 1000 * 60 * 60 * 5, msg_count: 2 }
  ];

  var MOCK_HISTORY = {
    items: [
      { id: 1, role: 'user', content: '看看 E:\\WH 里有什么', tool_calls: [], created_at: Date.now() - 720000 },
      {
        id: 2, role: 'assistant', content: '里面就四个文件，都是跑分记录',
        thinking: '先列一下目录再说话。',
        tool_calls: [{ id: 'c_hist_1', name: 'pc.list_dir', title: '列目录', args: { path: 'E:\\WH' } }],
        created_at: Date.now() - 718000
      },
      { id: 3, role: 'user', content: '好，先不管了', tool_calls: [], created_at: Date.now() - 700000 },
      { id: 4, role: 'assistant', content: '嗯，那我在这儿待着。', thinking: '', tool_calls: [], created_at: Date.now() - 699000 }
    ]
  };

  var MOCK_CONFIG = {
    brain: { provider: 'gateway', model: 'deepseek/deepseek-flash', reasoning: 'none' }
  };

  var MOCK_HEALTH = {
    ok: true, provider: 'gateway', model: 'deepseek/deepseek-flash',
    tools: 18, db: 'ok', uptime_s: 1287
  };

  function mSleep(ms) {
    return new Promise(function (res) {
      var t = setTimeout(res, ms);
      S.mockTimers.push(t);
    });
  }

  function mWaitDecision(id) {
    return new Promise(function (res) {
      S.mockDecisions[id] = res;
    });
  }

  function mockEmit(kind, payload) {
    if (S.mockCancel) return;
    handleEvent(kind, payload);
  }

  /* 序列 A：session → thinking → content → content → tool_call → tool_result → content → turn_end */
  function mockTurnPlain() {
    return mSleep(140).then(function () {
      mockEmit('session', { session_id: 's_mock0000000001' });
      return mSleep(160);
    }).then(function () {
      mockEmit('thinking', { text: '让我看看…' });
      return mSleep(220);
    }).then(function () {
      mockEmit('content', { text: '我看' });
      return mSleep(180);
    }).then(function () {
      mockEmit('content', { text: '了一下，' });
      return mSleep(260);
    }).then(function () {
      mockEmit('tool_call', {
        call_id: 'c_mock_1', name: 'pc.list_dir', title: '列目录',
        args: { path: 'E:\\WH' }
      });
      return mSleep(620);
    }).then(function () {
      mockEmit('tool_result', {
        call_id: 'c_mock_1', name: 'pc.list_dir', ok: true, ms: 412,
        output: 'E:\\WH 下 4 项：\n  run1.txt\n  run2.txt\n  run3.txt\n  run4.txt'
      });
      return mSleep(300);
    }).then(function () {
      mockEmit('content', { text: '里面就四个文件，都是跑分记录' });
      return mSleep(320);
    }).then(function () {
      mockEmit('turn_end', {
        message_id: 101, tool_count: 1, latency_ms: 2140, usage: { in: 1204, out: 63 }
      });
    });
  }

  /* 序列 B：带 approval，验证「流不停」 */
  function mockTurnApproval() {
    var cid = 'c_mock_del';
    var aid = 'a_mock0000000001';
    var path = 'E:\\WH\\pc-core\\workspace\\a.txt';
    return mSleep(120).then(function () {
      mockEmit('session', { session_id: 's_mock0000000001' });
      return mSleep(200);
    }).then(function () {
      mockEmit('thinking', { text: '要删文件，得先问一句。' });
      return mSleep(260);
    }).then(function () {
      mockEmit('tool_call', { call_id: cid, name: 'pc.delete', title: '删除', args: { path: path } });
      return mSleep(340);
    }).then(function () {
      mockEmit('approval', {
        approval_id: aid, call_id: cid, name: 'pc.delete', args: { path: path },
        say: '删之前问一句——' + path + '，真删啊？删了找不回来'
      });
      // 流在这里「挂着」，等用户决定；后端的 SSE 也会继续等，不是断流
      return mWaitDecision(aid);
    }).then(function (decision) {
      if (S.mockCancel) return null;
      if (decision === 'approve') {
        mockEmit('tool_result', { call_id: cid, name: 'pc.delete', ok: true, ms: 31, output: '已删除 ' + path });
        return mSleep(220).then(function () {
          mockEmit('content', { text: '删了。' });
          return mSleep(240);
        });
      }
      mockEmit('tool_result', { call_id: cid, name: 'pc.delete', ok: false, ms: 0, output: '用户没同意，没有动它' });
      return mSleep(220).then(function () {
        mockEmit('content', { text: '行，那我不动它' });
        return mSleep(240);
      });
    }).then(function () {
      if (S.mockCancel) return;
      mockEmit('turn_end', { message_id: 102, tool_count: 1, latency_ms: 1620, usage: { in: 880, out: 34 } });
    });
  }

  function runMockTurn(text) {
    S.mockCancel = false;
    S.mockTimers = [];
    var seq = /删|delete|移除/.test(text) ? mockTurnApproval() : mockTurnPlain();
    seq.catch(function (e) {
      if (S.mockCancel) return;
      errBar('mock 出错：' + (e && e.message));
      endTurn();
    });
  }

  function startMock() {
    dom.sideFoot.textContent = 'MOCK 模式 · 不连后端';
    loadSessions();
    loadConfig();
    checkHealth();
    showEmpty();
    // ?mock=1&auto=del 直接演一遍带确认的流程；?mock=1&auto=1 演普通流程
    var auto = /[?&]auto=([a-z]+)/.exec(location.search);
    var first = auto && auto[1] === 'del' ? '帮我删掉 workspace 里的 a.txt' : '看看 E:\\WH 里有什么';
    setTimeout(function () {
      if (S.streaming) return;
      userBubble(first);
      S.curThink = null; S.curBubble = null;
      resetPanel();
      dom.eventLog.innerHTML = '<div class="panel-empty">等待事件…</div>';
      setStreaming(true);
      runMockTurn(first);
    }, auto ? 200 : 500);
  }

  /* ================================================================ 绑定 */
  function bind() {
    dom.btnSend.addEventListener('click', function () { send(dom.input.value); });

    dom.input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        send(dom.input.value);
      }
    });
    dom.input.addEventListener('input', autosize);

    dom.btnStop.addEventListener('click', stopTurn);
    dom.btnNew.addEventListener('click', newSession);

    dom.btnSettings.addEventListener('click', function () {
      dom.cfgToken.value = (function () {
        try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
      })();
      openSettings();
    });
    dom.btnSettingsClose.addEventListener('click', closeSettings);
    dom.mask.addEventListener('click', closeSettings);

    Array.prototype.forEach.call(dom.segReasoning.children, function (b) {
      b.addEventListener('click', function () { setReasoning(b.dataset.reasoning); });
    });

    $('btn-save').addEventListener('click', saveConfig);
    if (dom.btnPluginInstall) dom.btnPluginInstall.addEventListener('click', installPlugin);
    if (dom.btnMarketRefresh) dom.btnMarketRefresh.addEventListener('click', renderMarket);
    if (dom.btnGhSearch) dom.btnGhSearch.addEventListener('click', searchGithub);
    if (dom.ghSearch) dom.ghSearch.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); searchGithub(); }
    });
    dom.bannerRetry.addEventListener('click', function () {
      hideBanner();
      checkHealth();
      loadSessions();
    });

    dom.btnPanel.addEventListener('click', function () { dom.panel.classList.toggle('open'); });
    dom.btnSidebar.addEventListener('click', function () { dom.sidebar.classList.toggle('open'); });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeSettings();
        dom.panel.classList.remove('open');
        dom.sidebar.classList.remove('open');
      }
    });
  }

  /* ================================================================ 启动 */
  function boot() {
    bind();
    autosize();

    if (IS_MOCK) { startMock(); return; }

    showEmpty();
    checkHealth();
    loadConfig();
    loadSessions().then(function () {
      // 后端在跑但没有会话时，保持空白页
      if (S.sessions.length && !S.sessionId) {
        // 不自动进入历史会话，让用户自己点
      }
    });
  }

  // 自测用句柄
  window.__PC = {
    state: S,
    handleEvent: handleEvent,
    send: send,
    parseFrame: parseFrame,
    isMock: IS_MOCK,
    newSession: newSession,
    openSession: openSession
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
