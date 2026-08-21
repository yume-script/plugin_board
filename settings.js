/* 플러그인 허브 — 설정 페이지: 세션 레인(칩 드래그 순서/세션 이동) + 카드형 3단 선택 UI
   코어 계약: new Function('window','pluginId','root','config', js)(...)
   저장은 코어 폼 submit이 root 내부 input/select[name]을 수집하므로:
   - 세션별 모드 select name: MODE_<plugin_id>__<session>, 값은 ''(기본) / 'merge'(허브에 합치기) / 'hide'(완전히 숨기기)
   - 세션별 순서 hidden input name: TAB_ORDER_<session> (콤마 구분 id 목록, merge인 것만)
   카드에서 'merge' 선택 → 레인에 칩 추가, 그 외로 바뀌거나 칩 x 클릭 → 칩 제거(select 값 연동).
   칩 드래그: 같은 레인 = 순서 변경, 다른 레인 = 세션 이동(select 값 연동, 대상 세션을 merge로).
   플러그인이 지원하지 않는 세션 레인으로는 이동 불가. */
(function () {
  'use strict';

  const SESSION_LABELS = { general: '일반', adult: '성인', audiobook: '오디오', video: '비디오' };
  const SESSIONS = Object.keys(SESSION_LABELS);
  const MODE_MERGE = 'merge';
  const MODE_HIDE = 'hide';
  const MODE_NORMAL = '';
  const grid = root.querySelector('[data-pv-role="grid"]');
  const lanesEl = root.querySelector('[data-pv-role="lanes"]');
  const excludedInput = root.querySelector('[data-pv-role="excluded-input"]');
  const selectAllBtn = root.querySelector('[data-pv-role="select-all"]');
  const deselectAllBtn = root.querySelector('[data-pv-role="deselect-all"]');
  if (!grid || !lanesEl) return;

  let catalogById = {};
  const orderInputs = {};

  function esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function ensureOrderInputs() {
    SESSIONS.forEach((s) => {
      const name = `TAB_ORDER_${s}`;
      let input = root.querySelector(`input[name="${name}"]`);
      if (!input) {
        input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        lanesEl.appendChild(input);
      }
      orderInputs[s] = input;
    });
  }

  function laneBody(session) {
    return lanesEl.querySelector(`[data-pv-lane="${session}"]`);
  }

  function chipSession(chip) {
    const body = chip.closest('[data-pv-lane]');
    return body ? body.getAttribute('data-pv-lane') : null;
  }

  function supports(pluginId, session) {
    const p = catalogById[pluginId];
    return !!(p && Array.isArray(p.sessions) && p.sessions.includes(session));
  }

  function syncOrder(session) {
    const body = laneBody(session);
    if (!body) return;
    const ids = Array.from(body.querySelectorAll('.pv-chip')).map((el) => el.getAttribute('data-pv-id'));
    orderInputs[session].value = ids.join(',');
    body.classList.toggle('pv-lane-empty', !ids.length);
  }

  function syncAllOrders() {
    SESSIONS.forEach(syncOrder);
  }

  function findSelect(pluginId, session) {
    return grid.querySelector(`select[data-pv-plugin="${CSS.escape(pluginId)}"][data-pv-session="${CSS.escape(session)}"]`);
  }

  function setMode(pluginId, session, mode) {
    const sel = findSelect(pluginId, session);
    if (sel) sel.value = mode;
  }

  function getMode(pluginId, session) {
    const sel = findSelect(pluginId, session);
    return sel ? sel.value : MODE_NORMAL;
  }

  /* ---------- 칩 (merge 상태인 것만 레인에 존재) ---------- */

  let dragChip = null;
  let dragFromSession = null;

  function clearDropHints() {
    lanesEl.querySelectorAll('.pv-lane-body').forEach((el) =>
      el.classList.remove('pv-drop-ok', 'pv-drop-deny'));
  }

  // 세션 이동 확정: 출발/도착 select 값 연동 + 순서 재계산
  function finishMove(pluginId, fromSession, toSession) {
    if (fromSession !== toSession) {
      setMode(pluginId, fromSession, MODE_NORMAL);
      setMode(pluginId, toSession, MODE_MERGE);
    }
    syncAllOrders();
  }

  function makeChip(pluginId) {
    const p = catalogById[pluginId] || { name: pluginId };
    const chip = document.createElement('span');
    chip.className = 'pv-chip';
    chip.setAttribute('data-pv-id', pluginId);
    chip.setAttribute('draggable', 'true');
    chip.innerHTML = `<span class="pv-chip-name">${esc(p.name)}</span><button type="button" class="pv-chip-x" title="기본으로">&times;</button>`;

    chip.querySelector('.pv-chip-x').addEventListener('click', (e) => {
      e.preventDefault();
      const s = chipSession(chip);
      if (s) setMode(pluginId, s, MODE_NORMAL);
      chip.remove();
      if (s) syncOrder(s);
    });

    chip.addEventListener('dragstart', (e) => {
      dragChip = chip;
      dragFromSession = chipSession(chip);
      chip.classList.add('pv-dragging');
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', pluginId); } catch (_) {}
    });
    chip.addEventListener('dragend', () => {
      chip.classList.remove('pv-dragging');
      clearDropHints();
      if (dragChip) {
        // 드롭 이벤트가 안 온 경우에도 DOM 상 현재 위치 기준으로 확정
        const toSession = chipSession(chip);
        if (toSession && dragFromSession) finishMove(pluginId, dragFromSession, toSession);
      }
      dragChip = null;
      dragFromSession = null;
    });
    // 다른 칩 위로 드래그: 지원 세션이면 그 위치로 삽입(레인 이동 포함)
    chip.addEventListener('dragover', (e) => {
      if (!dragChip || dragChip === chip) return;
      const targetSession = chipSession(chip);
      const dragId = dragChip.getAttribute('data-pv-id');
      if (!targetSession || !supports(dragId, targetSession)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const chips = Array.from(chip.parentElement.querySelectorAll('.pv-chip'));
      if (chips.includes(dragChip) && chips.indexOf(dragChip) < chips.indexOf(chip)) chip.after(dragChip);
      else chip.before(dragChip);
    });
    return chip;
  }

  function addChip(pluginId, session) {
    const body = laneBody(session);
    if (!body || body.querySelector(`.pv-chip[data-pv-id="${CSS.escape(pluginId)}"]`)) return;
    body.appendChild(makeChip(pluginId));
    syncOrder(session);
  }

  function removeChip(pluginId, session) {
    const body = laneBody(session);
    if (!body) return;
    const chip = body.querySelector(`.pv-chip[data-pv-id="${CSS.escape(pluginId)}"]`);
    if (chip) chip.remove();
    syncOrder(session);
  }

  /* ---------- 렌더 ---------- */

  function renderLanes(catalog, orders) {
    lanesEl.querySelectorAll('.pv-lane').forEach((el) => el.remove());
    SESSIONS.forEach((s) => {
      const lane = document.createElement('div');
      lane.className = 'pv-lane';
      lane.innerHTML = `<div class="pv-lane-title">${esc(SESSION_LABELS[s])}</div><div class="pv-lane-body pv-lane-empty" data-pv-lane="${esc(s)}"></div>`;
      const body = lane.querySelector('.pv-lane-body');
      // 레인 빈 공간으로 드래그: 지원 세션이면 맨 뒤에 추가(레인 이동 포함)
      body.addEventListener('dragover', (e) => {
        if (!dragChip) return;
        const dragId = dragChip.getAttribute('data-pv-id');
        clearDropHints();
        if (!supports(dragId, s)) {
          body.classList.add('pv-drop-deny');
          return;
        }
        body.classList.add('pv-drop-ok');
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        if (dragChip.parentElement !== body && !e.target.closest('.pv-chip')) {
          body.appendChild(dragChip);
        }
      });
      body.addEventListener('dragleave', () => body.classList.remove('pv-drop-ok', 'pv-drop-deny'));
      body.addEventListener('drop', (e) => {
        e.preventDefault();
        clearDropHints();
      });
      lanesEl.appendChild(lane);
    });

    // 'merge'로 선택된 플러그인을 저장된 순서 → 나머지 이름순으로 레인에 채움
    // 레인(탭 순서 시각화)에는 "실제로 지금 탭에 뜨는" 것만 넣는다 — 정지된 플러그인은
    // 모드는 유지되지만(재활성화 시 자동 복원용) 지금 탭으로 뜨지 않으므로 레인에선 제외.
    SESSIONS.forEach((s) => {
      const mergedIds = catalog
        .filter((p) => p.enabled !== false && p.modes && p.modes[s] === MODE_MERGE)
        .map((p) => p.id);
      const order = Array.isArray(orders && orders[s]) ? orders[s] : [];
      const sorted = order.filter((id) => mergedIds.includes(id))
        .concat(mergedIds.filter((id) => !order.includes(id)));
      sorted.forEach((id) => addChip(id, s));
      syncOrder(s);
    });
  }

  function renderCards(catalog) {
    if (!catalog.length) {
      grid.innerHTML = '<div class="pv-settings-empty">표시할 카테고리 뷰 플러그인이 설치되어 있지 않습니다.</div>';
      return;
    }
    grid.innerHTML = catalog.map((p) => {
      const version = p.version ? `v${esc(p.version)}` : '';
      const isEnabled = p.enabled !== false;
      const selects = (p.sessions || []).map((s) => {
        const key = `MODE_${p.id}__${s}`;
        const cur = (p.modes && p.modes[s]) || MODE_NORMAL;
        // 정지된 플러그인도 name/값은 그대로 둔다 — save-config가 config 전체를
        // 덮어쓰는 방식이라, 여기서 값을 지우거나 disabled로 빼면 저장 시 원래 선택이
        // 영구 소실된다. 대신 상호작용만 JS/CSS로 막아서(readOnly 흉내) 값은 항상 보존되게 한다.
        const opt = (val, label) => `<option value="${val}" ${cur === val ? 'selected' : ''}>${label}</option>`;
        return `
          <label class="pv-session-mode${isEnabled ? '' : ' pv-session-mode-locked'}">
            <span class="pv-session-mode-label">${esc(SESSION_LABELS[s] || s)}</span>
            <select name="${esc(key)}" data-pv-plugin="${esc(p.id)}" data-pv-session="${esc(s)}" data-pv-locked="${isEnabled ? '0' : '1'}" tabindex="${isEnabled ? '0' : '-1'}">
              ${opt('', '기본')}
              ${opt(MODE_MERGE, '허브에 합치기')}
              ${opt(MODE_HIDE, '완전히 숨기기')}
            </select>
          </label>`;
      }).join('');
      return `
        <div class="pv-card${isEnabled ? '' : ' pv-card-disabled'}">
          <div class="pv-card-head">
            <h5 class="pv-card-title">${esc(p.name)}</h5>
            ${version ? `<span class="pv-card-version">${version}</span>` : ''}
          </div>
          <div class="pv-card-id">${esc(p.id)}${isEnabled ? '' : ' · <span class="pv-card-badge">정지됨</span>'}</div>
          <div class="pv-card-sessions">${selects}</div>
        </div>`;
    }).join('');

    grid.querySelectorAll('select[data-pv-plugin]').forEach((sel) => {
      // 잠긴(정지된 플러그인) select는 상호작용 자체를 막아 값이 항상 유지되게 한다.
      sel.addEventListener('mousedown', (e) => {
        if (sel.getAttribute('data-pv-locked') === '1') e.preventDefault();
      });
      sel.addEventListener('keydown', (e) => {
        if (sel.getAttribute('data-pv-locked') === '1') e.preventDefault();
      });
      sel.addEventListener('change', () => {
        if (sel.getAttribute('data-pv-locked') === '1') return;
        const pid = sel.getAttribute('data-pv-plugin');
        const s = sel.getAttribute('data-pv-session');
        if (sel.value === MODE_MERGE) addChip(pid, s);
        else removeChip(pid, s);
      });
    });
  }

  // 일괄 합치기/기본으로: 잠긴(정지된 플러그인) select와 '완전히 숨기기'로 명시적으로
  // 지정된 것은 건드리지 않는다 — 둘 다 의도적으로 보존해야 하는 값이라서.
  function bulkSetMode(targetMode) {
    grid.querySelectorAll('select[data-pv-plugin]').forEach((sel) => {
      if (sel.getAttribute('data-pv-locked') === '1') return;
      if (sel.value === MODE_HIDE) return;
      if (sel.value === targetMode) return;
      sel.value = targetMode;
      const pid = sel.getAttribute('data-pv-plugin');
      const s = sel.getAttribute('data-pv-session');
      if (targetMode === MODE_MERGE) addChip(pid, s);
      else removeChip(pid, s);
    });
  }

  if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
      if (window.confirm('현재 목록에 보이는 모든(잠기지 않고, "완전히 숨기기"가 아닌) 플러그인을 전부 "허브에 합치기"로 바꿉니다. 계속할까요?')) {
        bulkSetMode(MODE_MERGE);
      }
    });
  }
  if (deselectAllBtn) {
    deselectAllBtn.addEventListener('click', () => {
      if (window.confirm('현재 "허브에 합치기"로 되어 있는 항목들을 전부 "기본"으로 되돌립니다. 저장을 누르면 반영됩니다. 계속할까요?')) {
        bulkSetMode(MODE_NORMAL);
      }
    });
  }

  function refreshOnlyViewerTabs() {
    try {
      window.dispatchEvent(new CustomEvent('plugin_hub:config_updated'));
      if (typeof window.reloadPluginHubTabs === 'function') {
        window.reloadPluginHubTabs();
      }
    } catch (_) {}
  }

  function wrapSaveConfigApi() {
    try {
      if (!window.__origFetchForPluginHub) {
        window.__origFetchForPluginHub = window.fetch;
        window.fetch = async function (resource, options) {
          const response = await window.__origFetchForPluginHub.apply(this, arguments);
          try {
            const url = typeof resource === 'string' ? resource : (resource && resource.url ? resource.url : '');
            if (url && url.includes('/api/media/metadata/plugins/save-config') && options && options.method === 'POST') {
              const cloned = response.clone();
              cloned.json().then((data) => {
                if (data && data.success) {
                  refreshOnlyViewerTabs();
                }
              }).catch(() => {});
            }
          } catch (_) {}
          return response;
        };
      }
    } catch (_) {}
  }

  async function load() {
    wrapSaveConfigApi();
    try {
      const res = await fetch(`/api/media/dashboard/widgets/${encodeURIComponent(pluginId)}/data?type=general`, {
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '조회 실패');
      const catalog = Array.isArray(data.catalog) ? data.catalog : [];
      catalogById = {};
      catalog.forEach((p) => { catalogById[p.id] = p; });
      ensureOrderInputs();
      renderCards(catalog);
      renderLanes(catalog, data.orders || {});
      if (excludedInput && typeof data.excluded_ids === 'string') {
        excludedInput.value = data.excluded_ids;
      }
    } catch (err) {
      console.error('[PluginHub-Settings] load error:', err);
      grid.innerHTML = `<div class="pv-settings-error">플러그인 목록을 불러오지 못했습니다: ${esc(err.message || '오류')}</div>`;
    }
  }

  load();
})();
