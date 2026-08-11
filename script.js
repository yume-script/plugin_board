// plugins/metadata/plugin_board/script.js
(function () {
  const PLUGIN_ID = "plugin_board";
  const LOG_PREFIX = "[Plugin-Board]";

  const statusEl = document.getElementById("pb-status");
  const gridEl = document.getElementById("pb-grid");
  const filtersEl = document.getElementById("pb-filters");
  const tallyEl = document.getElementById("pb-tally");
  const installedStatusEl = document.getElementById("pb-installed-status");
  const installedGridEl = document.getElementById("pb-installed-grid");

  let allItems = [];
  let activeFilter = "all";

  function getDbType() {
    const params = new URLSearchParams(window.location.search);
    return params.get("db_type") || "general";
  }

  function dataUrl() {
    // plugin_manager 등 기존 플러그인들과 동일하게 쿼리 파라미터명은 "type"을 사용
    return `/api/media/dashboard/widgets/${PLUGIN_ID}/data?type=${encodeURIComponent(getDbType())}`;
  }

  // GitHub 아이콘(SVG) — 정적 마크업이므로 innerHTML 사용은 안전함
  const GITHUB_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>';

  // 다운로드/설치 아이콘(SVG)
  const INSTALL_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0a.75.75 0 0 1 .75.75v7.19l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 1 1 1.06-1.06l2.22 2.22V.75A.75.75 0 0 1 8 0Z"/><path d="M1.5 10.5a.75.75 0 0 1 .75.75v2A.75.75 0 0 0 3 14h10a.75.75 0 0 0 .75-.75v-2a.75.75 0 0 1 1.5 0v2A2.25 2.25 0 0 1 13 15.5H3A2.25 2.25 0 0 1 .75 13.25v-2a.75.75 0 0 1 .75-.75Z"/></svg>';

  // ------------------------------------------------------------------
  // plugin_manager 연동 (https://github.com/madnite1/plugin_manager)
  // 실제 설치/업데이트는 이 시스템 플러그인의 apply-metadata 액션을 통해
  // 서버에서 처리된다 — plugin_board 자신은 파일 시스템에 쓰지 않는다.
  // ------------------------------------------------------------------
  const PLUGIN_MANAGER_ID = "plugin_manager";

  function pluginManagerListUrl(dbType) {
    return `/api/media/dashboard/widgets/${PLUGIN_MANAGER_ID}/data?type=${encodeURIComponent(dbType)}`;
  }

  async function fetchInstalledPlugins(dbType) {
    const res = await fetch(pluginManagerListUrl(dbType));
    const json = await res.json();
    if (!res.ok || !json || json.success === false) {
      throw new Error((json && json.error) || `HTTP ${res.status}`);
    }
    return Array.isArray(json.plugins) ? json.plugins : [];
  }

  async function callPluginManagerAction(dbType, actionData) {
    const res = await fetch("/api/media/books/0/apply-metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: dbType,
        source: PLUGIN_MANAGER_ID,
        item_data: actionData,
      }),
    });
    return res.json();
  }

  // ------------------------------------------------------------------
  // 토스트 알림 (카드 하단 액션 결과 안내용)
  // ------------------------------------------------------------------
  let toastTimer = null;
  function showToast(message, isError) {
    let toast = document.getElementById("pb-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "pb-toast";
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = "pb-toast " + (isError ? "pb-toast-error" : "pb-toast-success");
    toast.classList.add("pb-toast-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.remove("pb-toast-show");
    }, 4500);
  }

  // 설치/업데이트 버튼: 클릭 시점에 plugin_manager 설치 목록을 조회해
  // 이미 설치돼 있으면 update, 아니면 install_git 액션을 호출한다.
  function buildInstallButton(item) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pb-install-btn";
    btn.innerHTML = `${INSTALL_ICON}설치/업데이트`;

    btn.addEventListener("click", async () => {
      const originalHtml = btn.innerHTML;
      const dbType = getDbType();
      btn.disabled = true;
      btn.innerHTML = `${INSTALL_ICON}확인 중…`;

      try {
        const installed = await fetchInstalledPlugins(dbType);
        const match = installed.find((p) => p.id === item.id);

        let actionData;
        if (match && !match.has_update) {
          btn.disabled = false;
          btn.innerHTML = originalHtml;
          showToast(`'${item.title}'은(는) 이미 최신 버전(v${match.version})입니다.`, false);
          return;
        } else if (match) {
          actionData = { action: "update", plugin_id: item.id };
          btn.innerHTML = `${INSTALL_ICON}업데이트 중…`;
        } else {
          actionData = { action: "install_git", git_url: item.url };
          btn.innerHTML = `${INSTALL_ICON}설치 중…`;
        }

        const result = await callPluginManagerAction(dbType, actionData);
        btn.disabled = false;
        btn.innerHTML = originalHtml;

        if (result && result.success) {
          showToast(result.message || `'${item.title}' 처리가 완료되었습니다.`, false);
          loadInstalledPlugins();
        } else {
          showToast((result && result.error) || "요청이 실패했습니다.", true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 설치/업데이트 실패:`, err);
        btn.disabled = false;
        btn.innerHTML = originalHtml;
        showToast(
          "plugin_manager(https://github.com/madnite1/plugin_manager)가 설치되어 있어야 이 버튼을 사용할 수 있습니다.",
          true
        );
      }
    });

    return btn;
  }

  // ------------------------------------------------------------------
  // "서버에 설치된 플러그인" 섹션 — plugin_manager가 파악한 실제 설치 현황을
  // 그대로 보여준다. 위쪽 GITHUB_REPOS 큐레이션 목록과 무관하게, 이 서버에
  // 설치된 모든 메타데이터 플러그인(plugin_board·plugin_manager 자신 포함)이
  // 나열된다.
  // ------------------------------------------------------------------
  function typeBadges(p) {
    const badges = [];
    if (p.is_system) badges.push("시스템");
    if (p.is_searchable) badges.push("검색형");
    if (p.is_category) badges.push("카테고리 탭");
    if (p.is_widget) badges.push("위젯");
    if (p.has_config) badges.push("설정 있음");
    return badges;
  }

  function buildInstalledRow(p, dbType) {
    const row = document.createElement("article");
    row.className = "pb-irow" + (p.enabled ? "" : " pb-irow-disabled");

    const main = document.createElement("div");
    main.className = "pb-irow-main";

    const dot = document.createElement("span");
    dot.className = "pb-irow-dot" + (p.enabled ? " pb-irow-dot-on" : "");
    dot.title = p.enabled ? "활성화됨" : "비활성화됨";

    const nameWrap = document.createElement("div");
    const name = document.createElement("p");
    name.className = "pb-irow-name";
    name.textContent = p.name || p.id;
    const id = document.createElement("p");
    id.className = "pb-irow-id";
    id.textContent = p.id;
    nameWrap.append(name, id);

    main.append(dot, nameWrap);

    const badgesWrap = document.createElement("div");
    badgesWrap.className = "pb-irow-badges";
    typeBadges(p).forEach((label) => {
      const b = document.createElement("span");
      b.className = "pb-tag";
      b.textContent = label;
      badgesWrap.appendChild(b);
    });

    const versionWrap = document.createElement("div");
    versionWrap.className = "pb-irow-version";
    const vStamp = document.createElement("span");
    vStamp.className = "pb-stamp";
    vStamp.textContent = "v" + (p.version || "?");
    versionWrap.appendChild(vStamp);
    if (p.has_update) {
      const upd = document.createElement("span");
      upd.className = "pb-tag pb-tag-update";
      upd.textContent = `업데이트 가능 (v${p.latest_version || "?"})`;
      versionWrap.appendChild(upd);
    }

    const actions = document.createElement("div");
    actions.className = "pb-irow-actions";

    if (p.has_update) {
      const updBtn = document.createElement("button");
      updBtn.type = "button";
      updBtn.className = "pb-install-btn pb-install-btn-sm";
      updBtn.innerHTML = `${INSTALL_ICON}업데이트`;
      updBtn.addEventListener("click", async () => {
        const orig = updBtn.innerHTML;
        updBtn.disabled = true;
        updBtn.innerHTML = `${INSTALL_ICON}업데이트 중…`;
        try {
          const result = await callPluginManagerAction(dbType, {
            action: "update",
            plugin_id: p.id,
          });
          if (result && result.success) {
            showToast(result.message || `'${p.id}' 업데이트 완료`, false);
            loadInstalledPlugins();
          } else {
            showToast((result && result.error) || "업데이트 실패", true);
          }
        } catch (err) {
          showToast("업데이트 요청 중 통신 오류가 발생했습니다.", true);
        } finally {
          updBtn.disabled = false;
          updBtn.innerHTML = orig;
        }
      });
      actions.appendChild(updBtn);
    }

    if (!p.is_system) {
      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      toggleBtn.className = "pb-toggle-btn";
      toggleBtn.textContent = p.enabled ? "비활성화" : "활성화";
      toggleBtn.addEventListener("click", async () => {
        const orig = toggleBtn.textContent;
        toggleBtn.disabled = true;
        toggleBtn.textContent = "처리 중…";
        try {
          const result = await callPluginManagerAction(dbType, {
            action: "toggle",
            plugin_id: p.id,
            enabled: p.enabled ? "0" : "1",
          });
          if (result && result.success) {
            showToast(result.message || `'${p.id}' 상태가 변경되었습니다.`, false);
            loadInstalledPlugins();
          } else {
            showToast((result && result.error) || "상태 변경 실패", true);
            toggleBtn.disabled = false;
            toggleBtn.textContent = orig;
          }
        } catch (err) {
          showToast("상태 변경 요청 중 통신 오류가 발생했습니다.", true);
          toggleBtn.disabled = false;
          toggleBtn.textContent = orig;
        }
      });
      actions.appendChild(toggleBtn);
    }

    row.append(main, badgesWrap, versionWrap, actions);
    return row;
  }

  async function loadInstalledPlugins() {
    const dbType = getDbType();
    try {
      const plugins = await fetchInstalledPlugins(dbType);
      plugins.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id, "ko"));

      installedGridEl.innerHTML = "";
      plugins.forEach((p) => installedGridEl.appendChild(buildInstalledRow(p, dbType)));

      installedStatusEl.hidden = true;
      installedGridEl.hidden = false;
      console.log(`${LOG_PREFIX} 설치된 플러그인 ${plugins.length}개 확인`);
    } catch (err) {
      console.warn(`${LOG_PREFIX} plugin_manager 목록 조회 실패:`, err);
      installedStatusEl.textContent =
        "plugin_manager가 설치되어 있지 않아 설치 현황을 표시할 수 없습니다.";
      installedStatusEl.classList.add("pb-error");
      installedStatusEl.hidden = false;
      installedGridEl.hidden = true;
    }
  }

  function buildCard(item) {
    const card = document.createElement("article");
    card.className = "pb-card" + (item.error ? " pb-card-error" : "");
    card.dataset.type = item.type || "other";

    const head = document.createElement("div");
    head.className = "pb-card-head";

    const owner = document.createElement("p");
    owner.className = "pb-card-owner";
    owner.textContent = `${item.owner || ""} / ${item.id || ""}`;

    const title = document.createElement("h2");
    title.className = "pb-card-title";
    title.textContent = item.title || "";

    head.append(owner, title);

    const desc = document.createElement("p");
    desc.className = "pb-card-desc";
    desc.textContent = item.desc || "";

    const tagsWrap = document.createElement("div");
    tagsWrap.className = "pb-card-tags";

    // 분류 태그(검색형/탭형/기타)를 항상 첫 태그로 표시
    const typeTag = document.createElement("span");
    typeTag.className = "pb-tag pb-tag-type";
    typeTag.textContent = item.type_label || "기타";
    tagsWrap.appendChild(typeTag);

    (item.tags || []).forEach((tagText) => {
      const tag = document.createElement("span");
      tag.className = "pb-tag";
      tag.textContent = tagText; // textContent로만 삽입 (XSS 방지)
      tagsWrap.appendChild(tag);
    });

    const feats = document.createElement("ul");
    feats.className = "pb-card-feats";
    (item.features || []).forEach((featText) => {
      const li = document.createElement("li");
      li.textContent = featText;
      feats.appendChild(li);
    });

    const foot = document.createElement("div");
    foot.className = "pb-card-foot";

    const stamp = document.createElement("span");
    stamp.className = "pb-stamp";
    stamp.textContent = item.version_label || "—";

    const btnGroup = document.createElement("div");
    btnGroup.className = "pb-btn-group";

    const installBtn = buildInstallButton(item);

    const link = document.createElement("a");
    link.className = "pb-link";
    link.href = item.url || "#";
    link.target = "_blank";
    link.rel = "noopener";
    link.innerHTML = `${GITHUB_ICON}GitHub`;

    btnGroup.append(installBtn, link);
    foot.append(stamp, btnGroup);

    const parts = [head, desc, tagsWrap];
    if ((item.features || []).length > 0) parts.push(feats);
    parts.push(foot);
    card.append(...parts);
    return card;
  }

  function render() {
    gridEl.innerHTML = "";
    const items = allItems.filter(
      (it) => activeFilter === "all" || it.type === activeFilter
    );
    if (items.length === 0) {
      const empty = document.createElement("p");
      empty.className = "pb-status";
      empty.textContent = "해당 분류의 플러그인이 없습니다.";
      gridEl.appendChild(empty);
      return;
    }
    items.forEach((item) => gridEl.appendChild(buildCard(item)));
  }

  // 실제 데이터에 존재하는 type만으로 필터 버튼과 집계를 동적으로 구성한다.
  // 새 저장소를 TYPE_OVERRIDES 없이 추가해도 "기타" 필터가 자동으로 나타난다.
  function buildFiltersAndTally() {
    const counts = {};
    allItems.forEach((it) => {
      const t = it.type || "other";
      counts[t] = (counts[t] || 0) + 1;
    });
    const types = Object.keys(counts).sort();

    // 집계
    tallyEl.innerHTML = "";
    const totalBlock = document.createElement("div");
    const totalStrong = document.createElement("strong");
    totalStrong.textContent = String(allItems.length);
    const totalSpan = document.createElement("span");
    totalSpan.textContent = "등록 플러그인";
    totalBlock.append(totalStrong, totalSpan);
    tallyEl.appendChild(totalBlock);

    types.forEach((t) => {
      const item = allItems.find((it) => it.type === t);
      const block = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = String(counts[t]);
      const span = document.createElement("span");
      span.textContent = (item && item.type_label) || t;
      block.append(strong, span);
      tallyEl.appendChild(block);
    });

    // 필터 버튼
    filtersEl.innerHTML = "";
    const makeBtn = (filter, label, active) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pb-filter-btn" + (active ? " active" : "");
      btn.dataset.filter = filter;
      btn.textContent = label;
      btn.addEventListener("click", () => {
        filtersEl
          .querySelectorAll(".pb-filter-btn")
          .forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeFilter = filter;
        render();
      });
      return btn;
    };

    filtersEl.appendChild(makeBtn("all", "전체", true));
    types.forEach((t) => {
      const item = allItems.find((it) => it.type === t);
      filtersEl.appendChild(makeBtn(t, (item && item.type_label) || t, false));
    });
  }

  async function load() {
    console.log(`${LOG_PREFIX} 데이터 요청: ${dataUrl()}`);
    try {
      const res = await fetch(dataUrl());
      const json = await res.json();
      console.log(`${LOG_PREFIX} 응답 수신, status=${res.status}`);

      if (!res.ok || !json || json.success === false) {
        throw new Error((json && json.error) || `HTTP ${res.status}`);
      }

      allItems = Array.isArray(json.items) ? json.items : [];
      statusEl.hidden = true;
      gridEl.hidden = false;
      buildFiltersAndTally();
      render();

      const errorCount = allItems.filter((it) => it.error).length;
      console.log(
        `${LOG_PREFIX} 카드 ${allItems.length}개 렌더링 완료` +
          (errorCount ? ` (GitHub 조회 실패 ${errorCount}건)` : "")
      );
    } catch (err) {
      console.error(`${LOG_PREFIX} 로드 실패:`, err);
      statusEl.textContent = "플러그인 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.";
      statusEl.classList.add("pb-error");
      statusEl.hidden = false;
      gridEl.hidden = true;
    }
  }

  load();
  loadInstalledPlugins();
})();
