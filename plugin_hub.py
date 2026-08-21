# -*- coding: utf-8 -*-
"""
플러그인 허브 (Plugin Hub) 플러그인.

설치된 카테고리 레벨 플러그인들(예: 11t / HYB / KH / MangaDex / TK / Wolf Viewer)의
카테고리 뷰를 하나의 화면에서 각 플러그인 이름의 탭으로 구분해 통합 표시한다.

동작 원리:
- 허브 자체는 모든 세션(sessions: all)에 노출된다.
- 설정에서 뷰어별·세션별 체크박스(SHOW_<plugin_id>__<session>)로
  "이 보관함의 허브에 표시"를 선택한다 (기본: 꺼짐 = 기존 개별 탭 유지).
- 하나라도 통합 표시로 선택된 플러그인은 category_tab 을 런타임 디스크립터로
  오버라이드하여 사이드바 개별 탭에서 실시간으로 숨긴다.
- 프론트엔드는 get_dashboard_data 로 현재 세션의 탭 목록을 받고,
  각 뷰어의 UI 번들은 /api/media/plugins/<id>/ui 로 조회해 직접 마운트한다.
"""

import json

from plugins.metadata.base import BaseMetadataProvider

SELF_ID = "plugin_hub"

_SESSION_LABELS = {
    "general": "일반",
    "adult": "성인",
    "audiobook": "오디오",
    "video": "비디오",
}

# 런타임 category_tab 오버라이드 원본 보관: {plugin_id: 원본 category_tab dict}
_ORIG_TABS = {}


def _self_installed():
    """플러그인 허브 자신이 아직 설치되어 있는지 확인 (삭제 시 자가 복구용)."""
    import os

    return os.path.isdir(os.path.dirname(os.path.abspath(__file__)))


def _load_general_config(force_refresh=False):
    """4개 세션 DB(general/adult/audiobook/video) 중 PLUGIN_CONFIG_plugin_hub가
    가장 최근에 저장(updated_at 최신)된 DB의 설정을 통째로 사용한다.

    코어 저장 API(save-config)는 항상 전체 config 스냅샷을 통째로 덮어쓰고,
    그 스냅샷이 어느 DB(general/adult/...)에 쓰이는지는 저장 당시 관리자가 보고 있던
    라이브러리 세션(state.currentLibraryType)에 따라 달라진다. 예전에는 4개 DB를
    무조건 general→adult→audiobook→video 순서로 키 단위 병합했는데, 이러면 "최신 저장"이
    아니라 그냥 "반복문에서 나중에 도는 DB"가 항상 이겨버려서, 예를 들어 예전에 audiobook
    세션에서 저장했던 오래된 값이 방금 general 세션에서 한 새 저장을 덮어써버리는 버그가 있었다.
    updated_at 타임스탬프를 직접 비교해 진짜 최신 저장을 골라야 한다."""
    try:
        from services.plugin_db_gateway import PluginDatabaseGateway
    except Exception:
        return {}

    best_data = {}
    best_ts = None
    for session in ("general", "adult", "audiobook", "video"):
        try:
            gw = PluginDatabaseGateway(session)
            row = gw.fetch_one(
                "SELECT `value`, `updated_at` FROM settings WHERE `key` = ?",
                (f"PLUGIN_CONFIG_{SELF_ID}",),
            )
            if not row:
                continue
            raw_val = row["value"]
            raw_ts = row["updated_at"]
            try:
                data = json.loads(raw_val)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if best_ts is None or (raw_ts is not None and raw_ts >= best_ts):
                best_ts = raw_ts
                best_data = data
        except Exception:
            continue
    return best_data


def _tab_sessions(tab):
    if not isinstance(tab, dict):
        return ["general"]
    raw = tab.get("sessions")
    if raw is None:
        return ["general"]
    if isinstance(raw, str):
        if raw.strip().lower() == "all":
            return list(_SESSION_LABELS.keys())
        raw = [raw]
    if isinstance(raw, (list, tuple, set)):
        valid = [str(x).strip().lower() for x in raw if str(x).strip().lower() in _SESSION_LABELS]
        return valid or ["general"]
    return ["general"]


