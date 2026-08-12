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
import base64
import concurrent.futures
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

# plugin_board 자기 자신은 개발 중인 저장소라 plugin_list.txt에 없을 수 있다.
# 코어의 별도 자동 업데이트 화면에 의존하지 않고 이 카드 목록 안에서도 스스로의
# 업데이트 여부를 확인/설치할 수 있도록, 목록에 없으면 자동으로 포함시킨다.
SELF_REPO_URL = "https://github.com/yume-script/plugin_board"

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
    "yume-script/plugin_board": "tab",
}

TYPE_LABELS = {
    "search": "검색형 메타데이터",
    "tab": "카테고리 탭 UI",
    "other": "기타",
}

_DESC_CACHE = {}  # {"owner/repo": (timestamp, {desc, tags, url, default_branch, error})}
_DESC_CACHE_TTL_SECONDS = 86400  # 24시간 — 설명·토픽은 거의 바뀌지 않으므로 길게 캐시

_VERSION_CACHE = {}  # {"owner/repo": (timestamp, {version_label, remote_version, error})}
_VERSION_CACHE_TTL_SECONDS = 3600  # 1시간 — 버전은 더 자주 바뀔 수 있으므로 짧게 캐시
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


def _has_settings_ui(plugin_id):
    """settings.html이 있으면 config_schema가 비어 있어도 커스텀 설정 화면을
    제공하는 것이므로, 환경설정(⚙) 버튼 노출 여부 판단에 함께 사용한다."""
    return os.path.isfile(
        os.path.join(_plugins_metadata_dir(), plugin_id, "settings.html")
    )


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
            "has_config": bool(attrs.get("config_schema")) or _has_settings_ui(entry),
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


def _fetch_description_info(owner, repo, token):
    """GitHub 저장소 API(설명·토픽·default_branch)만 조회해 24시간 캐시한다.
    이 정보는 저장소 관리자가 바꾸지 않는 한 거의 변하지 않으므로 길게 캐시해
    api.github.com 호출 자체를 줄인다."""
    key = owner + "/" + repo
    cached = _DESC_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _DESC_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        api_data = _http_get_json(
            "https://api.github.com/repos/%s/%s" % (owner, repo), token
        )
        info = {
            "desc": api_data.get("description") or "(GitHub에 등록된 설명이 없습니다)",
            "tags": api_data.get("topics") or [],
            "url": api_data.get("html_url") or ("https://github.com/%s/%s" % (owner, repo)),
            "default_branch": api_data.get("default_branch"),
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        info = {
            "desc": "GitHub API 호출 제한 또는 오류(%s)" % exc.code,
            "tags": [],
            "url": "https://github.com/%s/%s" % (owner, repo),
            "default_branch": None,
            "error": True,
        }
    except Exception as exc:
        info = {
            "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [],
            "url": "https://github.com/%s/%s" % (owner, repo),
            "default_branch": None,
            "error": True,
        }

    _DESC_CACHE[key] = (time.time(), info)
    return info


def _fetch_version_info(owner, repo, token, default_branch):
    """저장소의 VERSION 파일만 조회해 1시간 캐시한다. 설명/토픽보다 자주 바뀔 수
    있는 값이므로(플러그인 릴리즈 주기) 캐시 수명을 짧게 유지한다."""
    key = owner + "/" + repo
    cached = _VERSION_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _VERSION_CACHE_TTL_SECONDS:
        return cached[1]

    remote_version = _fetch_remote_version(owner, repo, default_branch, token)
    info = {
        "version_label": ("v" + remote_version) if remote_version else "—",
        "remote_version": remote_version,
        "error": remote_version is None,
    }
    _VERSION_CACHE[key] = (time.time(), info)
    return info


def _fetch_remote_info(owner, repo, token):
    """설명(24시간 캐시)과 버전(1시간 캐시)을 각각 독립적으로 조회해 합친다.
    설명 캐시가 살아있으면 api.github.com 호출 없이 버전만 새로 확인하므로,
    캐시 만료 주기마다 매번 두 요청을 다 보내던 것보다 평균 호출 수가 줄어든다."""
    desc_info = _fetch_description_info(owner, repo, token)
    version_info = _fetch_version_info(owner, repo, token, desc_info.get("default_branch"))
    return {
        "desc": desc_info["desc"],
        "tags": desc_info["tags"],
        "version_label": version_info["version_label"],
        "remote_version": version_info["remote_version"],
        "url": desc_info["url"],
        "error": desc_info["error"] or version_info["error"],
    }


def _fetch_remote_info_parallel(owner_repo_pairs, token, max_workers=8):
    """여러 저장소의 GitHub 정보를 동시에 조회한다. plugin_board 로딩 시간의
    가장 큰 병목이 저장소 개수만큼 순차적으로 쌓이는 네트워크 왕복이었기 때문에,
    이 부분만 스레드 풀로 병렬화해 전체 대기 시간을 '가장 느린 요청 1개' 수준으로
    줄인다. 캐시가 이미 있는 저장소는 스레드 안에서도 즉시 반환되므로 비용이 없다."""
    results = {}
    if not owner_repo_pairs:
        return results

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max_workers, len(owner_repo_pairs))
    ) as executor:
        future_map = {
            executor.submit(_fetch_remote_info, owner, repo, token): (owner, repo)
            for owner, repo in owner_repo_pairs
        }
        for future in concurrent.futures.as_completed(future_map):
            owner, repo = future_map[future]
            try:
                results[(owner, repo)] = future.result()
            except Exception as exc:
                results[(owner, repo)] = {
                    "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
                    "tags": [],
                    "version_label": "—",
                    "remote_version": None,
                    "url": "https://github.com/%s/%s" % (owner, repo),
                    "error": True,
                }
    return results


