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
      wrap.appendChild(input);
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
  function renderCustomSettingsUi(bodyEl, p, config) {
    const form = document.createElement("form");
    form.id = "pb-settings-form";
    form.dataset.pluginId = p.id;

    const root = document.createElement("div");
    root.className = "pb-settings-ui-root";
    root.innerHTML = p.settings_ui.html; // 플러그인 제작자가 제공하는 신뢰된 관리자용 UI

    form.appendChild(root);
    bodyEl.appendChild(form);

    if (p.settings_ui.css) {
      const styleEl = document.createElement("style");
      styleEl.textContent = p.settings_ui.css;
      root.appendChild(styleEl);
    }

    if (p.settings_ui.js) {
      try {
        const fn = new Function("window", "pluginId", "root", "config", p.settings_ui.js);
        fn(window, p.id, root, config);
      } catch (err) {
        console.error(`${LOG_PREFIX} settings.js 실행 오류 (${p.id}):`, err);
      }
    }

    // innerHTML로 삽입된 <script> 태그는 브라우저가 자동 실행하지 않으므로 직접 실행
    root.querySelectorAll("script").forEach((script) => {
      try {
        const fn = new Function("window", "pluginId", "root", "config", script.textContent);
        fn(window, p.id, root, config);
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
      const config = p.config || {};
      const hasCustomUi = !!(p.settings_ui && p.settings_ui.html);

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
    const row = document.createElement("div");
    row.className = "pb-manage-row";

    const left = document.createElement("div");
    left.className = "pb-manage-left";

    const switchLabel = document.createElement("label");
    switchLabel.className = "pb-switch";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !!item.enabled;
    const slider = document.createElement("span");
    slider.className = "pb-switch-slider";
    switchLabel.append(checkbox, slider);

    const statusText = document.createElement("span");
    statusText.className = "pb-manage-status";
    statusText.textContent = item.enabled ? "사용 중" : "중지됨";

    left.append(switchLabel, statusText);

    const actions = document.createElement("div");
    actions.className = "pb-manage-actions";

    if (item.has_config) {
      const gearBtn = document.createElement("button");
      gearBtn.type = "button";
      gearBtn.className = "pb-icon-btn";
      gearBtn.title = "환경설정";
      gearBtn.innerHTML = GEAR_ICON;
      gearBtn.addEventListener("click", () => {
        const dbType = getDbType();
        wireSettingsSave(dbType);
        openSettingsModal(item, dbType);
      });
      actions.appendChild(gearBtn);
    }

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

    row.append(left, actions);
    return row;
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

    if (item.id === "plugin_board") {
      const selfTag = document.createElement("span");
      selfTag.className = "pb-tag pb-tag-self";
      selfTag.textContent = "이 플러그인게시판";
      tagsWrap.appendChild(selfTag);
    }

    if (item.discovered) {
      const discTag = document.createElement("span");
      discTag.className = "pb-tag pb-tag-discovered";
      discTag.title = "plugin_list.txt에 등록되지 않고 GitHub Topics로 자동 발견된 저장소입니다. 별도 검수를 거치지 않았으니 설치 전 내용을 직접 확인하세요.";
      discTag.textContent = "⚠ 미검수 · 토픽 발견";
      tagsWrap.appendChild(discTag);
    }

    if (item.local_only) {
      const localTag = document.createElement("span");
      localTag.className = "pb-tag pb-tag-local";
      localTag.title = "GitHub 저장소 정보 없이, 이 서버에 설치된 파일에서만 확인한 플러그인입니다.";
      localTag.textContent = "[로컬플러그인]";
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

    // 설치됨+최신 상태에서는 "설치됨 · vX.X.X" 배지가 버전을 이미 보여주므로,
    // 상단 버전 스탬프를 또 붙이면 같은 버전이 두 번 표시된다. 그 경우에만 생략한다.
    const showStamp = !(item.installed && !item.has_update);
    if (showStamp) {
      foot.appendChild(stamp);
    }
    foot.appendChild(btnGroup);

    const parts = [head];
    if (item.desc) parts.push(desc);
    parts.push(tagsWrap);
    if ((item.features || []).length > 0) parts.push(feats);
    parts.push(foot);
    // plugin_board 자기 자신은 삭제/비활성화가 백엔드에서 항상 거부되므로,
    // 혼란을 주지 않도록 관리 행(스위치·삭제) 자체를 표시하지 않는다.
    if (item.installed && item.id !== "plugin_board") parts.push(buildManageRow(item));
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
    const discoveredCount = allItems.filter((it) => it.discovered).length;

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
    if (discoveredCount > 0) {
      addTally(discoveredCount, "토픽 발견(미검수)");
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

  // ------------------------------------------------------------------
  // "Git 저장소 URL 설치" 패널 — plugin_list.txt에 없는 임의의 GitHub 저장소도
  // URL만 입력하면 바로 설치할 수 있다(update_manifest 규격을 따르는 저장소만).
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
      if (!/^https?:\/\/github\.com\/[^/]+\/[^/]+/i.test(url)) {
        showToast("올바른 GitHub 저장소 주소를 입력해주세요. (예: https://github.com/user/repo)", true);
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
  // "목록 새로고침" 버튼 — 캐시(최대 1시간) 만료를 기다리지 않고 plugin_list.txt를
  // 즉시 다시 불러온다. 실제 설치 상태에는 영향 없음(순수 목록 재조회).
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


  wireRefreshListButton();
  wireGitInstallPanel();
  load();
})();
