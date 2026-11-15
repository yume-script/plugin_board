// plugins/metadata/plugin_board/script.js
(function () {
  // 화면 언어: BookOasis에서 고른 언어(window.i18n.currentLang, 없으면 저장된 bookoasis_lang)가 영어면 영어 문구.
  // T(한국어, 영어) - 두 문구를 나란히 적어 둔다 (BookOasis 코어 번역 파일에는 플러그인 문구를 넣을 수 없어서)
  const PB_LANG = (() => {
    try {
      const l = (window.i18n && window.i18n.currentLang) || localStorage.getItem("bookoasis_lang") || "ko";
      return String(l).toLowerCase().startsWith("en") ? "en" : "ko";
    } catch (e) { return "ko"; }
  })();
  function T(ko, en) { return PB_LANG === "en" ? en : ko; }
  // index.html의 고정 문구: data-en(글자) / data-en-html(정적 HTML, 이 파일에 적힌 것만) / data-en-title / data-en-placeholder
  (function applyStaticLang() {
    if (PB_LANG !== "en") return;
    const root = document.querySelector(".pb-root") || document;
    root.querySelectorAll("[data-en]").forEach((el) => { el.textContent = el.getAttribute("data-en"); });
    root.querySelectorAll("[data-en-html]").forEach((el) => { el.innerHTML = el.getAttribute("data-en-html"); });
    root.querySelectorAll("[data-en-title]").forEach((el) => { el.title = el.getAttribute("data-en-title"); });
    root.querySelectorAll("[data-en-placeholder]").forEach((el) => { el.placeholder = el.getAttribute("data-en-placeholder"); });
  })();

  const PLUGIN_ID = "plugin_board";
  const LOG_PREFIX = "[Plugin-Board]";

  const statusEl = document.getElementById("pb-status");
  const gridEl = document.getElementById("pb-grid");
  const filtersEl = document.getElementById("pb-filters");
  const tallyEl = document.getElementById("pb-tally");
  const ownerFilterWrapEl = document.getElementById("pb-owner-filter-wrap");

  let allItems = [];
  let isAdmin = false;
  let autoUpdateEnabledGlobal = false; // [PATCH-10] 체크박스 툴팁 안내용 // 서버 응답을 받기 전 기본값(fail-closed) — 응답에서 갱신됨
  let activeFilter = "all";
  let activeOwner = "all"; // 제작자별 필터 — activeFilter(분류/설치여부)와 별개 축, AND로 결합
  let catalogTopic = ""; // 서버 응답의 catalog_topic — 비어있으면 "카탈로그" 탭을 숨긴다

  // ------------------------------------------------------------------
  // 설치/업데이트가 끝난 뒤 Ctrl+F5(강력 새로고침)와 동등한 효과를 낸다.
  // 새로 설치된 플러그인의 사이드바 항목·JS/CSS가 실제로 동작하려면
  // 단순 location.reload()로는 부족한 경우가 있어(브라우저가 캐시된
  // 리소스를 그대로 쓸 수 있음), 캐시 스토리지를 정리하고 URL에
  // 캐시 무효화용 쿼리 파라미터를 붙여 완전히 새로운 요청으로 페이지
  // 전체를 다시 불러온다.
  // ------------------------------------------------------------------
  function hardReloadPage() {
    const doReload = () => {
      const url = new URL(window.location.href);
      url.searchParams.set("_pb_reload", Date.now().toString());
      window.location.replace(url.toString());
    };

    try {
      if (window.caches && typeof caches.keys === "function") {
        caches
          .keys()
          .then((names) => Promise.all(names.map((name) => caches.delete(name))))
          .catch(() => {})
          .finally(doReload);
        return;
      }
    } catch (err) {
      // 무시 — 캐시 정리 실패해도 새로고침 자체는 진행한다
    }
    doReload();
  }

  function reloadAfterInstall(message) {
    showToast((message || T("설치가 완료되었습니다.", "Installation complete.")) + T(" 잠시 후 페이지를 새로고침합니다…", " The page will refresh shortly…"), false);
    setTimeout(hardReloadPage, 1200); // 토스트 메시지를 읽을 시간을 준 뒤 새로고침
  }

  // 코어는 플러그인 켜짐 상태(PLUGIN_ENABLED_*)와 설정(PLUGIN_CONFIG_*)을 늘 'general' DB에서 읽는다.
  // 플러그인게시판은 성인·오디오북·영상 강좌 사이드바에서도 열리므로(category_tab.sessions='all'),
  // 어느 서재에서 열든 읽기·저장·켜고 끄기는 모두 'general'로 한다 (다른 DB에 쓰면 코어가 보지 않는다).
  function getDbType() {
    return "general";
  }

  function dataUrl() {
    return `/api/media/dashboard/widgets/${PLUGIN_ID}/data?type=${encodeURIComponent(getDbType())}`;
  }

  // GitHub 아이콘(SVG) — 정적 마크업이므로 innerHTML 사용은 안전함
  const GITHUB_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>';

  // Gitea(자체 호스팅) 저장소 표시용 — 특정 브랜드 로고 대신 범용 git-branch
  // 아이콘(Lucide, ISC 라이선스)을 사용한다.
  const GITEA_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/></svg>';

  // 별(star) 아이콘 — GitHub 다운로드 횟수는 API로 못 구해서, 공개로 제공되는
  // 별 개수를 참고용 인기도 지표로 대신 보여줄 때 쓴다.
  const STAR_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"/></svg>';

  function formatStars(n) {
    if (typeof n !== "number") return String(n);
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k";
    return String(n);
  }

  // GitHub/Gitea의 pushed_at·updated_at(ISO 8601) 또는 로컬 폴더 mtime 문자열을
  // "YYYY-MM-DD"로 표시한다. 파싱 실패 시(형식이 다르거나 아예 없으면) null을
  // 반환해 호출부가 아무것도 표시하지 않도록 한다.
  function formatPushedAt(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  // 설치 아이콘(다운로드), 업데이트 아이콘(리프레시), 완료 아이콘(체크) — 전부 자체 SVG
  const INSTALL_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 0a.75.75 0 0 1 .75.75v7.19l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 1 1 1.06-1.06l2.22 2.22V.75A.75.75 0 0 1 8 0Z"/><path d="M1.5 10.5a.75.75 0 0 1 .75.75v2A.75.75 0 0 0 3 14h10a.75.75 0 0 0 .75-.75v-2a.75.75 0 0 1 1.5 0v2A2.25 2.25 0 0 1 13 15.5H3A2.25 2.25 0 0 1 .75 13.25v-2a.75.75 0 0 1 .75-.75Z"/></svg>';
  const UPDATE_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 2.5a5.5 5.5 0 1 0 5.163 3.606.75.75 0 1 1 1.408-.512A7 7 0 1 1 8 1v-.75a.25.25 0 0 1 .429-.176l2.5 2.5a.25.25 0 0 1 0 .354l-2.5 2.5A.25.25 0 0 1 8 5.25V3.5a.5.5 0 0 0-.5-.5H8Z"/></svg>';
  const CHECK_ICON =
    '<svg viewBox="0 0 16 16"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-6.5 6.5a.75.75 0 0 1-1.06 0l-3-3a.75.75 0 1 1 1.06-1.06L6.75 10.19l5.97-5.97a.75.75 0 0 1 1.06 0Z"/></svg>';
  const GEAR_ICON =
    '<svg viewBox="0 0 16 16"><path d="M9.405 1.05c-.413-1.4-2.397-1.4-2.81 0l-.1.34a1.464 1.464 0 0 1-2.105.872l-.31-.17c-1.283-.698-2.686.705-1.987 1.987l.169.311c.446.82.023 1.841-.872 2.105l-.34.1c-1.4.413-1.4 2.397 0 2.81l.34.1a1.464 1.464 0 0 1 .872 2.105l-.17.31c-.698 1.283.705 2.686 1.987 1.987l.311-.169a1.464 1.464 0 0 1 2.105.872l.1.34c.413 1.4 2.397 1.4 2.81 0l.1-.34a1.464 1.464 0 0 1 2.105-.872l.31.17c1.283.698 2.686-.705 1.987-1.987l-.169-.311a1.464 1.464 0 0 1 .872-2.105l.34-.1c1.4-.413 1.4-2.397 0-2.81l-.34-.1a1.464 1.464 0 0 1-.872-2.105l.17-.31c.698-1.283-.705-2.686-1.987-1.987l-.311.169a1.464 1.464 0 0 1-2.105-.872l-.1-.34zM8 10.93a2.929 2.929 0 1 1 0-5.858 2.929 2.929 0 0 1 0 5.858z"/></svg>';
  const TRASH_ICON =
    '<svg viewBox="0 0 16 16"><path d="M6.5 1a1 1 0 0 0-1 1v.5H3a.75.75 0 0 0 0 1.5h.35l.6 9.03A1.75 1.75 0 0 0 5.7 14.75h4.6a1.75 1.75 0 0 0 1.75-1.72l.6-9.03H13a.75.75 0 0 0 0-1.5h-2.5V2a1 1 0 0 0-1-1h-3Zm.5 3.5a.75.75 0 0 1 .75.75v5.5a.75.75 0 0 1-1.5 0v-5.5A.75.75 0 0 1 7 4.5Zm2.75.75a.75.75 0 0 0-1.5 0v5.5a.75.75 0 0 0 1.5 0v-5.5Z"/></svg>';
  const EYE_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 3C4.5 3 1.73 5.11.5 8c1.23 2.89 4 5 7.5 5s6.27-2.11 7.5-5C14.27 5.11 11.5 3 8 3Zm0 8.5A3.5 3.5 0 1 1 8 4.5a3.5 3.5 0 0 1 0 7Zm0-5.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z"/></svg>';
  const EYE_OFF_ICON =
    '<svg viewBox="0 0 16 16"><path d="M13.36 2.22 2.22 13.36l.7.7L4.6 12.4A8.26 8.26 0 0 0 8 13c3.5 0 6.27-2.11 7.5-5a9.4 9.4 0 0 0-2.66-3.54l1.82-1.82-.7-.7ZM8 11.5a3.48 3.48 0 0 1-1.87-.55l1.02-1.02a2 2 0 0 0 2.36-2.36l1.02-1.02c.34.53.55 1.16.55 1.83a3.5 3.5 0 0 1-3.5 3.5.5.5 0 0 1-.5 0Zm-6-3.5c1.1-2.09 3.19-3.7 5.7-3.98L6.3 5.42A3.5 3.5 0 0 0 4.42 7.3L2.9 8.83A9.4 9.4 0 0 1 2 8Z"/></svg>';
  // "Git 주소 변경" 버튼용 연필 아이콘 — user_registered(직접 설치 이력) 카드에서
  // 저장소 이름/owner/호스트가 바뀐 경우 재설치 없이 추적 주소만 갱신할 때 사용.
  const EDIT_ICON =
    '<svg viewBox="0 0 16 16"><path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168l10-10ZM11.207 2.5 13.5 4.793l1.293-1.293L12.5 1.207 11.207 2.5Zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293l6.5-6.5ZM3.032 10.68l-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.32Z"/></svg>';
  // "등록 해제" 버튼용 아이콘 — 원본 저장소가 삭제되는 등으로 더 이상 추적할
  // 수 없을 때, 설치된 파일은 그대로 두고 github.txt 등록만 제거할 때 사용.
  const UNLINK_ICON =
    '<svg viewBox="0 0 16 16"><path d="M8 15A7 7 0 1 0 8 1a7 7 0 0 0 0 14Zm0 1A8 8 0 1 1 8 0a8 8 0 0 1 0 16Z"/><path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708Z"/></svg>';

  // lucide "history" — 이력 버튼
  const HISTORY_ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>';

  // 카드 종류별 아이콘 — 직접 그리지 않고 Lucide 아이콘(ISC 라이선스, 자유 재사용
  // 가능)의 실제 path를 그대로 사용한다. 필채우기가 아니라 선(stroke) 기반이라
  // 다른 아이콘들과 속성이 다르다.
  const LUCIDE_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  const TYPE_ICON_SEARCH = // lucide "search"
    `<svg ${LUCIDE_ATTRS}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`;
  const TYPE_ICON_TAB = // lucide "layout-grid"
    `<svg ${LUCIDE_ATTRS}><rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/></svg>`;
  const TYPE_ICON_WIDGET = // lucide "layout-dashboard"
    `<svg ${LUCIDE_ATTRS}><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>`;
  const TYPE_ICON_OTHER = // lucide "puzzle"
    `<svg ${LUCIDE_ATTRS}><path d="M19.439 7.85c-.049.322.059.648.289.878l1.568 1.568c.47.47.706 1.087.706 1.704s-.235 1.233-.706 1.704l-1.611 1.611a.98.98 0 0 1-.837.276c-.47-.07-.802-.48-.968-.925a2.501 2.501 0 1 0-3.214 3.214c.446.166.855.497.925.968a.979.979 0 0 1-.276.837l-1.61 1.61a2.404 2.404 0 0 1-1.705.707 2.402 2.402 0 0 1-1.704-.706l-1.568-1.568a1.026 1.026 0 0 0-.877-.29c-.493.074-.84.504-1.02.968a2.5 2.5 0 1 1-3.237-3.237c.464-.18.894-.527.967-1.02a1.026 1.026 0 0 0-.289-.877l-1.568-1.568A2.402 2.402 0 0 1 1.998 12c0-.617.236-1.234.706-1.704L4.315 8.685a.97.97 0 0 1 .837-.276c.47.07.802.48.968.925a2.501 2.501 0 1 0 3.214-3.214c-.446-.166-.855-.497-.925-.968a.979.979 0 0 1 .276-.837l1.61-1.61A2.402 2.402 0 0 1 12 1.998c.617 0 1.234.236 1.704.706l1.568 1.568c.23.23.556.338.877.29.493-.074.84-.504 1.02-.968a2.5 2.5 0 1 1 3.237 3.237c-.464.18-.894.527-.967 1.02Z"/></svg>`;

  function buildCardIcon(item) {
    const badge = document.createElement("div");
    let markup = TYPE_ICON_OTHER;
    let modifier = "pb-card-icon-other";
    if (item.type === "search") {
      markup = TYPE_ICON_SEARCH;
      modifier = "pb-card-icon-search";
    } else if (item.type === "tab") {
      markup = TYPE_ICON_TAB;
      modifier = "pb-card-icon-tab";
    } else if (item.type === "home" || item.type === "desk" || item.type === "widget") {
      markup = TYPE_ICON_WIDGET;
      modifier = "pb-card-icon-widget";
    }
    badge.className = "pb-card-icon " + modifier;
    badge.innerHTML = markup;
    return badge;
  }

  // ------------------------------------------------------------------
  // 신규설치/업데이트/활성화·비활성화/삭제 액션.
  // [PATCH-4] API 문서가 범용 플러그인 RPC로 인정한 컨텍스트 메뉴 액션 경로
  // (plugin_id + action_id + context → run_context_menu_action)를 쓴다. 이 경로가
  // 없는 구버전 코어(404/405)에서만 예전 apply-metadata 우회 호출로 폴백한다.
  // ------------------------------------------------------------------
  const RPC_URL = "/api/media/context-menu/book/plugins/action";
  const LEGACY_RPC_URL = "/api/media/books/0/apply-metadata";
  let useLegacyRpc = false;

  function rpcRequest(dbType, actionData, signal) {
    if (useLegacyRpc) {
      return fetch(LEGACY_RPC_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: dbType, source: PLUGIN_ID, item_data: actionData }),
        signal,
      });
    }
    const { action, ...context } = actionData;
    return fetch(RPC_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: dbType, plugin_id: PLUGIN_ID, action_id: action, context }),
      signal,
    });
  }

  async function callPluginBoardAction(dbType, actionData, timeoutMs = 60000) {
    let res;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      res = await rpcRequest(dbType, actionData, controller.signal);
      if (!useLegacyRpc && (res.status === 404 || res.status === 405)) {
        console.warn(`${LOG_PREFIX} 컨텍스트 메뉴 RPC 경로가 없어 구버전 경로로 폴백합니다.`);
        useLegacyRpc = true;
        res = await rpcRequest(dbType, actionData, controller.signal);
      }
    } catch (networkErr) {
      if (networkErr && networkErr.name === "AbortError") {
        // 브라우저가 응답을 아예 못 받고 있는 상태 — openresty의 기본 500 페이지처럼
        // 프록시가 백엔드와의 연결이 끊긴 경우 이쪽으로 잡히는 경우가 많다.
        return {
          success: false,
          error:
            T(`요청이 ${Math.round(timeoutMs / 1000)}초 안에 응답을 받지 못해 중단했습니다. `, `The request got no response within ${Math.round(timeoutMs / 1000)} seconds and was stopped. `) +
            T("서버가 아직 처리 중이거나 타임아웃/충돌했을 수 있습니다. 파일이 크다면 크기를 줄이거나 ", "The server may still be working, or it timed out or crashed. If the file is large, make it smaller or ") +
            T("Git 저장소 URL 설치를 대신 사용해보세요. 잠시 후 새로고침해 실제로 설치됐는지도 확인해보세요.", "use the Git repository URL install instead. Refresh in a moment to check whether it was actually installed."),
        };
      }
      // fetch 자체가 실패(오프라인, DNS, CORS 등) — 서버 응답조차 못 받은 경우
      return {
        success: false,
        error: T(`서버에 연결하지 못했습니다: ${networkErr && networkErr.message ? networkErr.message : networkErr}`, `Could not connect to the server: ${networkErr && networkErr.message ? networkErr.message : networkErr}`),
      };
    } finally {
      clearTimeout(timer);
    }

    let bodyText = "";
    try {
      bodyText = await res.text();
    } catch (readErr) {
      return { success: false, error: T(`응답 본문을 읽지 못했습니다 (HTTP ${res.status}).`, `Could not read the response body (HTTP ${res.status}).`) };
    }

    let json = null;
    if (bodyText) {
      try {
        json = JSON.parse(bodyText);
      } catch (parseErr) {
        // 서버/프록시가 JSON이 아닌 오류 페이지(예: 413 요청 크기 초과, 502/504,
        // 또는 openresty가 백엔드 연결 실패 시 자체 생성하는 기본 500 페이지 등)를
        // 돌려준 경우 — 상태 코드와 본문 일부를 그대로 보여줘 원인을 알 수 있게 한다.
        const snippet = bodyText.replace(/\s+/g, " ").trim().slice(0, 160);
        let hint = "";
        if (res.status === 413) {
          hint = T(" 파일이 너무 커서 서버(또는 앞단 프록시)가 요청을 거부한 것으로 보입니다.", " The file seems too large and the server (or a proxy in front of it) refused the request.");
        } else if (res.status === 502 || res.status === 504) {
          hint = T(" 서버(백엔드)와 프록시 사이의 연결/응답 지연 문제로 보입니다.", " This looks like a connection or response delay between the backend and the proxy.");
        } else if (
          res.status === 500 &&
          /openresty|nginx/i.test(snippet) &&
          !/traceback|werkzeug/i.test(snippet)
        ) {
          hint =
            T(" 프록시가 보여주는 기본 오류 페이지입니다 — plugin_board 코드가 아니라 ", " This is the proxy's default error page — not plugin_board code; ") +
            T("백엔드 프로세스가 타임아웃되었거나 요청 처리 중 다운되었을 가능성이 높습니다. ", "the backend process most likely timed out or went down while handling the request. ") +
            T("서버(Gunicorn/Flask) 로그를 확인해주세요.", "Check the server (Gunicorn/Flask) logs.");
        } else if (res.status >= 500) {
          hint = T(" 서버 내부 오류로 보입니다.", " This looks like an internal server error.");
        }
        return {
          success: false,
          error: T(`서버가 올바른 응답을 반환하지 않았습니다 (HTTP ${res.status}).${hint}`, `The server did not return a valid response (HTTP ${res.status}).${hint}`) +
            (snippet ? T(` 응답 일부: ${snippet}`, ` Part of the response: ${snippet}`) : ""),
        };
      }
    }

    if (!res.ok && (!json || typeof json.success === "undefined")) {
      return {
        success: false,
        error: (json && (json.error || json.message)) || T(`요청이 실패했습니다 (HTTP ${res.status}).`, `The request failed (HTTP ${res.status}).`),
      };
    }

    return json || { success: false, error: T("서버로부터 빈 응답을 받았습니다.", "The server returned an empty response.") };
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
    if (item.notice) {
      // [PATCH-6] 검색 실패/안내 카드 — 설치할 대상이 아니다
      const badge = document.createElement("span");
      badge.className = "pb-installed-badge pb-installed-badge-muted";
      badge.textContent = T("안내", "Notice");
      return badge;
    }
    if (item.installed && !item.has_update) {
      const badge = document.createElement("span");
      badge.className = "pb-installed-badge";
      // 버전 문자열은 외부 저장소의 VERSION 파일 값이라 텍스트 노드로만 넣는다(XSS 방지)
      badge.innerHTML = CHECK_ICON;
      badge.appendChild(
        document.createTextNode(T(`설치됨${item.installed_version ? " · v" + item.installed_version : ""}`, `Installed${item.installed_version ? " · v" + item.installed_version : ""}`))
      );
      return badge;
    }

    if (!isAdmin) {
      // 관리자가 아니면 백엔드도 설치/업데이트 요청을 거부하므로, 눌러서
      // 오류를 보게 하는 대신 처음부터 비활성 안내로 대체한다.
      const badge = document.createElement("span");
      badge.className = "pb-installed-badge pb-installed-badge-muted";
      badge.innerHTML = item.installed
        ? T(`${UPDATE_ICON}업데이트 필요 (관리자 전용)`, `${UPDATE_ICON}Update available (admin only)`)
        : T(`${INSTALL_ICON}미설치 (관리자 전용)`, `${INSTALL_ICON}Not installed (admin only)`);
      return badge;
    }

    const isUpdate = !!item.installed;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pb-install-btn" + (isUpdate ? " pb-install-btn-update" : "");
    btn.innerHTML = isUpdate
      ? T(`${UPDATE_ICON}업데이트`, `${UPDATE_ICON}Update`)
      : T(`${INSTALL_ICON}신규설치`, `${INSTALL_ICON}Install`);

    btn.addEventListener("click", async () => {
      const originalHtml = btn.innerHTML;
      const dbType = getDbType();
      btn.disabled = true;
      btn.innerHTML = isUpdate
        ? T(`${UPDATE_ICON}업데이트 중…`, `${UPDATE_ICON}Updating…`)
        : T(`${INSTALL_ICON}설치 중…`, `${INSTALL_ICON}Installing…`);

      try {
        const result = await callPluginBoardAction(dbType, {
          action: isUpdate ? "update" : "install_git",
          plugin_id: item.id,
          // 업데이트일 때는 화면에 보이는 URL(item.url)을 보내지 않는다 — 이 값은
          // 카드 표시용으로 자격증명을 뺀 주소라서, 그대로 보내면 백엔드가
          // github.txt 레지스트리에 저장된 자격증명 포함 URL을 찾아 쓰는 폴백
          // 로직이 아예 발동하지 않는다(git_url이 비어있을 때만 그 폴백이
          // 동작하므로). 신규설치일 때만 방금 알아낸 URL을 그대로 전달한다.
          ...(isUpdate ? {} : { git_url: item.url }),
        });

        if (result && result.success) {
          reloadAfterInstall(result.message || T(`'${item.title}' 처리가 완료되었습니다.`, `'${item.title}' is done.`));
        } else {
          showToast((result && result.error) || T("요청이 실패했습니다.", "The request failed."), true);
          btn.disabled = false;
          btn.innerHTML = originalHtml;
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 설치/업데이트 오류:`, err);
        showToast(T(`설치/업데이트 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the install/update request: ${err && err.message ? err.message : err}`), true);
        btn.disabled = false;
        btn.innerHTML = originalHtml;
      }
    });

    return btn;
  }

  // ------------------------------------------------------------------
  // 환경설정 모달 — 코어 공통 API(모든 플러그인이 함께 쓰는 엔드포인트)를 사용.
  // GET  /api/media/metadata/plugins/manage           → config_schema + 현재 설정값
  // POST /api/media/metadata/plugins/save-config       → 저장
  // (madnite1/plugin_manager의 환경설정 모달과 동일한 코어 API를 그대로 사용)
  // ------------------------------------------------------------------
  function ensureSettingsModal() {
    let modal = document.getElementById("pb-settings-modal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "pb-settings-modal";
    modal.className = "pb-modal-overlay";
    modal.innerHTML = T(`
      <div class="pb-modal">
        <div class="pb-modal-head">
          <h3 id="pb-settings-modal-title">설정</h3>
          <button type="button" class="pb-modal-close" id="pb-settings-modal-close">&times;</button>
        </div>
        <div class="pb-modal-body" id="pb-settings-modal-body"></div>
        <div class="pb-modal-foot">
          <button type="button" class="pb-modal-btn pb-modal-btn-cancel" id="pb-settings-modal-cancel">취소</button>
          <button type="button" class="pb-modal-btn pb-modal-btn-save" id="pb-settings-modal-save">저장</button>
        </div>
      </div>
    `, `
      <div class="pb-modal">
        <div class="pb-modal-head">
          <h3 id="pb-settings-modal-title">Settings</h3>
          <button type="button" class="pb-modal-close" id="pb-settings-modal-close">&times;</button>
        </div>
        <div class="pb-modal-body" id="pb-settings-modal-body"></div>
        <div class="pb-modal-foot">
          <button type="button" class="pb-modal-btn pb-modal-btn-cancel" id="pb-settings-modal-cancel">Cancel</button>
          <button type="button" class="pb-modal-btn pb-modal-btn-save" id="pb-settings-modal-save">Save</button>
        </div>
      </div>
    `);
    document.body.appendChild(modal);

    const close = () => modal.classList.remove("pb-modal-show");
    modal.addEventListener("click", (e) => {
      if (e.target === modal) close();
    });
    modal.querySelector("#pb-settings-modal-close").addEventListener("click", close);
    modal.querySelector("#pb-settings-modal-cancel").addEventListener("click", close);
    return modal;
  }

  // ------------------------------------------------------------------
  // [PATCH-6] "Gitea 서버" 설정(GITEA_TOKENS) 편집 UI.
  // 저장 형식은 서버별 {host, scheme, username, password, token} JSON 목록이다.
  // 구버전 콤마 문자열("호스트:토큰", "호스트:아이디:비밀번호", "호스트:포트:토큰")도
  // 읽어서 이 화면에서 한 번 저장하면 새 형식으로 바뀐다. 내부 입력칸에는 name
  // 속성을 달지 않아, 저장 시에는 hidden input(GITEA_TOKENS) 하나만 수집된다.
  // ------------------------------------------------------------------
  function normalizeGiteaServer(raw, fallbackScheme) {
    let text = String(raw || "").trim();
    let scheme = fallbackScheme || "";
    const m = text.match(/^([a-z][a-z0-9+.-]*):\/\//i);
    if (m) {
      scheme = m[1].toLowerCase();
      text = text.slice(m[0].length);
    }
    const host = text.split("/")[0].split("@").pop().trim().toLowerCase();
    if (scheme !== "http" && scheme !== "https") scheme = "https";
    return { scheme, host };
  }

  function parseOwnersInput(value) {
    const list = Array.isArray(value) ? value : String(value || "").split(",");
    return [...new Set(list.map((o) => String(o).trim().replace(/^\/+|\/+$/g, "")).filter(Boolean))];
  }

  function parseGiteaTokensValue(raw) {
    const text = String(raw || "").trim();
    if (!text) return [];
    if (text.startsWith("[")) {
      try {
        const arr = JSON.parse(text);
        return (Array.isArray(arr) ? arr : [])
          .filter((e) => e && e.host)
          .map((e) => {
            const { scheme, host } = normalizeGiteaServer(e.host, e.scheme);
            return {
              host,
              scheme,
              username: e.username || "",
              password: e.password || "",
              token: e.token || "",
              owners: parseOwnersInput(e.owners),
            };
          });
      } catch (err) {
        console.warn(`${LOG_PREFIX} GITEA_TOKENS JSON 파싱 실패:`, err);
        return [];
      }
    }
    const entries = [];
    text.split(",").forEach((chunk) => {
      chunk = chunk.trim();
      if (!chunk || !chunk.includes(":")) return;
      let scheme = "https";
      const m = chunk.match(/^(https?):\/\//i);
      if (m) {
        scheme = m[1].toLowerCase();
        chunk = chunk.slice(m[0].length);
      }
      const parts = chunk.split(":").map((x) => x.trim());
      let host = (parts.shift() || "").toLowerCase();
      if (parts.length && /^\d+$/.test(parts[0])) host += ":" + parts.shift();
      if (!host) return;
      if (parts.length === 1 && parts[0]) {
        entries.push({ host, scheme, username: "", password: "", token: parts[0], owners: [] });
      } else if (parts.length === 2 && parts[0] && parts[1]) {
        entries.push({ host, scheme, username: parts[0], password: parts[1], token: "", owners: [] });
      }
    });
    return entries;
  }

  function serializeGiteaTokensValue(entries) {
    if (!entries.length) return "";
    return JSON.stringify(
      entries.map((e) => {
        const out = { host: e.host, scheme: e.scheme || "https" };
        if (e.username) out.username = e.username;
        if (e.password) out.password = e.password;
        if (e.token) out.token = e.token;
        if (e.owners && e.owners.length) out.owners = e.owners;
        return out;
      })
    );
  }

  const GITEA_TEST_MARK = { ok: "✓", warn: "!", fail: "✗", skip: "–" };

  function renderGiteaTestResult(targetEl, data) {
    targetEl.innerHTML = "";
    targetEl.hidden = false;
    (data.checks || []).forEach((c) => {
      const row = document.createElement("div");
      row.className = "pb-gitea-test-row pb-gitea-test-" + (c.status || "skip");
      const mark = document.createElement("span");
      mark.className = "pb-gitea-test-mark";
      mark.textContent = GITEA_TEST_MARK[c.status] || "·";
      const label = document.createElement("strong");
      label.textContent = c.label || "";
      const detail = document.createElement("span");
      detail.textContent = c.detail || "";
      row.append(mark, label, detail);
      targetEl.appendChild(row);
    });
    if (Array.isArray(data.topics) && data.topics.length) {
      const topicsEl = document.createElement("div");
      topicsEl.className = "pb-gitea-test-repos";
      topicsEl.textContent = T("검색 토픽: ", "Topics searched: ") + data.topics.join(", ");
      targetEl.appendChild(topicsEl);
    }
    const repos = data.repos || [];
    if (repos.length) {
      const list = document.createElement("div");
      list.className = "pb-gitea-test-repos";
      list.textContent =
        T("발견된 저장소: ", "Repositories found: ") + repos.map((r) => r.name + (r.private ? T(" (비공개)", " (private)") : "")).join(", ");
      targetEl.appendChild(list);
    }
  }

  async function runGiteaTest(entry, resultEl, btn) {
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = T("테스트 중…", "Testing…");
    resultEl.hidden = false;
    resultEl.textContent = T("연결을 확인하는 중…", "Checking the connection…");
    try {
      const result = await callPluginBoardAction(getDbType(), {
        action: "test_gitea",
        host: entry.host,
        scheme: entry.scheme,
        username: entry.username,
        password: entry.password,
        token: entry.token,
        owners: (entry.owners || []).join(","),
      });
      if (result && result.success && result.message && typeof result.message === "object") {
        renderGiteaTestResult(resultEl, result.message);
      } else {
        resultEl.textContent = (result && result.error) || T("연결 테스트에 실패했습니다.", "The connection test failed.");
      }
    } catch (err) {
      resultEl.textContent = T(`연결 테스트 중 오류: ${err && err.message ? err.message : err}`, `Error during the connection test: ${err && err.message ? err.message : err}`);
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  }

  function buildGiteaServersField(key, currentValue) {
    const container = document.createElement("div");
    container.className = "pb-gitea-servers";

    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = key; // 저장 시 이 값만 GITEA_TOKENS로 수집된다

    const listEl = document.createElement("div");
    listEl.className = "pb-gitea-servers-list";

    let entries = parseGiteaTokensValue(currentValue);
    let editingIndex = -1; // -1이면 새 서버 추가 모드

    const syncHidden = () => {
      hidden.value = serializeGiteaTokensValue(entries);
    };

    const mask = (v) => "•".repeat(Math.min(String(v || "").length, 10));

    const renderList = () => {
      listEl.innerHTML = "";
      if (entries.length === 0) {
        const empty = document.createElement("p");
        empty.className = "pb-gitea-servers-empty";
        empty.textContent = T("등록된 Gitea 서버가 없습니다.", "No Gitea servers registered.");
        listEl.appendChild(empty);
        return;
      }
      entries.forEach((entry, idx) => {
        const wrap = document.createElement("div");
        wrap.className = "pb-gitea-servers-item";

        const row = document.createElement("div");
        row.className = "pb-gitea-servers-row";

        const hostEl = document.createElement("span");
        hostEl.className = "pb-gitea-servers-host";
        hostEl.textContent = `${entry.scheme}://${entry.host}`;

        const authParts = [];
        if (entry.username) authParts.push(T(`계정 ${entry.username}${entry.password ? " / " + mask(entry.password) : " (비밀번호 없음)"}`, `Account ${entry.username}${entry.password ? " / " + mask(entry.password) : " (no password)"}`));
        if (entry.token) authParts.push(T(`토큰 ${mask(entry.token)}`, `Token ${mask(entry.token)}`));
        if (entry.owners && entry.owners.length) authParts.push(T(`소유자 ${entry.owners.join(", ")}`, `Owners ${entry.owners.join(", ")}`));
        const authEl = document.createElement("span");
        authEl.className = "pb-gitea-servers-auth";
        authEl.textContent = authParts.length ? authParts.join(" · ") : T("인증 정보 없음(공개 저장소만)", "No credentials (public repositories only)");

        const testBtn = document.createElement("button");
        testBtn.type = "button";
        testBtn.className = "pb-gitea-servers-action";
        testBtn.textContent = T("연결 테스트", "Test connection");

        const editBtn = document.createElement("button");
        editBtn.type = "button";
        editBtn.className = "pb-gitea-servers-action";
        editBtn.textContent = T("수정", "Edit");
        editBtn.addEventListener("click", () => startEdit(idx));

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "pb-gitea-servers-del";
        delBtn.title = T("삭제", "Delete");
        delBtn.innerHTML = "&times;";
        delBtn.addEventListener("click", () => {
          entries.splice(idx, 1);
          if (editingIndex === idx) resetForm();
          syncHidden();
          renderList();
        });

        const resultEl = document.createElement("div");
        resultEl.className = "pb-gitea-test-result";
        resultEl.hidden = true;
        testBtn.addEventListener("click", () => runGiteaTest(entry, resultEl, testBtn));

        row.append(hostEl, authEl, testBtn, editBtn, delBtn);
        wrap.append(row, resultEl);
        listEl.appendChild(wrap);
      });
    };

    // ---- 추가/수정 폼
    const formEl = document.createElement("div");
    formEl.className = "pb-gitea-servers-form pb-gitea-servers-form-grid";

    const makeInput = (type, placeholder) => {
      const input = document.createElement("input");
      input.type = type;
      input.placeholder = placeholder;
      input.autocomplete = type === "password" ? "new-password" : "off";
      return input;
    };
    const hostInput = makeInput("text", T("서버 주소 (예: https://gitea.example.com 또는 http://host:3000)", "Server address (e.g. https://gitea.example.com or http://host:3000)"));
    const userInput = makeInput("text", T("아이디", "Username"));
    const passInput = makeInput("password", T("비밀번호", "Password"));
    const tokenInput = makeInput("password", T("읽기 토큰 (repository 읽기 권한)", "Read token (repository read permission)"));
    const ownersInput = makeInput("text", T("소유자 (쉼표 구분, 선택 — 예: javara999)", "Owners (comma separated, optional — e.g. javara999)"));

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.textContent = T("+ 추가", "+ Add");
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = T("취소", "Cancel");
    cancelBtn.hidden = true;
    const testFormBtn = document.createElement("button");
    testFormBtn.type = "button";
    testFormBtn.textContent = T("입력값으로 테스트", "Test with these values");
    const formResultEl = document.createElement("div");
    formResultEl.className = "pb-gitea-test-result";
    formResultEl.hidden = true;

    const hint = document.createElement("p");
    hint.className = "pb-gitea-servers-hint";
    hint.textContent =
      T("아이디/비밀번호를 저장하면 이 서버의 저장소를 https://서버/소유자/저장소 처럼 자격증명 없이 ", "If you save a username and password, repositories on this server entered without credentials like https://server/owner/repo ") +
      T("입력해도 https://아이디:비밀번호@서버/... 로 자동 등록됩니다. 토픽 검색·버전 확인에는 읽기 ", "are registered automatically as https://user:password@server/... Topic search and version checks use the read ") +
      T("토큰을 우선 사용합니다. '소유자'에 적은 사용자·조직의 저장소는 토픽이 없어도 전부 살펴보고, ", "token first. Repositories of the users and organizations listed in 'Owners' are all checked even without topics, ") +
      T("VERSION 파일이 있는 저장소를 플러그인으로 표시합니다(이 서버에서 설치한 적 있는 소유자는 ", "and those with a VERSION file are shown as plugins (owners you have installed from on this server are ") +
      T("적지 않아도 자동 포함). 추가·수정 후 아래 '저장'을 눌러야 반영됩니다.", "included automatically). After adding or editing, press 'Save' below to apply.");

    const readForm = () => {
      const { scheme, host } = normalizeGiteaServer(hostInput.value, "");
      return {
        host,
        scheme,
        username: userInput.value.trim(),
        password: passInput.value,
        token: tokenInput.value.trim(),
        owners: parseOwnersInput(ownersInput.value),
      };
    };

    function resetForm() {
      editingIndex = -1;
      hostInput.value = "";
      userInput.value = "";
      passInput.value = "";
      tokenInput.value = "";
      ownersInput.value = "";
      submitBtn.textContent = T("+ 추가", "+ Add");
      cancelBtn.hidden = true;
      formResultEl.hidden = true;
    }

    function startEdit(idx) {
      const e = entries[idx];
      editingIndex = idx;
      hostInput.value = `${e.scheme}://${e.host}`;
      userInput.value = e.username || "";
      passInput.value = e.password || "";
      tokenInput.value = e.token || "";
      ownersInput.value = (e.owners || []).join(", ");
      submitBtn.textContent = T("수정 완료", "Done");
      cancelBtn.hidden = false;
      formResultEl.hidden = true;
      hostInput.focus();
    }

    const submit = () => {
      const entry = readForm();
      if (!entry.host) {
        showToast(T("Gitea 서버 주소를 입력해주세요.", "Enter the Gitea server address."), true);
        return;
      }
      if (Boolean(entry.username) !== Boolean(entry.password)) {
        showToast(T("아이디와 비밀번호는 함께 입력해주세요.", "Enter the username and password together."), true);
        return;
      }
      const dupIdx = entries.findIndex((e) => e.host === entry.host);
      if (dupIdx !== -1 && dupIdx !== editingIndex) {
        showToast(T(`이미 등록된 서버입니다: ${entry.host} — 목록에서 '수정'을 눌러주세요.`, `This server is already registered: ${entry.host} — press 'Edit' in the list.`), true);
        return;
      }
      if (editingIndex >= 0) {
        entries[editingIndex] = entry;
      } else {
        entries.push(entry);
      }
      if (!entry.username && !entry.token) {
        showToast(T("인증 정보 없이 등록했습니다 — 공개 저장소만 검색됩니다.", "Registered without credentials — only public repositories will be searched."), false);
      }
      syncHidden();
      renderList();
      resetForm();
    };

    submitBtn.addEventListener("click", submit);
    cancelBtn.addEventListener("click", resetForm);
    testFormBtn.addEventListener("click", () => {
      const entry = readForm();
      if (!entry.host) {
        showToast(T("테스트할 서버 주소를 입력해주세요.", "Enter the server address to test."), true);
        return;
      }
      runGiteaTest(entry, formResultEl, testFormBtn);
    });
    [hostInput, userInput, passInput, tokenInput, ownersInput].forEach((input) =>
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          submit();
        }
      })
    );

    const btnRow = document.createElement("div");
    btnRow.className = "pb-gitea-servers-form-buttons";
    btnRow.append(testFormBtn, cancelBtn, submitBtn);
    formEl.append(hostInput, userInput, passInput, tokenInput, ownersInput, btnRow);

    syncHidden();
    renderList();
    container.append(listEl, formEl, formResultEl, hint, hidden);
    return container;
  }

  function renderSchemaField(field, currentValue) {
    const label = field.label || field.key;
    const required = !!field.required;
    const type = (field.type || "text").toLowerCase();
    const key = field.key || "";
    const requiredMark = required ? '<span class="pb-field-required">*</span>' : "";
    const descHtml = field.description
      ? `<p class="pb-field-desc"></p>`
      : "";

    const wrap = document.createElement("div");
    wrap.className = "pb-field";

    const labelEl = document.createElement("label");
    // 라벨은 다른 플러그인의 config_schema 값이라 텍스트로 넣고, 필수 표시만 마크업으로 붙인다
    labelEl.textContent = `${label} `;
    if (required) labelEl.insertAdjacentHTML("beforeend", requiredMark);
    wrap.appendChild(labelEl);

    if (key === "GITEA_TOKENS") {
      // 코어의 범용 "환경설정 → 플러그인 설정" 화면은 이 필드가 무슨 커스텀
      // type인지 모르므로(표준 타입만 렌더링 가능), config_schema에는 표준
      // 타입("password")을 그대로 선언해둔다 — 대신 이 모달(plugin_board
      // 자신의 카드에서 여는 설정 창)에서만 key로 식별해 전용 위젯으로
      // 바꿔치기한다. 저장되는 값 형식은 동일하므로 코어 화면에서 수정해도
      // (거칠지만) 여전히 정상 동작한다.
      wrap.appendChild(buildGiteaServersField(key, currentValue));
    } else if (type === "checkbox") {
      const row = document.createElement("label");
      row.className = "pb-field-checkbox-row";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = key;
      input.checked = currentValue === true || currentValue === "1" || currentValue === 1 || currentValue === "true";
      row.append(input, document.createTextNode(T(" 사용", " Use")));
      wrap.appendChild(row);
    } else if (type === "select") {
      const select = document.createElement("select");
      select.name = key;
      (field.options || []).forEach((opt) => {
        const val = typeof opt === "object" ? opt.value : opt;
        const optLabel = typeof opt === "object" ? opt.label : opt;
        const option = document.createElement("option");
        option.value = val;
        option.textContent = optLabel;
        if (String(val) === String(currentValue ?? field.default ?? "")) option.selected = true;
        select.appendChild(option);
      });
      wrap.appendChild(select);
    } else {
      const input = document.createElement("input");
      input.type = type === "password" ? "password" : type === "number" ? "number" : "text";
      input.name = key;
      input.value = currentValue ?? field.default ?? "";

      if (type === "password") {
        // 비밀번호 타입 필드는 값이 점(•)으로 가려져 잘 안 보인다는 피드백을 반영해,
        // 눈 모양 버튼으로 평문 확인을 토글할 수 있게 한다.
        const passWrap = document.createElement("div");
        passWrap.className = "pb-field-password-wrap";
        const toggleBtn = document.createElement("button");
        toggleBtn.type = "button";
        toggleBtn.className = "pb-field-password-toggle";
        toggleBtn.title = T("값 표시/숨기기", "Show/hide value");
        toggleBtn.innerHTML = EYE_ICON;
        toggleBtn.addEventListener("click", () => {
          const showing = input.type === "text";
          input.type = showing ? "password" : "text";
          toggleBtn.innerHTML = showing ? EYE_ICON : EYE_OFF_ICON;
        });
        passWrap.append(input, toggleBtn);
        wrap.appendChild(passWrap);
      } else {
        wrap.appendChild(input);
      }
    }

    if (field.description) {
      const desc = document.createElement("p");
      desc.className = "pb-field-desc";
      desc.textContent = field.description;
      wrap.appendChild(desc);
    }

    return wrap;
  }

  // ------------------------------------------------------------------
  // 커스텀 설정 UI(settings.html/css/js)를 코어가 렌더링한 결과(settings_ui)를
  // 그대로 삽입·실행한다. madnite1/plugin_manager의 환경설정 모달과 동일한 방식:
  // - settings_ui.html은 form 안에 그대로 삽입 (name 속성이 있는 input/select만
  //   저장 시 수집되므로, settings.html 작성자가 name을 config 키와 맞춰야 한다)
  // - settings_ui.css는 <style>로 주입
  // - settings_ui.js와 삽입된 HTML 안의 <script> 태그는 new Function으로 실행
  //   (window, pluginId, root, config 인자 전달)
  // ------------------------------------------------------------------
  function prefillNamedFieldsFromConfig(root, config) {
    // unified_book처럼 별도 settings.js 없이 name 속성만으로 값을 저장/복원하도록
    // 작성된(=우리 자동 생성 폼과 동일한 관례를 따르는) 커스텀 UI를 위한 범용
    // 채우기 로직. 저장된 값이 실제로 있는 필드만 건드리고, 값이 없는 필드는
    // 플러그인이 HTML에 하드코딩해둔 기본값(예: 기본 selected 옵션)을 그대로
    // 둔다 — 없는 값을 빈 문자열로 덮어써서 의도된 기본값을 지우지 않기 위함이다.
    if (!config) return;
    root.querySelectorAll("[name]").forEach((el) => {
      const key = el.name;
      if (!key || !Object.prototype.hasOwnProperty.call(config, key)) return;
      const val = config[key];

      if (el.tagName === "SELECT") {
        let matched = false;
        Array.from(el.options).forEach((opt) => {
          const isMatch = String(opt.value) === String(val);
          opt.selected = isMatch;
          if (isMatch) matched = true;
        });
        if (!matched) el.value = val == null ? "" : String(val);
      } else if (el.type === "checkbox") {
        el.checked = val === true || val === "true" || val === "1" || val === 1;
      } else if (el.type === "radio") {
        el.checked = String(el.value) === String(val);
      } else {
        el.value = val == null ? "" : val;
      }
    });
  }

  function renderCustomSettingsUi(bodyEl, p, config) {
    const form = document.createElement("form");
    form.id = "pb-settings-form";
    form.dataset.pluginId = p.id;

    const root = document.createElement("div");
    root.className = "pb-settings-ui-root";
    // plugin_manager와 동일한 규격으로 저장된 설정값을 data 속성에도 함께 심어둔다.
    // 일부 플러그인의 settings.js는 함수 인자(config)가 아니라 이 DOM 속성에서
    // 직접 읽어가도록 작성돼 있어서, 함수 인자만 넘기면 저장된 값이 화면에
    // 채워지지 않는 문제가 있었다. 두 경로 모두 지원해 호환성을 맞춘다.
    // 주의: setAttribute는 HTML 파싱을 거치지 않으므로(plugin_manager가 innerHTML
    // 문자열 조립 방식이라 값을 미리 HTML 이스케이프하는 것과 달리) 여기서는
    // JSON 문자열을 그대로 넣어야 한다 — 이스케이프하면 다시 읽을 때 깨진다.
    root.setAttribute("data-plugin-settings-root", p.id);
    root.setAttribute("data-plugin-config", JSON.stringify(config || {}));
    root.innerHTML = p.settings_ui.html; // 플러그인 제작자가 제공하는 신뢰된 관리자용 UI

    form.appendChild(root);
    bodyEl.appendChild(form);

    // DOM에 실제로 붙은 뒤, data 속성을 다시 파싱해 최종 config로 사용한다
    // (plugin_manager와 동일하게 — 파싱 실패 시 원래 config로 폴백).
    let pluginConfig = config || {};
    try {
      const rawConfig = root.dataset.pluginConfig;
      if (rawConfig) pluginConfig = JSON.parse(rawConfig);
    } catch (err) {
      console.warn(`${LOG_PREFIX} data-plugin-config 파싱 실패, 원본 config로 대체 (${p.id}):`, err);
    }

    // 자체 settings.js가 없는 플러그인(예: unified_book)도 저장된 값이 보이도록,
    // name 속성 기준 범용 채우기를 먼저 적용한다. 플러그인 자체 JS가 있다면
    // 아래에서 실행되며 이 결과를 덮어쓸 수 있다.
    prefillNamedFieldsFromConfig(root, pluginConfig);

    if (p.settings_ui.css) {
      const styleEl = document.createElement("style");
      styleEl.textContent = p.settings_ui.css;
      root.appendChild(styleEl);
    }

    if (p.settings_ui.js) {
      try {
        const fn = new Function("window", "pluginId", "root", "config", p.settings_ui.js);
        fn(window, p.id, root, pluginConfig);
      } catch (err) {
        console.error(`${LOG_PREFIX} settings.js 실행 오류 (${p.id}):`, err);
      }
    }

    // innerHTML로 삽입된 <script> 태그는 브라우저가 자동 실행하지 않으므로 직접 실행
    root.querySelectorAll("script").forEach((script) => {
      try {
        const fn = new Function("window", "pluginId", "root", "config", script.textContent);
        fn(window, p.id, root, pluginConfig);
      } catch (err) {
        console.error(`${LOG_PREFIX} settings.html 인라인 스크립트 오류 (${p.id}):`, err);
      }
    });
  }

  async function openSettingsModal(item, dbType) {
    const modal = ensureSettingsModal();
    const titleEl = modal.querySelector("#pb-settings-modal-title");
    const bodyEl = modal.querySelector("#pb-settings-modal-body");
    const saveBtn = modal.querySelector("#pb-settings-modal-save");

    titleEl.textContent = T(`${item.title} (${item.id}) 설정`, `${item.title} (${item.id}) settings`);
    bodyEl.innerHTML = T('<p class="pb-status" style="padding:24px 0;">설정 정보를 불러오는 중…</p>', '<p class="pb-status" style="padding:24px 0;">Loading settings…</p>');
    modal.classList.add("pb-modal-show");

    try {
      const res = await fetch("/api/media/metadata/plugins/manage");
      const data = await res.json();
      if (!data || data.success === false || !data.plugins) {
        throw new Error((data && data.error) || T("플러그인 설정 정보를 가져오지 못했습니다.", "Could not get the plugin settings."));
      }
      // 코어는 클래스 id로 플러그인을 식별한다 — 설치 폴더명(item.id)과 다를 수 있다
      const classId = item.class_id || item.id;
      const p =
        data.plugins.find((x) => x.id === classId) || data.plugins.find((x) => x.id === item.id);
      if (!p) throw new Error(T("선택한 플러그인 정보를 찾을 수 없습니다.", "Could not find the selected plugin."));

      const schema = p.config_schema || [];
      const configFromManage = p.config || {};
      const hasCustomUi = !!(p.settings_ui && p.settings_ui.html);

      // /manage API의 config 필드만 믿지 않고, DB 게이트웨이(가이드 §4의
      // settings 테이블 PLUGIN_CONFIG_{id})에서 직접 한 번 더 조회해 병합한다.
      // 값이 있는 쪽(DB 게이트웨이)을 우선시켜, /manage가 값을 못 돌려주는
      // 경우에도 실제 저장된 설정이 화면에 반영되도록 한다.
      let config = configFromManage;
      try {
        const gwResult = await callPluginBoardAction(dbType, {
          action: "get_config",
          plugin_id: item.id,
        });
        if (gwResult && gwResult.success && gwResult.message && typeof gwResult.message === "object") {
          config = Object.assign({}, configFromManage, gwResult.message);
        }
      } catch (err) {
        console.warn(`${LOG_PREFIX} DB 게이트웨이 설정 조회 실패, /manage 값만 사용 (${item.id}):`, err);
      }

      bodyEl.innerHTML = "";

      if (hasCustomUi) {
        // settings.html이 있으면 config_schema 자동 생성 폼보다 우선한다
        saveBtn.hidden = false;
        renderCustomSettingsUi(bodyEl, p, config);
        return;
      }

      if (schema.length === 0) {
        const empty = document.createElement("p");
        empty.className = "pb-status";
        empty.style.padding = "24px 0";
        empty.textContent = T("이 플러그인은 별도의 설정 항목이 없습니다.", "This plugin has no settings.");
        bodyEl.appendChild(empty);
        saveBtn.hidden = true;
        return;
      }

      saveBtn.hidden = false;
      const form = document.createElement("form");
      form.id = "pb-settings-form";
      form.dataset.pluginId = p.id; // save-config는 클래스 id 기준
      schema.forEach((field) => form.appendChild(renderSchemaField(field, config[field.key])));
      bodyEl.appendChild(form);
    } catch (err) {
      bodyEl.innerHTML = "";
      const errorEl = document.createElement("p");
      errorEl.className = "pb-status pb-error";
      errorEl.style.padding = "24px 0";
      errorEl.textContent = err.message || T("설정 정보를 불러오지 못했습니다.", "Could not load the settings.");
      bodyEl.appendChild(errorEl);
      saveBtn.hidden = true;
    }
  }

  function wireSettingsSave(dbType) {
    const modal = ensureSettingsModal();
    const saveBtn = modal.querySelector("#pb-settings-modal-save");
    if (saveBtn.dataset.wired) return;
    saveBtn.dataset.wired = "1";

    saveBtn.addEventListener("click", async () => {
      const form = modal.querySelector("#pb-settings-form");
      if (!form) {
        modal.classList.remove("pb-modal-show");
        return;
      }
      const pluginId = form.dataset.pluginId;
      const config = {};
      form.querySelectorAll("input, select, textarea").forEach((input) => {
        if (!input.name) return;
        config[input.name] = input.type === "checkbox" ? !!input.checked : String(input.value ?? "").trim();
      });

      const orig = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.textContent = T("저장 중…", "Saving…");
      try {
        const res = await fetch("/api/media/metadata/plugins/save-config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: dbType, plugin_id: pluginId, config }),
        });
        const data = await res.json();
        saveBtn.disabled = false;
        saveBtn.textContent = orig;
        if (data && data.success) {
          showToast(data.message || T("설정이 저장되었습니다.", "Settings saved."), false);
          modal.classList.remove("pb-modal-show");
        } else {
          showToast((data && data.error) || T("설정 저장에 실패했습니다.", "Could not save the settings."), true);
        }
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.textContent = orig;
        showToast(T(`설정 저장 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while saving the settings: ${err && err.message ? err.message : err}`), true);
      }
    });
  }

  // ------------------------------------------------------------------
  // [PATCH-5] 이력 모달 — "변경 내용"(저장소 HISTORY.md/CHANGELOG.md 또는 Releases)과
  // "이 서버 기록"(plugins/data/plugin_board/history.jsonl) 두 탭. item이 null이면
  // 헤더의 "설치 이력" 버튼으로 연 전체 기록 보기(삭제된 플러그인 포함)다.
  // 모든 외부 텍스트(changelog 본문, 메시지)는 textContent로만 넣는다.
  // ------------------------------------------------------------------
  const HISTORY_ACTION_LABELS = {
    install: T("신규 설치", "Install"),
    update: T("업데이트", "Update"),
    delete: T("삭제", "Delete"),
    enable: T("활성화", "Enable"),
    disable: T("비활성화", "Disable"),
    url_changed: T("Git 주소 변경", "Change Git URL"),
    unregister: T("추적 해제", "Stop tracking"),
    auto_update_off: T("자동 업데이트 제외", "Excluded from auto-update"),
    auto_update_on: T("자동 업데이트 포함", "Included in auto-update"),
  };
  const HISTORY_RESULT_LABELS = {
    success: T("성공", "Success"),
    failed: T("실패", "Failed"),
    rolled_back: T("롤백됨", "Rolled back"),
  };

  function ensureHistoryModal() {
    let modal = document.getElementById("pb-history-modal");
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "pb-history-modal";
    modal.className = "pb-modal-overlay";
    modal.innerHTML = T(`
      <div class="pb-modal pb-modal-wide">
        <div class="pb-modal-head">
          <h3 id="pb-history-modal-title">이력</h3>
          <button type="button" class="pb-modal-close" id="pb-history-modal-close">&times;</button>
        </div>
        <div class="pb-hist-tabs" id="pb-history-tabs"></div>
        <div class="pb-modal-body" id="pb-history-modal-body"></div>
      </div>
    `, `
      <div class="pb-modal pb-modal-wide">
        <div class="pb-modal-head">
          <h3 id="pb-history-modal-title">History</h3>
          <button type="button" class="pb-modal-close" id="pb-history-modal-close">&times;</button>
        </div>
        <div class="pb-hist-tabs" id="pb-history-tabs"></div>
        <div class="pb-modal-body" id="pb-history-modal-body"></div>
      </div>
    `);
    document.body.appendChild(modal);
    const close = () => modal.classList.remove("pb-modal-show");
    modal.addEventListener("click", (e) => {
      if (e.target === modal) close();
    });
    modal.querySelector("#pb-history-modal-close").addEventListener("click", close);
    return modal;
  }

  function historyStatus(bodyEl, text, isError) {
    bodyEl.innerHTML = "";
    const p = document.createElement("p");
    p.className = "pb-status" + (isError ? " pb-error" : "");
    p.style.padding = "24px 0";
    p.textContent = text;
    bodyEl.appendChild(p);
  }

  function formatHistoryTime(epochSeconds) {
    const d = new Date(Number(epochSeconds) * 1000);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function buildFilesSummary(files) {
    const counts = (files && files.counts) || {};
    const total = (counts.added || 0) + (counts.removed || 0) + (counts.modified || 0);
    if (!total) return null;
    const details = el("details", "pb-hist-files");
    const summary = el(
      "summary",
      null,
      T(`변경 파일: 추가 ${counts.added || 0} · 삭제 ${counts.removed || 0} · 수정 ${counts.modified || 0}`, `Changed files: ${counts.added || 0} added · ${counts.removed || 0} removed · ${counts.modified || 0} modified`)
    );
    details.appendChild(summary);
    const list = el("ul");
    (files.modified || []).forEach((m) => {
      const lines = m.added === null || m.added === undefined ? T("(바이너리/대용량)", "(binary/large)") : `+${m.added} −${m.removed}`;
      list.appendChild(el("li", "pb-hist-file-mod", T(`수정  ${m.path}  ${lines}`, `Modified  ${m.path}  ${lines}`)));
    });
    (files.added || []).forEach((f) => list.appendChild(el("li", "pb-hist-file-add", T(`추가  ${f}`, `Added  ${f}`))));
    (files.removed || []).forEach((f) => list.appendChild(el("li", "pb-hist-file-del", T(`삭제  ${f}`, `Removed  ${f}`))));
    if (list.childNodes.length) details.appendChild(list);
    return details;
  }

  function renderHistoryEntries(bodyEl, entries, showPluginName) {
    bodyEl.innerHTML = "";
    if (!entries.length) {
      historyStatus(bodyEl, T("아직 기록이 없습니다. 이 버전부터 설치·업데이트·삭제 등이 기록됩니다.", "No records yet. Installs, updates, deletions and so on are recorded from this version on."));
      return;
    }
    const list = el("div", "pb-hist-list");
    entries.forEach((e) => {
      const row = el("div", "pb-hist-entry pb-hist-result-" + (e.result || "success"));
      const head = el("div", "pb-hist-entry-head");
      head.appendChild(el("span", "pb-hist-time", formatHistoryTime(e.ts)));
      if (showPluginName) {
        head.appendChild(el("span", "pb-hist-plugin", e.folder || e.class_id || T("(알 수 없음)", "(unknown)")));
      }
      head.appendChild(el("span", "pb-hist-action", HISTORY_ACTION_LABELS[e.action] || e.action || ""));
      head.appendChild(
        el("span", "pb-hist-badge pb-hist-badge-" + (e.result || "success"), HISTORY_RESULT_LABELS[e.result] || e.result || "")
      );
      if (e.mode === "auto") head.appendChild(el("span", "pb-hist-badge pb-hist-badge-auto", T("자동", "Auto")));
      row.appendChild(head);

      const metaParts = [];
      if (e.from_version || e.to_version) {
        metaParts.push(
          e.from_version && e.to_version
            ? `v${e.from_version} → v${e.to_version}`
            : e.to_version
            ? `v${e.to_version}`
            : `v${e.from_version}`
        );
      }
      if (e.origin) metaParts.push(e.origin);
      if (e.user) metaParts.push(`by ${e.user}`);
      if (e.class_id && e.class_id !== e.folder) metaParts.push(`id=${e.class_id}`);
      if (metaParts.length) row.appendChild(el("div", "pb-hist-meta", metaParts.join("  ·  ")));
      if (e.message) row.appendChild(el("div", "pb-hist-message", e.message));
      const files = buildFilesSummary(e.files);
      if (files) row.appendChild(files);
      list.appendChild(row);
    });
    bodyEl.appendChild(list);
  }

  function renderChangelog(bodyEl, data, item) {
    bodyEl.innerHTML = "";
    const info = el("p", "pb-hist-info");
    if (data.source === "file") {
      info.textContent = T(`출처: 저장소의 ${data.file}`, `Source: ${data.file} in the repository`);
    } else if (data.source === "releases") {
      info.textContent = T("출처: 저장소 릴리즈(Releases)", "Source: repository releases");
    } else {
      info.textContent = data.error
        ? T(`변경 내용을 불러오지 못했습니다: ${data.error}`, `Could not load the changes: ${data.error}`)
        : T("이 저장소에는 HISTORY.md / CHANGELOG.md / CHANGES.md 파일이나 릴리즈가 없습니다. ", "This repository has no HISTORY.md / CHANGELOG.md / CHANGES.md file or releases. ") +
          T("제작자에게 변경 기록을 남겨달라고 요청해보세요.", "Ask the author to keep a change log.");
    }
    bodyEl.appendChild(info);

    if (data.source !== "none") {
      let rangeText = "";
      if (!data.installed_version) {
        rangeText = T("이 서버에 설치되지 않은 플러그인입니다 — 최근 변경 내용을 보여줍니다.", "This plugin is not installed on this server — showing the latest changes.");
      } else if (data.in_range) {
        rangeText = T(`설치된 v${data.installed_version} 이후`, `Changes after the installed v${data.installed_version}`) +
          (data.remote_version ? ` ~ v${data.remote_version}` : "") + T("의 변경 내용입니다.", ".");
      } else {
        rangeText = T(`설치된 v${data.installed_version} 이후의 새 항목이 없어 최근 기록을 참고로 보여줍니다.`, `Nothing new after the installed v${data.installed_version}, so the latest entries are shown for reference.`);
      }
      bodyEl.appendChild(el("p", "pb-hist-info pb-hist-range", rangeText));
    }

    (data.entries || []).forEach((entry) => {
      const sec = el("section", "pb-changelog-entry");
      const head = el("div", "pb-changelog-head");
      head.appendChild(el("strong", null, entry.title || `v${entry.version}`));
      if (entry.date) head.appendChild(el("span", "pb-hist-time", String(entry.date).slice(0, 10)));
      sec.appendChild(head);
      if (entry.body) sec.appendChild(el("div", "pb-changelog-body", entry.body));
      bodyEl.appendChild(sec);
    });

    if (data.raw) {
      bodyEl.appendChild(
        el("p", "pb-hist-info", T("버전별 제목(## 1.2.3 형식)을 찾지 못해 파일 앞부분을 그대로 보여줍니다.", "No version headings (## 1.2.3) found, so the start of the file is shown as is."))
      );
      bodyEl.appendChild(el("div", "pb-changelog-body pb-changelog-raw", data.raw));
    }

    if (data.repo_url || (item && item.url)) {
      const link = el("a", "pb-hist-repo-link", T("저장소에서 보기 ↗", "View in the repository ↗"));
      link.href = data.repo_url || item.url;
      link.target = "_blank";
      link.rel = "noopener";
      bodyEl.appendChild(link);
    }
  }

  async function loadHistoryTab(tab, item, bodyEl) {
    const dbType = getDbType();
    historyStatus(bodyEl, T("불러오는 중…", "Loading…"));
    if (tab === "changelog") {
      const versionLabel = String(item.version_label || "");
      const result = await callPluginBoardAction(dbType, {
        action: "get_changelog",
        plugin_id: item.installed ? item.id : "",
        git_url: item.url || "",
        remote_version: /^v?\d/.test(versionLabel) ? versionLabel.replace(/^v/i, "") : "",
      });
      if (!result || !result.success || !result.message || typeof result.message !== "object") {
        historyStatus(bodyEl, (result && result.error) || T("변경 내용을 불러오지 못했습니다.", "Could not load the changes."), true);
        return;
      }
      renderChangelog(bodyEl, result.message, item);
      return;
    }
    const result = await callPluginBoardAction(dbType, {
      action: "get_history",
      plugin_id: item ? item.id : "",
      class_id: item ? item.class_id || "" : "",
      limit: item ? 200 : 500,
    });
    if (!result || !result.success || !result.message || typeof result.message !== "object") {
      historyStatus(bodyEl, (result && result.error) || T("이력을 불러오지 못했습니다.", "Could not load the history."), true);
      return;
    }
    renderHistoryEntries(bodyEl, result.message.entries || [], !item);
  }

  function openHistoryModal(item) {
    const modal = ensureHistoryModal();
    const titleEl = modal.querySelector("#pb-history-modal-title");
    const tabsEl = modal.querySelector("#pb-history-tabs");
    const bodyEl = modal.querySelector("#pb-history-modal-body");

    titleEl.textContent = item ? T(`${item.title} (${item.id}) 이력`, `${item.title} (${item.id}) history`) : T("이 서버의 플러그인 설치 이력", "Plugin install history on this server");
    tabsEl.innerHTML = "";

    const tabs = item
      ? [
          ["changelog", item.has_update ? T("업데이트 변경 내용", "Changes in this update") : T("변경 내용", "Changes")],
          ["server", T("이 서버 기록", "This server's records")],
        ]
      : [["server", T("전체 기록", "All records")]];
    // 로컬 전용(저장소 주소 없음) 카드는 변경 내용을 가져올 곳이 없으므로 서버 기록부터 보여준다
    const initial = item && item.installed && !item.has_update && !item.url ? "server" : tabs[0][0];

    const select = (key) => {
      tabsEl.querySelectorAll(".pb-hist-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === key));
      loadHistoryTab(key, item, bodyEl);
    };
    tabs.forEach(([key, label]) => {
      const btn = el("button", "pb-hist-tab", label);
      btn.type = "button";
      btn.dataset.tab = key;
      btn.addEventListener("click", () => select(key));
      tabsEl.appendChild(btn);
    });
    tabsEl.hidden = tabs.length < 2;

    modal.classList.add("pb-modal-show");
    select(initial);
  }

  // ------------------------------------------------------------------
  // 관리 행 — 활성화/비활성화 스위치 + 환경설정(gear) + 삭제(trash).
  // 이미 설치된 카드에만 표시된다.
  // ------------------------------------------------------------------
  // ------------------------------------------------------------------
  // [PATCH-10] 플러그인별 "자동 업데이트 안 함" 체크박스. 전역 자동 업데이트가 꺼져 있어도
  // 미리 설정해둘 수 있고, 수동 "업데이트" 버튼은 이 설정과 무관하게 동작한다.
  // ------------------------------------------------------------------
  function buildAutoUpdateSkipControl(item) {
    const label = document.createElement("label");
    label.className = "pb-auto-skip";
    label.title = autoUpdateEnabledGlobal
      ? T("체크하면 자동 업데이트에서 이 플러그인을 건너뜁니다(수동 업데이트는 가능).", "When checked, auto-update skips this plugin (manual updates still work).")
      : T("전역 자동 업데이트가 꺼져 있습니다 — 켜면 이 설정이 적용됩니다(수동 업데이트는 항상 가능).", "Global auto-update is off — this takes effect once it is on (manual updates always work).");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!item.auto_update_skip;
    const text = document.createElement("span");
    text.textContent = T("자동 업데이트 안 함", "No auto-update");
    label.append(box, text);
    label.classList.toggle("pb-auto-skip-on", box.checked);

    box.addEventListener("change", async () => {
      const wanted = box.checked;
      box.disabled = true;
      try {
        const result = await callPluginBoardAction(getDbType(), {
          action: "set_auto_update_skip",
          plugin_id: item.id,
          skip: wanted,
        });
        if (result && result.success) {
          item.auto_update_skip = wanted;
          label.classList.toggle("pb-auto-skip-on", wanted);
          showToast(result.message || T("저장했습니다.", "Saved."), false);
        } else {
          box.checked = !wanted;
          showToast((result && result.error) || T("자동 업데이트 설정을 저장하지 못했습니다.", "Could not save the auto-update setting."), true);
        }
      } catch (err) {
        box.checked = !wanted;
        showToast(T(`자동 업데이트 설정 저장 중 오류: ${err && err.message ? err.message : err}`, `Error while saving the auto-update setting: ${err && err.message ? err.message : err}`), true);
      } finally {
        box.disabled = false;
      }
    });
    return label;
  }

  function buildManageRow(item) {
    // plugin_board 자기 자신은 삭제·비활성화가 백엔드에서 항상 거부되므로 이
    // 함수 자체가 자기 카드에는 호출되지 않는다(buildCard에서 걸러짐).
    const isSelf = item.id === "plugin_board";

    const row = document.createElement("div");
    row.className = "pb-manage-row";

    const left = document.createElement("div");
    left.className = "pb-manage-left";
    let checkbox = null;
    let statusText = null;

    if (!isSelf) {
      const switchLabel = document.createElement("label");
      switchLabel.className = "pb-switch";
      checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = !!item.enabled;
      const slider = document.createElement("span");
      slider.className = "pb-switch-slider";
      switchLabel.append(checkbox, slider);

      statusText = document.createElement("span");
      statusText.className = "pb-manage-status";
      statusText.textContent = item.enabled ? T("사용 중", "In use") : T("중지됨", "Stopped");

      left.append(switchLabel, statusText);
    }

    left.appendChild(buildAutoUpdateSkipControl(item));

    const actions = document.createElement("div");
    actions.className = "pb-manage-actions";

    if (!isSelf) {
      const trashBtn = document.createElement("button");
      trashBtn.type = "button";
      trashBtn.className = "pb-icon-btn pb-icon-btn-danger";
      trashBtn.title = T("삭제", "Delete");
      trashBtn.innerHTML = TRASH_ICON;
      trashBtn.addEventListener("click", async () => {
        if (!window.confirm(T(`'${item.title}' 플러그인을 삭제할까요? 이 작업은 되돌릴 수 없습니다.`, `Delete the '${item.title}' plugin? This cannot be undone.`))) {
          return;
        }
        trashBtn.disabled = true;
        try {
          const result = await callPluginBoardAction(getDbType(), {
            action: "delete",
            plugin_id: item.id,
          });
          if (result && result.success) {
            showToast(result.message || T(`'${item.title}'이(가) 삭제되었습니다.`, `'${item.title}' was deleted.`), false);
            load();
          } else {
            showToast((result && result.error) || T("삭제에 실패했습니다.", "Could not delete it."), true);
            trashBtn.disabled = false;
          }
        } catch (err) {
          showToast(T(`삭제 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the delete request: ${err && err.message ? err.message : err}`), true);
          trashBtn.disabled = false;
        }
      });
      actions.appendChild(trashBtn);

      // 모든 설치된 플러그인(자기 자신 제외) 카드에 "Git 주소 변경"/"등록 해제"
      // 버튼을 동일하게 노출한다. 원래는 Git URL로 직접 등록한 이력(github.txt)이
      // 있는 카드에만 보였지만, 토픽 발견 카드나 로컬 전용 플러그인도 나중에
      // 저장소가 이름을 바꾸거나 URL 관리가 필요해질 수 있어 3버튼 체계로
      // 통일했다. 아직 등록 이력이 없는 카드에서 "Git 주소 변경"을 쓰면 그
      // 순간 새로 등록되고(update_url이 신규 등록도 지원), "등록 해제"는
      // 등록된 게 없으면 그 사실을 안내만 하고 아무 것도 바꾸지 않는다.
      {
        const editUrlBtn = document.createElement("button");
        editUrlBtn.type = "button";
        editUrlBtn.className = "pb-icon-btn";
        editUrlBtn.title = item.user_registered
          ? T("Git 주소 변경 (저장소가 다른 곳으로 옮겨간 경우)", "Change Git URL (when the repository moved elsewhere)")
          : T("Git 주소 등록/변경 (등록하면 이후 이 주소로 업데이트를 확인합니다)", "Register/change Git URL (updates are then checked against this address)");
        editUrlBtn.innerHTML = EDIT_ICON;
        editUrlBtn.addEventListener("click", async () => {
          const currentUrl = item.url || "";
          const input = window.prompt(
            T(`'${item.title}'의 Git 저장소 주소를 입력하세요.\n`, `Enter the Git repository URL for '${item.title}'.\n`) +
              T("(등록된 적이 없으면 새로 등록되고, 이미 등록돼 있다면 저장소가 다른 계정/호스트로\n", "(If none is registered it is added; if one is registered, it is updated for a repository that moved to another\n") +
              T(" 옮겨갔거나 이름이 바뀐 경우에 맞춰 갱신됩니다. 재설치 없이 다음 '업데이트'부터\n", " account/host or was renamed. No reinstall needed — the next 'Update' checks\n") +
              T(" 이 주소를 기준으로 확인합니다.)", " against this address.)"),
            currentUrl
          );
          if (input === null) return; // 취소
          const newUrl = input.trim();
          if (!newUrl) return;
          if (!/^https?:\/\/[^/]+\/[^/]+\/[^/]+/i.test(newUrl)) {
            showToast(
              T("올바른 저장소 주소를 입력해주세요. (예: https://github.com/user/repo)", "Enter a valid repository URL. (e.g. https://github.com/user/repo)"),
              true
            );
            return;
          }
          editUrlBtn.disabled = true;
          try {
            const result = await callPluginBoardAction(getDbType(), {
              action: "update_url",
              plugin_id: item.id,
              git_url: newUrl,
            });
            if (result && result.success) {
              showToast(result.message || T("Git 주소가 갱신되었습니다.", "Git URL updated."), false);
              load();
            } else {
              showToast((result && result.error) || T("Git 주소 갱신에 실패했습니다.", "Could not update the Git URL."), true);
            }
          } catch (err) {
            showToast(T(`Git 주소 갱신 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the Git URL update: ${err && err.message ? err.message : err}`), true);
          } finally {
            editUrlBtn.disabled = false;
          }
        });
        actions.appendChild(editUrlBtn);

        const unregisterBtn = document.createElement("button");
        unregisterBtn.type = "button";
        unregisterBtn.className = "pb-icon-btn";
        unregisterBtn.title = T("등록 해제 (원본 저장소가 삭제된 경우 — 설치된 파일은 유지됩니다)", "Unregister (when the original repository was deleted — installed files are kept)");
        unregisterBtn.innerHTML = UNLINK_ICON;
        unregisterBtn.addEventListener("click", async () => {
          if (
            !window.confirm(
              T(`'${item.title}'의 등록된 Git 주소를 목록에서 제거할까요?\n`, `Remove the registered Git URL of '${item.title}' from the list?\n`) +
                T("설치된 플러그인 파일은 그대로 유지되며, 더 이상 이 주소로 업데이트를 확인하지 않습니다.\n", "The installed plugin files stay, and updates are no longer checked against this URL.\n") +
                T("(등록된 주소가 원래 없었다면 아무 변화도 없습니다.)", "(Nothing changes if no URL was registered.)")
            )
          ) {
            return;
          }
          unregisterBtn.disabled = true;
          try {
            const result = await callPluginBoardAction(getDbType(), {
              action: "unregister",
              plugin_id: item.id,
            });
            if (result && result.success) {
              showToast(result.message || T("등록이 해제되었습니다.", "Unregistered."), false);
              load();
            } else {
              showToast((result && result.error) || T("등록된 Git 주소가 없습니다.", "No Git URL is registered."), true);
              unregisterBtn.disabled = false;
            }
          } catch (err) {
            showToast(T(`등록 해제 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the unregister request: ${err && err.message ? err.message : err}`), true);
            unregisterBtn.disabled = false;
          }
        });
        actions.appendChild(unregisterBtn);
      }

      checkbox.addEventListener("change", async () => {
        const nextEnabled = checkbox.checked;
        checkbox.disabled = true;
        try {
          const result = await callPluginBoardAction(getDbType(), {
            action: "toggle",
            plugin_id: item.id,
            enabled: nextEnabled ? "1" : "0",
          });
          if (result && result.success) {
            statusText.textContent = nextEnabled ? T("사용 중", "In use") : T("중지됨", "Stopped");
            showToast(result.message || T("상태가 변경되었습니다.", "Status changed."), false);
          } else {
            checkbox.checked = !nextEnabled; // 실패 시 원상복구
            showToast((result && result.error) || T("상태 변경에 실패했습니다.", "Could not change the status."), true);
          }
        } catch (err) {
          checkbox.checked = !nextEnabled;
          showToast(T(`상태 변경 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the status change: ${err && err.message ? err.message : err}`), true);
        } finally {
          checkbox.disabled = false;
        }
      });
    }

    row.append(left, actions);
    return row;
  }

  function buildCard(item) {
    const card = document.createElement("article");
    card.className = "pb-card" + (item.error ? " pb-card-error" : "");
    card.dataset.type = item.type || "other";

    const head = document.createElement("div");
    head.className = "pb-card-head";

    const headMain = document.createElement("div");
    headMain.className = "pb-card-head-main";

    const iconBadge = buildCardIcon(item);

    const titleGroup = document.createElement("div");
    titleGroup.className = "pb-card-title-group";

    const owner = document.createElement("p");
    owner.className = "pb-card-owner";
    owner.textContent = item.owner ? `${item.owner} / ${item.id}` : (item.id || "");

    const title = document.createElement("h2");
    title.className = "pb-card-title";
    title.textContent = item.title || "";

    titleGroup.append(owner, title);
    headMain.append(iconBadge, titleGroup);
    head.appendChild(headMain);

    // 설정(⚙) 버튼은 설치 여부·하단 관리 행 유무와 무관하게 항상 카드 헤더
    // 우측 상단 같은 자리에 고정한다(찾기 쉽게). 단, 관리자가 아니면 애초에
    // 표시하지 않는다(백엔드도 동일 기준으로 관리 액션 자체를 거부함).
    if (item.installed && item.has_config && isAdmin) {
      const headGearBtn = document.createElement("button");
      headGearBtn.type = "button";
      headGearBtn.className = "pb-icon-btn pb-card-head-gear";
      headGearBtn.title = T("환경설정", "Settings");
      headGearBtn.innerHTML = GEAR_ICON;
      headGearBtn.addEventListener("click", () => {
        const dbType = getDbType();
        wireSettingsSave(dbType);
        openSettingsModal(item, dbType);
      });
      head.appendChild(headGearBtn);
    }

    const desc = document.createElement("p");
    desc.className = "pb-card-desc";
    desc.textContent = item.desc || "";

    const tagsWrap = document.createElement("div");
    tagsWrap.className = "pb-card-tags";

    // 분류 태그(검색형/탭형/기타)를 항상 첫 태그로 표시
    const typeTag = document.createElement("span");
    typeTag.className = "pb-tag pb-tag-type";
    typeTag.textContent = item.type_label || T("기타", "Other");
    tagsWrap.appendChild(typeTag);

    // 카테고리 탭 UI 플러그인이 사이드바에서 몇 번째로 표시되는지(order 값).
    // 0도 유효한 순서 값이므로 falsy 체크 대신 타입으로 존재 여부를 판단한다.
    if (typeof item.tab_order === "number") {
      const orderTag = document.createElement("span");
      orderTag.className = "pb-tag pb-tag-order";
      orderTag.title = T("사이드바 카테고리 탭에서의 표시 순서 (숫자가 작을수록 앞에 표시됩니다)", "Display order in the sidebar category tabs (smaller numbers come first)");
      orderTag.textContent = `ORDER ${item.tab_order}`;
      tagsWrap.appendChild(orderTag);
    }

    if (item.has_update) {
      const updTag = document.createElement("span");
      updTag.className = "pb-tag pb-tag-update";
      updTag.textContent = T("업데이트 가능", "Update available");
      tagsWrap.appendChild(updTag);
    }

    if (item.id === "plugin_board") {
      const selfTag = document.createElement("span");
      selfTag.className = "pb-tag pb-tag-self";
      selfTag.textContent = T("이 플러그인게시판", "This plugin board");
      tagsWrap.appendChild(selfTag);
    }

    if (item.discovered) {
      const discTag = document.createElement("span");
      if (item.installed) {
        // 이미 이 서버에 설치되어 사용 중인 플러그인이라면 "설치 전 검토하라"는
        // 경고("미검수")는 더 이상 맞지 않는다 — 정적 검증을 통과해 이미 설치된
        // 상태이므로, 출처만 알려주는 중립적인 표기로 바꾼다.
        discTag.className = "pb-tag pb-tag-registered";
        discTag.title = T("GitHub Topics 검색으로 발견되어 이 서버에 설치되어 있는 플러그인입니다.", "Found by the GitHub Topics search and installed on this server.");
        discTag.textContent = T("토픽 발견 · 설치됨", "Topic found · installed");
      } else {
        discTag.className = "pb-tag pb-tag-discovered";
        discTag.title = T("GitHub Topics로 자동 발견된 저장소입니다. 별도 검수를 거치지 않았으니 설치 전 내용을 직접 확인하세요.", "Repository found automatically through GitHub Topics. It has not been reviewed, so check its contents yourself before installing.");
        discTag.textContent = T("토픽 발견 (미설치)", "Topic found (not installed)");
      }
      tagsWrap.appendChild(discTag);
    }

    if (item.admin_only) {
      const adminTag = document.createElement("span");
      adminTag.className = "pb-tag pb-tag-local";
      adminTag.title = T("admin_only로 선언된 플러그인 — 관리자에게만 표시됩니다.", "Declared admin_only — shown to administrators only.");
      adminTag.textContent = T("관리자 전용", "Admin only");
      tagsWrap.appendChild(adminTag);
    }

    if (item.user_registered) {
      const regTag = document.createElement("span");
      regTag.className = "pb-tag pb-tag-registered";
      regTag.title = T("GitHub Topics로는 발견되지 않았지만, 이 서버에서 Git URL로 직접 설치한 이력이 있어 계속 추적 중인 저장소입니다.", "Not found through GitHub Topics, but still tracked because it was installed on this server from a Git URL.");
      regTag.textContent = T("직접 설치됨", "Installed directly");
      tagsWrap.appendChild(regTag);
    }

    if (item.local_only) {
      const localTag = document.createElement("span");
      localTag.className = "pb-tag pb-tag-local";
      localTag.title = T("GitHub 저장소 정보 없이, 이 서버에 설치된 파일에서만 확인한 플러그인입니다.", "Plugin known only from the files installed on this server, without GitHub repository information.");
      localTag.textContent = T("로컬플러그인", "Local plugin");
      tagsWrap.appendChild(localTag);
    }

    (item.tags || []).forEach((tagText) => {
      const tag = document.createElement("span");
      tag.className = "pb-tag pb-tag-topic";
      tag.textContent = "#" + tagText; // GitHub Topics 출처임을 해시태그 표기로 구분 (textContent로만 삽입, XSS 방지)
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

    // [PATCH-5] 이력 버튼 — 이 서버 기록 + 저장소 변경 내용(관리자 전용)
    if (isAdmin && !item.notice) {
      const histBtn = document.createElement("button");
      histBtn.type = "button";
      histBtn.className = "pb-link pb-history-btn";
      histBtn.innerHTML = HISTORY_ICON;
      histBtn.appendChild(document.createTextNode(T("이력", "History")));
      histBtn.title = item.has_update
        ? T("업데이트로 바뀌는 내용과 이 서버의 설치 이력 보기", "See what this update changes and this server's install history")
        : T("변경 내용과 이 서버의 설치 이력 보기", "See the changes and this server's install history");
      histBtn.addEventListener("click", () => openHistoryModal(item));
      btnGroup.appendChild(histBtn);
    }

    // GitHub/Gitea 저장소 주소를 모르는(local_only) 항목은 이 버튼을 표시하지 않음
    if (item.url) {
      const link = document.createElement("a");
      link.className = "pb-link";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.innerHTML = item.gitea ? `${GITEA_ICON}Gitea` : `${GITHUB_ICON}GitHub`;
      btnGroup.appendChild(link);
    }

    // 설치됨+최신 상태에서는 "설치됨 · vX.X.X" 배지가 버전을 이미 보여주므로,
    // 상단 버전 스탬프를 또 붙이면 같은 버전이 두 번 표시된다. 그 경우에만 생략한다.
    const showStamp = !(item.installed && !item.has_update);
    const footLeft = document.createElement("div");
    footLeft.className = "pb-foot-left";
    if (showStamp) {
      footLeft.appendChild(stamp);
    }
    // GitHub 다운로드 횟수는 API로 구할 수 없어(비소유 저장소의 클론/다운로드
    // 통계는 GitHub가 비공개로 막아둠) 참고용 인기도 지표인 별(star) 개수로
    // 대신 보여준다. GitHub/Gitea 응답에 이미 포함된 값이라 추가 호출이 없다.
    if (item.stars !== null && item.stars !== undefined) {
      const starsEl = document.createElement("span");
      starsEl.className = "pb-stars";
      starsEl.innerHTML = `${STAR_ICON}${formatStars(item.stars)}`;
      starsEl.title = T(`별(star) ${item.stars.toLocaleString()}개 — 다운로드 횟수가 아닌 참고용 인기도 지표입니다`, `${item.stars.toLocaleString()} stars — a popularity hint, not a download count`);
      footLeft.appendChild(starsEl);
    }
    // 최종 업데이트 일자 — GitHub/Gitea면 저장소의 마지막 코드 푸시 시각, 로컬
    // 전용(local_only) 카드면 원격 정보가 없어 설치 폴더의 마지막 수정 시각을
    // 근사치로 대신 쓴다(item.local_only로 구분해 안내 문구만 다르게 표시).
    const pushedAtText = formatPushedAt(item.pushed_at);
    if (pushedAtText) {
      const pushedEl = document.createElement("span");
      pushedEl.className = "pb-pushed-at";
      pushedEl.textContent = T(`최종 업데이트 ${pushedAtText}`, `Last updated ${pushedAtText}`);
      pushedEl.title = item.local_only
        ? T("이 서버에 설치된 폴더가 마지막으로 바뀐 시각입니다 (원격 저장소 정보를 알 수 없어 근사치로 표시).", "When the folder installed on this server last changed (shown as an approximation since the remote repository is unknown).")
        : T("GitHub/Gitea 저장소에 마지막으로 코드가 반영된(push) 시각입니다.", "When code was last pushed to the GitHub/Gitea repository.");
      footLeft.appendChild(pushedEl);
    }
    if (footLeft.childNodes.length > 0) {
      foot.appendChild(footLeft);
    }
    foot.appendChild(btnGroup);

    const parts = [head];
    if (item.desc) parts.push(desc);
    parts.push(tagsWrap);
    if ((item.features || []).length > 0) parts.push(feats);
    parts.push(foot);
    // plugin_board 자기 자신은 삭제/비활성화가 백엔드에서 항상 거부되므로
    // 관리 행(스위치·삭제) 자체를 표시하지 않는다. 설정(⚙) 버튼은 이제
    // 카드 헤더 우측 상단에 항상 고정 표시되므로 이 행과는 무관하다.
    // 관리자가 아니면 이 행 전체(활성화 스위치·삭제)도 표시하지 않는다 —
    // 백엔드도 동일 기준으로 toggle/delete 요청을 거부한다.
    // [PATCH-10] plugin_board 자신도 "자동 업데이트 안 함" 체크박스를 쓰도록 관리 행을 표시한다
    // (자기 카드에서는 스위치·삭제·주소 버튼은 buildManageRow 안에서 계속 숨겨진다).
    if (item.installed && isAdmin) {
      parts.push(buildManageRow(item));
    }
    card.append(...parts);
    return card;
  }

  function render() {
    gridEl.innerHTML = "";
    const items = allItems.filter((it) => {
      if (activeOwner !== "all" && (it.owner || "") !== activeOwner) return false;
      if (activeFilter === "all") return true;
      if (activeFilter === "uninstalled") return !it.installed;
      if (activeFilter === "catalog") return !!it.in_catalog;
      return it.type === activeFilter;
    });
    if (items.length === 0) {
      const empty = document.createElement("p");
      empty.className = "pb-status";
      empty.textContent = T("해당 분류의 플러그인이 없습니다.", "No plugins in this category.");
      gridEl.appendChild(empty);
      return;
    }
    items.forEach((item) => gridEl.appendChild(buildCard(item)));
  }

  // 제작자(activeOwner) 선택에 따라 달라지는 숫자들 — 상단 집계 박스, 그리고
  // "미설치 (N)"/"카탈로그 (N)" 버튼 라벨 — 만 다시 계산해 갱신한다. 필터
  // 버튼 자체(활성 상태·클릭 핸들러)는 그대로 두고 텍스트만 바꾼다. 제작자
  // 드롭다운 자체의 항목별 개수(예: "javara999 (7)")는 전체 데이터 기준
  // 절대값이라 여기서 건드리지 않는다(별도로 buildFiltersAndTally에서 계산).
  function refreshOwnerScopedCounts() {
    const baseItems =
      activeOwner === "all" ? allItems : allItems.filter((it) => (it.owner || "") === activeOwner);

    const counts = {};
    baseItems.forEach((it) => {
      const t = it.type || "other";
      counts[t] = (counts[t] || 0) + 1;
    });
    const installedCount = baseItems.filter((it) => it.installed).length;
    const uninstalledCount = baseItems.length - installedCount;
    const uninstalledDiscoveredCount = baseItems.filter((it) => it.discovered && !it.installed).length;
    const catalogCount = baseItems.filter((it) => it.in_catalog).length;

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
    addTally(baseItems.length, T("등록 플러그인", "Registered plugins"));
    addTally(installedCount, T("이 서버에 설치됨", "Installed on this server"));
    if (uninstalledDiscoveredCount > 0) {
      addTally(uninstalledDiscoveredCount, T("토픽 발견(미검수)", "Found by topic (unreviewed)"));
    }
    Object.keys(counts).sort().forEach((t) => {
      const item = allItems.find((it) => it.type === t);
      addTally(counts[t], (item && item.type_label) || t);
    });

    const uninstalledBtn = filtersEl.querySelector('[data-filter="uninstalled"]');
    if (uninstalledBtn) uninstalledBtn.textContent = T(`미설치 (${uninstalledCount})`, `Not installed (${uninstalledCount})`);

    if (catalogTopic) {
      const catalogBtn = filtersEl.querySelector('[data-filter="catalog"]');
      if (catalogBtn) catalogBtn.textContent = T(`카탈로그 (${catalogCount})`, `Catalog (${catalogCount})`);
    }
  }

  // 실제 데이터에 존재하는 type만으로 필터 버튼과 집계를 동적으로 구성한다.
  function buildFiltersAndTally() {
    const counts = {};
    allItems.forEach((it) => {
      const t = it.type || "other";
      counts[t] = (counts[t] || 0) + 1;
    });
    const types = Object.keys(counts).sort();

    // 필터 버튼 — 숫자가 들어가는 "카탈로그"/"미설치" 라벨은 임시로 만들어두고,
    // 아래 refreshOwnerScopedCounts()가 마지막에 실제 값으로 채운다(제작자
    // 필터에 따라 값이 달라지므로 한 곳에서만 계산한다).
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

    filtersEl.appendChild(makeBtn("all", T("전체", "All"), true));
    if (catalogTopic) {
      // 카탈로그 토픽이 설정돼 있을 때만 탭을 노출한다 — 설정 안 하면 탭 자체가 없다.
      filtersEl.appendChild(makeBtn("catalog", T("카탈로그", "Catalog"), false));
    }
    types.forEach((t) => {
      const item = allItems.find((it) => it.type === t);
      filtersEl.appendChild(makeBtn(t, (item && item.type_label) || t, false));
    });
    // "설치 여부"는 type과 별개 축이라 마지막에 별도 필터로 추가한다.
    filtersEl.appendChild(makeBtn("uninstalled", T("미설치", "Not installed"), false));

    // 제작자별 필터 — owner 값 종류가 많아질 수 있어 버튼 나열 대신 드롭다운으로
    // 구성한다. activeFilter(분류/설치여부)와는 별개 축이라 AND로 함께 적용된다.
    const ownerCounts = {};
    allItems.forEach((it) => {
      if (it.owner) ownerCounts[it.owner] = (ownerCounts[it.owner] || 0) + 1;
    });
    const owners = Object.keys(ownerCounts).sort((a, b) => a.localeCompare(b));

    ownerFilterWrapEl.innerHTML = "";
    if (owners.length > 0) {
      const label = document.createElement("label");
      label.className = "pb-owner-filter-label";
      label.textContent = T("제작자", "Author");
      label.htmlFor = "pb-owner-filter-select";

      const select = document.createElement("select");
      select.id = "pb-owner-filter-select";
      select.className = "pb-owner-filter-select";

      const allOpt = document.createElement("option");
      allOpt.value = "all";
      allOpt.textContent = T(`전체 제작자 (${allItems.length})`, `All authors (${allItems.length})`);
      select.appendChild(allOpt);

      owners.forEach((owner) => {
        const opt = document.createElement("option");
        opt.value = owner;
        opt.textContent = `${owner} (${ownerCounts[owner]})`;
        select.appendChild(opt);
      });

      // 이전에 선택돼 있던 제작자가 이번 데이터에도 여전히 있으면 유지하고,
      // 없어졌으면(예: 그 제작자의 마지막 플러그인을 방금 삭제) "전체"로 되돌린다.
      activeOwner = owners.includes(activeOwner) ? activeOwner : "all";
      select.value = activeOwner;

      select.addEventListener("change", () => {
        activeOwner = select.value;
        refreshOwnerScopedCounts();
        render();
      });

      ownerFilterWrapEl.append(label, select);
    } else {
      activeOwner = "all";
    }

    // 위에서 activeOwner가 최종 확정된 뒤(제작자 목록에 없어져 "전체"로
    // 되돌아간 경우 포함) 집계/버튼 숫자를 채운다.
    refreshOwnerScopedCounts();
  }

  // 헤더 제목("플러그인게시판") 옆에 plugin_board 자기 자신의 현재 설치된
  // 버전을 표시한다. 값이 없으면(설치 확인 자체가 안 된 극단적 상황) 조용히 숨긴다.
  // 규약 검사에 막힌 플러그인 (설정 '플러그인 규약 위반 알림 보낼 곳'이 '알리지 않음'이면 서버가 빈 목록을 준다)
  function showContractProblems(list) {
    const el = document.getElementById("pb-contract-box");
    if (!el) return;
    list = Array.isArray(list) ? list : [];
    el.hidden = !list.length;
    el.textContent = "";
    if (!list.length) return;
    const head = document.createElement("div");
    head.className = "pb-contract-title";
    head.textContent = T("규약 검사를 통과하지 못해 설치·업데이트가 막힌 플러그인", "Plugins whose install or update was stopped by the rule check") + ` (${list.length})`;
    el.appendChild(head);
    list.forEach((p) => {
      const row = document.createElement("details");
      row.className = "pb-contract-row";
      const sum = document.createElement("summary");
      const code = document.createElement("code");
      code.textContent = p.id;
      sum.appendChild(code);
      if (p.at) sum.appendChild(document.createTextNode(" · " + new Date(p.at * 1000).toLocaleString()));
      row.appendChild(sum);
      const pre = document.createElement("div");
      pre.className = "pb-contract-items";
      pre.textContent = (p.items || []).join("\n");
      row.appendChild(pre);
      el.appendChild(row);
    });
    const note = document.createElement("div");
    note.className = "pb-contract-note";
    note.textContent = T("고쳐진 버전으로 다시 설치하거나 플러그인을 지우면 사라집니다. 알릴 곳은 환경설정 > 플러그인 설정 > 플러그인게시판에서 바꿉니다.",
      "It disappears once a fixed version is installed or the plugin is deleted. Change where this is shown in Settings > Plugin settings > Plugin Board.");
    el.appendChild(note);
  }

  function showTitleVersion(version) {
    const el = document.getElementById("pb-title-version");
    if (!el) return;
    if (!version) {
      el.hidden = true;
      return;
    }
    el.textContent = "v" + version;
    el.hidden = false;
  }

  // 마지막으로 GitHub Topics를 실제로 검색한 시각을 헤더에 표시한다. 캐시가
  // 살아있어 재검색을 안 한 경우에도 이전 검색 시각이 그대로 남아있으므로,
  // "지금 이 카드 목록이 몇 분 전 정보인지"를 사용자가 가늠할 수 있게 한다.
  function showTopicSearchTime(epochSeconds, topics) {
    const el = document.getElementById("pb-topic-search-time");
    if (!el) return;
    // [PATCH-8] 설정한 추가 발견/카탈로그 토픽이 실제로 검색에 들어갔는지 화면에서 확인할 수 있게 한다
    const topicsText = Array.isArray(topics) && topics.length ? T(` · 검색 토픽: ${topics.join(", ")}`, ` · topics searched: ${topics.join(", ")}`) : "";
    if (!epochSeconds) {
      if (topicsText) {
        el.textContent = `🔍${topicsText}`;
        el.hidden = false;
      } else {
        el.hidden = true;
      }
      return;
    }
    const date = new Date(epochSeconds * 1000);
    const diffMs = Date.now() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);

    let relative;
    if (diffMin < 1) relative = T("방금 전", "just now");
    else if (diffMin < 60) relative = T(`${diffMin}분 전`, `${diffMin} min ago`);
    else {
      const diffHour = Math.floor(diffMin / 60);
      relative = diffHour < 24 ? T(`${diffHour}시간 전`, `${diffHour} h ago`) : T(`${Math.floor(diffHour / 24)}일 전`, `${Math.floor(diffHour / 24)} days ago`);
    }

    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    el.textContent = T(`🔍 토픽 검색: ${relative} (${hh}:${mm} 기준, 최대 1시간마다 자동 갱신)${topicsText}`, `🔍 Topic search: ${relative} (as of ${hh}:${mm}, refreshed automatically at most hourly)${topicsText}`);
    el.hidden = false;
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
      isAdmin = json.is_admin === true; // 명시적으로 true일 때만 관리자로 간주(fail-closed)
      catalogTopic = typeof json.catalog_topic === "string" ? json.catalog_topic : "";

      const gitPanel = document.getElementById("pb-git-panel");
      if (gitPanel) gitPanel.hidden = !isAdmin; // 설치도 관리자만 가능하므로 패널 자체를 숨김
      const zipPanel = document.getElementById("pb-zip-panel");
      if (zipPanel) zipPanel.hidden = !isAdmin;
      const resetCacheBtn = document.getElementById("pb-reset-cache-btn");
      if (resetCacheBtn) resetCacheBtn.hidden = !isAdmin; // 캐시 초기화도 관리자 전용
      const refreshBtn = document.getElementById("pb-refresh-list-btn");
      if (refreshBtn) refreshBtn.hidden = !isAdmin; // 캐시 비우기(=GitHub 재조회)도 관리자 전용
      const historyAllBtn = document.getElementById("pb-history-all-btn");
      if (historyAllBtn) historyAllBtn.hidden = !isAdmin; // 설치 이력도 관리자 전용
      statusEl.hidden = true;
      gridEl.hidden = false;
      buildFiltersAndTally();
      render();
      showTopicSearchTime(json.topic_search_at, json.searched_topics);
      showTitleVersion(json.plugin_board_version);
      showContractProblems(isAdmin ? json.contract_problems : []);

      const errorCount = allItems.filter((it) => it.error).length;
      console.log(
        `${LOG_PREFIX} 카드 ${allItems.length}개 렌더링 완료` +
          (errorCount ? T(` (GitHub 조회 실패 ${errorCount}건)`, ` (${errorCount} GitHub lookups failed)`) : "")
      );

      autoUpdateEnabledGlobal = !!json.auto_update_enabled;
      if (json.auto_update_enabled && isAdmin) {
        runAutoUpdates();
      }
    } catch (err) {
      console.error(`${LOG_PREFIX} 로드 실패:`, err);
      statusEl.textContent = T("플러그인 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.", "Could not load the plugin list. Please try again in a moment.");
      statusEl.classList.add("pb-error");
      statusEl.hidden = false;
      gridEl.hidden = true;
    }
  }

  // ------------------------------------------------------------------
  // 사용 중인(활성화된) 플러그인에 업데이트가 있으면 자동으로 설치한다.
  // 설정(⚙)의 "사용 중인 플러그인 자동 업데이트" 체크박스로만 켜지며 기본은
  // 꺼짐이다. 같은 세션에서 너무 자주 반복 실행되지 않도록 쿨다운을 둔다.
  // ------------------------------------------------------------------
  let autoUpdateInFlight = false;
  let lastAutoUpdateAt = 0;
  const AUTO_UPDATE_COOLDOWN_MS = 5 * 60 * 1000; // 5분

  async function runAutoUpdates() {
    if (autoUpdateInFlight) return;
    const now = Date.now();
    if (now - lastAutoUpdateAt < AUTO_UPDATE_COOLDOWN_MS) return;

    // [PATCH-10] "자동 업데이트 안 함"으로 체크한 플러그인은 대상에서 뺀다(백엔드도 한 번 더 거른다)
    const targets = allItems.filter(
      (it) => it.installed && it.enabled && it.has_update && it.url && !it.auto_update_skip
    );
    if (targets.length === 0) return;

    autoUpdateInFlight = true;
    lastAutoUpdateAt = now;
    const dbType = getDbType();
    const succeeded = [];
    const failed = [];

    console.log(`${LOG_PREFIX} 자동 업데이트 대상 ${targets.length}개:`, targets.map((it) => it.id));

    // 동시에 여러 저장소를 받으면 자원을 많이 쓰므로 순차적으로 하나씩 처리한다.
    for (const item of targets) {
      try {
        const result = await callPluginBoardAction(dbType, {
          action: "update",
          plugin_id: item.id,
          auto: true, // [PATCH-5] 이력에 "자동 업데이트"로 기록
          // git_url을 일부러 안 보낸다 — 화면 표시용 item.url은 자격증명이
          // 빠져 있어서, 그대로 보내면 github.txt 레지스트리에 저장된 자격증명
          // 포함 URL을 백엔드가 찾아 쓰지 못한다(git_url이 비어있을 때만 그
          // 조회가 동작함). plugin_id만 보내 백엔드가 직접 찾도록 한다.
        });
        if (result && result.success) {
          succeeded.push(item.title || item.id);
        } else {
          failed.push(item.title || item.id);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 자동 업데이트 실패 (${item.id}):`, err);
        failed.push(item.title || item.id);
      }
    }

    autoUpdateInFlight = false;

    if (succeeded.length > 0) {
      showToast(
        T(`자동 업데이트 완료: ${succeeded.join(", ")}`, `Auto-update done: ${succeeded.join(", ")}`) +
          (failed.length ? T(` (실패: ${failed.join(", ")})`, ` (failed: ${failed.join(", ")})`) : ""),
        false
      );
      load(); // 카드 상태 새로고침 (자동 업데이트이므로 강제 새로고침은 하지 않음)
    } else if (failed.length > 0) {
      showToast(T(`자동 업데이트 실패: ${failed.join(", ")}`, `Auto-update failed: ${failed.join(", ")}`), true);
    }
  }

  // ------------------------------------------------------------------
  // "Git 저장소 URL 설치" 패널 — GitHub Topics 검색에 아직 안 잡힌 임의의
  // 저장소도 URL만 입력하면 바로 설치할 수 있다(update_manifest 규격을
  // 따르는 저장소만). GitHub뿐 아니라 다른 호스트(Gitea 등)도 지원하며,
  // 인증이 필요하면 https://아이디:비밀번호@host/owner/repo 형식으로
  // URL에 직접 담는다.
  // ------------------------------------------------------------------
  function wireGitInstallPanel() {
    const form = document.getElementById("pb-git-install-form");
    const input = document.getElementById("pb-git-install-input");
    const btn = document.getElementById("pb-git-install-btn");
    if (!form || !input || !btn) return;

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const url = input.value.trim();
      if (!url) return;
      // GitHub뿐 아니라 어떤 호스트든(Gitea 등) 받아들인다. 자격증명이 담긴
      // https://아이디:비밀번호@host/owner/repo 형식도 통과해야 하므로, 호스트
      // 부분은 github.com으로 제한하지 않고 "owner/repo" 구조만 검사한다.
      if (!/^https?:\/\/[^/]+\/[^/]+\/[^/]+/i.test(url)) {
        showToast(
          T("올바른 저장소 주소를 입력해주세요. (예: https://github.com/user/repo 또는 ", "Enter a valid repository URL. (e.g. https://github.com/user/repo or ") +
            T("https://아이디:비밀번호@gitea.example.com/user/repo)", "https://user:password@gitea.example.com/user/repo)"),
          true
        );
        return;
      }

      const origText = btn.textContent;
      btn.disabled = true;
      input.disabled = true;
      btn.textContent = T("설치 중…", "Installing…");

      try {
        const result = await callPluginBoardAction(getDbType(), {
          action: "install_git",
          git_url: url,
        });
        if (result && result.success) {
          input.value = "";
          reloadAfterInstall(result.message || T("설치가 완료되었습니다.", "Installation complete."));
        } else {
          showToast((result && result.error) || T("설치에 실패했습니다.", "Installation failed."), true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} Git URL 설치 오류:`, err);
        showToast(T(`설치 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the install request: ${err && err.message ? err.message : err}`), true);
      } finally {
        btn.disabled = false;
        input.disabled = false;
        btn.textContent = origText;
      }
    });
  }

  // ------------------------------------------------------------------
  // "ZIP 파일 업로드 설치" 패널 — VERSION + 파이썬 코드가 담긴 zip을 base64로
  // 인코딩해 install_zip 액션으로 보낸다. plugin_manager의 파일 선택 버튼
  // 패턴(숨긴 input + 텍스트 표시용 버튼)을 그대로 따른다.
  // ------------------------------------------------------------------
  const PB_SUPPORTED_ARCHIVE_RE = /\.(zip|tar|tar\.gz|tgz|tar\.bz2|tbz2|tar\.xz|txz|7z)$/i;
  const PB_ARCHIVE_DEFAULT_LABEL = T("압축 파일 선택…", "Choose an archive…");

  function wireZipInstallPanel() {
    const form = document.getElementById("pb-zip-install-form");
    const fileInput = document.getElementById("pb-zip-file-input");
    const selectBtn = document.getElementById("pb-zip-file-select-btn");
    const fileLabel = document.getElementById("pb-zip-file-label");
    const installBtn = document.getElementById("pb-zip-install-btn");
    if (!form || !fileInput || !selectBtn || !fileLabel || !installBtn) return;

    selectBtn.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (file) {
        fileLabel.textContent = file.name;
        selectBtn.classList.add("pb-zip-file-selected");
      } else {
        fileLabel.textContent = PB_ARCHIVE_DEFAULT_LABEL;
        selectBtn.classList.remove("pb-zip-file-selected");
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        showToast(T("설치할 압축 파일을 먼저 선택해주세요.", "Choose an archive to install first."), true);
        return;
      }
      if (!PB_SUPPORTED_ARCHIVE_RE.test(file.name)) {
        showToast(
          T("지원하지 않는 압축 형식입니다. zip / tar / tar.gz / tar.bz2 / tar.xz / 7z 파일만 업로드할 수 있습니다.", "Unsupported archive format. Only zip / tar / tar.gz / tar.bz2 / tar.xz / 7z files can be uploaded."),
          true
        );
        return;
      }

      const origText = installBtn.textContent;
      installBtn.disabled = true;
      selectBtn.disabled = true;
      installBtn.textContent = T("설치 중…", "Installing…");

      try {
        const zipDataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(reader.error || new Error(T("파일을 읽지 못했습니다.", "Could not read the file.")));
          reader.readAsDataURL(file);
        });

        const result = await callPluginBoardAction(getDbType(), {
          action: "install_zip", // 액션 이름은 하위 호환용, 파일명 확장자로 형식을 판별한다
          zip_data: zipDataUrl, // "data:...;base64,XXXX" 형태 — 백엔드가 접두어를 알아서 제거
          filename: file.name,
        });

        if (result && result.success) {
          fileInput.value = "";
          fileLabel.textContent = PB_ARCHIVE_DEFAULT_LABEL;
          selectBtn.classList.remove("pb-zip-file-selected");
          reloadAfterInstall(result.message || T("설치가 완료되었습니다.", "Installation complete."));
        } else {
          showToast((result && result.error) || T("설치에 실패했습니다.", "Installation failed."), true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} ZIP 설치 오류:`, err);
        showToast(T(`설치 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the install request: ${err && err.message ? err.message : err}`), true);
      } finally {
        installBtn.disabled = false;
        selectBtn.disabled = false;
        installBtn.textContent = origText;
      }
    });
  }

  // ------------------------------------------------------------------
  // "목록 새로고침" 버튼 — 캐시(최대 1시간) 만료를 기다리지 않고 GitHub Topics
  // 검색 결과를 즉시 다시 불러온다. 실제 설치 상태에는 영향 없음(순수 목록 재조회).
  // ------------------------------------------------------------------
  function wireRefreshListButton() {
    const btn = document.getElementById("pb-refresh-list-btn");
    if (!btn) return;

    btn.addEventListener("click", async () => {
      const origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add("pb-refresh-spinning");

      try {
        const result = await callPluginBoardAction(getDbType(), { action: "refresh_list" });
        if (result && result.success) {
          showToast(result.message || T("목록을 새로 불러왔습니다.", "List reloaded."), false);
          await load();
        } else {
          showToast((result && result.error) || T("목록을 새로 불러오지 못했습니다.", "Could not reload the list."), true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 목록 새로고침 오류:`, err);
        showToast(T(`새로고침 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the refresh request: ${err && err.message ? err.message : err}`), true);
      } finally {
        btn.disabled = false;
        btn.classList.remove("pb-refresh-spinning");
        btn.innerHTML = origHtml;
      }
    });
  }

  // ------------------------------------------------------------------
  // "캐시 초기화" 버튼 — 목록 새로고침(메모리 캐시만 비움)보다 더 강한 초기화.
  // 캐시 파일(plugins/data/plugin_board/cache.json)과 공유 캐시를 삭제한다. 목록에 이상한/중복된 항목이 계속 남아
  // 있는 등 캐시 문제로 의심될 때, 재시작 없이 바로 완전히 새로 불러오는 용도.
  // ------------------------------------------------------------------
  function wireResetCacheButton() {
    const btn = document.getElementById("pb-reset-cache-btn");
    if (!btn) return;

    btn.addEventListener("click", async () => {
      if (
        !window.confirm(
          T("캐시 파일과 공유 캐시를 삭제하고 완전히 새로 불러올까요?\n", "Delete the cache file and the shared cache and reload everything?\n") +
            T("설치된 플러그인에는 영향이 없으며, GitHub 정보만 다시 조회합니다.", "Installed plugins are not affected; only the GitHub information is fetched again.")
        )
      ) {
        return;
      }
      const origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add("pb-refresh-spinning");

      try {
        const result = await callPluginBoardAction(getDbType(), { action: "reset_cache" });
        if (result && result.success) {
          showToast(result.message || T("캐시를 초기화했습니다.", "Cache cleared."), false);
          await load();
        } else {
          showToast((result && result.error) || T("캐시 초기화에 실패했습니다.", "Could not clear the cache."), true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 캐시 초기화 오류:`, err);
        showToast(T(`캐시 초기화 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, `Error while handling the cache reset request: ${err && err.message ? err.message : err}`), true);
      } finally {
        btn.disabled = false;
        btn.classList.remove("pb-refresh-spinning");
        btn.innerHTML = origHtml;
      }
    });
  }


  wireRefreshListButton();
  wireResetCacheButton();
  const globalHistoryBtn = document.getElementById("pb-history-all-btn");
  if (globalHistoryBtn) globalHistoryBtn.addEventListener("click", () => openHistoryModal(null));
  wireGitInstallPanel();
  wireZipInstallPanel();
  load();
})();