def _fetch_repo_entry(url, token, is_enabled_fn, preloaded_info=None):
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
        has_config = bool(local_attrs.get("config_schema")) or _has_settings_ui(repo)

    # 병렬로 미리 가져온 원격 정보가 있으면 그걸 쓰고, 없으면(단건 호출 등) 직접 조회
    info = preloaded_info if preloaded_info is not None else _fetch_remote_info(owner, repo, token)
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

    _DESC_CACHE.clear()  # 삭제된 플러그인이 GitHub 캐시에 남아 잘못된 정보를 주지 않도록
    _VERSION_CACHE.clear()
    _try_hot_reload(plugin_id)
    return True, "'%s' 플러그인이 삭제되었습니다." % plugin_id


def _extract_plugin_id_from_py(py_path):
    """.py 파일 안의 클래스에서 id = "..." 선언을 AST로만(코드 실행 없이) 찾는다."""
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
                        if isinstance(target, ast.Name) and target.id == "id":
                            try:
                                val = ast.literal_eval(stmt.value)
                            except Exception:
                                continue
                            if isinstance(val, str) and val.strip():
                                return val.strip()
    return None


def _is_plugin_directory(dpath):
    """이 디렉토리가 BookOasis 플러그인처럼 보이는지 판별한다
    (VERSION 파일이 있거나, id = "..."를 선언한 .py 파일이 있으면 인정)."""
    if not os.path.isdir(dpath):
        return False
    if os.path.isfile(os.path.join(dpath, "VERSION")):
        return True
    try:
        for fname in os.listdir(dpath):
            if fname.endswith(".py") and fname not in ("__init__.py", "base.py"):
                if _extract_plugin_id_from_py(os.path.join(dpath, fname)):
                    return True
    except Exception:
        pass
    return False


