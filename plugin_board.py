# -*- coding: utf-8 -*-
"""
plugin_board — BookOasis 카테고리 탭 플러그인

좌측 사이드바에 "플러그인 목록장" 탭을 추가하고, 직접 만든 BookOasis 플러그인 저장소를
색인 카드 형태로 보여준다. 카드 내용(설명·버전)은 코드에 직접 적어두지 않고 GitHub 저장소
주소만 저장한 뒤 화면을 열 때마다 실시간으로 가져온다.

이 버전부터는 외부 plugin_manager 플러그인 없이도 카드에서 바로 "신규설치"/"업데이트"를
수행할 수 있다. 설치 방식은 madnite1/plugin_manager가 쓰는 것과 동일한 원리를 그대로
가져왔다: git 바이너리 없이 GitHub codeload(zip) 소스를 받아, 대상 플러그인의
update_manifest를 AST로만(코드 실행 없이) 추출해 명시된 파일만 골라 설치한다.
(참고: https://github.com/madnite1/plugin_manager)

가이드 문서(플러그인 개발 가이드 §3, §5)의 계약을 따른다:
- 필수: search(), apply()
- 선택: category_tab, get_dashboard_data(), update_manifest
"""

import ast
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from plugins.metadata.base import BaseMetadataProvider


# ----------------------------------------------------------------------
# 새 플러그인을 추가하려면 GitHub 저장소 주소만 한 줄 추가하면 됩니다.
# 제목·설명·버전·설치 여부는 화면을 열 때 자동으로 채워집니다.
# ----------------------------------------------------------------------
GITHUB_REPOS = [
    "https://github.com/javara999/naverkakaoridi",
    "https://github.com/colaiuta77/achievements",
    "https://github.com/yume-script/pixiv_ranking",
    "https://github.com/yume-script/unified_book",
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
_DOWNLOAD_TIMEOUT = 30

_PLUGIN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


# ========================================================================
# 공통 HTTP 유틸
# ========================================================================
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
    m = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", (url or "").strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


# ========================================================================
# 로컬 설치 상태 확인 (plugins/metadata 디렉토리를 직접 조회 — 외부 플러그인 불필요)
# ========================================================================
def _plugins_metadata_dir():
    """plugins/metadata 루트 경로 (plugin_board 자신의 부모 디렉토리)"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_installed(plugin_id):
    return os.path.isdir(os.path.join(_plugins_metadata_dir(), plugin_id))


def _local_version(plugin_id):
    version_file = os.path.join(_plugins_metadata_dir(), plugin_id, "VERSION")
    if not os.path.isfile(version_file):
        return None
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("plugin version") or data.get("version")
    except Exception:
        return None


def _version_tuple(v):
    if not v:
        return None
    m = _VERSION_RE.match(str(v).strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def _remote_is_newer(local_v, remote_v):
    lt, rt = _version_tuple(local_v), _version_tuple(remote_v)
    if lt is None or rt is None:
        return False
    return rt > lt


def _fetch_remote_version(owner, repo, default_branch, token):
    """저장소의 VERSION 파일에서 최신 버전을 가져온다(원본 문자열, 'v' 접두사 없음)."""
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
                return str(version)
        except Exception:
            continue
    return None


def _fetch_repo_entry(url, token):
    owner, repo = _parse_owner_repo(url)
    if not owner or not repo:
        return {
            "id": url, "owner": "", "title": url, "type": "other",
            "type_label": TYPE_LABELS["other"],
            "desc": "저장소 주소를 해석하지 못했습니다.",
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
            "installed": False, "installed_version": None, "has_update": False,
        }

    key = owner + "/" + repo
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    plugin_type = TYPE_OVERRIDES.get(key, "other")
    installed = _is_installed(repo)
    installed_version = _local_version(repo) if installed else None

    try:
        api_data = _http_get_json(
            "https://api.github.com/repos/%s/%s" % (owner, repo), token
        )
        remote_version = _fetch_remote_version(
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
            "version_label": ("v" + remote_version) if remote_version else "—",
            "url": api_data.get("html_url") or url,
            "error": False,
            "installed": installed,
            "installed_version": installed_version,
            "has_update": installed and _remote_is_newer(installed_version, remote_version),
        }
    except urllib.error.HTTPError as exc:
        # API 실패(예: rate limit) 시에도 VERSION만은 main/master 추정으로 시도
        remote_version = _fetch_remote_version(owner, repo, None, token)
        item = {
            "id": repo, "owner": owner, "title": repo, "type": plugin_type,
            "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
            "desc": "GitHub API 호출 제한 또는 오류(%s)" % exc.code,
            "tags": [], "features": [],
            "version_label": ("v" + remote_version) if remote_version else "—",
            "url": url, "error": True,
            "installed": installed, "installed_version": installed_version,
            "has_update": installed and _remote_is_newer(installed_version, remote_version),
        }
    except Exception as exc:
        item = {
            "id": repo, "owner": owner, "title": repo, "type": plugin_type,
            "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
            "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
            "installed": installed, "installed_version": installed_version,
            "has_update": False,
        }

    _CACHE[key] = (time.time(), item)
    return item


# ========================================================================
# 설치/업데이트 엔진 — git 바이너리·plugin_manager 없이 codeload zip으로 처리
# (madnite1/plugin_manager와 동일한 원리: 릴리즈 대신 브랜치 우선순위,
#  update_manifest는 AST로만 추출해 코드 실행 없이 안전하게 읽는다)
# ========================================================================
def _validate_plugin_id(plugin_id):
    if not _PLUGIN_ID_RE.match(plugin_id or ""):
        raise ValueError("허용되지 않는 플러그인 ID입니다: %r" % plugin_id)


def _safe_join(base_dir, *parts):
    """경로 이탈(Path Traversal) 방지 — 결과 경로가 base_dir 하위인지 검증 후 반환."""
    base_norm = os.path.normpath(base_dir)
    target = os.path.normpath(os.path.join(base_dir, *parts))
    if target != base_norm and not target.startswith(base_norm + os.sep):
        raise ValueError("허용되지 않는 경로입니다(path traversal 감지): %s" % target)
    return target


def _download_zip(url, dest_path, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)


def _extract_zip_safe(zip_path, extract_dir):
    """Zip Slip 방지 — 모든 압축 해제 대상 경로가 extract_dir 하위인지 검증 후 해제."""
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            _safe_join(extract_dir, member)  # 경로 이탈 시 예외 발생
        zf.extractall(extract_dir)


def _find_extracted_root(extract_dir):
    entries = [
        e for e in os.listdir(extract_dir)
        if os.path.isdir(os.path.join(extract_dir, e))
    ]
    if len(entries) == 1:
        return os.path.join(extract_dir, entries[0])
    return extract_dir


def _extract_update_manifest(py_path):
    """대상 플러그인 .py 파일에서 update_manifest 딕셔너리를 AST로만 추출한다.
    코드를 import/exec 하지 않으므로 클론된 소스가 악의적이어도 실행되지 않는다."""
    if not os.path.isfile(py_path):
        return None
    try:
        with open(py_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=py_path)
    except Exception:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "update_manifest":
                            try:
                                return ast.literal_eval(stmt.value)
                            except Exception:
                                return None
    return None


def _candidate_branches(default_branch):
    branches = []
    for b in (default_branch, "main", "master"):
        if b and b not in branches:
            branches.append(b)
    return branches


def _try_hot_reload(plugin_id):
    """가능하면 코어의 hot reload를 호출해 서버 재시작 없이 즉시 반영을 시도한다.
    실패해도 설치 자체는 이미 완료된 상태이므로 조용히 무시한다."""
    try:
        from services.metadata_factory import MetadataFactory
        if hasattr(MetadataFactory, "hot_reload_plugin"):
            MetadataFactory.hot_reload_plugin(plugin_id)
            return True
    except Exception:
        pass
    return False


def _install_or_update(owner, repo, token=None):
    _validate_plugin_id(repo)

    default_branch = None
    try:
        api_data = _http_get_json(
            "https://api.github.com/repos/%s/%s" % (owner, repo), token
        )
        default_branch = api_data.get("default_branch")
    except Exception:
        pass

    last_error = None
    for branch in _candidate_branches(default_branch):
        zip_url = "https://codeload.github.com/%s/%s/zip/refs/heads/%s" % (
            owner, repo, branch,
        )
        tmp_dir = tempfile.mkdtemp(prefix="plugin_board_")
        try:
            zip_path = os.path.join(tmp_dir, "src.zip")
            _download_zip(zip_url, zip_path, token)

            extract_dir = os.path.join(tmp_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            _extract_zip_safe(zip_path, extract_dir)
            src_root = _find_extracted_root(extract_dir)

            module_py = os.path.join(src_root, repo + ".py")
            manifest = _extract_update_manifest(module_py)
            if not manifest or not isinstance(manifest.get("files"), list):
                last_error = (
                    "'%s.py'에서 update_manifest.files를 찾지 못했습니다 "
                    "(가이드 규격을 따르는 저장소인지 확인해주세요)." % repo
                )
                continue

            base_dir = _plugins_metadata_dir()
            target_dir = _safe_join(base_dir, repo)

            # manifest에 명시된 파일만 골라 존재 여부와 경로 안전성을 먼저 검증
            for rel_file in manifest["files"]:
                rel_file = str(rel_file)
                if ".." in rel_file.replace("\\", "/").split("/") or rel_file.startswith("/"):
                    raise ValueError("manifest 파일 경로가 유효하지 않습니다: %s" % rel_file)
                src_file = os.path.join(src_root, rel_file)
                if not os.path.isfile(src_file):
                    raise ValueError("소스에 파일이 없습니다: %s" % rel_file)

            os.makedirs(target_dir, exist_ok=True)
            for rel_file in manifest["files"]:
                src_file = os.path.join(src_root, rel_file)
                dst_file = _safe_join(target_dir, rel_file)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                shutil.copy2(src_file, dst_file)

            _CACHE.pop(owner + "/" + repo, None)  # 설치 직후 카드가 최신 상태를 반영하도록 캐시 무효화
            _try_hot_reload(repo)

            new_version = _local_version(repo) or "?"
            return True, "'%s' 설치/업데이트 완료 (브랜치: %s, 버전: v%s)" % (
                repo, branch, new_version,
            )
        except Exception as exc:
            last_error = str(exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return False, "설치/업데이트 실패: %s" % (last_error or "알 수 없는 오류")


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

    # GitHub raw 기반 자동 업데이트 계약 (plugin_board 자기 자신의 업데이트용)
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
    def search(self, db_type, query):
        return {"success": True, "items": []}

    # ------------------------------------------------------------------
    # 카드의 "신규설치"/"업데이트" 버튼이 호출하는 액션 엔드포인트.
    # item_data = {"action": "install_git" | "update", "plugin_id": ..., "git_url": ...}
    # ------------------------------------------------------------------
    def apply(self, db_type, book_id, item_data):
        if not isinstance(item_data, dict):
            return False, "유효하지 않은 요청 데이터 형식입니다."

        action = str(item_data.get("action", "")).strip().lower()
        if action not in ("install_git", "update"):
            return False, "지원하지 않는 액션입니다: %s" % action

        git_url = str(item_data.get("git_url", "")).strip()
        plugin_id = str(item_data.get("plugin_id", "")).strip()

        owner, repo = _parse_owner_repo(git_url) if git_url else (None, None)
        if not owner or not repo:
            # git_url 없이 plugin_id만 온 경우, GITHUB_REPOS에서 대응하는 주소를 찾는다
            match = next(
                (u for u in GITHUB_REPOS if _parse_owner_repo(u)[1] == plugin_id), None
            )
            if match:
                owner, repo = _parse_owner_repo(match)

        if not owner or not repo:
            return False, "Git 저장소 정보를 확인할 수 없습니다."

        cfg = self.get_plugin_config(db_type, default={})
        token = cfg.get("GITHUB_TOKEN") or None
        return _install_or_update(owner, repo, token)

    # ------------------------------------------------------------------
    # 카테고리 풀페이지 탭이 script.js를 통해 호출하는 데이터 엔드포인트.
    # GITHUB_REPOS에 저장된 주소만으로 매 호출마다(캐시 만료 시) GitHub에서
    # 최신 설명·토픽·버전을 가져오고, plugins/metadata 디렉토리를 직접 확인해
    # 설치 여부·업데이트 필요 여부까지 함께 반환한다.
    # ------------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        token = cfg.get("GITHUB_TOKEN") or None
        items = [_fetch_repo_entry(url, token) for url in GITHUB_REPOS]
        return {"success": True, "items": items}
