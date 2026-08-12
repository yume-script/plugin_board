# -*- coding: utf-8 -*-
"""
plugin_board — BookOasis 카테고리 탭 플러그인

좌측 사이드바에 "플러그인게시판" 탭을 추가하고, BookOasis 플러그인 저장소 목록을
색인 카드 형태로 보여준다. 카드 내용(설명·버전)은 코드에 직접 적어두지 않고, 표시할
저장소 주소 목록 자체도 GitHub의 plugin_list.txt에서 화면을 열 때마다 실시간으로
가져온다 — 목록을 갱신하려면 코드 배포 없이 그 파일만 수정하면 된다.

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
# 카드로 보여줄 GitHub 저장소 목록은 이 파일에서 매번 실시간으로 읽어온다.
# 한 줄에 저장소 주소 하나, '#'으로 시작하는 줄은 주석으로 무시한다.
# 목록을 바꾸고 싶으면 이 URL이 가리키는 GitHub 저장소의 plugin_list.txt만
# 수정하면 되고, plugin_board 코드를 다시 배포할 필요가 없다.
# ----------------------------------------------------------------------
REMOTE_PLUGIN_LIST_URL = (
    "https://raw.githubusercontent.com/yume-script/plugin_board/main/plugin_list.txt"
)

_LIST_CACHE = {"ts": 0.0, "urls": []}
_LIST_CACHE_TTL_SECONDS = 3600  # 1시간마다 목록을 다시 조회

# GitHub API/README만으로는 "검색형 메타데이터"인지 "카테고리 탭 UI"인지 구분할 수
# 없어서, 분류가 필요할 때만 owner/repo 키로 지정합니다. 지정하지 않으면 화면에서
# "기타" 분류로 표시됩니다(이미 설치되어 있다면 소스에서 자동으로 재추정됩니다).
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

# plugins/metadata 아래에 있어도 실제 플러그인이 아닌 폴더는 카드로 만들지 않는다.
# (예: bytecode 캐시, 잘못 생성된 빈 폴더 등)
_EXCLUDED_DIR_NAMES = {"__pycache__", "-", ".git", ".github", ".DS_Store", "base"}
# 영문/숫자를 최소 1자 이상 포함해야 유효한 플러그인 폴더명으로 인정 ("-"만 있는 폴더 등 배제)
_VALID_PLUGIN_DIRNAME_RE = re.compile(r"^(?=.*[a-zA-Z0-9])[a-zA-Z0-9_-]+$")


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


def _fetch_repo_list(token, force=False):
    """REMOTE_PLUGIN_LIST_URL(plugin_list.txt)에서 카드로 보여줄 GitHub 저장소
    주소 목록을 읽어온다. 한 줄에 주소 하나, '#'으로 시작하는 줄은 주석으로 무시.
    1시간 캐시하며, 조회에 실패하면 이전에 성공적으로 받아온 목록을 그대로
    반환해 화면이 완전히 비지 않도록 한다(그마저도 없으면 빈 목록)."""
    now = time.time()
    if not force and _LIST_CACHE["urls"] and (now - _LIST_CACHE["ts"]) < _LIST_CACHE_TTL_SECONDS:
        return _LIST_CACHE["urls"]

    try:
        text = _http_get_text(REMOTE_PLUGIN_LIST_URL, token)
        urls = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
        if urls:
            _LIST_CACHE["urls"] = urls
            _LIST_CACHE["ts"] = now
        return urls
    except Exception:
        return _LIST_CACHE["urls"]  # 실패 시 이전 캐시(있다면)라도 유지


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


def _read_local_class_attrs(plugin_id):
    """설치된 플러그인의 {plugin_id}.py에서 name/id/is_searchable/category_tab 등
    주요 클래스 속성을 AST로만(코드 실행 없이) 읽어온다. plugin_list.txt 목록에 없는
    플러그인의 표시 이름·분류를 최대한 정확히 추정하는 데 사용한다."""
    path = os.path.join(_plugins_metadata_dir(), plugin_id, plugin_id + ".py")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except Exception:
        return {}

    wanted = {"name", "id", "is_searchable", "category_tab", "dashboard_widget", "config_schema"}
    attrs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id in wanted:
                            try:
                                attrs[target.id] = ast.literal_eval(stmt.value)
                            except Exception:
                                pass
            if attrs:
                break  # 관례상 파일당 provider 클래스는 하나
    return attrs


def _looks_like_plugin_dir(entry, full_path):
    """plugins/metadata 아래의 폴더가 실제 플러그인처럼 보이는지 판별한다.
    __pycache__, '-', 숨김 폴더 등 카드로 만들면 안 되는 항목을 걸러낸다."""
    if entry in _EXCLUDED_DIR_NAMES:
        return False
    if entry.startswith(".") or entry.startswith("__"):
        return False
    if not _VALID_PLUGIN_DIRNAME_RE.match(entry):
        return False
    # 진짜 플러그인이라면 {entry}.py(메인 모듈) 또는 VERSION 파일 중 하나는 있어야 한다
    has_module = os.path.isfile(os.path.join(full_path, entry + ".py"))
    has_version = os.path.isfile(os.path.join(full_path, "VERSION"))
    return has_module or has_version


def _scan_uncurated_installed(curated_ids, is_enabled_fn):
    """plugin_list.txt(원격 큐레이션 목록)에 없지만 이 서버에 실제로 설치되어 있는
    메타데이터 플러그인을 plugins/metadata 디렉토리에서 직접 찾아 카드로 만든다.
    GitHub 저장소 주소를 모르므로 설명·최신 버전·업데이트 확인은 제공하지 않는다."""
    base_dir = _plugins_metadata_dir()
    items = []
    try:
        entries = sorted(os.listdir(base_dir))
    except Exception:
        return items

    for entry in entries:
        if entry in curated_ids or entry == "plugin_board":
            continue
        full_path = os.path.join(base_dir, entry)
        if not os.path.isdir(full_path):
            continue
        if not _looks_like_plugin_dir(entry, full_path):
            continue

        version = _local_version(entry)
        attrs = _read_local_class_attrs(entry)
        title = attrs.get("name") or entry

        if attrs.get("is_searchable"):
            plugin_type = "search"
        elif attrs.get("category_tab"):
            plugin_type = "tab"
        else:
            plugin_type = "other"

        items.append({
            "id": entry,
            "owner": "",
            "title": title,
            "type": plugin_type,
            "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
            "desc": "",
            "tags": [],
            "features": [],
            "version_label": ("v" + version) if version else "—",
            "url": None,
            "error": False,
            "installed": True,
            "installed_version": version,
            "has_update": False,
            "has_config": bool(attrs.get("config_schema")),
            "enabled": is_enabled_fn(entry),
            "local_only": True,
        })

    return items


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


def _fetch_remote_info(owner, repo, token):
    """GitHub API/버전 조회 결과만 캐시한다 (설치 여부·활성화 상태처럼 자주 바뀌는
    로컬 상태는 캐시하지 않고 매 호출마다 새로 계산한다)."""
    key = owner + "/" + repo
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        api_data = _http_get_json(
            "https://api.github.com/repos/%s/%s" % (owner, repo), token
        )
        remote_version = _fetch_remote_version(
            owner, repo, api_data.get("default_branch"), token
        )
        info = {
            "desc": api_data.get("description") or "(GitHub에 등록된 설명이 없습니다)",
            "tags": api_data.get("topics") or [],
            "version_label": ("v" + remote_version) if remote_version else "—",
            "remote_version": remote_version,
            "url": api_data.get("html_url") or ("https://github.com/%s/%s" % (owner, repo)),
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        remote_version = _fetch_remote_version(owner, repo, None, token)
        info = {
            "desc": "GitHub API 호출 제한 또는 오류(%s)" % exc.code,
            "tags": [],
            "version_label": ("v" + remote_version) if remote_version else "—",
            "remote_version": remote_version,
            "url": "https://github.com/%s/%s" % (owner, repo),
            "error": True,
        }
    except Exception as exc:
        info = {
            "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [],
            "version_label": "—",
            "remote_version": None,
            "url": "https://github.com/%s/%s" % (owner, repo),
            "error": True,
        }

    _CACHE[key] = (time.time(), info)
    return info


def _fetch_repo_entry(url, token, is_enabled_fn):
    owner, repo = _parse_owner_repo(url)
    if not owner or not repo:
        return {
            "id": url, "owner": "", "title": url, "type": "other",
            "type_label": TYPE_LABELS["other"],
            "desc": "저장소 주소를 해석하지 못했습니다.",
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
            "installed": False, "installed_version": None, "has_update": False,
            "has_config": False, "enabled": None,
        }

    key = owner + "/" + repo
    plugin_type = TYPE_OVERRIDES.get(key, "other")
    installed = _is_installed(repo)
    installed_version = _local_version(repo) if installed else None
    has_config = False

    if installed:
        # 이미 설치되어 있다면 실제 소스에서 분류·설정 여부를 더 정확히 추정
        local_attrs = _read_local_class_attrs(repo)
        if local_attrs.get("is_searchable"):
            plugin_type = "search"
        elif local_attrs.get("category_tab"):
            plugin_type = "tab"
        has_config = bool(local_attrs.get("config_schema"))

    info = _fetch_remote_info(owner, repo, token)
    remote_version = info["remote_version"]

    item = {
        "id": repo,
        "owner": owner,
        "title": repo,
        "type": plugin_type,
        "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
        "desc": info["desc"],
        "tags": info["tags"],
        "features": [],
        "version_label": info["version_label"],
        "url": info["url"],
        "error": info["error"],
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(repo) if installed else None,
    }
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


def _toggle_plugin_enabled(plugin_id, enabled_val, db_type):
    """madnite1/plugin_manager와 동일하게 코어의 PluginService를 그대로 사용해
    활성화/비활성화 상태를 변경한다. plugin_board는 이 로직을 직접 구현하지 않고
    코어 서비스에 위임한다."""
    try:
        _validate_plugin_id(plugin_id)
    except ValueError as exc:
        return False, str(exc)

    if plugin_id == "plugin_board":
        return False, "plugin_board 자기 자신은 이 화면에서 비활성화할 수 없습니다."

    try:
        from services.plugin_service import PluginService
    except Exception as exc:
        return False, "코어 PluginService를 사용할 수 없습니다 (%s)" % exc

    try:
        ok, err = PluginService.toggle_plugin_enabled(db_type, plugin_id, str(enabled_val))
        if not ok:
            return False, err or "상태 변경에 실패했습니다."
    except Exception as exc:
        return False, "상태 변경 중 오류가 발생했습니다: %s" % exc

    _try_hot_reload(plugin_id)
    status_text = "활성화" if str(enabled_val) == "1" else "비활성화"
    return True, "'%s' 상태가 '%s'로 변경되었습니다." % (plugin_id, status_text)


def _delete_plugin(plugin_id):
    """plugins/metadata/{plugin_id} 폴더를 삭제한다. 경로는 항상 plugins/metadata
    경계 안에 있는지 검증한 뒤에만 삭제한다(_validate_plugin_id + _safe_join 재사용)."""
    if plugin_id == "plugin_board":
        return False, "plugin_board 자기 자신은 이 화면에서 삭제할 수 없습니다."

    try:
        _validate_plugin_id(plugin_id)
        target_dir = _safe_join(_plugins_metadata_dir(), plugin_id)
    except ValueError as exc:
        return False, str(exc)

    if not os.path.isdir(target_dir):
        return False, "존재하지 않는 플러그인입니다: %s" % plugin_id

    try:
        shutil.rmtree(target_dir)
    except Exception as exc:
        return False, "삭제 실패: %s" % exc

    _CACHE.clear()  # 삭제된 플러그인이 GitHub 캐시에 남아 잘못된 정보를 주지 않도록
    _try_hot_reload(plugin_id)
    return True, "'%s' 플러그인이 삭제되었습니다." % plugin_id


def _prune_files_not_in_manifest(target_dir, manifest_files):
    """update_manifest.files 목록에 없는 파일은 대상 폴더에서 전부 삭제해,
    설치 결과가 항상 manifest와 정확히 일치하도록 동기화한다
    (madnite1/plugin_manager의 Git URL 설치와 동일한 정책)."""
    keep = {os.path.normpath(str(f)) for f in manifest_files}
    for root, dirs, files in os.walk(target_dir, topdown=False):
        for fname in files:
            abs_path = os.path.join(root, fname)
            rel_path = os.path.normpath(os.path.relpath(abs_path, target_dir))
            if rel_path not in keep:
                try:
                    os.remove(abs_path)
                except OSError:
                    pass
        # 파일을 지우고 남은 빈 디렉토리 정리
        if root != target_dir:
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass


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

            _prune_files_not_in_manifest(target_dir, manifest["files"])

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
    name = "플러그인게시판"
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
        "title": "플러그인게시판",
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
    # 카드의 버튼들이 호출하는 액션 엔드포인트.
    # item_data = {
    #   "action": "install_git" | "update" | "toggle" | "delete",
    #   "plugin_id": ..., "git_url": ..., "enabled": "0" | "1"  (toggle 전용)
    # }
    # ------------------------------------------------------------------
    def apply(self, db_type, book_id, item_data):
        if not isinstance(item_data, dict):
            return False, "유효하지 않은 요청 데이터 형식입니다."

        action = str(item_data.get("action", "")).strip().lower()
        plugin_id = str(item_data.get("plugin_id", "")).strip()

        if action == "toggle":
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            enabled_val = str(item_data.get("enabled", "1")).strip()
            return _toggle_plugin_enabled(plugin_id, enabled_val, db_type)

        if action == "delete":
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            return _delete_plugin(plugin_id)

        if action in ("install_git", "update"):
            cfg = self.get_plugin_config(db_type, default={})
            token = cfg.get("GITHUB_TOKEN") or None

            git_url = str(item_data.get("git_url", "")).strip()
            owner, repo = _parse_owner_repo(git_url) if git_url else (None, None)
            if not owner or not repo:
                # git_url 없이 plugin_id만 온 경우, 원격 목록(plugin_list.txt)에서
                # 대응하는 주소를 찾는다
                match = next(
                    (u for u in _fetch_repo_list(token) if _parse_owner_repo(u)[1] == plugin_id),
                    None,
                )
                if match:
                    owner, repo = _parse_owner_repo(match)

            if not owner or not repo:
                return False, "Git 저장소 정보를 확인할 수 없습니다."

            return _install_or_update(owner, repo, token)

        return False, "지원하지 않는 액션입니다: %s" % action

    # ------------------------------------------------------------------
    # 카테고리 풀페이지 탭이 script.js를 통해 호출하는 데이터 엔드포인트.
    # 카드로 보여줄 저장소 목록 자체를 REMOTE_PLUGIN_LIST_URL(plugin_list.txt)에서
    # 매 호출마다(캐시 만료 시) 가져오고, 각 저장소의 최신 설명·토픽·버전도 GitHub에서
    # 가져온다. plugins/metadata 디렉토리를 직접 확인해 설치 여부·업데이트 필요
    # 여부·활성화 상태·설정 보유 여부까지 함께 반환한다.
    # ------------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        token = cfg.get("GITHUB_TOKEN") or None

        repo_urls = _fetch_repo_list(token)
        if not repo_urls:
            return {
                "success": False,
                "error": (
                    "플러그인 목록을 가져오지 못했습니다 "
                    "(%s 조회 실패)" % REMOTE_PLUGIN_LIST_URL
                ),
            }

        try:
            gateway = self.get_db_gateway(db_type)
        except Exception:
            gateway = None

        def is_enabled_fn(plugin_id):
            if gateway is None:
                return True
            try:
                raw = gateway.get_setting("PLUGIN_ENABLED_%s" % plugin_id, default="1")
                if isinstance(raw, dict):
                    raw = raw.get("value", "1")
                return str(raw) == "1"
            except Exception:
                return True

        curated_items = [
            _fetch_repo_entry(url, token, is_enabled_fn) for url in repo_urls
        ]
        curated_ids = {it["id"] for it in curated_items}
        local_items = _scan_uncurated_installed(curated_ids, is_enabled_fn)
        return {"success": True, "items": curated_items + local_items}
