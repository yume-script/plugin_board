// plugins/metadata/plugin_board/script.js
(function () {
  const PLUGIN_ID = "plugin_board";
  const LOG_PREFIX = "[Plugin-Board]";

  const statusEl = document.getElementById("pb-status");
  const gridEl = document.getElementById("pb-grid");
  const filtersEl = document.getElementById("pb-filters");
  const tallyTotalEl = document.getElementById("pb-tally-total");
  const tallySearchEl = document.getElementById("pb-tally-search");
  const tallyTabEl = document.getElementById("pb-tally-tab");

  let allItems = [];
  let activeFilter = "all";

  function getDbType() {
    const params = new URLSearchParams(window.location.search);
    return params.get("db_type") || "general";
  }

  function dataUrl() {
    return `/api/media/dashboard/widgets/${PLUGIN_ID}/data?db_type=${encodeURIComponent(getDbType())}`;
  }

  // GitHub 아이콘(SVG) — 정적 마크업이므로 innerHTML 사용은 안전함
  const GITHUB_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>';

  function buildCard(item) {
    const card = document.createElement("article");
    card.className = "pb-card";
    card.dataset.type = item.type || "";

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
    stamp.textContent = item.version_label || "";

    const link = document.createElement("a");
    link.className = "pb-link";
    link.href = item.url || "#";
    link.target = "_blank";
    link.rel = "noopener";
    link.innerHTML = `${GITHUB_ICON}GitHub`;

    foot.append(stamp, link);
    card.append(head, desc, tagsWrap, feats, foot);
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

  function updateTally() {
    const total = allItems.length;
    const searchCount = allItems.filter((it) => it.type === "search").length;
    const tabCount = allItems.filter((it) => it.type === "tab").length;
    tallyTotalEl.textContent = String(total);
    tallySearchEl.textContent = String(searchCount);
    tallyTabEl.textContent = String(tabCount);
  }

  function bindFilters() {
    filtersEl.querySelectorAll(".pb-filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        filtersEl
          .querySelectorAll(".pb-filter-btn")
          .forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeFilter = btn.dataset.filter;
        render();
      });
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
      updateTally();
      bindFilters();
      render();
      console.log(`${LOG_PREFIX} 카드 ${allItems.length}개 렌더링 완료`);
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
