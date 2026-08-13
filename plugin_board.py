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
from datetime import datetime

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


_MAX_ZIP_ENTRIES = 3000  # 파일 개수 상한 — .git 폴더 등을 통째로 담은 zip 방지
_MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 압축 해제 후 총 용량 상한(zip bomb 방지)


def _extract_zip_safe(zip_path, extract_dir):
    """Zip Slip 방지 — 모든 압축 해제 대상 경로가 extract_dir 하위인지 검증 후 해제.
    항목 개수·압축 해제 후 총 용량도 함께 제한해, 원본 zip은 작아도 내부에
    (예: .git 폴더처럼) 파일이 수천~수만 개거나 압축률이 비정상적으로 높은
    경우(zip bomb) 서버 자원을 과도하게 쓰다 타임아웃/다운되는 것을 막는다."""
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()

        if len(infos) > _MAX_ZIP_ENTRIES:
            raise ValueError(
                "zip 안의 파일 개수가 너무 많습니다 (%d개, 최대 %d개). "
                "'.git' 폴더 등 불필요한 항목이 포함되지 않았는지 확인해주세요."
                % (len(infos), _MAX_ZIP_ENTRIES)
            )

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > _MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError(
                "압축을 풀었을 때 총 용량이 너무 큽니다 (%.1fMB, 최대 %.0fMB)."
                % (total_uncompressed / (1024 * 1024), _MAX_ZIP_UNCOMPRESSED_BYTES / (1024 * 1024))
            )

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



# ========================================================================
# Zip 업로드 설치 파이프라인 (madnite1/plugin_manager의 _install_from_zip을
# 참고해 동일한 절차·검증 항목으로 재구현)
#   1~3. base64 디코드 → 임시 디렉토리에 압축 해제 (Zip Slip/개수/용량 검증)
#   4~6. 플러그인 루트·ID 식별, ID 형식·예약어 검증
#   7.   1차 검증 — 정적 소스 검증 (코드 실행 없음, AST/파일 스캔만)
#   8~10. 배치 — 경로 검증 → 기존 폴더 삭제 → 복사 → .zip_source 메타 저장
#   11~13. 활성화 → 핫 리로드 → 2차 검증(실제 로드 확인, 실패 시 자동 롤백)
#   14.  완료 — 임시 폴더 정리, 검증 통과/경고 포함 성공 메시지
# ========================================================================
_RESERVED_PLUGIN_IDS = {"base.py", "base", "__pycache__", "plugin_manager"}


