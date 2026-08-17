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
import concurrent.futures
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
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

# ----------------------------------------------------------------------
# 하이브리드 발견(discovery) — plugin_list.txt의 큐레이션 목록과 별개로,
# GitHub Topics에 이 토픽이 달린 저장소를 자동으로 찾아 "미검수" 카드로 함께
# 보여준다(Search API 사용). 기본값은 "bookoasis-plugin" 하나뿐이지만, 이
# 리스트에 문자열을 더 추가하면(코드 배포로) 여러 토픽을 동시에 검색할 수
# 있다. 코드를 건드리지 않고 서버별로 토픽을 추가하고 싶으면 플러그인 설정의
# EXTRA_DISCOVERY_TOPICS(콤마 구분)를 쓰면 된다 — 둘은 합쳐져서 함께 검색된다.
# ----------------------------------------------------------------------
DISCOVERY_TOPICS = ["bookoasis-plugin"]

# 토픽은 GitHub 전역에서 공유되는 이름이라, 흔한 단어를 추가 토픽으로 넣으면
# 전혀 무관한 저장소가 대량으로 섞여 들어올 수 있다(실측: 흔한 이름 하나로
# 무관한 저장소 50개 이상이 잡힌 사례 있음). 그래서 두 단계로 방어한다:
#   1) VERSION 파일을 실제로 찾은(=BookOasis 플러그인일 가능성이 높은) 저장소만
#      발견 카드로 인정 — 이미 설치되어 있는 저장소는 예외적으로 항상 허용
#   2) 그래도 남는 개수를 아래 상한으로 한 번 더 자른다
_MAX_DISCOVERED_ITEMS = 30

_TOPIC_CACHE = {}  # {"topic1,topic2": (timestamp, [repo_json, ...])}
_TOPIC_CACHE_TTL_SECONDS = 3600  # 1시간 — plugin_list.txt와 동일한 주기
_SEARCH_REQUEST_TIMEOUT = 8

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

# ----------------------------------------------------------------------
# 캐시 디스크 영속화 — GITHUB_TOKEN을 설정하지 않은 사용자(무인증 시간당 60회
# 한도)는 서버가 재시작될 때마다 메모리 캐시가 전부 사라져 다시 "콜드 스타트"로
# GitHub를 두드리게 되는 게 rate limit을 가장 빨리 소진시키는 원인이었다.
# 그래서 캐시를 이 플러그인 폴더의 .cache.json에도 저장해, 재시작 후에도
# TTL이 남아있는 동안은 다시 조회하지 않도록 한다. 저장/로드가 실패해도
# 기능에는 영향이 없도록 전부 조용히 무시한다(순수 성능 최적화용 캐시일 뿐).
# ----------------------------------------------------------------------
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache.json")


def _save_disk_cache():
    try:
        data = {
            "list": {"ts": _LIST_CACHE.get("ts", 0.0), "urls": _LIST_CACHE.get("urls", [])},
            "desc": {k: [ts, v] for k, (ts, v) in _DESC_CACHE.items()},
            "version": {k: [ts, v] for k, (ts, v) in _VERSION_CACHE.items()},
            "topic": {k: [ts, v] for k, (ts, v) in _TOPIC_CACHE.items()},
        }
        tmp_path = _CACHE_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, _CACHE_FILE)
    except Exception:
        pass


def _load_disk_cache():
    try:
        if not os.path.isfile(_CACHE_FILE):
            return
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        list_data = data.get("list") or {}
        if isinstance(list_data.get("urls"), list):
            _LIST_CACHE["ts"] = float(list_data.get("ts", 0.0))
            _LIST_CACHE["urls"] = list_data["urls"]

        for k, pair in (data.get("desc") or {}).items():
            if isinstance(pair, list) and len(pair) == 2:
                _DESC_CACHE[k] = (float(pair[0]), pair[1])

        for k, pair in (data.get("version") or {}).items():
            if isinstance(pair, list) and len(pair) == 2:
                _VERSION_CACHE[k] = (float(pair[0]), pair[1])

        for k, pair in (data.get("topic") or {}).items():
            if isinstance(pair, list) and len(pair) == 2:
                _TOPIC_CACHE[k] = (float(pair[0]), pair[1])
    except Exception:
        pass  # 손상된 캐시 파일은 조용히 무시하고 콜드 스타트로 진행