def _find_plugin_root_dir(start_dir):
    """압축을 해제한 폴더 트리 안에서, 폴더 깊이에 상관없이 실제 플러그인 루트를
    찾는다. zip 안에 파일이 바로 있는 경우/저장소 하나로 한 번 감싸인 경우/그보다
    더 깊이 중첩된 경우를 전부 다룬다."""
    if _is_plugin_directory(start_dir):
        return start_dir

    for root, dirs, _files in os.walk(start_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
        if _is_plugin_directory(root):
            return root

    # 플러그인 구조를 못 찾았지만 하위 폴더가 정확히 1개뿐이면 그걸 사용한다
    # (흔한 "저장소이름-브랜치/" 형태로 한 번만 감싸져 있는 경우)
    try:
        subdirs = [
            os.path.join(start_dir, d)
            for d in os.listdir(start_dir)
            if os.path.isdir(os.path.join(start_dir, d))
            and not d.startswith(".")
            and d != "__MACOSX"
        ]
    except Exception:
        subdirs = []
    if len(subdirs) == 1:
        return subdirs[0]

    return start_dir


def _detect_plugin_id(plugin_dir, fallback_name=None):
    """플러그인 루트 디렉토리에서 plugin_id를 추정한다.
    1) VERSION 파일의 id/plugin_id 값 → 2) .py 파일의 id = "..." 선언(AST) →
    3) 폴더 이름 → 4) zip 파일명 순으로 시도한다."""
    version_path = os.path.join(plugin_dir, "VERSION")
    if os.path.isfile(version_path):
        try:
            with open(version_path, "r", encoding="utf-8") as f:
                vdata = json.load(f)
            pid = vdata.get("id") or vdata.get("plugin_id")
            if pid and _PLUGIN_ID_RE.match(str(pid).strip()):
                return str(pid).strip()
        except Exception:
            pass

    try:
        for fname in sorted(os.listdir(plugin_dir)):
            if fname.endswith(".py") and fname not in ("__init__.py", "base.py"):
                pid = _extract_plugin_id_from_py(os.path.join(plugin_dir, fname))
                if pid:
                    return pid
    except Exception:
        pass

    folder_name = os.path.basename(os.path.normpath(plugin_dir))
    if folder_name and not folder_name.lower().startswith(("tmp", "extract")):
        return folder_name

    if fallback_name:
        clean = re.sub(r"\.zip$", "", str(fallback_name), flags=re.IGNORECASE)
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", clean).strip("_")
        if clean:
            return clean

    return ""


def _install_from_zip(zip_data_b64, filename, db_type):
    """업로드된 zip 파일(base64)로 플러그인을 설치한다. GitHub 없이도 동작하며,
    zip 내부 폴더 깊이(바로 최상위 / 한 번 감싸짐 / 더 깊이 중첩)에 상관없이
    실제 플러그인 루트를 찾아 그 내용을 plugins/metadata/{id}/로 복사한다."""
    if not zip_data_b64:
        return False, "zip 데이터가 없습니다."

    if "," in zip_data_b64:
        zip_data_b64 = zip_data_b64.split(",", 1)[1]  # data:...;base64, 접두어 제거

    try:
        zip_bytes = base64.b64decode(zip_data_b64)
    except Exception as exc:
        return False, "zip 데이터를 해석하지 못했습니다: %s" % exc

    tmp_dir = tempfile.mkdtemp(prefix="plugin_board_zip_")
    try:
        zip_path = os.path.join(tmp_dir, "upload.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        extract_dir = os.path.join(tmp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            _extract_zip_safe(zip_path, extract_dir)  # Zip Slip 방지 검증 포함
        except Exception as exc:
            return False, "zip 압축 해제에 실패했습니다: %s" % exc

        plugin_root = _find_plugin_root_dir(extract_dir)
        if not _is_plugin_directory(plugin_root):
            return False, (
                "zip 안에서 유효한 플러그인 구조를 찾지 못했습니다 "
                "(VERSION 파일 또는 id = \"...\"를 선언한 .py 파일이 필요합니다)."
            )

        plugin_id = _detect_plugin_id(plugin_root, fallback_name=filename)
        if not plugin_id:
            return False, "플러그인 ID를 식별하지 못했습니다."

        try:
            _validate_plugin_id(plugin_id)
        except ValueError as exc:
            return False, str(exc)

        if plugin_id == "plugin_board":
            return False, "plugin_board 자기 자신은 이 화면에서 덮어쓸 수 없습니다."

        base_dir = _plugins_metadata_dir()
        target_dir = _safe_join(base_dir, plugin_id)

        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        shutil.copytree(
            plugin_root,
            target_dir,
            ignore=shutil.ignore_patterns(
                ".git", ".github", "__pycache__", "*.pyc", "__MACOSX", ".DS_Store"
            ),
        )

        # 이 plugin_id가 큐레이션 목록의 저장소와 같다면 캐시도 함께 무효화
        for cache in (_DESC_CACHE, _VERSION_CACHE):
            for key in [k for k in cache if k.endswith("/" + plugin_id)]:
                cache.pop(key, None)

        _try_hot_reload(plugin_id)

        new_version = _local_version(plugin_id) or "?"
        return True, "'%s' zip 설치 완료 (버전: v%s)" % (plugin_id, new_version)
    except Exception as exc:
        return False, "zip 설치 중 오류가 발생했습니다: %s" % exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _install_or_update(owner, repo, token=None):
    """저장소 zip을 받아 plugins/metadata/{repo}/를 통째로 교체한다.
    update_manifest.files 화이트리스트로 파일을 골라내지 않고, 검증에 성공한
    새 소스로 기존 설치 폴더를 완전히 대체한다(전체 재다운로드 방식)."""
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

            # 최소한의 신원 확인: 저장소 이름과 같은 메인 모듈 파일이 있어야
            # BookOasis 플러그인 저장소로 간주한다(가이드의 폴더형 구조 관례).
            module_py = os.path.join(src_root, repo + ".py")
            if not os.path.isfile(module_py):
                last_error = (
                    "'%s.py' 파일을 찾지 못했습니다 — BookOasis 플러그인 저장소가 맞는지, "
                    "메인 모듈 파일명이 저장소 이름과 같은지 확인해주세요." % repo
                )
                continue

            base_dir = _plugins_metadata_dir()
            target_dir = _safe_join(base_dir, repo)

            # 검증(모듈 파일 존재 확인)을 통과한 뒤에야 기존 설치를 지운다 —
            # 검증에 실패하면 이 지점에 도달하지 않으므로 기존 설치는 그대로 보존된다.
            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            shutil.copytree(src_root, target_dir)

            key = owner + "/" + repo
            _DESC_CACHE.pop(key, None)  # 설치 직후 카드가 최신 상태를 반영하도록 캐시 무효화
            _VERSION_CACHE.pop(key, None)
            _try_hot_reload(repo)

            new_version = _local_version(repo) or "?"
            return True, "'%s' 설치/업데이트 완료 (브랜치: %s, 버전: v%s, 저장소 전체 교체)" % (
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
        "raw_base_url": "https://raw.githubusercontent.com/yume-script/plugin_board/refs/heads/main",
        "files": [
            "plugin_board.py",
            "__init__.py",
            "VERSION",
            "index.html",
            "style.css",
            "script.js",
            "README.md",
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

        if action == "refresh_list":
            cfg = self.get_plugin_config(db_type, default={})
            token = cfg.get("GITHUB_TOKEN") or None
            urls = _fetch_repo_list(token, force=True)
            if not urls:
                return False, (
                    "plugin_list.txt를 다시 가져오지 못했습니다 "
                    "(%s 조회 실패)" % REMOTE_PLUGIN_LIST_URL
                )
            return True, "플러그인 목록을 새로 불러왔습니다 (%d개 저장소)." % len(urls)

        if action == "install_zip":
            zip_data = str(item_data.get("zip_data", "")).strip()
            filename = str(item_data.get("filename", "")).strip()
            if not zip_data:
                return False, "zip_data가 필요합니다."
            return _install_from_zip(zip_data, filename, db_type)

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

        # plugin_board 자기 자신이 원격 목록에 없다면 자동으로 포함시켜, 개발 중인
        # 버전도 다른 플러그인과 동일하게 카드 + 업데이트 버튼으로 관리할 수 있게 한다.
        existing_repo_names = {_parse_owner_repo(u)[1] for u in repo_urls}
        if "plugin_board" not in existing_repo_names:
            repo_urls = repo_urls + [SELF_REPO_URL]

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

        curated_items = []
        owner_repo_pairs = []
        for url in repo_urls:
            owner, repo = _parse_owner_repo(url)
            if owner and repo:
                owner_repo_pairs.append((owner, repo))

        # 저장소 개수만큼 순차 호출하던 GitHub 조회를 병렬로 한 번에 처리 —
        # 캐시가 살아있는 저장소는 이 안에서도 즉시 반환되므로 추가 비용이 없다.
        remote_infos = _fetch_remote_info_parallel(owner_repo_pairs, token)

        for url in repo_urls:
            owner, repo = _parse_owner_repo(url)
            preloaded = remote_infos.get((owner, repo)) if owner and repo else None
            curated_items.append(_fetch_repo_entry(url, token, is_enabled_fn, preloaded))

        curated_ids = {it["id"] for it in curated_items}
        local_items = _scan_uncurated_installed(curated_ids, is_enabled_fn)
        return {"success": True, "items": curated_items + local_items}
