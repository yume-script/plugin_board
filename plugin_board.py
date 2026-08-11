# -*- coding: utf-8 -*-
"""
plugin_board — BookOasis 카테고리 탭 플러그인

이 플러그인은 검색/메타데이터 적용 기능이 없는 순수 안내용(category_tab) 플러그인입니다.
좌측 사이드바에 "플러그인 목록장" 탭을 추가하고, 직접 만든 BookOasis 플러그인 저장소를
색인 카드 형태로 보여줍니다.

카드 내용(제목/설명/버전)은 코드에 직접 적어두지 않고, GitHub 저장소 주소만 저장한 뒤
화면을 열 때마다 GitHub API·raw 파일에서 실시간으로 가져옵니다.
  - 설명/토픽 : GitHub 저장소 API (api.github.com) — 시간당 60회 무인증 한도가 있어
    GITHUB_TOKEN 설정 시 한도가 크게 늘어납니다.
  - 최신 버전 : 각 저장소의 VERSION 파일 (raw.githubusercontent.com) — 이 가이드의
    자동 업데이트 규격을 따르는 저장소라면 별도 인증 없이 항상 최신값을 가져옵니다.

가이드 문서(플러그인 개발 가이드 §3, §5)의 계약을 따릅니다:
- 필수: search(), apply()
- 선택: category_tab, get_dashboard_data(), update_manifest
"""

import json
import re
import time
import urllib.error
import urllib.request

from plugins.metadata.base import BaseMetadataProvider


# ----------------------------------------------------------------------
# 새 플러그인을 추가하려면 GitHub 저장소 주소만 한 줄 추가하면 됩니다.
# 제목·설명·버전은 화면을 열 때 GitHub에서 자동으로 가져옵니다.
# ----------------------------------------------------------------------
GITHUB_REPOS = [
    "https://github.com/javara999/naverkakaoridi",
    "https://github.com/colaiuta77/achievements",
    "https://github.com/yume-script/pixiv_ranking",
    "https://github.com/yume-script/extract_isbn",
    "https://github.com/colaiuta77/activity",
    "https://github.com/colaiuta77/activity_desk",
    "https://github.com/colaiuta77/achievements",
    "https://github.com/yume-script/unified_book",
    "https://github.com/madnite1/plugin_manager",
]

# GitHub API/README만으로는 "검색형 메타데이터"인지 "카테고리 탭 UI"인지 구분할 수
# 없어서, 분류가 필요할 때만 owner/repo 키로 지정합니다. 지정하지 않으면 화면에서
# "기타" 분류로 표시됩니다 — 새 저장소를 추가할 때 반드시 채워야 하는 값은 아닙니다.
TYPE_OVERRIDES = {
    "javara999/naverkakaoridi": "search",
    "colaiuta77/achievements": "tab",
    "yume-script/pixiv_ranking": "tab",
    "yume-script/unified_book": "search",
}

TYPE_LABELS = {
    "search": "검색형 메타데이터",
    "tab": "카테고리 탭 UI",
    "other": "기타",
}

_CACHE = {}  # {"owner/repo": (timestamp, item_dict)}
_CACHE_TTL_SECONDS = 3600  # 1시간마다 GitHub에서 다시 조회
_REQUEST_TIMEOUT = 6


def _headers(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "BookOasis-Plugin-Board",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _http_get_json(url, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def _parse_owner_repo(url):
    m = re.search(r"github\.com/([^/]+)/([^/]+?)/?$", (url or "").strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _fetch_version_label(owner, repo, default_branch, token):
    """저장소의 VERSION 파일에서 최신 버전을 가져온다. default_branch 조회에
    실패한 경우를 대비해 main/master도 함께 시도한다."""
    branches = [b for b in (default_branch, "main", "master") if b]
    seen = set()
    for branch in branches:
        if branch in seen:
            continue
        seen.add(branch)
        raw_url = "https://raw.githubusercontent.com/%s/%s/%s/VERSION" % (
            owner, repo, branch,
        )
        try:
            data = json.loads(_http_get_text(raw_url, token))
            version = data.get("plugin version")
            if version:
                return "v" + str(version)
        except Exception:
            continue
    return "—"


def _fetch_repo_entry(url, token):
    owner, repo = _parse_owner_repo(url)
    if not owner or not repo:
        return {
            "id": url, "owner": "", "title": url, "type": "other",
            "type_label": TYPE_LABELS["other"],
            "desc": "저장소 주소를 해석하지 못했습니다.",
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
        }

    key = owner + "/" + repo
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    plugin_type = TYPE_OVERRIDES.get(key, "other")

    try:
        api_data = _http_get_json(
            "https://api.github.com/repos/%s/%s" % (owner, repo), token
        )
        version_label = _fetch_version_label(
            owner, repo, api_data.get("default_branch"), token
        )
        item = {
            "id": repo,
            "owner": owner,
            "title": repo,
            "type": plugin_type,
            "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
            "desc": api_data.get("description") or "(GitHub에 등록된 설명이 없습니다)",
            "tags": api_data.get("topics") or [],
            "features": [],
            "version_label": version_label,
            "url": api_data.get("html_url") or url,
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        # API 실패(예: rate limit) 시에도 VERSION만은 main/master 추정으로 시도
        version_label = _fetch_version_label(owner, repo, None, token)
        detail = "GitHub API 호출 제한 또는 오류(%s)" % exc.code
        item = {
            "id": repo, "owner": owner, "title": repo, "type": plugin_type,
            "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
            "desc": detail, "tags": [], "features": [],
            "version_label": version_label, "url": url, "error": True,
        }
    except Exception as exc:
        item = {
            "id": repo, "owner": owner, "title": repo, "type": plugin_type,
            "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
            "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
        }

    _CACHE[key] = (time.time(), item)
    return item


class PluginBoardMetadataProvider(BaseMetadataProvider):
    id = "plugin_board"
    name = "플러그인 목록장"
    is_searchable = False

    config_schema = [
        {
            "key": "GITHUB_TOKEN",
            "label": "GitHub Personal Access Token (선택)",
            "type": "password",
            "required": False,
        },
    ]

    # 좌측 사이드바 1등 시민 카테고리 메뉴로 등록
    category_tab = {
        "title": "플러그인 목록장",
        "icon": "fa-solid fa-layer-group",
        "order": 90,
    }

    # GitHub raw 기반 자동 업데이트 계약
    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": (
            "https://raw.githubusercontent.com/<org>/<repo>/<branch>/"
            "plugins/metadata/plugin_board"
        ),
        "files": [
            "plugin_board.py",
            "__init__.py",
            "VERSION",
            "index.html",
            "style.css",
            "script.js",
        ],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # ------------------------------------------------------------------
    # 필수 계약 — 이 플러그인은 검색/적용을 지원하지 않는 순수 안내용입니다.
    # ------------------------------------------------------------------
    def search(self, db_type, query):
        return {"success": True, "items": []}

    def apply(self, db_type, book_id, item_data):
        return False, "이 플러그인은 메타데이터 검색·적용을 지원하지 않습니다."

    # ------------------------------------------------------------------
    # 카테고리 풀페이지 탭이 script.js를 통해 호출하는 데이터 엔드포인트.
    # GITHUB_REPOS에 저장된 주소만으로 매 호출마다(캐시 만료 시) GitHub에서
    # 최신 설명·토픽·버전을 가져와 반환한다.
    # ------------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        token = cfg.get("GITHUB_TOKEN") or None
        items = [_fetch_repo_entry(url, token) for url in GITHUB_REPOS]
        return {"success": True, "items": items}