_load_disk_cache()  # 모듈이 처음 임포트될 때(서버 시작 시) 1회 복원

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


def _find_module_file(plugin_dir, plugin_id):
    """GitHub 저장소 이름은 하이픈을 흔히 쓰지만(예: bookoasis-tk), 파이썬 파일명은
    하이픈을 쓸 수 없어 언더스코어로 짓는 경우가 많다(예: bookoasis_tk.py). 폴더
    이름(plugin_id) 그대로의 파일명뿐 아니라 하이픈↔언더스코어를 서로 바꾼 표기도
    함께 시도해 실제 메인 모듈 파일을 찾는다. 찾으면 그 경로를, 못 찾으면 None을
    반환한다."""
    candidates = []
    seen = set()
    for candidate_id in (plugin_id, plugin_id.replace("-", "_"), plugin_id.replace("_", "-")):
        if candidate_id and candidate_id not in seen:
            seen.add(candidate_id)
            candidates.append(candidate_id)
    for candidate_id in candidates:
        path = os.path.join(plugin_dir, candidate_id + ".py")
        if os.path.isfile(path):
            return path
    return None


def _read_local_class_attrs(plugin_id):
    """설치된 플러그인의 메인 .py에서 name/id/is_searchable/category_tab 등
    주요 클래스 속성을 AST로만(코드 실행 없이) 읽어온다. plugin_list.txt 목록에 없는
    플러그인의 표시 이름·분류를 최대한 정확히 추정하는 데 사용한다."""
    path = _find_module_file(os.path.join(_plugins_metadata_dir(), plugin_id), plugin_id)
    if not path:
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


# ========================================================================
# GitHub Topics 기반 발견(discovery) — plugin_list.txt 큐레이션과는 별개로
# Search API로 DISCOVERY_TOPICS가 달린 저장소를 찾아 "미검수" 카드로 함께
# 보여준다. 검증 없이 자동 노출되므로 카드에는 반드시 미검수 표시를 한다.
# ========================================================================
def _fetch_repos_by_topic(topics, token):
    """GitHub Search API(`/search/repositories?q=topic:...`)로 지정된 토픽이
    달린 공개 저장소를 찾는다. 토픽 하나가 실패해도 나머지는 계속 시도하며,
    전체 결과는 1시간 캐시한다(Search API는 분당 요청 제한이 따로 있어
    plugin_list.txt보다도 더 아껴 써야 한다)."""
    topics = [t.strip() for t in topics if t and t.strip()]
    if not topics:
        return []

    cache_key = ",".join(sorted(set(topics)))
    now = time.time()
    cached = _TOPIC_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _TOPIC_CACHE_TTL_SECONDS:
        return cached[1]

    seen = {}
    for topic in topics:
        try:
            query = urllib.parse.quote("topic:%s" % topic, safe="")
            url = "https://api.github.com/search/repositories?q=%s&per_page=50" % query
            data = _http_get_json(url, token)
            for repo_json in data.get("items", []) or []:
                full_name = repo_json.get("full_name")
                if full_name and full_name not in seen:
                    seen[full_name] = repo_json
        except Exception:
            continue  # 토픽 하나가 실패해도 나머지 토픽 검색은 계속한다

    results = list(seen.values())
    _TOPIC_CACHE[cache_key] = (now, results)
    return results