def _is_plugin_directory(dpath):
    """디렉토리가 유효한 플러그인 구성 요소를 포함하고 있는지 판별."""
    if not os.path.isdir(dpath):
        return False
    if os.path.isfile(os.path.join(dpath, "VERSION")):
        return True
    try:
        for fname in os.listdir(dpath):
            if fname.endswith(".py") and fname not in ("base.py", "__init__.py"):
                fpath = os.path.join(dpath, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if "BaseMetadataProvider" in content or "id =" in content or "id=" in content:
                        return True
    except Exception:
        pass
    return False


def _find_plugin_root_dir(start_dir):
    """압축 해제된 폴더 안에서 플러그인 루트 디렉토리를 지능 탐색한다.
    zip 안에 폴더가 하나 더 감싸져 있어도(예: 저장소이름-브랜치/) 실제 루트를
    찾고, __MACOSX·숨김 폴더는 탐색에서 제외한다."""
    if _is_plugin_directory(start_dir):
        return start_dir

    for root, dirs, _files in os.walk(start_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
        if _is_plugin_directory(root):
            return root

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
    """VERSION의 id/plugin_id → 메인 .py의 id = "..." → 폴더 이름 → zip 파일명
    순으로 plugin_id를 결정한다."""
    vpath = os.path.join(plugin_dir, "VERSION")
    if os.path.isfile(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                vdata = json.load(f)
            pid = vdata.get("id") or vdata.get("plugin_id")
            if pid and _PLUGIN_ID_RE.match(str(pid).strip()):
                return str(pid).strip()
        except Exception:
            pass

    try:
        for fname in os.listdir(plugin_dir):
            if fname.endswith(".py") and fname not in ("__init__.py", "base.py"):
                fpath = os.path.join(plugin_dir, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    m = re.search(r'id\s*=\s*["\']([a-zA-Z0-9_-]+)["\']', content)
                    if m:
                        return m.group(1).strip()
    except Exception:
        pass

    folder_name = os.path.basename(os.path.normpath(plugin_dir))
    if folder_name and folder_name not in ("temp", "tmp") and not folder_name.lower().startswith(
        ("plugin_board_zip", "extract", "tmp")
    ):
        return folder_name

    if fallback_name:
        clean = re.sub(r"\.zip$", "", str(fallback_name), flags=re.IGNORECASE)
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", clean).strip("_")
        if clean:
            return clean

    return ""


def _extract_update_manifest_files(plugin_dir):
    """플러그인 .py 소스에서 update_manifest dict를 AST로만(코드 실행 없이)
    추출한다. 반환: (files 리스트, manifest dict) 또는 (None, None)."""
    try:
        for fname in sorted(os.listdir(plugin_dir)):
            if not fname.endswith(".py") or fname in ("__init__.py", "base.py"):
                continue
            fpath = os.path.join(plugin_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    tree = ast.parse(f.read(), filename=fpath)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    value_node = None
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name) and target.id == "update_manifest":
                                value_node = stmt.value
                                break
                    elif (
                        isinstance(stmt, ast.AnnAssign)
                        and isinstance(stmt.target, ast.Name)
                        and stmt.target.id == "update_manifest"
                    ):
                        value_node = stmt.value
                    if value_node is None:
                        continue
                    try:
                        value = ast.literal_eval(value_node)
                    except Exception:
                        value = None
                    if not isinstance(value, dict):
                        continue
                    raw_files = value.get("files")
                    if isinstance(raw_files, list):
                        files_clean = [str(x).strip() for x in raw_files if str(x).strip()]
                        if files_clean:
                            return files_clean, value
    except Exception:
        pass
    return None, None


def _validate_plugin_source(plugin_dir, detected_id):
    """설치 대상 플러그인 소스 정적 검증 (코드 실행 없음 — AST/파일 스캔만).
    개발 가이드(guide_plugins.md) 규격 기반.

    검증 항목:
      1. VERSION: update_manifest 선언 시 필수 (JSON + 'plugin version' 키).
         미선언 시 VERSION 없음/비표준은 경고만 (업데이트 미지원 플러그인 허용)
      2. 메인 .py 존재 (BaseMetadataProvider 상속 클래스)
      3. 클래스 id == 감지된 plugin_id (폴더명과 일치해야 목록/카테고리 표시)
      4. 필수 클래스 필드: name(str), is_searchable(bool), config_schema(list)
      5. 필수 메서드 search/apply 구현 (AST 클래스 본문 검사)
      6. 금지 패턴 없음 (eval/exec/subprocess/os.system/os.popen/shell=True)
      7. 심볼릭 링크 없음
      8. update_manifest 규격: provider=='github-raw' + version_file/version_key/
         files 존재 + raw_base_url 비어있지 않음 + files 실제 존재
      9. category_tab 선언 시 UI 번들(index.html/script.js/style.css) 필수

    반환: (성공 여부, 체크 결과 리스트 [{'name','ok','detail','warn'?}])
    """
    if os.path.basename(os.path.normpath(plugin_dir)) == "__pycache__":
        return False, []

    checks = []
    base_names = ("base.py", "__init__.py")

    manifest_files, manifest = _extract_update_manifest_files(plugin_dir)

    # 1. VERSION 파일 검사
    vpath = os.path.join(plugin_dir, "VERSION")
    vfile_ok = False
    vdetail = ""
    if os.path.isfile(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                vdata = json.load(f)
            vkey = vdata.get("plugin version") or vdata.get("version")
            if vkey:
                vfile_ok = True
                vdetail = "버전 %s" % vkey
            else:
                vdetail = "'plugin version' 키가 없습니다 (업데이트 체크 불가)"
        except Exception:
            vdetail = "VERSION 형식이 표준 JSON이 아닙니다 (업데이트 체크 불가)"
    else:
        vdetail = "VERSION 파일 없음"

    if manifest_files:
        if vfile_ok:
            checks.append({"name": "VERSION", "ok": True, "detail": vdetail})
        else:
            checks.append({"name": "VERSION", "ok": False,
                            "detail": "update_manifest 선언 시 VERSION 필수 — " + vdetail})
    elif vfile_ok:
        checks.append({"name": "VERSION", "ok": True, "detail": vdetail})
    else:
        checks.append({"name": "VERSION", "ok": True, "warn": True,
                        "detail": "경고: " + vdetail + " (업데이트 체크 불가)"})

    # 2~6. 파이썬 소스 AST 분석
    try:
        py_files = [
            f for f in sorted(os.listdir(plugin_dir))
            if f.endswith(".py") and f not in base_names
            and os.path.isfile(os.path.join(plugin_dir, f))
        ]
    except Exception:
        py_files = []

    provider_found = False
    class_id = None
    cls_attrs = set()
    has_search = False
    has_apply = False
    forbidden_hits = []

    for fname in py_files:
        fpath = os.path.join(plugin_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            tree = ast.parse(content, filename=fpath)
        except SyntaxError:
            forbidden_hits.append("%s: 파이썬 구문 오류" % fname)
            continue

        # 금지 패턴 검사 (AST 기반 — 실제 호출/import만 차단, 주석/문자열은 무시)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in ("eval", "exec"):
                    forbidden_hits.append("%s: %s() 호출 발견" % (fname, fn.id))
                elif isinstance(fn, ast.Attribute) and fn.attr in ("system", "popen"):
                    forbidden_hits.append("%s: os.%s() 호출 발견" % (fname, fn.attr))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "subprocess" or a.name.startswith("subprocess."):
                        forbidden_hits.append("%s: subprocess import 발견" % fname)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    forbidden_hits.append("%s: subprocess import 발견" % fname)
            elif isinstance(node, ast.keyword) and node.arg == "shell":
                try:
                    if ast.literal_eval(node.value) is True:
                        forbidden_hits.append("%s: shell=True 사용" % fname)
                except Exception:
                    pass

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    bases.append("")

            cls_id = None
            cls_fields = set()
            cls_search = False
            cls_apply = False
            for stmt in node.body:
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    for t in targets:
                        if not isinstance(t, ast.Name):
                            continue
                        val = stmt.value
                        if t.id == "id":
                            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                cls_id = val.value
                        elif t.id == "name":
                            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                cls_fields.add("name")
                        elif t.id == "is_searchable":
                            if isinstance(val, ast.Constant) and isinstance(val.value, bool):
                                cls_fields.add("is_searchable")
                        elif t.id == "config_schema":
                            if isinstance(val, (ast.List, ast.Tuple)):
                                cls_fields.add("config_schema")
                        elif t.id in ("category_tab", "update_manifest", "dashboard_widget"):
                            if isinstance(val, ast.Dict):
                                cls_fields.add(t.id)
                elif isinstance(stmt, ast.FunctionDef):
                    if stmt.name == "search":
                        cls_search = True
                    elif stmt.name == "apply":
                        cls_apply = True

            is_provider = any("BaseMetadataProvider" in b for b in bases)
            if not is_provider and cls_id is not None:
                is_provider = True

            if is_provider and cls_id is not None and class_id is None:
                class_id = cls_id

            if is_provider:
                provider_found = True
                cls_attrs.update(cls_fields)
                if cls_search:
                    has_search = True
                if cls_apply:
                    has_apply = True

    if not py_files:
        checks.append({"name": "소스", "ok": False, "detail": "메인 .py 파일이 없습니다"})
    elif not provider_found:
        checks.append({"name": "소스", "ok": False,
                        "detail": "BaseMetadataProvider 상속 클래스를 찾을 수 없습니다"})
    else:
        checks.append({"name": "소스", "ok": True,
                        "detail": "%d개 .py 파일, BaseMetadataProvider 클래스 발견" % len(py_files)})

    # 3. 클래스 id 일치 검사
    if class_id is not None:
        if str(class_id).strip() == str(detected_id).strip():
            checks.append({"name": "클래스 id", "ok": True, "detail": class_id})
        else:
            checks.append({"name": "클래스 id", "ok": False,
                            "detail": "코드 내 id='%s' \u2260 감지된 id='%s' — 설치 후 목록에 "
                                      "표시되지 않을 수 있습니다" % (class_id, detected_id)})
    elif provider_found:
        checks.append({"name": "클래스 id", "ok": False, "detail": "플러그인 클래스에 id 속성이 없습니다"})
    else:
        checks.append({"name": "클래스 id", "ok": False, "detail": "클래스를 찾을 수 없어 검사 불가"})

    # 4. 필수 클래스 필드
    if provider_found:
        missing_fields = [f for f in ("name", "is_searchable", "config_schema") if f not in cls_attrs]
        if missing_fields:
            checks.append({"name": "필수 필드", "ok": False, "detail": "클래스에 없음: " + ", ".join(missing_fields)})
        else:
            checks.append({"name": "필수 필드", "ok": True, "detail": "name/is_searchable/config_schema 확인"})
    else:
        checks.append({"name": "필수 필드", "ok": False, "detail": "클래스 없음"})

    # 5. 필수 메서드
    if provider_found:
        missing = []
        if not has_search:
            missing.append("search")
        if not has_apply:
            missing.append("apply")
        if missing:
            checks.append({"name": "필수 메서드", "ok": False, "detail": "구현 안 됨: " + ", ".join(missing)})
        else:
            checks.append({"name": "필수 메서드", "ok": True, "detail": "search/apply 확인"})
    else:
        checks.append({"name": "필수 메서드", "ok": False, "detail": "클래스 없음"})

    # 6. 금지 패턴
    if forbidden_hits:
        checks.append({"name": "금지 패턴", "ok": False, "detail": "; ".join(forbidden_hits[:3])})
    else:
        checks.append({"name": "금지 패턴", "ok": True, "detail": "eval/exec/subprocess 없음"})

    # __init__.py 존재 여부 (없으면 폴백 로드 — 경고만)
    if os.path.isfile(os.path.join(plugin_dir, "__init__.py")):
        checks.append({"name": "__init__.py", "ok": True, "detail": "확인"})
    else:
        checks.append({"name": "__init__.py", "ok": True, "warn": True,
                        "detail": "경고: __init__.py 없음 (폴백 로드 사용)"})

    # 7. 심볼릭 링크 검사
    symlinks = []
    try:
        for root_dir, dirs, files in os.walk(plugin_dir):
            for entry in dirs + files:
                p = os.path.join(root_dir, entry)
                if os.path.islink(p):
                    symlinks.append(os.path.relpath(p, plugin_dir))
    except Exception:
        pass
    if symlinks:
        checks.append({"name": "심볼릭 링크", "ok": False,
                        "detail": "플러그인 폴더 내 심볼릭 링크 금지: " + ", ".join(symlinks[:3])})
    else:
        checks.append({"name": "심볼릭 링크", "ok": True, "detail": "없음"})

    # 8. update_manifest 규격 검사 (선언된 경우에만)
    if manifest_files:
        problems = []
        m_provider = str(manifest.get("provider") or "").strip()
        if m_provider != "github-raw":
            problems.append("provider='%s' (github-raw만 지원)" % (m_provider or "없음"))
        if not str(manifest.get("version_file") or "").strip():
            problems.append("version_file 없음")
        if not str(manifest.get("version_key") or "").strip():
            problems.append("version_key 없음")
        missing_files = [rel for rel in manifest_files
                          if not os.path.isfile(os.path.join(plugin_dir, rel))]
        if missing_files:
            problems.append("files에 선언된 파일이 없음: " + ", ".join(missing_files[:3]))
        if not str(manifest.get("raw_base_url") or "").strip():
            problems.append("raw_base_url이 비어 있음")
        if problems:
            checks.append({"name": "update_manifest", "ok": False, "detail": "; ".join(problems[:4])})
        else:
            checks.append({"name": "update_manifest", "ok": True,
                            "detail": "provider/files %d개/raw_base_url/version_file/version_key 확인"
                                      % len(manifest_files)})
    else:
        checks.append({"name": "update_manifest", "ok": True, "detail": "미선언 (업데이트 미지원)"})

    # 9. UI 번들 검사 (category_tab 선언 시 index.html/script.js/style.css 필수)
    ui_files = {f: os.path.isfile(os.path.join(plugin_dir, f)) for f in ("index.html", "script.js", "style.css")}
    if "category_tab" in cls_attrs:
        missing_ui = [f for f, ok in ui_files.items() if not ok]
        if missing_ui:
            checks.append({"name": "UI 번들", "ok": False,
                            "detail": "category_tab 선언 시 필수: " + ", ".join(missing_ui)})
        else:
            checks.append({"name": "UI 번들", "ok": True, "detail": "index/script/style 확인"})
    else:
        present_ui = [f for f, ok in ui_files.items() if ok]
        if present_ui and len(present_ui) < 3:
            checks.append({"name": "UI 번들", "ok": True, "warn": True,
                            "detail": "경고: UI 파일 일부만 존재 (" + ", ".join(present_ui) + ")"})
        elif present_ui:
            checks.append({"name": "UI 번들", "ok": True, "detail": "UI 번들 확인"})
        else:
            checks.append({"name": "UI 번들", "ok": True, "detail": "미선언"})

    all_ok = all(c.get("ok") for c in checks)
    return all_ok, checks


def _validate_plugin_path(plugin_id):
    """플러그인 ID 및 경로 안전성 검증. 반환: (target_path, None) 또는 (None, 오류메시지)."""
    pid = str(plugin_id or "").strip()
    if not pid or not _PLUGIN_ID_RE.match(pid):
        return None, "유효하지 않은 플러그인 ID입니다 (영문, 숫자, 언더바, 하이픈만 허용)."
    try:
        target = _safe_join(_plugins_metadata_dir(), pid)
    except ValueError as exc:
        return None, str(exc)
    return target, None


def _verify_plugin_loaded(plugin_id):
    """2차 검증 — 코어가 실제로 이 플러그인을 로드했는지 확인한다.
    확인 자체가 불가능한 경우도 안전하게 '로드 실패'로 간주한다(fail-closed)."""
    try:
        from services.metadata_factory import MetadataFactory
        providers = MetadataFactory.get_available_providers()
        return any(str(p.get("id")) == plugin_id for p in providers)
    except Exception:
        return False


def _install_from_zip(zip_data_b64, filename, db_type):
    """업로드된 zip(base64)으로 플러그인을 설치한다. 모듈 상단 주석의 14단계
    절차를 그대로 따른다."""
    if not zip_data_b64:
        return False, "압축 파일 데이터가 누락되었습니다."

    if "," in zip_data_b64:
        zip_data_b64 = zip_data_b64.split(",", 1)[1]  # data:...;base64, 접두어 제거

    try:
        zip_bytes = base64.b64decode(zip_data_b64)
    except Exception as exc:
        return False, "zip 데이터를 해석하지 못했습니다: %s" % exc

    tmp_dir = tempfile.mkdtemp(prefix="plugin_board_zip_")
    try:
        # 1~3. 임시 파일로 저장 후 압축 해제 (Zip Slip·개수·용량 검증 포함)
        zip_path = os.path.join(tmp_dir, "upload.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        extract_dir = os.path.join(tmp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            _extract_zip_safe(zip_path, extract_dir)
        except zipfile.BadZipFile:
            return False, "올바른 zip 압축 파일 형식이 아닙니다."
        except Exception as exc:
            return False, "zip 압축 해제에 실패했습니다: %s" % exc

        # 4. 플러그인 루트 지능 탐색
        plugin_root = _find_plugin_root_dir(extract_dir)

        # 5. 플러그인 ID 식별
        plugin_id = _detect_plugin_id(plugin_root, fallback_name=filename)
        if not plugin_id:
            return False, (
                "플러그인 ID를 식별할 수 없습니다. "
                "(BaseMetadataProvider 클래스 또는 VERSION 파일 필요)"
            )

        # 6. ID 형식 검증 + 예약어 가드 (plugin_manager 등 핵심 플러그인 보호)
        if not _PLUGIN_ID_RE.match(plugin_id):
            return False, "유효하지 않은 플러그인 ID입니다 (영문/숫자/언더바/하이픈만 허용): %s" % plugin_id
        if plugin_id in _RESERVED_PLUGIN_IDS or plugin_id == "plugin_board":
            return False, "시스템 예약어 또는 핵심 플러그인은 덮어쓸 수 없습니다: %s" % plugin_id

        # 7. 1차 검증 — 정적 소스 검증 (코드 실행 없음)
        source_ok, source_checks = _validate_plugin_source(plugin_root, plugin_id)
        if not source_ok:
            failed_items = ["- %s: %s" % (c["name"], c["detail"]) for c in source_checks if not c.get("ok")]
            return False, (
                "플러그인 검증 실패 — 설치를 중단했습니다 (기존 폴더는 변경되지 않음):\n"
                + "\n".join(failed_items)
            )

        # 8. 대상 경로 확인
        dest_dir, path_err = _validate_plugin_path(plugin_id)
        if path_err or not dest_dir:
            return False, path_err or "유효하지 않은 플러그인 경로입니다."

        # 9. 기존 폴더 삭제 후 복사 (.git/.github/__pycache__/__MACOSX/.DS_Store 제외)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(
            plugin_root,
            dest_dir,
            ignore=shutil.ignore_patterns(
                ".git", ".github", "__pycache__", "*.pyc", "__MACOSX", ".DS_Store"
            ),
        )

        # 10. zip 출처 메타 정보 저장
        zip_source_info = {
            "source_type": "zip_upload",
            "filename": filename or "plugin.zip",
            "installed_at": datetime.now().isoformat(),
        }
        try:
            with open(os.path.join(dest_dir, ".zip_source"), "w", encoding="utf-8") as f:
                json.dump(zip_source_info, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # 메타 저장 실패는 설치 자체를 막을 이유가 아님

        for cache in (_DESC_CACHE, _VERSION_CACHE):
            for key in [k for k in cache if k.endswith("/" + plugin_id)]:
                cache.pop(key, None)

        # 11. 즉시 활성화
        _toggle_plugin_enabled(plugin_id, "1", db_type)

        # 12. 핫 리로드
        _try_hot_reload(plugin_id)

        # 13. 2차 검증 — 실제 로드 확인, 실패 시 자동 롤백(설치 폴더 삭제)
        if not _verify_plugin_loaded(plugin_id):
            shutil.rmtree(dest_dir, ignore_errors=True)
            return False, (
                "검증 실패: '%s' 플러그인이 설치 후 로드되지 않았습니다. "
                "(클래스 id와 폴더명이 일치하는지 확인 필요) — 설치 폴더를 삭제했습니다."
                % plugin_id
            )

        # 14. 완료
        passed = [c["name"] for c in source_checks if c.get("ok") and not c.get("warn")]
        warns = [c["detail"] for c in source_checks if c.get("warn")]
        new_version = _local_version(plugin_id) or "?"
        result_msg = (
            "zip 압축 파일을 통해 '%s' 플러그인이 성공적으로 설치 및 활성화되었습니다! "
            "(버전 v%s, 검증 통과: %s)" % (plugin_id, new_version, ", ".join(passed))
        )
        if warns:
            result_msg += " 경고: " + "; ".join(warns)
        return True, result_msg

    except zipfile.BadZipFile:
        return False, "올바른 zip 압축 파일 형식이 아닙니다."
    except Exception as exc:
        return False, "zip 플러그인 설치 중 오류가 발생했습니다: %s" % exc
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
        """모든 액션의 진입점. 실제 처리는 _dispatch_apply에 위임하고, 여기서는
        예상치 못한 예외가 그대로 새어나가 코어/프록시 단에서 정체불명의 500으로
        보이지 않도록 마지막 안전망 역할만 한다."""
        try:
            return self._dispatch_apply(db_type, book_id, item_data)
        except Exception as exc:
            return False, "예상치 못한 오류가 발생했습니다: %s" % exc

    def _dispatch_apply(self, db_type, book_id, item_data):
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