def _session_order(config, session):
    """설정에 저장된 세션별 탭 순서(TAB_ORDER_<session>: 콤마 구분 id 목록)를 파싱."""
    raw = config.get(f"TAB_ORDER_{session}", "")
    if not isinstance(raw, str):
        return []
    return [s for s in (x.strip() for x in raw.split(",")) if s]


def _sort_by_order(items, order, name_key):
    """order 목록에 있는 항목은 그 순서대로, 없는 항목은 뒤에 이름순으로."""
    pos = {p_id: i for i, p_id in enumerate(order)}
    known = [it for it in items if it["id"] in pos]
    rest = [it for it in items if it["id"] not in pos]
    known.sort(key=lambda it: pos[it["id"]])
    rest.sort(key=lambda it: str(it.get(name_key) or "").lower())
    return known + rest


def _is_on(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "off", "no", "")


_MODE_MERGE = "merge"
_MODE_HIDE = "hide"
_MODE_NORMAL = ""  # 기본값: 허브에도 안 넣고, 개별 사이드바 탭도 그대로 유지


def _get_mode(config, p_id, session):
    """세션별 3가지 모드 중 하나를 읽는다: 'merge'(허브에 합치기) / 'hide'(완전히 숨기기) / ''(기본, 그대로 표시).
    저장 키: MODE_<plugin_id>__<session>. 과거 버전의 불리언 SHOW_<id>__<session> 값도
    하위 호환으로 인식한다(True/'1' 등 켜져 있었으면 'merge'로 취급)."""
    raw = config.get(f"MODE_{p_id}__{session}")
    if raw in (_MODE_MERGE, _MODE_HIDE):
        return raw
    # 하위 호환: 예전 체크박스(SHOW_) 값이 남아있으면 merge로 승격
    legacy = config.get(f"SHOW_{p_id}__{session}")
    if legacy is not None and _is_on(legacy):
        return _MODE_MERGE
    return _MODE_NORMAL


def _unified_sessions_for(config, p_id, sessions):
    """설정에서 이 플러그인이 허브에 통합 표시되도록('merge') 선택된 세션 목록."""
    return [s for s in sessions if _get_mode(config, p_id, s) == _MODE_MERGE]


def _hidden_sessions_for(config, p_id, sessions):
    """설정에서 이 플러그인이 완전히 숨겨지도록('hide') 선택된 세션 목록."""
    return [s for s in sessions if _get_mode(config, p_id, s) == _MODE_HIDE]


def _non_normal_sessions_for(config, p_id, sessions):
    """'merge' 또는 'hide' — 즉 개별 사이드바 탭이 더 이상 기본 상태가 아닌 세션 목록.
    두 모드 다 개별 탭은 숨겨야 하므로(merge=허브 안으로, hide=완전 숨김) 하나로 묶어서 쓴다."""
    return [s for s in sessions if _get_mode(config, p_id, s) in (_MODE_MERGE, _MODE_HIDE)]


_DEFAULT_EXCLUDED_IDS = "bookoasis_plugins_viewer"


def _excluded_ids(config):
    """설정에 저장된 제외 플러그인 id 목록(EXCLUDED_IDS: 콤마 구분).
    키 자체가 아직 저장된 적이 없으면(한 번도 저장 안 함) 기본값으로 원본
    '플러그인 모아보기'(bookoasis_plugins_viewer)를 제외한다 — 허브 안에
    또 다른 통합 뷰어(허브)가 탭으로 들어가는 걸 막기 위함. 저장 화면에서
    빈 문자열로 명시적으로 저장하면(키는 존재, 값만 빈 문자열) 제외 없음으로 취급된다."""
    raw = config.get("EXCLUDED_IDS", _DEFAULT_EXCLUDED_IDS)
    if not isinstance(raw, str):
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}


def _current_request_session():
    """Flask request context에서 현재 요청 세션(db_type)을 추출한다."""
    try:
        from flask import request

        if request:
            s = request.args.get("type") or request.form.get("type")
            if not s and request.is_json:
                data = request.get_json(silent=True) or {}
                s = data.get("type")
            if s and str(s).strip().lower() in _SESSION_LABELS:
                return str(s).strip().lower()
    except Exception:
        pass
    return None


