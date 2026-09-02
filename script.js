// plugins/metadata/plugin_board/script.js
(function () {
  const PLUGIN_ID = "plugin_board";
  const LOG_PREFIX = "[Plugin-Board]";

  const statusEl = document.getElementById("pb-status");
  const gridEl = document.getElementById("pb-grid");
  const filtersEl = document.getElementById("pb-filters");
  const tallyEl = document.getElementById("pb-tally");
  const ownerFilterWrapEl = document.getElementById("pb-owner-filter-wrap");

  let allItems = [];
  let isAdmin = true; // 서버 응답을 받기 전 기본값 — 응답에서 갱신됨
  let activeFilter = "all";
  let activeOwner = "all"; // 제작자별 필터 — activeFilter(분류/설치여부)와 별개 축, AND로 결합

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
    showToast((message || "설치가 완료되었습니다.") + " 잠시 후 페이지를 새로고침합니다…", false);
    setTimeout(hardReloadPage, 1200); // 토스트 메시지를 읽을 시간을 준 뒤 새로고침
  }

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

  // 카드 종류별 아이콘 — 직접 그리지 않고 Lucide 아이콘(ISC 라이선스, 자유 재사용
  // 가능)의 실제 path를 그대로 사용한다. 필채우기가 아니라 선(stroke) 기반이라
  // 다른 아이콘들과 속성이 다르다.
  const LUCIDE_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  const TYPE_ICON_SEARCH = // lucide "search"
    `<svg ${LUCIDE_ATTRS}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`;
  const TYPE_ICON_TAB = // lucide "layout-grid"
    `<svg ${LUCIDE_ATTRS}><rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/></svg>`;
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
    }
    badge.className = "pb-card-icon " + modifier;
    badge.innerHTML = markup;
    return badge;
  }

  // ------------------------------------------------------------------
  // 신규설치/업데이트/활성화·비활성화/삭제 액션 — 전부 plugin_board 자신의
  // apply()를 호출한다 (source: "plugin_board"). 외부 플러그인 불필요.
  // ------------------------------------------------------------------
  async function callPluginBoardAction(dbType, actionData, timeoutMs = 60000) {
    let res;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      res = await fetch("/api/media/books/0/apply-metadata", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: dbType,
          source: PLUGIN_ID,
          item_data: actionData,
        }),
        signal: controller.signal,
      });
    } catch (networkErr) {
      if (networkErr && networkErr.name === "AbortError") {
        // 브라우저가 응답을 아예 못 받고 있는 상태 — openresty의 기본 500 페이지처럼
        // 프록시가 백엔드와의 연결이 끊긴 경우 이쪽으로 잡히는 경우가 많다.
        return {
          success: false,
          error:
            `요청이 ${Math.round(timeoutMs / 1000)}초 안에 응답을 받지 못해 중단했습니다. ` +
            "서버가 아직 처리 중이거나 타임아웃/충돌했을 수 있습니다. 파일이 크다면 크기를 줄이거나 " +
            "Git 저장소 URL 설치를 대신 사용해보세요. 잠시 후 새로고침해 실제로 설치됐는지도 확인해보세요.",
        };
      }
      // fetch 자체가 실패(오프라인, DNS, CORS 등) — 서버 응답조차 못 받은 경우
      return {
        success: false,
        error: `서버에 연결하지 못했습니다: ${networkErr && networkErr.message ? networkErr.message : networkErr}`,
      };
    } finally {
      clearTimeout(timer);
    }

    let bodyText = "";
    try {
      bodyText = await res.text();
    } catch (readErr) {
      return { success: false, error: `응답 본문을 읽지 못했습니다 (HTTP ${res.status}).` };
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
          hint = " 파일이 너무 커서 서버(또는 앞단 프록시)가 요청을 거부한 것으로 보입니다.";
        } else if (res.status === 502 || res.status === 504) {
          hint = " 서버(백엔드)와 프록시 사이의 연결/응답 지연 문제로 보입니다.";
        } else if (
          res.status === 500 &&
          /openresty|nginx/i.test(snippet) &&
          !/traceback|werkzeug/i.test(snippet)
        ) {
          hint =
            " 프록시가 보여주는 기본 오류 페이지입니다 — plugin_board 코드가 아니라 " +
            "백엔드 프로세스가 타임아웃되었거나 요청 처리 중 다운되었을 가능성이 높습니다. " +
            "서버(Gunicorn/Flask) 로그를 확인해주세요.";
        } else if (res.status >= 500) {
          hint = " 서버 내부 오류로 보입니다.";
        }
        return {
          success: false,
          error: `서버가 올바른 응답을 반환하지 않았습니다 (HTTP ${res.status}).${hint}` +
            (snippet ? ` 응답 일부: ${snippet}` : ""),
        };
      }
    }

    if (!res.ok && (!json || typeof json.success === "undefined")) {
      return {
        success: false,
        error: (json && (json.error || json.message)) || `요청이 실패했습니다 (HTTP ${res.status}).`,
      };
    }

    return json || { success: false, error: "서버로부터 빈 응답을 받았습니다." };
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

    if (!isAdmin) {
      // 관리자가 아니면 백엔드도 설치/업데이트 요청을 거부하므로, 눌러서
      // 오류를 보게 하는 대신 처음부터 비활성 안내로 대체한다.
      const badge = document.createElement("span");
      badge.className = "pb-installed-badge pb-installed-badge-muted";
      badge.innerHTML = item.installed
        ? `${UPDATE_ICON}업데이트 필요 (관리자 전용)`
        : `${INSTALL_ICON}미설치 (관리자 전용)`;
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
          // 업데이트일 때는 화면에 보이는 URL(item.url)을 보내지 않는다 — 이 값은
          // 카드 표시용으로 자격증명을 뺀 주소라서, 그대로 보내면 백엔드가
          // github.txt 레지스트리에 저장된 자격증명 포함 URL을 찾아 쓰는 폴백
          // 로직이 아예 발동하지 않는다(git_url이 비어있을 때만 그 폴백이
          // 동작하므로). 신규설치일 때만 방금 알아낸 URL을 그대로 전달한다.
          ...(isUpdate ? {} : { git_url: item.url }),
        });

        if (result && result.success) {
          reloadAfterInstall(result.message || `'${item.title}' 처리가 완료되었습니다.`);
        } else {
          showToast((result && result.error) || "요청이 실패했습니다.", true);
          btn.disabled = false;
          btn.innerHTML = originalHtml;
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 설치/업데이트 오류:`, err);
        showToast(`설치/업데이트 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
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
    modal.innerHTML = `
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
    `;
    document.body.appendChild(modal);

    const close = () => modal.classList.remove("pb-modal-show");
    modal.addEventListener("click", (e) => {
      if (e.target === modal) close();
    });
    modal.querySelector("#pb-settings-modal-close").addEventListener("click", close);
    modal.querySelector("#pb-settings-modal-cancel").addEventListener("click", close);
    return modal;
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
    labelEl.innerHTML = `${label} ${requiredMark}`;
    wrap.appendChild(labelEl);

    if (type === "checkbox") {
      const row = document.createElement("label");
      row.className = "pb-field-checkbox-row";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = key;
      input.checked = currentValue === true || currentValue === "1" || currentValue === 1 || currentValue === "true";
      row.append(input, document.createTextNode(" 사용"));
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
        toggleBtn.title = "값 표시/숨기기";
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

    titleEl.textContent = `${item.title} (${item.id}) 설정`;
    bodyEl.innerHTML = '<p class="pb-status" style="padding:24px 0;">설정 정보를 불러오는 중…</p>';
    modal.classList.add("pb-modal-show");

    try {
      const res = await fetch("/api/media/metadata/plugins/manage");
      const data = await res.json();
      if (!data || data.success === false || !data.plugins) {
        throw new Error((data && data.error) || "플러그인 설정 정보를 가져오지 못했습니다.");
      }
      const p = data.plugins.find((x) => x.id === item.id);
      if (!p) throw new Error("선택한 플러그인 정보를 찾을 수 없습니다.");

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
        empty.textContent = "이 플러그인은 별도의 설정 항목이 없습니다.";
        bodyEl.appendChild(empty);
        saveBtn.hidden = true;
        return;
      }

      saveBtn.hidden = false;
      const form = document.createElement("form");
      form.id = "pb-settings-form";
      form.dataset.pluginId = item.id;
      schema.forEach((field) => form.appendChild(renderSchemaField(field, config[field.key])));
      bodyEl.appendChild(form);
    } catch (err) {
      bodyEl.innerHTML = "";
      const errorEl = document.createElement("p");
      errorEl.className = "pb-status pb-error";
      errorEl.style.padding = "24px 0";
      errorEl.textContent = err.message || "설정 정보를 불러오지 못했습니다.";
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
      form.querySelectorAll("input, select").forEach((input) => {
        if (!input.name) return;
        config[input.name] = input.type === "checkbox" ? !!input.checked : String(input.value ?? "").trim();
      });

      const orig = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.textContent = "저장 중…";
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
          showToast(data.message || "설정이 저장되었습니다.", false);
          modal.classList.remove("pb-modal-show");
        } else {
          showToast((data && data.error) || "설정 저장에 실패했습니다.", true);
        }
      } catch (err) {
        saveBtn.disabled = false;
        saveBtn.textContent = orig;
        showToast(`설정 저장 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
      }
    });
  }

  // ------------------------------------------------------------------
  // 관리 행 — 활성화/비활성화 스위치 + 환경설정(gear) + 삭제(trash).
  // 이미 설치된 카드에만 표시된다.
  // ------------------------------------------------------------------
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
      statusText.textContent = item.enabled ? "사용 중" : "중지됨";

      left.append(switchLabel, statusText);
    }

    const actions = document.createElement("div");
    actions.className = "pb-manage-actions";

    if (!isSelf) {
      const trashBtn = document.createElement("button");
      trashBtn.type = "button";
      trashBtn.className = "pb-icon-btn pb-icon-btn-danger";
      trashBtn.title = "삭제";
      trashBtn.innerHTML = TRASH_ICON;
      trashBtn.addEventListener("click", async () => {
        if (!window.confirm(`'${item.title}' 플러그인을 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) {
          return;
        }
        trashBtn.disabled = true;
        try {
          const result = await callPluginBoardAction(getDbType(), {
            action: "delete",
            plugin_id: item.id,
          });
          if (result && result.success) {
            showToast(result.message || `'${item.title}'이(가) 삭제되었습니다.`, false);
            load();
          } else {
            showToast((result && result.error) || "삭제에 실패했습니다.", true);
            trashBtn.disabled = false;
          }
        } catch (err) {
          showToast(`삭제 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
          trashBtn.disabled = false;
        }
      });
      actions.appendChild(trashBtn);

      // Git URL로 직접 설치한 이력이 있는 카드(user_registered)에만 "Git 주소
      // 변경"/"등록 해제" 버튼을 보여준다 — GitHub Topics 발견 카드나 로컬 전용
      // 플러그인은 애초에 github.txt 레지스트리 항목이 아니라 대상이 아니다.
      // 원본 저장소가 이름/owner/호스트를 옮겼거나(주소 변경) 아예 삭제된
      // 경우(등록 해제)에 대한 대응 수단이다.
      if (item.user_registered) {
        const editUrlBtn = document.createElement("button");
        editUrlBtn.type = "button";
        editUrlBtn.className = "pb-icon-btn";
        editUrlBtn.title = "Git 주소 변경 (저장소가 다른 곳으로 옮겨간 경우)";
        editUrlBtn.innerHTML = EDIT_ICON;
        editUrlBtn.addEventListener("click", async () => {
          const currentUrl = item.url || "";
          const input = window.prompt(
            `'${item.title}'의 새 Git 저장소 주소를 입력하세요.\n` +
              "(저장소가 다른 계정/호스트로 옮겨갔거나 이름이 바뀐 경우 여기에 새 주소를 입력하면,\n" +
              " 재설치 없이 다음 '업데이트'부터 이 주소를 기준으로 확인합니다.)",
            currentUrl
          );
          if (input === null) return; // 취소
          const newUrl = input.trim();
          if (!newUrl) return;
          if (!/^https?:\/\/[^/]+\/[^/]+\/[^/]+/i.test(newUrl)) {
            showToast(
              "올바른 저장소 주소를 입력해주세요. (예: https://github.com/user/repo)",
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
              showToast(result.message || "Git 주소가 갱신되었습니다.", false);
              load();
            } else {
              showToast((result && result.error) || "Git 주소 갱신에 실패했습니다.", true);
            }
          } catch (err) {
            showToast(`Git 주소 갱신 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
          } finally {
            editUrlBtn.disabled = false;
          }
        });
        actions.appendChild(editUrlBtn);

        const unregisterBtn = document.createElement("button");
        unregisterBtn.type = "button";
        unregisterBtn.className = "pb-icon-btn";
        unregisterBtn.title = "등록 해제 (원본 저장소가 삭제된 경우 — 설치된 파일은 유지됩니다)";
        unregisterBtn.innerHTML = UNLINK_ICON;
        unregisterBtn.addEventListener("click", async () => {
          if (
            !window.confirm(
              `'${item.title}'의 등록된 Git 주소를 목록에서 제거할까요?\n` +
                "설치된 플러그인 파일은 그대로 유지되며, 더 이상 이 주소로 업데이트를 확인하지 않습니다."
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
              showToast(result.message || "등록이 해제되었습니다.", false);
              load();
            } else {
              showToast((result && result.error) || "등록 해제에 실패했습니다.", true);
              unregisterBtn.disabled = false;
            }
          } catch (err) {
            showToast(`등록 해제 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
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
            statusText.textContent = nextEnabled ? "사용 중" : "중지됨";
            showToast(result.message || "상태가 변경되었습니다.", false);
          } else {
            checkbox.checked = !nextEnabled; // 실패 시 원상복구
            showToast((result && result.error) || "상태 변경에 실패했습니다.", true);
          }
        } catch (err) {
          checkbox.checked = !nextEnabled;
          showToast(`상태 변경 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
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
      headGearBtn.title = "환경설정";
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
    typeTag.textContent = item.type_label || "기타";
    tagsWrap.appendChild(typeTag);

    if (item.has_update) {
      const updTag = document.createElement("span");
      updTag.className = "pb-tag pb-tag-update";
      updTag.textContent = "업데이트 가능";
      tagsWrap.appendChild(updTag);
    }

    if (item.id === "plugin_board") {
      const selfTag = document.createElement("span");
      selfTag.className = "pb-tag pb-tag-self";
      selfTag.textContent = "이 플러그인게시판";
      tagsWrap.appendChild(selfTag);
    }

    if (item.discovered) {
      const discTag = document.createElement("span");
      if (item.installed) {
        // 이미 이 서버에 설치되어 사용 중인 플러그인이라면 "설치 전 검토하라"는
        // 경고("미검수")는 더 이상 맞지 않는다 — 정적 검증을 통과해 이미 설치된
        // 상태이므로, 출처만 알려주는 중립적인 표기로 바꾼다.
        discTag.className = "pb-tag pb-tag-registered";
        discTag.title = "GitHub Topics 검색으로 발견되어 이 서버에 설치되어 있는 플러그인입니다.";
        discTag.textContent = "토픽 발견 · 설치됨";
      } else {
        discTag.className = "pb-tag pb-tag-discovered";
        discTag.title = "GitHub Topics로 자동 발견된 저장소입니다. 별도 검수를 거치지 않았으니 설치 전 내용을 직접 확인하세요.";
        discTag.textContent = "토픽 발견 (미설치)";
      }
      tagsWrap.appendChild(discTag);
    }

    if (item.user_registered) {
      const regTag = document.createElement("span");
      regTag.className = "pb-tag pb-tag-registered";
      regTag.title = "GitHub Topics로는 발견되지 않았지만, 이 서버에서 Git URL로 직접 설치한 이력이 있어 계속 추적 중인 저장소입니다.";
      regTag.textContent = "직접 설치됨";
      tagsWrap.appendChild(regTag);
    }

    if (item.local_only) {
      const localTag = document.createElement("span");
      localTag.className = "pb-tag pb-tag-local";
      localTag.title = "GitHub 저장소 정보 없이, 이 서버에 설치된 파일에서만 확인한 플러그인입니다.";
      localTag.textContent = "로컬플러그인";
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
      starsEl.title = `별(star) ${item.stars.toLocaleString()}개 — 다운로드 횟수가 아닌 참고용 인기도 지표입니다`;
      footLeft.appendChild(starsEl);
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
    if (item.installed && item.id !== "plugin_board" && isAdmin) {
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
      return it.type === activeFilter;
    });
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
    const uninstalledCount = allItems.length - installedCount;
    // "미검수" 집계는 설치 전(=아직 검토가 필요한) 발견 카드만 센다. 이미 설치되어
    // 사용 중인 발견 카드는 카드 태그도 "설치됨"으로 바뀌므로 여기서도 제외한다.
    const uninstalledDiscoveredCount = allItems.filter((it) => it.discovered && !it.installed).length;

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
    if (uninstalledDiscoveredCount > 0) {
      addTally(uninstalledDiscoveredCount, "토픽 발견(미검수)");
    }
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
    // "설치 여부"는 type과 별개 축이라 마지막에 별도 필터로 추가한다.
    filtersEl.appendChild(makeBtn("uninstalled", `미설치 (${uninstalledCount})`, false));

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
      label.textContent = "제작자";
      label.htmlFor = "pb-owner-filter-select";

      const select = document.createElement("select");
      select.id = "pb-owner-filter-select";
      select.className = "pb-owner-filter-select";

      const allOpt = document.createElement("option");
      allOpt.value = "all";
      allOpt.textContent = `전체 제작자 (${allItems.length})`;
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
        render();
      });

      ownerFilterWrapEl.append(label, select);
    } else {
      activeOwner = "all";
    }
  }

  // 헤더 제목("플러그인게시판") 옆에 plugin_board 자기 자신의 현재 설치된
  // 버전을 표시한다. 값이 없으면(설치 확인 자체가 안 된 극단적 상황) 조용히 숨긴다.
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
  function showTopicSearchTime(epochSeconds) {
    const el = document.getElementById("pb-topic-search-time");
    if (!el) return;
    if (!epochSeconds) {
      el.hidden = true;
      return;
    }
    const date = new Date(epochSeconds * 1000);
    const diffMs = Date.now() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);

    let relative;
    if (diffMin < 1) relative = "방금 전";
    else if (diffMin < 60) relative = `${diffMin}분 전`;
    else {
      const diffHour = Math.floor(diffMin / 60);
      relative = diffHour < 24 ? `${diffHour}시간 전` : `${Math.floor(diffHour / 24)}일 전`;
    }

    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    el.textContent = `🔍 토픽 검색: ${relative} (${hh}:${mm} 기준, 최대 1시간마다 자동 갱신)`;
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
      isAdmin = json.is_admin !== false; // 명시적으로 false일 때만 비관리자로 간주

      const gitPanel = document.getElementById("pb-git-panel");
      if (gitPanel) gitPanel.hidden = !isAdmin; // 설치도 관리자만 가능하므로 패널 자체를 숨김
      const zipPanel = document.getElementById("pb-zip-panel");
      if (zipPanel) zipPanel.hidden = !isAdmin;
      const resetCacheBtn = document.getElementById("pb-reset-cache-btn");
      if (resetCacheBtn) resetCacheBtn.hidden = !isAdmin; // 캐시 초기화도 관리자 전용
      statusEl.hidden = true;
      gridEl.hidden = false;
      buildFiltersAndTally();
      render();
      showTopicSearchTime(json.topic_search_at);
      showTitleVersion(json.plugin_board_version);

      const errorCount = allItems.filter((it) => it.error).length;
      console.log(
        `${LOG_PREFIX} 카드 ${allItems.length}개 렌더링 완료` +
          (errorCount ? ` (GitHub 조회 실패 ${errorCount}건)` : "")
      );

      if (json.auto_update_enabled) {
        runAutoUpdates();
      }
    } catch (err) {
      console.error(`${LOG_PREFIX} 로드 실패:`, err);
      statusEl.textContent = "플러그인 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.";
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

    const targets = allItems.filter(
      (it) => it.installed && it.enabled && it.has_update && it.url
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
        `자동 업데이트 완료: ${succeeded.join(", ")}` +
          (failed.length ? ` (실패: ${failed.join(", ")})` : ""),
        false
      );
      load(); // 카드 상태 새로고침 (자동 업데이트이므로 강제 새로고침은 하지 않음)
    } else if (failed.length > 0) {
      showToast(`자동 업데이트 실패: ${failed.join(", ")}`, true);
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
          "올바른 저장소 주소를 입력해주세요. (예: https://github.com/user/repo 또는 " +
            "https://아이디:비밀번호@gitea.example.com/user/repo)",
          true
        );
        return;
      }

      const origText = btn.textContent;
      btn.disabled = true;
      input.disabled = true;
      btn.textContent = "설치 중…";

      try {
        const result = await callPluginBoardAction(getDbType(), {
          action: "install_git",
          git_url: url,
        });
        if (result && result.success) {
          input.value = "";
          reloadAfterInstall(result.message || "설치가 완료되었습니다.");
        } else {
          showToast((result && result.error) || "설치에 실패했습니다.", true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} Git URL 설치 오류:`, err);
        showToast(`설치 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
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
  const PB_ARCHIVE_DEFAULT_LABEL = "압축 파일 선택…";

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
        showToast("설치할 압축 파일을 먼저 선택해주세요.", true);
        return;
      }
      if (!PB_SUPPORTED_ARCHIVE_RE.test(file.name)) {
        showToast(
          "지원하지 않는 압축 형식입니다. zip / tar / tar.gz / tar.bz2 / tar.xz / 7z 파일만 업로드할 수 있습니다.",
          true
        );
        return;
      }

      const origText = installBtn.textContent;
      installBtn.disabled = true;
      selectBtn.disabled = true;
      installBtn.textContent = "설치 중…";

      try {
        const zipDataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(reader.error || new Error("파일을 읽지 못했습니다."));
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
          reloadAfterInstall(result.message || "설치가 완료되었습니다.");
        } else {
          showToast((result && result.error) || "설치에 실패했습니다.", true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} ZIP 설치 오류:`, err);
        showToast(`설치 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
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
          showToast(result.message || "목록을 새로 불러왔습니다.", false);
          await load();
        } else {
          showToast((result && result.error) || "목록을 새로 불러오지 못했습니다.", true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 목록 새로고침 오류:`, err);
        showToast(`새로고침 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
      } finally {
        btn.disabled = false;
        btn.classList.remove("pb-refresh-spinning");
        btn.innerHTML = origHtml;
      }
    });
  }

  // ------------------------------------------------------------------
  // "캐시 초기화" 버튼 — 목록 새로고침(메모리 캐시만 비움)보다 더 강한 초기화.
  // .cache.json 파일 자체를 삭제한다. 목록에 이상한/중복된 항목이 계속 남아
  // 있는 등 캐시 문제로 의심될 때, 재시작 없이 바로 완전히 새로 불러오는 용도.
  // ------------------------------------------------------------------
  function wireResetCacheButton() {
    const btn = document.getElementById("pb-reset-cache-btn");
    if (!btn) return;

    btn.addEventListener("click", async () => {
      if (
        !window.confirm(
          "캐시 파일(.cache.json)을 삭제하고 완전히 새로 불러올까요?\n" +
            "설치된 플러그인에는 영향이 없으며, GitHub 정보만 다시 조회합니다."
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
          showToast(result.message || "캐시를 초기화했습니다.", false);
          await load();
        } else {
          showToast((result && result.error) || "캐시 초기화에 실패했습니다.", true);
        }
      } catch (err) {
        console.error(`${LOG_PREFIX} 캐시 초기화 오류:`, err);
        showToast(`캐시 초기화 요청 처리 중 오류가 발생했습니다: ${err && err.message ? err.message : err}`, true);
      } finally {
        btn.disabled = false;
        btn.classList.remove("pb-refresh-spinning");
        btn.innerHTML = origHtml;
      }
    });
  }


  wireRefreshListButton();
  wireResetCacheButton();
  wireGitInstallPanel();
  wireZipInstallPanel();
  load();
})();