def _fetch_versions_parallel(specs, token, max_workers=8):
    """[(owner, repo, default_branch), ...]에 대해 버전 정보를 병렬로 조회한다.
    _fetch_version_info의 1시간 캐시를 그대로 활용한다."""
    results = {}
    if not specs:
        return results
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max_workers, len(specs))
    ) as executor:
        future_map = {
            executor.submit(_fetch_version_info, owner, repo, token, branch): (owner, repo)
            for owner, repo, branch in specs
        }
        for future in concurrent.futures.as_completed(future_map):
            key = future_map[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = {"version_label": "—", "remote_version": None, "error": True}
    return results


def _build_discovered_item(repo_json, version_info, is_enabled_fn, excluded_ids):
    """GitHub Search API 결과 하나를 카드 항목으로 변환한다. 설명·토픽·URL은
    검색 결과에 이미 포함돼 있으므로 추가 조회 없이 그대로 쓰고, 버전만
    미리 병렬로 조회해둔 version_info를 사용한다."""
    owner_login = ((repo_json.get("owner") or {}).get("login")) or ""
    repo_name = repo_json.get("name") or ""
    if not owner_login or not repo_name or repo_name in excluded_ids:
        return None

    key = owner_login + "/" + repo_name
    installed = _is_installed(repo_name)
    installed_version = _local_version(repo_name) if installed else None

    plugin_type = TYPE_OVERRIDES.get(key, "other")
    has_config = False
    title = repo_name
    if installed:
        local_attrs = _read_local_class_attrs(repo_name)
        if local_attrs.get("is_searchable"):
            plugin_type = "search"
        elif local_attrs.get("category_tab"):
            plugin_type = "tab"
        has_config = bool(local_attrs.get("config_schema")) or _has_settings_ui(repo_name)
        title = local_attrs.get("name") or repo_name

    remote_version = version_info["remote_version"] if version_info else None
    version_label = version_info["version_label"] if version_info else "—"

    return {
        "id": repo_name,
        "owner": owner_login,
        "title": title,
        "type": plugin_type,
        "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
        "desc": repo_json.get("description") or "(GitHub에 등록된 설명이 없습니다)",
        "tags": repo_json.get("topics") or [],
        "features": [],
        "version_label": version_label,
        "url": repo_json.get("html_url") or ("https://github.com/%s" % key),
        "error": bool(version_info and version_info.get("error")),
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(repo_name) if installed else None,
        "discovered": True,
    }


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
    title = repo

    if installed:
        # 이미 설치되어 있다면 실제 소스에서 분류·설정 여부·표시 이름을 더 정확히 추정
        local_attrs = _read_local_class_attrs(repo)
        if local_attrs.get("is_searchable"):
            plugin_type = "search"
        elif local_attrs.get("category_tab"):
            plugin_type = "tab"
        has_config = bool(local_attrs.get("config_schema")) or _has_settings_ui(repo)
        title = local_attrs.get("name") or repo

    # 병렬로 미리 가져온 원격 정보가 있으면 그걸 쓰고, 없으면(단건 호출 등) 직접 조회
    info = preloaded_info if preloaded_info is not None else _fetch_remote_info(owner, repo, token)
    remote_version = info["remote_version"]

    item = {
        "id": repo,
        "owner": owner,
        "title": title,
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
    _save_disk_cache()
    _try_hot_reload(plugin_id)
    return True, "'%s' 플러그인이 삭제되었습니다." % plugin_id



def _install_or_update(owner, repo, token=None):
    """저장소 zip을 받아 plugins/metadata/{repo}/를 통째로 교체한다.
    update_manifest.files 화이트리스트로 파일을 골라내지 않고, 검증에 성공한
    새 소스로 기존 설치 폴더를 완전히 대체한다(전체 재다운로드 방식)."""
    _validate_plugin_id(repo)

    # default_branch는 카드 목록을 불러올 때(_fetch_description_info, 24시간 캐시)
    # 이미 조회해둔 값을 그대로 재사용한다. 여기서 별도로 api.github.com을 다시
    # 부르면 신규설치/업데이트 버튼을 누를 때마다 코어 API 호출이 하나씩 더
    # 늘어나는데, GITHUB_TOKEN을 설정하지 않은 사용자(무인증 시간당 60회)에게는
    # 이 중복 호출이 rate limit을 훨씬 빨리 소진시키는 주요 원인이었다.
    info = _fetch_description_info(owner, repo, token)
    default_branch = info.get("default_branch")

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

            # 최소한의 신원 확인: 저장소 이름(또는 하이픈↔언더스코어를 바꾼 표기)과
            # 같은 메인 모듈 파일이 있어야 BookOasis 플러그인 저장소로 간주한다.
            # GitHub 저장소명은 하이픈을 흔히 쓰지만 파이썬 파일명은 하이픈을 못 써서
            # 언더스코어로 짓는 경우가 많다(예: bookoasis-tk 저장소 → bookoasis_tk.py).
            module_py = _find_module_file(src_root, repo)
            if not module_py:
                # 다운로드·압축 해제까지는 성공했으므로, 이후 브랜치를 더 시도해도
                # 같은 이유로 실패할 뿐이다. 다른 브랜치의 무관한 오류(예: 존재하지
                # 않는 브랜치의 404)가 이 더 정확한 원인을 덮어쓰지 않도록 여기서
                # 바로 반환한다.
                return False, (
                    "'%s.py'(또는 '%s.py') 파일을 찾지 못했습니다 — BookOasis 플러그인 "
                    "저장소가 맞는지, 메인 모듈 파일명이 저장소 이름과 같은지(하이픈은 "
                    "언더스코어로 바꿔서도 확인함) 확인해주세요." % (repo, repo.replace("-", "_"))
                )

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
            _save_disk_cache()
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
        {
            "key": "EXTRA_DISCOVERY_TOPICS",
            "label": "추가 발견 토픽 (콤마로 구분, 선택)",
            "type": "text",
            "required": False,
            "description": (
                "코드 수정 없이 GitHub Topics 발견 대상을 늘리고 싶을 때 사용합니다. "
                "기본값 'bookoasis-plugin'에 더해 검색할 토픽을 콤마(,)로 구분해 입력하세요. "
                "⚠ 토픽은 GitHub 전역에서 공유되는 이름이라, 흔한 단어를 넣으면 전혀 무관한 "
                "저장소가 대량으로 섞여 들어올 수 있습니다(VERSION 파일이 없는 저장소는 자동 "
                "제외되지만, 가급적 다른 곳과 겹치지 않는 구체적인 토픽 이름만 추가하세요)."
            ),
        },
        {
            "key": "AUTO_UPDATE_ENABLED",
            "label": "사용 중인 플러그인 자동 업데이트",
            "type": "checkbox",
            "required": False,
            "default": False,
            "description": (
                "체크하면, 활성화(사용 중)된 플러그인에 새 버전이 있을 때 이 화면을 열 때마다 "
                "자동으로 업데이트를 시도합니다(plugin_board 자기 자신도 대상에 포함됩니다). "
                "기본값은 꺼짐이며, 체크 전까지는 지금처럼 `업데이트` 버튼을 직접 눌러야만 "
                "갱신됩니다. 자동 업데이트도 §5의 전체 재다운로드 방식(검증 후 폴더 교체)을 "
                "그대로 사용합니다."
            ),
        },
    ]

    # 좌측 사이드바 1등 시민 카테고리 메뉴로 등록
    category_tab = {
        "title": "플러그인게시판",
        "icon": "fa-solid fa-layer-group",
        "order": 90,
        "sessions": "all", 
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

        if action == "get_config":
            # /api/media/metadata/plugins/manage 응답의 config 필드만 믿지 않고,
            # 가이드 문서(§4)에 명시된 저장 위치(settings 테이블의
            # PLUGIN_CONFIG_{id}, JSON 문자열)를 DB 게이트웨이로 직접 조회한다.
            # 어떤 플러그인이 설정을 저장했는데도 /manage가 그 값을 안 돌려주는
            # 경우에 대비한 더 확실한(authoritative) 조회 경로다.
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            try:
                gateway = self.get_db_gateway(db_type)
            except Exception as exc:
                return False, "DB 게이트웨이를 가져오지 못했습니다: %s" % exc
            try:
                raw = gateway.get_setting("PLUGIN_CONFIG_%s" % plugin_id, default=None)
            except Exception as exc:
                return False, "설정 조회 중 오류가 발생했습니다: %s" % exc

            if raw is None:
                return True, {}
            if isinstance(raw, dict):
                # 일부 게이트웨이 구현은 {"value": "...json..."} 형태로 감싸서
                # 반환하기도 하므로(예: plugin_manager의 gateway.get_setting 사용 예),
                # 그 경우까지 함께 처리한다.
                if "value" in raw and isinstance(raw.get("value"), str):
                    try:
                        parsed = json.loads(raw["value"])
                        return True, parsed if isinstance(parsed, dict) else {}
                    except Exception:
                        return True, {}
                return True, raw
            try:
                parsed = json.loads(raw)
                return True, parsed if isinstance(parsed, dict) else {}
            except Exception:
                return True, {}

        if action == "refresh_list":
            cfg = self.get_plugin_config(db_type, default={})
            token = cfg.get("GITHUB_TOKEN") or None
            urls = _fetch_repo_list(token, force=True)
            _TOPIC_CACHE.clear()  # GitHub Topics 발견 캐시도 함께 강제 갱신
            _save_disk_cache()
            if not urls:
                return False, (
                    "plugin_list.txt를 다시 가져오지 못했습니다 "
                    "(%s 조회 실패)" % REMOTE_PLUGIN_LIST_URL
                )
            return True, "플러그인 목록을 새로 불러왔습니다 (%d개 저장소)." % len(urls)

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
        auto_update_enabled = bool(cfg.get("AUTO_UPDATE_ENABLED"))

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

        # plugin_board 자기 자신은(plugin_list.txt 어디에 적혀있든, 혹은 위에서
        # 자동 추가됐든) 항상 카드 목록 맨 앞에 오도록 재정렬한다.
        self_urls = [u for u in repo_urls if _parse_owner_repo(u)[1] == "plugin_board"]
        other_urls = [u for u in repo_urls if _parse_owner_repo(u)[1] != "plugin_board"]
        repo_urls = self_urls + other_urls

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

        # 하이브리드 발견: plugin_list.txt 큐레이션과 별개로 GitHub Topics에서
        # 자동으로 찾아온 저장소도 "미검수" 카드로 함께 보여준다. 큐레이션
        # 목록에 이미 있는 저장소는 여기서 제외해 카드가 중복되지 않게 한다.
        extra_topics_raw = str(cfg.get("EXTRA_DISCOVERY_TOPICS") or "").strip()
        extra_topics = [t.strip() for t in extra_topics_raw.split(",") if t.strip()]
        all_topics = list(dict.fromkeys(DISCOVERY_TOPICS + extra_topics))  # 순서 유지 + 중복 제거

        discovered_items = []
        try:
            topic_repos = _fetch_repos_by_topic(all_topics, token)
        except Exception:
            topic_repos = []

        if topic_repos:
            version_specs = []
            for repo_json in topic_repos:
                owner_login = ((repo_json.get("owner") or {}).get("login")) or ""
                repo_name = repo_json.get("name") or ""
                if owner_login and repo_name and repo_name not in curated_ids:
                    version_specs.append((owner_login, repo_name, repo_json.get("default_branch")))
            version_infos = _fetch_versions_parallel(version_specs, token)

            seen_discovered_ids = set()
            for repo_json in topic_repos:
                owner_login = ((repo_json.get("owner") or {}).get("login")) or ""
                repo_name = repo_json.get("name") or ""
                vinfo = version_infos.get((owner_login, repo_name))
                item = _build_discovered_item(
                    repo_json, vinfo, is_enabled_fn, curated_ids | seen_discovered_ids
                )
                if not item:
                    continue
                # 노이즈 필터: VERSION 파일을 못 찾았고 이미 설치된 것도 아니면
                # BookOasis 플러그인이 아닐 가능성이 높으므로 카드에서 제외한다.
                if not item["installed"] and item["version_label"] == "—":
                    continue
                seen_discovered_ids.add(item["id"])
                discovered_items.append(item)

            if len(discovered_items) > _MAX_DISCOVERED_ITEMS:
                discovered_items = discovered_items[:_MAX_DISCOVERED_ITEMS]

        discovered_ids = {it["id"] for it in discovered_items}
        local_items = _scan_uncurated_installed(curated_ids | discovered_ids, is_enabled_fn)
        _save_disk_cache()  # 이번 요청에서 새로 채워진 캐시를 재시작에도 살아남도록 저장
        return {
            "success": True,
            "items": curated_items + discovered_items + local_items,
            "auto_update_enabled": auto_update_enabled,
        }