class _DynamicPluginCategoryTab:
    """개별 플러그인의 category_tab 동적 디스크립터.

    세션별 3가지 모드:
      - 'merge'  : 허브 탭 안으로 통합 표시. 개별 사이드바 탭은 숨김.
      - 'hide'   : 허브에도 안 넣고, 개별 사이드바 탭도 완전히 숨김.
      - '' (기본): 손대지 않음. 개별 사이드바 탭 그대로 노출.
    즉 'merge'/'hide' 둘 다 개별 탭은 숨겨야 하므로 판정 자체는 동일하게 처리한다.
    """

    def __init__(self, plugin_id, orig_tab):
        self.plugin_id = plugin_id
        self._orig = orig_tab

    def __get__(self, obj, objtype=None):
        if not _self_installed():
            return self._orig
        try:
            _discover_viewer_classes()
            config = _load_general_config()
            sessions = _tab_sessions(self._orig)
            req_session = _current_request_session()
            if req_session:
                if req_session in sessions and _get_mode(config, self.plugin_id, req_session) in (
                    _MODE_MERGE,
                    _MODE_HIDE,
                ):
                    return None
            else:
                non_normal = _non_normal_sessions_for(config, self.plugin_id, sessions)
                if non_normal and len(non_normal) == len(sessions):
                    return None
        except Exception:
            pass
        return self._orig


def _is_plugin_enabled(p_id):
    """코어 표준 계약: general 스코프의 PLUGIN_ENABLED_<id> 설정 (PluginDatabaseGateway.get_setting 사용).

    PluginDatabaseGateway.get_setting(key, default)은:
      - 값이 DB에 있으면 {"value": <실제값>} 형태의 dict를 반환
      - 값이 없으면 default 인자를 그대로(가공 없이) 반환
    이 형태를 정확히 언랩해야 하며, 그냥 str()로 비교하면 dict 문자열과
    비교하게 되어 절대 매치되지 않는다 (실제로 이 버그로 정지 판별이 항상 실패했었음).

    코어(services/metadata_factory.py, plugin_service.py)와 동일하게
    '명시적으로 0이 저장된 경우에만 비활성'으로 판정한다. 값이 없거나 '1'이거나
    그 외 값이면 전부 활성으로 간주한다. 조회 자체가 실패해도 안전하게 활성으로 간주한다."""
    try:
        from services.plugin_db_gateway import PluginDatabaseGateway

        gw = PluginDatabaseGateway("general")
        row = gw.get_setting(f"PLUGIN_ENABLED_{p_id}", default=None)
        if row is None:
            return True
        val = row.get("value") if isinstance(row, dict) else row
        if val is None:
            return True
        return str(val).strip() != "0"
    except Exception:
        return True


