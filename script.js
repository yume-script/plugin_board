// plugins/metadata/plugin_board/script.js
(function () {
  const PLUGIN_ID = "plugin_board";
  const LOG_PREFIX = "[Plugin-Board]";

  const statusEl = document.getElementById("pb-status");
  const gridEl = document.getElementById("pb-grid");
  const filtersEl = document.getElementById("pb-filters");
  const tallyEl = document.getElementById("pb-tally");

  let allItems = [];
  let activeFilter = "all";

  function getDbType() {
    const params = new URLSearchParams(window.location.search);
    return params.get("db_type") || "general";
  }

  function dataUrl() {
    return `/api/media/dashboard/widgets/${PLUGIN_ID}/data?type=${encodeURIComponent(getDbType())}`;
  }

  // GitHub 아이콘(SVG) — 정적 마크업이므로 innerHTML 사용은 안전함
  const GITHUB_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>';

  // 설치 아이콘(다운로드), 업데이트 아이콘(리프레시), 완료 아이콘(체크) — 전부 자체 SVG
  const INSTALL_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0a.75.75 0 0 1 .75.75v7.19l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 1 1 1.06-1.06l2.22 2.22V.75A.75.75 0 0 1 8 0Z"/><path d="M1.5 10.5a.75.75 0 0 1 .75.75v2A.75.75 0 0 0 3 14h10a.75.75 0 0 0 .75-.75v-2a.75.75 0 0 1 1.5 0v2A2.25 2.25 0 0 1 13 15.5H3A2.25 2.25 0 0 1 .75 13.25v-2a.75.75 0 0 1 .75-.75Z"/></svg>';
  const UPDATE_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 2.5a5.5 5.5 0 1 0 5.163 3.606.75.75 0 1 1 1.408-.512A7 7 0 1 1 8 1v-.75a.25.25 0 0 1 .429-.176l2.5 2.5a.25.25 0 0 1 0 .354l-2.5 2.5A.25.25 0 0 1 8 5.25V3.5a.5.5 0 0 0-.5-.5H8Z"/></svg>';
  const CHECK_ICON =
    '<svg viewBox="0 0 16 16"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-6.5 6.5a.75.75 0 0 1-1.06 0l-3-3a.75.75 0 1 1 1.06-1.06L6.75 10.19l5.97-5.97a.75.75 0 0 1 1.06 0Z"/></svg>';

  // ------------------------------------------------------------------
  // 신규설치/업데이트 액션 — plugin_manager 등 외부 플러그인 없이
  // plugin_board 자신의 apply()를 호출한다 (source: "plugin_board").
  // ------------------------------------------------------------------
  async function callPluginBoardAction(dbType, actionData) {
    const res = await fetch("/api/media/books/0/apply-metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: dbType,
        source: PLUGIN_ID,
        item_data: actionData,
      }),
    });
    return res.json();
  }

  // ------------------------------------------------------------------
  // 토스트 알림
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

  // item.installed / item.has_update 값(백엔드가 plugins/metadata 디렉토리를 직접
  // 확인해 계산)에 따라 "신규설치" / "업데이트" 버튼 또는 "설치됨" 배지를 만든다.
  function buildActionControl(item) {
    if (item.installed && !item.has_update) {
      const badge = document.createElement("span");
      badge.className = "pb-installed-badge";
      badge.innerHTML = `${CHECK_ICON}설치됨${item.installed_version ? " · v" + item.installed_version : ""}`;
      return badge;
    }

    const isUpdate = !!item.installed;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pb-install-btn" + (isUpdate ? " pb-install-btn-update" : "");
    btn.innerHTML = isUpdate
      ? `${UPDATE_ICON}업데이트`
      : `${INSTALL_ICON}신규설치`;

    btn.addEventListener("click", async () => {
      const originalHtml = btn.innerHTML;
      const dbType = getDbType();
      btn.disabled = true;
      btn.innerHTML = isUpdate
        ? `${UPDATE_ICON}업데이트 중…`
        : `${INSTALL_ICON}설치 중…`;

      try {
        const result = await callPluginBoardAction(dbType, {
          action: isUpdate ? "update" : "install_git",
          plugin_id: item.id,
          git_url: item.url,
        });

        if (result && result.success) {
          showToast(result.message || `'${item.title}' 처리가 완료되었습니다.`, false);
          load(); // 설치 상태가 바뀌었으므로 전체 카드 새로고침
        } else {
          showToast((result && result.error) || "요청이 실패했습니다.", true);
          btn.disabled = false;
          btn.innerHTML = originalHtml;
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 설치/업데이트 통신 오류:`, err);
        showToast("설치/업데이트 요청 중 통신 오류가 발생했습니다.", true);
        btn.disabled = false;
        btn.innerHTML = originalHtml;
      }
    });

    return btn;
  }

  function buildCard(item) {
    const card = document.createElement("article");
    card.className = "pb-card" + (item.error ? " pb-card-error" : "");
    card.dataset.type = item.type || "other";

    const head = document.createElement("div");
    head.className = "pb-card-head";

    const owner = document.createElement("p");
    owner.className = "pb-card-owner";
    owner.textContent = item.owner ? `${item.owner} / ${item.id}` : (item.id || "");

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

    if (item.has_update) {
      const updTag = document.createElement("span");
      updTag.className = "pb-tag pb-tag-update";
      updTag.textContent = "업데이트 가능";
      tagsWrap.appendChild(updTag);
    }

    if (item.local_only) {
      const localTag = document.createElement("span");
      localTag.className = "pb-tag pb-tag-local";
      localTag.textContent = "GitHub 미등록";
      tagsWrap.appendChild(localTag);
    }

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
    btnGroup.appendChild(buildActionControl(item));

    // GitHub 저장소 주소를 모르는(local_only) 항목은 GitHub 버튼을 표시하지 않음
    if (item.url) {
      const link = document.createElement("a");
      link.className = "pb-link";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.innerHTML = `${GITHUB_ICON}GitHub`;
      btnGroup.appendChild(link);
    }

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
  function buildFiltersAndTally() {
    const counts = {};
    allItems.forEach((it) => {
      const t = it.type || "other";
      counts[t] = (counts[t] || 0) + 1;
    });
    const types = Object.keys(counts).sort();
    const installedCount = allItems.filter((it) => it.installed).length;

    // 집계
    tallyEl.innerHTML = "";
    const addTally = (value, label) => {
      const block = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = String(value);
      const span = document.createElement("span");
      span.textContent = label;
      block.append(strong, span);
      tallyEl.appendChild(block);
    };
    addTally(allItems.length, "등록 플러그인");
    addTally(installedCount, "이 서버에 설치됨");
    types.forEach((t) => {
      const item = allItems.find((it) => it.type === t);
      addTally(counts[t], (item && item.type_label) || t);
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
})();