def _discover_viewer_classes():
    """category_tab 을 가진 (자신 제외, 설정에서 제외 처리된 id 제외) 설치 플러그인 탐색 및 동적 디스크립터 바인딩.
    정지(비활성) 플러그인도 포함해서 반환하되 enabled 플래그로 구분한다
    (탭 목록에서는 제외하지만, 설정 카탈로그에서는 계속 보여주고 체크박스만 꺼둔 채로 노출하기 위함).
    단, EXCLUDED_IDS 에 든 id는 카탈로그에도 아예 나타나지 않는다(원본 '플러그인 모아보기' 등).

    각 플러그인 처리는 개별 try/except로 감싼다 — 예전에는 for 루프 전체가 하나의
    try/except였는데, 그러면 특정 플러그인 하나 처리 중 예외가 나면 그 뒤 순서의
    플러그인들은 통째로 처리가 안 되고 건너뛰어지는 문제가 있었다."""
    viewers = []
    try:
        from plugins.metadata.base import BaseMetadataProvider

        config = _load_general_config()
        excluded = _excluded_ids(config)
        all_subclasses = BaseMetadataProvider.__subclasses__()
    except Exception as e:
        print(f"[PluginHub] _discover_viewer_classes 초기화 실패: {e!r}", flush=True)
        return viewers

    seen = set()
    for target_class in all_subclasses:
        try:
            if not target_class:
                continue
            p_id = getattr(target_class, "id", None)
            if not p_id or p_id == SELF_ID or p_id in seen or p_id in excluded:
                continue
            seen.add(p_id)

            orig_tab = None
            desc = None
            for klass in type.mro(target_class):
                if "category_tab" in klass.__dict__:
                    desc = klass.__dict__["category_tab"]
                    break
            if desc is not None and hasattr(desc, "_orig"):
                orig_tab = desc._orig
            if not isinstance(orig_tab, dict):
                raw_tab = getattr(target_class, "category_tab", None)
                if isinstance(raw_tab, dict):
                    orig_tab = raw_tab
            if not isinstance(orig_tab, dict):
                continue

            _ORIG_TABS[p_id] = orig_tab

            # 모든 카테고리 뷰어 플러그인의 category_tab을 _DynamicPluginCategoryTab으로 감싸기
            if not isinstance(desc, _DynamicPluginCategoryTab):
                target_class.category_tab = _DynamicPluginCategoryTab(p_id, orig_tab)

            p_name = orig_tab.get("title") or getattr(target_class, "name", p_id)
            enabled = _is_plugin_enabled(p_id)
            viewers.append((p_id, p_name, _tab_sessions(orig_tab), target_class, enabled))
        except Exception as e:
            print(f"[PluginHub] 플러그인 처리 중 예외 (target_class={target_class!r}): {e!r}", flush=True)
            continue
    return viewers


def _apply_session_overrides(force_refresh_config=False):
    """모든 타겟 뷰어 클래스 탐색 및 오버라이드 바인딩 적용."""
    _discover_viewer_classes()


def _read_plugin_version(p_id):
    """플러그인 폴더의 VERSION 파일에서 버전 문자열 파싱."""
    import os

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vpath = os.path.join(base_dir, p_id, "VERSION")
        if not os.path.isfile(vpath):
            return ""
        with open(vpath, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return ""
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k in ("plugin version", "version", "VERSION"):
                    if k in data:
                        return str(data[k]).strip()
                for v in data.values():
                    return str(v).strip()
            return str(data).strip()
        except (ValueError, TypeError):
            pass
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                return line.split(":", 1)[1].strip().strip('"')
            return line.strip('"')
    except Exception:
        pass
    return ""


class _DynamicCategoryTab:
    """코어가 허브의 category_tab 을 읽는 시점(사이드바 렌더 등)에
    다른 뷰어들의 표시 오버라이드를 재적용한다."""

    _TAB = {
        "title": "플러그인 허브",
        "icon": "fa-solid fa-object-group",
        "order": 89,
        "sessions": "all",
    }

    def __get__(self, obj, objtype=None):
        _apply_session_overrides()
        return dict(self._TAB)


class _DynamicConfigSchema:
    """설정 페이지 접근 시점에 설치된 뷰어 x 세션 셀렉트 스키마 생성.
    실제 UI는 settings.html/settings.js가 그리지만, 코어가 "설정 있음" 배지 판정 등에
    이 스키마 존재 여부를 참고하므로 최신 키 형식(MODE_)에 맞춰 계속 채워둔다."""

    def __get__(self, obj, objtype=None):
        _apply_session_overrides()
        schema = []
        for p_id, p_name, sessions, _cls, _enabled in _discover_viewer_classes():
            for s in sessions:
                label_session = _SESSION_LABELS.get(s, s)
                schema.append(
                    {
                        "key": f"MODE_{p_id}__{s}",
                        "label": f"{p_name} — {label_session}",
                        "type": "select",
                        "required": False,
                        "default": "",
                        "options": [
                            {"value": "", "label": "기본(개별 탭 그대로)"},
                            {"value": _MODE_MERGE, "label": "허브에 합치기"},
                            {"value": _MODE_HIDE, "label": "완전히 숨기기"},
                        ],
                        "description": (
                            f"{label_session} 보관함에서 {p_name}({p_id})를 어떻게 표시할지 선택합니다. "
                            "'허브에 합치기'와 '완전히 숨기기' 둘 다 개별 사이드바 탭은 숨겨집니다."
                        ),
                    }
                )
        if not schema:
            schema.append(
                {
                    "key": "_NO_VIEWERS",
                    "label": "표시할 카테고리 뷰 플러그인 없음",
                    "type": "text",
                    "required": False,
                    "default": "",
                    "description": "카테고리 뷰 플러그인이 설치되면 여기에 표시 여부 옵션이 나타납니다.",
                }
            )
        return schema


class PluginHubMetadataProvider(BaseMetadataProvider):
    id = "plugin_hub"
    name = "플러그인 허브"
    is_searchable = False
    config_schema = []
    category_tab = {
        "title": "플러그인 허브",
        "icon": "fa-solid fa-object-group",
        "order": 89,
        "sessions": "all",
    }

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/yume-script/plugin_hub/refs/heads/main/",
        "files": [
            "plugin_hub.py",
            "__init__.py",
            "VERSION",
            "index.html",
            "style.css",
            "script.js",
            "settings.html",
            "settings.css",
            "settings.js",
            "README.md",
        ],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": False,
    }

    def search(self, db_type, query):
        return []

    def apply(self, db_type, book_id, item_data):
        return False, "플러그인 허브는 메타데이터 적용 기능을 제공하지 않습니다."

    def get_dashboard_data(self, db_type, limit=10):
        """현재 세션(db_type)의 허브 탭 목록 반환."""
        _apply_session_overrides(force_refresh_config=True)
        config = _load_general_config()
        session = str(db_type or "general").strip().lower()

        discovered = _discover_viewer_classes()

        # 탭 목록: 정지된 플러그인은 제외
        tabs = []
        for p_id, p_name, sessions, _cls, enabled in discovered:
            if not enabled:
                continue
            picked = _unified_sessions_for(config, p_id, sessions)
            if session not in picked:
                continue
            tab = _ORIG_TABS.get(p_id) or {}
            tabs.append(
                {
                    "id": p_id,
                    "title": p_name,
                    "icon": (tab.get("icon") if isinstance(tab, dict) else None)
                    or "fa-solid fa-puzzle-piece",
                    "order": int((tab.get("order") if isinstance(tab, dict) else 50) or 50),
                }
            )
        tabs = _sort_by_order(tabs, _session_order(config, session), "title")

        # 설정 카탈로그: 정지된 플러그인도 목록에는 계속 노출한다.
        # 모드 값은 항상 "실제 저장된 값" 그대로 보여준다(강제 초기화 금지) — save-config API가
        # 전체 config JSON을 통째로 덮어쓰는 방식이라, 여기서 강제로 값을 바꿔 보여주면
        # 사용자가 저장 버튼을 누르는 순간 원래 선택값이 영구 소실된다. 대신 프론트(settings.js)에서
        # enabled=False인 카드는 조작만 막아(값은 유지) 재설정 없이도 다시 켜면 그대로 복원되게 한다.
        catalog = []
        for p_id, p_name, sessions, _cls, enabled in discovered:
            modes = {s: (_get_mode(config, p_id, s) or "normal") for s in sessions}
            catalog.append(
                {
                    "id": p_id,
                    "name": p_name,
                    "version": _read_plugin_version(p_id),
                    "sessions": sessions,
                    "modes": modes,
                    "enabled": enabled,
                }
            )
        catalog.sort(key=lambda x: x["name"].lower())

        orders = {s: _session_order(config, s) for s in _SESSION_LABELS}
        excluded_ids_str = str(config.get("EXCLUDED_IDS", _DEFAULT_EXCLUDED_IDS))

        return {
            "success": True,
            "viewers": tabs,
            "catalog": catalog,
            "orders": orders,
            "excluded_ids": excluded_ids_str,
        }


# 검증기 통과용 리터럴 선언을 런타임 동적 디스크립터로 교체
PluginHubMetadataProvider.config_schema = _DynamicConfigSchema()
PluginHubMetadataProvider.category_tab = _DynamicCategoryTab()

# 모듈 로드 즉시 오버라이드 적용 (모든 대상 플러그인 category_tab을 실시간 디스크립터로 즉시 감쌈)
try:
    _apply_session_overrides(force_refresh_config=True)
except Exception:
    pass
