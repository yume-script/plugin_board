# -*- coding: utf-8 -*-
"""
plugin_board — BookOasis 카테고리 탭 플러그인

좌측 사이드바에 "플러그인게시판" 탭을 추가하고, BookOasis 플러그인 저장소 목록을
색인 카드 형태로 보여준다. 카드로 보여줄 저장소 목록 자체는 GitHub Topics 검색
(`bookoasis-plugin` 토픽)으로 실시간 수집한다 — 별도로 관리하는 큐레이션 목록
파일이 없으므로, 새 플러그인 저장소는 그 저장소에 토픽만 달면 자동으로 카드에
나타난다.

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
import urllib.parse
import urllib.request
import tarfile
import zipfile

from plugins.metadata.base import BaseMetadataProvider


def _is_admin_session():
    """현재 요청의 Flask 세션이 관리자(role == 'admin')인지 확인한다
    (api/auth.py의 admin_required 데코레이터와 동일한 판별 기준).
    플러그인 메서드도 같은 Flask 요청 컨텍스트 안에서 실행되므로 session을
    직접 읽을 수 있다. 세션을 못 읽는 예외적인 상황(요청 컨텍스트 밖에서 호출
    되는 등)에는 기존 동작을 깨지 않도록 안전하게 True(관리자로 간주)로
    폴백한다 — role 기반 세션이 없는 구버전 코어에서도 버튼이 계속 보이도록."""
    try:
        from flask import session
        role = session.get("role")
        if role is None:
            return True  # role 정보 자체가 없는 환경(구버전 등) — 기존처럼 표시
        return role == "admin"
    except Exception:
        return True


# plugin_board 자기 자신도 GitHub Topics 검색으로 발견될 수 있지만("미검수" 표시가
# 붙는 것을 피하고, 검색 결과에 아직 안 잡히는 개발 중인 버전도 항상 다룰 수 있도록)
# 별도 경로로 직접 조회해 카드 목록 맨 앞에 고정한다. 코어의 별도 자동 업데이트
# 화면에 의존하지 않고 이 카드 목록 안에서도 스스로의 업데이트 여부를 확인/설치한다.
SELF_REPO_URL = "https://github.com/yume-script/plugin_board"

# ----------------------------------------------------------------------
# GitHub Topics에 이 토픽이 달린 저장소를 자동으로 찾아 카드로 보여준다(Search
# API 사용). 기본값은 "bookoasis-plugin" 하나뿐이지만, 이 리스트에 문자열을
# 더 추가하면(코드 배포로) 여러 토픽을 동시에 검색할 수 있다. 코드를 건드리지
# 않고 서버별로 토픽을 추가하고 싶으면 플러그인 설정의 EXTRA_DISCOVERY_TOPICS
# (콤마 구분)를 쓰면 된다 — 둘은 합쳐져서 함께 검색된다.
# ----------------------------------------------------------------------
DISCOVERY_TOPICS = ["bookoasis-plugin"]

# 토픽은 GitHub 전역에서 공유되는 이름이라, 흔한 단어를 추가 토픽으로 넣으면
# 전혀 무관한 저장소가 대량으로 섞여 들어올 수 있다(실측: 흔한 이름 하나로
# 무관한 저장소 50개 이상이 잡힌 사례 있음). 그래서 두 단계로 방어한다:
#   1) VERSION 파일을 실제로 찾은(=BookOasis 플러그인일 가능성이 높은) 저장소만
#      카드로 인정 — 이미 설치되어 있는 저장소는 예외적으로 항상 허용
#   2) 그래도 남는 개수를 아래 상한으로 한 번 더 자른다
_MAX_DISCOVERED_ITEMS = 30

_TOPIC_CACHE = {}  # {"topic1,topic2": (timestamp, [repo_json, ...])}
_TOPIC_CACHE_TTL_SECONDS = 3600  # 1시간마다 검색 결과를 다시 조회
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
_REQUEST_TIMEOUT = 10  # 6초는 서버-GitHub 간 왕복 지연이 큰 환경에서 일시적으로 짧을 수 있어 늘림
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
        # api.github.com은 "Bearer"/"token" 둘 다 인식하지만, 비공개 저장소의
        # raw.githubusercontent.com(VERSION 파일)과 codeload.github.com(zip
        # 다운로드)은 "token" 방식만 확실히 동작한다("Bearer"는 무시되거나
        # 실패하는 사례가 보고됨). 세 서비스 모두에서 동작하는 공통 표기를 쓴다.
        headers["Authorization"] = "token " + token
    return headers


def _github_api_error_message(exc, has_token):
    """GitHub/Gitea API 오류를 원인별로 구분해 사람이 읽을 메시지를 만든다.
    401(Bad credentials)과 403(rate limit 또는 권한 부족)을 뭉뚱그려 "호출
    제한 또는 오류"로만 표시하면, 실제로는 토큰이 잘못됐거나 만료된 경우에도
    사용자가 rate limit 문제로 오인하게 된다."""
    if exc.code == 401:
        if has_token:
            return (
                "GitHub 인증 실패(401) — 설정한 GITHUB_TOKEN이 잘못됐거나 만료/폐기됐을 "
                "수 있습니다. GitHub에서 토큰을 다시 확인하거나 새로 발급해 설정에 저장해주세요."
            )
        return "GitHub 인증 실패(401) — 원인을 알 수 없는 인증 오류입니다. 잠시 후 다시 시도해주세요."
    if exc.code == 403:
        if has_token:
            return "GitHub API 호출 제한(403) — 인증된 토큰 기준 한도(시간당 5,000회)를 초과했을 수 있습니다."
        return "GitHub API 호출 제한(403) — 무인증 한도(시간당 60회)를 초과했습니다. GITHUB_TOKEN 설정을 권장합니다."
    return "GitHub API 오류(%s)" % exc.code


def _http_get_json(url, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return resp.read().decode("utf-8")


_REPO_URL_RE = re.compile(r"^https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?/?$")


def _extract_url_credentials(url):
    """URL에 https://user:pass@host/... 형식으로 자격증명이 직접 포함돼 있으면
    분리해 (자격증명이 제거된_URL, username, password)로 반환한다. 없으면
    (원본 url, None, None). 저장소 카드 링크·github.txt 레지스트리에는 항상
    이 함수로 정제한 URL만 남겨서 비밀번호가 그대로 노출되지 않도록 한다."""
    try:
        parsed = urllib.parse.urlsplit((url or "").strip())
        if not parsed.username and not parsed.password:
            return url, None, None
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += ":%d" % parsed.port
        clean = urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        username = urllib.parse.unquote(parsed.username) if parsed.username else None
        password = urllib.parse.unquote(parsed.password) if parsed.password else None
        return clean, username, password
    except Exception:
        return url, None, None


def _parse_repo_url(url):
    """URL에서 (host, owner, repo)를 호스트 무관하게 추출한다(GitHub·Gitea 등
    어떤 Git 호스팅이든 동일한 owner/repo 형태의 주소라고 가정). URL에 자격증명이
    포함돼 있으면 먼저 제거한 뒤 파싱한다. 실패하면 (None, None, None)."""
    clean_url, _, _ = _extract_url_credentials(url)
    m = _REPO_URL_RE.match((clean_url or "").strip())
    if not m:
        return None, None, None
    return m.group(1), m.group(2), m.group(3)


def _url_scheme(url):
    """URL의 스킴(http/https)을 반환한다. Gitea 서버가 Cloudflare 등 프록시
    뒤에서 http로만 서비스되는 경우(HTTPS로 강제 접속하면 523 "origin
    unreachable" 오류가 남) 사용자가 준 스킴을 그대로 존중해야 한다.
    파싱 실패 시에만 안전하게 https로 폴백한다."""
    m = re.match(r"^(https?)://", (url or "").strip(), re.IGNORECASE)
    return m.group(1).lower() if m else "https"


def _is_github_host(host):
    return (host or "").lower() in ("github.com", "www.github.com")


def _parse_owner_repo(url):
    """GitHub 저장소 URL에서만 (owner, repo)를 추출한다. GitHub가 아닌 호스트는
    (None, None)을 반환한다(Gitea 등은 _parse_repo_url + _effective_gitea_cfg로 별도 처리)."""
    host, owner, repo = _parse_repo_url(url)
    if not host or not _is_github_host(host):
        return None, None
    return owner, repo


# ------------------------------------------------------------------
# Gitea(및 호환 포크) 지원 — GitHub가 아닌 모든 호스트는 서버별 허용 목록 없이
# 전부 Gitea REST API(Gitea 1.23+에서도 동작이 확인된 형태)로 시도한다. 인증이
# 필요하면 서버 설정이 아니라 URL 자체에 담는다(https://아이디:비밀번호@host/...
# 또는 https://토큰@host/...) — 저장소마다 다른 Gitea 서버·다른 계정을 자유롭게
# 섞어 써도 서로 간섭하지 않도록 하기 위함이다. GitHub는 아이디+비밀번호 인증을
# 2021년에 폐지했지만 Gitea는 여전히 지원하므로, 토큰이 없는 사용자를 위해
# Basic Auth(사용자명+비밀번호)도 함께 지원한다.
# ------------------------------------------------------------------
def _effective_gitea_cfg(url):
    """URL에 담긴 자격증명(https://아이디:비밀번호@host/... 또는 https://토큰@host/...)
    만으로 Gitea 인증 정보를 만든다. 서버별 전역 설정을 두지 않으므로 도메인 개수에
    제한이 없다 — 저장소마다 다른 Gitea 서버·다른 계정을 자유롭게 쓸 수 있다."""
    _, username, password = _extract_url_credentials(url)
    if username and password:
        return {"token": None, "username": username, "password": password}
    if username:  # https://TOKEN@host/owner/repo 형태(토큰만 있는 경우)
        return {"token": username, "username": None, "password": None}
    return {"token": None, "username": None, "password": None}


def _effective_github_token(url, fallback_token):
    """URL에 담긴 자격증명을 우선 쓰고, 없으면 GITHUB_TOKEN 설정값으로 폴백한다.
    https://user:TOKEN@github.com/... 형태면 비밀번호 자리를, https://TOKEN@github.com/...
    형태(사용자명 자리에 토큰만)면 사용자명 자리를 토큰으로 간주한다."""
    _, username, password = _extract_url_credentials(url)
    if password:
        return password
    if username:
        return username
    return fallback_token


def _gitea_headers(gitea_cfg):
    headers = {"Accept": "application/json", "User-Agent": "BookOasis-Plugin-Board"}
    if not gitea_cfg:
        return headers
    # 토큰이 있으면 우선 사용(Gitea 1.23+에서 Basic Auth가 폐지 예정이라 더 안전),
    # 없으면 사용자명+비밀번호로 Basic Auth를 시도한다(GitHub와 달리 Gitea는
    # 여전히 지원 — 사용자가 "아이디/비밀번호"만 갖고 있는 경우를 위함).
    if gitea_cfg.get("token"):
        headers["Authorization"] = "token " + gitea_cfg["token"]
    elif gitea_cfg.get("username") and gitea_cfg.get("password"):
        raw = ("%s:%s" % (gitea_cfg["username"], gitea_cfg["password"])).encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    return headers


def _gitea_get_json(host, path, gitea_cfg, scheme="https"):
    req = urllib.request.Request("%s://%s%s" % (scheme, host, path), headers=_gitea_headers(gitea_cfg))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gitea_get_text(host, path, gitea_cfg, scheme="https"):
    req = urllib.request.Request("%s://%s%s" % (scheme, host, path), headers=_gitea_headers(gitea_cfg))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def _gitea_download_zip(host, path, dest_path, gitea_cfg, scheme="https"):
    req = urllib.request.Request("%s://%s%s" % (scheme, host, path), headers=_gitea_headers(gitea_cfg))
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)


def _gitea_fetch_description_info(host, owner, repo, gitea_cfg, scheme="https"):
    """Gitea REST API(`GET /api/v1/repos/{owner}/{repo}`)로 설명·기본 브랜치를
    조회한다. GitHub 캐시와 섞이지 않도록 키에 "gitea:호스트/" 접두어를 쓴다."""
    key = "gitea:%s/%s/%s" % (host, owner, repo)
    cached = _DESC_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _DESC_CACHE_TTL_SECONDS:
        return cached[1]

    fallback_url = "%s://%s/%s/%s" % (scheme, host, owner, repo)
    try:
        data = _gitea_get_json(host, "/api/v1/repos/%s/%s" % (owner, repo), gitea_cfg, scheme)
        info = {
            "desc": data.get("description") or "(등록된 설명이 없습니다)",
            "tags": [],  # Gitea 토픽 발견은 v1 미지원(GitHub Topics 전용 기능)
            "url": data.get("html_url") or fallback_url,
            "default_branch": data.get("default_branch"),
            "stars": data.get("stars_count"),
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        hint = " (인증 정보를 확인해주세요)" if exc.code in (401, 403) else ""
        info = {
            "desc": "Gitea API 호출 오류 (HTTP %s)%s" % (exc.code, hint),
            "tags": [], "url": fallback_url, "default_branch": None, "stars": None, "error": True,
        }
    except Exception as exc:
        info = {
            "desc": "Gitea 저장소 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [], "url": fallback_url, "default_branch": None, "stars": None, "error": True,
        }

    _DESC_CACHE[key] = (time.time(), info)
    return info


def _gitea_fetch_version(host, owner, repo, default_branch, gitea_cfg, scheme="https"):
    """저장소의 VERSION 파일을 Gitea raw API로 조회한다.
    `/api/v1/repos/{owner}/{repo}/raw/{branch}/{filepath}` 형식(브랜치를 쿼리
    파라미터가 아니라 경로에 직접 포함)을 쓴다 — Gitea 1.23부터 `?ref=` 방식이
    제거되었기 때문에, 구버전·신버전 모두에서 동작하는 경로 방식으로 통일했다."""
    for branch in _candidate_branches(default_branch):
        try:
            text = _gitea_get_text(
                host, "/api/v1/repos/%s/%s/raw/%s/VERSION" % (owner, repo, branch), gitea_cfg, scheme
            )
            data = json.loads(text)
            version = data.get("plugin version")
            if version:
                return str(version)
        except Exception:
            continue
    return None


def _gitea_fetch_version_info(host, owner, repo, default_branch, gitea_cfg, scheme="https"):
    key = "gitea:%s/%s/%s" % (host, owner, repo)
    cached = _VERSION_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _VERSION_CACHE_TTL_SECONDS:
        return cached[1]

    remote_version = _gitea_fetch_version(host, owner, repo, default_branch, gitea_cfg, scheme)
    info = {
        "version_label": ("v" + remote_version) if remote_version else "—",
        "remote_version": remote_version,
        "error": remote_version is None,
    }
    _VERSION_CACHE[key] = (time.time(), info)
    return info


# ========================================================================
# 로컬 설치 상태 확인 (plugins/metadata 디렉토리를 직접 조회 — 외부 플러그인 불필요)
# ========================================================================
def _plugins_metadata_dir():
    """plugins/metadata 루트 경로 (plugin_board 자신의 부모 디렉토리)"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plugins_root_dir():
    """plugins/ 루트 경로 (plugins/metadata의 부모)."""
    return os.path.dirname(_plugins_metadata_dir())


def _github_registry_path():
    """Git URL로 설치(또는 업데이트)한 저장소 주소를 기록해두는 파일 경로.
    GitHub Topics(커뮤니티 자율 태그)에 없어도 — 검색 결과는 이 플러그인이
    통제할 수 없는 외부 신호라 사라지거나 바뀔 수 있음 — 이 서버에서 실제로
    설치했던 이력만큼은 독자적으로 보존해, 이후에도 계속 업데이트 확인
    대상에 남도록 한다."""
    return os.path.join(_plugins_root_dir(), "data", "plugin_board", "github.txt")


def _load_github_registry():
    """github.txt에 기록된 저장소 주소 목록을 읽는다. 파일이 없거나 읽기에
    실패하면 빈 목록을 반환한다(레지스트리는 성능/편의용 부가 기능이라
    실패해도 플러그인 동작 자체를 막지 않는다)."""
    path = _github_registry_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except Exception:
        return []


def _remember_repo_install(url):
    """설치/업데이트에 성공한 저장소 주소(GitHub든 Gitea든)를 github.txt에
    기록한다. URL에 자격증명(https://아이디:비밀번호@host/...)이 담겨 있으면
    그대로(정제하지 않고) 저장한다 — 이후 대시보드에서 업데이트를 확인할 때도
    같은 자격증명으로 계속 인증하기 위함이다(도메인/계정마다 별도 설정을 두지
    않고, URL 저장 자체가 곧 인증 정보 저장이 되는 방식).

    이미 같은 저장소 이름이 등록돼 있으면 최신 URL(자격증명 포함 여부 포함)로
    교체한다 — 예를 들어 처음엔 자격증명 없이 설치했다가 나중에 자격증명이
    담긴 URL로 다시 설치하면, 그 최신 URL로 갱신되어야 계속 인증이 유지된다.
    기록 실패는 설치 자체를 막을 이유가 아니므로 예외를 조용히 무시한다."""
    try:
        _, _, repo = _parse_repo_url(url)
        if not repo:
            return
        existing = _load_github_registry()
        new_lines = []
        replaced = False
        for line in existing:
            if _parse_repo_url(line)[2] == repo:
                new_lines.append(url)
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(url)

        path = _github_registry_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + ("\n" if new_lines else ""))
    except Exception:
        pass


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
    주요 클래스 속성을 AST로만(코드 실행 없이) 읽어온다. GitHub Topics
    검색으로 아직 발견되지 않았거나 검색 결과가 부실한 플러그인의 표시
    이름·분류를 최대한 정확히 추정하는 데 사용한다."""
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
    """GitHub Topics 검색으로도, github.txt 레지스트리로도 추적되지 않지만
    이 서버에 실제로 설치되어 있는 메타데이터 플러그인을 plugins/metadata
    디렉토리에서 직접 찾아 카드로 만든다. GitHub 저장소 주소를 모르므로
    설명·최신 버전·업데이트 확인은 제공하지 않는다."""
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
            "stars": api_data.get("stargazers_count"),
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        info = {
            "desc": _github_api_error_message(exc, bool(token)),
            "tags": [],
            "url": "https://github.com/%s/%s" % (owner, repo),
            "default_branch": None,
            "stars": None,
            "error": True,
        }
    except Exception as exc:
        info = {
            "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [],
            "url": "https://github.com/%s/%s" % (owner, repo),
            "default_branch": None,
            "stars": None,
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
        "stars": desc_info.get("stars"),
        "error": desc_info["error"] or version_info["error"],
    }





# ========================================================================
# GitHub Topics 기반 발견(discovery) — Search API로 DISCOVERY_TOPICS가 달린
# 저장소를 찾아 카드로 보여준다. 별도로 관리하는 큐레이션 목록이 없으므로
# 이 검색이 카드 목록의 유일한 수집 경로다. 검증 없이 자동 노출되므로
# 카드에는 여전히 "미검수" 표시를 한다(수동으로 확인된 목록이 아니라는 뜻).
# ========================================================================
def _topic_cache_key(topics):
    """_fetch_repos_by_topic와 동일한 방식으로 캐시 키를 만든다(정렬된 중복
    제거 콤마 결합). get_dashboard_data가 검색 직후 그 시각(_TOPIC_CACHE의
    타임스탬프)을 조회할 때도 재사용한다."""
    cleaned = [t.strip() for t in topics if t and t.strip()]
    return ",".join(sorted(set(cleaned)))


def _fetch_repos_by_topic(topics, token):
    """GitHub Search API(`/search/repositories?q=topic:...`)로 지정된 토픽이
    달린 공개 저장소를 찾는다. 토픽 하나가 실패해도 나머지는 계속 시도하며,
    전체 결과는 1시간 캐시한다(Search API는 분당 요청 제한이 따로 있어
    아껴 써야 한다)."""
    topics = [t.strip() for t in topics if t and t.strip()]
    if not topics:
        return []

    cache_key = _topic_cache_key(topics)
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
        "stars": repo_json.get("stargazers_count"),
        "error": bool(version_info and version_info.get("error")),
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(repo_name) if installed else None,
        "discovered": True,
    }


def _fetch_repo_entry(url, token, is_enabled_fn, preloaded_info=None):
    host, owner, repo = _parse_repo_url(url)
    if not host or not owner or not repo:
        return {
            "id": url, "owner": "", "title": url, "type": "other",
            "type_label": TYPE_LABELS["other"],
            "desc": "저장소 주소를 해석하지 못했습니다.",
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
            "installed": False, "installed_version": None, "has_update": False,
            "has_config": False, "enabled": None,
        }

    if not _is_github_host(host):
        # GitHub가 아닌 모든 호스트는 Gitea 호환 API로 시도한다(서버별 허용
        # 목록 없음 — URL에 담긴 자격증명만으로 인증하므로 도메인 개수 제한이 없다).
        gitea_cfg = _effective_gitea_cfg(url)
        scheme = _url_scheme(url)  # http로 준 주소는 http로 그대로 조회(523 방지)
        return _fetch_gitea_repo_entry(host, owner, repo, is_enabled_fn, gitea_cfg, scheme)

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

    # 병렬로 미리 가져온 원격 정보가 있으면 그걸 쓰고, 없으면(단건 호출 등) URL에
    # 담긴 자격증명을 우선 적용해(없으면 GITHUB_TOKEN 설정으로 폴백) 직접 조회
    if preloaded_info is not None:
        info = preloaded_info
    else:
        info = _fetch_remote_info(owner, repo, _effective_github_token(url, token))
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
        "stars": info.get("stars"),
        "error": info["error"],
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(repo) if installed else None,
    }
    return item


def _fetch_gitea_repo_entry(host, owner, repo, is_enabled_fn, gitea_cfg, scheme="https"):
    """GitHub 카드와 동일한 형태의 item dict를 Gitea API로 채워 만든다."""
    key = owner + "/" + repo
    plugin_type = TYPE_OVERRIDES.get(key, "other")
    installed = _is_installed(repo)
    installed_version = _local_version(repo) if installed else None
    has_config = False
    title = repo

    if installed:
        local_attrs = _read_local_class_attrs(repo)
        if local_attrs.get("is_searchable"):
            plugin_type = "search"
        elif local_attrs.get("category_tab"):
            plugin_type = "tab"
        has_config = bool(local_attrs.get("config_schema")) or _has_settings_ui(repo)
        title = local_attrs.get("name") or repo

    desc_info = _gitea_fetch_description_info(host, owner, repo, gitea_cfg, scheme)
    version_info = _gitea_fetch_version_info(
        host, owner, repo, desc_info.get("default_branch"), gitea_cfg, scheme
    )
    remote_version = version_info["remote_version"]

    return {
        "id": repo,
        "owner": owner,
        "title": title,
        "type": plugin_type,
        "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
        "desc": desc_info["desc"],
        "tags": desc_info["tags"],
        "features": [],
        "version_label": version_info["version_label"],
        "url": desc_info["url"],
        "stars": desc_info.get("stars"),
        "error": desc_info["error"] or version_info["error"],
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(repo) if installed else None,
        "gitea": True,
    }


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


# tar 계열(.tar/.tar.gz/.tgz/.tar.bz2/.tbz2/.tar.xz/.txz) 확장자 목록.
# 순서 중요 — endswith 검사 시 더 긴 확장자를 먼저 검사해야 하므로 길이 내림차순.
_ARCHIVE_TAR_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".tar")


def _detect_archive_kind(filename):
    """파일명 확장자로 압축 형식을 판별한다. zip/tar 계열/7z만 인식."""
    name = (filename or "").strip().lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(_ARCHIVE_TAR_EXTS):
        return "tar"
    if name.endswith(".7z"):
        return "7z"
    return None


def _extract_tar_safe(archive_path, extract_dir):
    """tar/tar.gz/tar.bz2/tar.xz 안전 압축 해제. tar도 zip과 동일하게 경로 이탈
    (tar slip) 위험이 있고, 추가로 심볼릭/하드 링크로 압축 폴더 밖 임의 경로를
    참조하게 만들 수 있어 이 두 종류의 멤버는 아예 거부한다. 압축을 열어보기
    전까지는 실제 형식(gzip/bzip2/xz/무압축)을 알 수 없으므로 "r:*"로 자동 감지."""
    with tarfile.open(archive_path, mode="r:*") as tf:
        members = tf.getmembers()

        if len(members) > _MAX_ZIP_ENTRIES:
            raise ValueError(
                "압축 안의 파일 개수가 너무 많습니다 (%d개, 최대 %d개). "
                "'.git' 폴더 등 불필요한 항목이 포함되지 않았는지 확인해주세요."
                % (len(members), _MAX_ZIP_ENTRIES)
            )

        total_uncompressed = sum(m.size for m in members if m.isfile())
        if total_uncompressed > _MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError(
                "압축을 풀었을 때 총 용량이 너무 큽니다 (%.1fMB, 최대 %.0fMB)."
                % (total_uncompressed / (1024 * 1024), _MAX_ZIP_UNCOMPRESSED_BYTES / (1024 * 1024))
            )

        for m in members:
            if m.issym() or m.islnk():
                raise ValueError(
                    "보안 경고: 압축 파일 안에 심볼릭/하드 링크가 포함되어 있어 거부합니다: %s" % m.name
                )
            _safe_join(extract_dir, m.name)  # 경로 이탈 시 예외 발생

        tf.extractall(extract_dir)  # 위에서 멤버 단위 검증을 이미 마쳤으므로 안전


def _extract_7z_safe(archive_path, extract_dir):
    """7z 안전 압축 해제. 파이썬 표준 라이브러리에는 7z 해제 기능이 없어
    서드파티 py7zr이 필요하다 — 없으면(대부분의 서버가 그럴 것) 명확한 안내
    메시지로 우아하게 실패시키고, 있으면 zip/tar와 동일한 기준(개수 상한·
    경로 이탈 검증)으로 안전하게 해제한다. import 실패가 plugin_board의 다른
    기능(카드 조회 등)에는 전혀 영향을 주지 않도록 이 함수 안에서만 시도한다."""
    try:
        import py7zr
    except ImportError:
        raise ValueError(
            "이 서버에는 7z 압축 해제 라이브러리(py7zr)가 설치되어 있지 않아 "
            "7z 파일을 처리할 수 없습니다. zip 또는 tar(.tar/.tar.gz/.tar.bz2/"
            ".tar.xz) 형식으로 다시 올려주세요."
        )

    with py7zr.SevenZipFile(archive_path, mode="r") as zf:
        names = zf.getnames()
        if len(names) > _MAX_ZIP_ENTRIES:
            raise ValueError(
                "압축 안의 파일 개수가 너무 많습니다 (%d개, 최대 %d개)."
                % (len(names), _MAX_ZIP_ENTRIES)
            )
        for name in names:
            _safe_join(extract_dir, name)  # 경로 이탈 시 예외 발생

        total_uncompressed = 0
        try:
            for info in zf.list():
                total_uncompressed += getattr(info, "uncompressed", 0) or 0
        except Exception:
            total_uncompressed = 0  # 크기 정보를 못 가져와도 해제 자체는 진행(개수 제한은 이미 확인함)
        if total_uncompressed > _MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError(
                "압축을 풀었을 때 총 용량이 너무 큽니다 (%.1fMB, 최대 %.0fMB)."
                % (total_uncompressed / (1024 * 1024), _MAX_ZIP_UNCOMPRESSED_BYTES / (1024 * 1024))
            )

        zf.extractall(path=extract_dir)


def _extract_archive_safe(archive_path, extract_dir, filename):
    """파일명 확장자로 압축 형식을 판별해 알맞은 안전 해제 함수로 위임한다."""
    kind = _detect_archive_kind(filename)
    if kind == "zip":
        _extract_zip_safe(archive_path, extract_dir)
    elif kind == "tar":
        _extract_tar_safe(archive_path, extract_dir)
    elif kind == "7z":
        _extract_7z_safe(archive_path, extract_dir)
    else:
        raise ValueError(
            "지원하지 않는 압축 형식입니다: %s "
            "(zip, tar/tar.gz/tar.bz2/tar.xz, 7z만 지원)" % (filename or "(파일명 없음)")
        )


def _find_extracted_root(extract_dir):
    entries = [
        e for e in os.listdir(extract_dir)
        if os.path.isdir(os.path.join(extract_dir, e))
    ]
    if len(entries) == 1:
        return os.path.join(extract_dir, entries[0])
    return extract_dir


# ========================================================================
# Zip/tar/7z 파일 업로드 설치 — madnite1/plugin_manager의 _install_from_zip을
# 참고해 재구현하고, zip 외에 tar 계열·7z(라이브러리 있을 때)도 지원하도록 확장. plugin_manager와 달리 소스 메타를 sqlite가 아니라 이미 있는
# github.txt 레지스트리(§2-2)에 기록해, 설치 방식(zip이든 Git URL이든)과
# 무관하게 동일한 방식으로 업데이트를 계속 추적한다.
# ========================================================================
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
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            tree = ast.parse(f.read(), filename=fpath)
                    except SyntaxError:
                        continue
                    for node in ast.walk(tree):
                        if not isinstance(node, ast.ClassDef):
                            continue
                        try:
                            bases = [ast.unparse(b) for b in node.bases]
                        except Exception:
                            bases = []
                        is_provider = any("BaseMetadataProvider" in b for b in bases)
                        has_id_attr = any(
                            (isinstance(stmt, ast.Assign)
                             and any(isinstance(t, ast.Name) and t.id == "id" for t in stmt.targets))
                            or (isinstance(stmt, ast.AnnAssign)
                                and isinstance(stmt.target, ast.Name) and stmt.target.id == "id")
                            for stmt in node.body
                        )
                        if is_provider or has_id_attr:
                            return True
    except Exception:
        pass
    return False


def _find_plugin_root_dir(start_dir):
    """압축 해제된 폴더 안에서(사용자가 올린 zip은 폴더 깊이가 제각각일 수 있음)
    실제 플러그인 루트 디렉토리를 지능 탐색한다."""
    if _is_plugin_directory(start_dir):
        return start_dir
    for root, dirs, _files in os.walk(start_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
        if _is_plugin_directory(root):
            return root
    try:
        subdirs = [
            os.path.join(start_dir, d) for d in os.listdir(start_dir)
            if os.path.isdir(os.path.join(start_dir, d))
            and not d.startswith(".") and d != "__MACOSX"
        ]
    except Exception:
        subdirs = []
    if len(subdirs) == 1:
        return subdirs[0]
    return start_dir


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
                    elif (isinstance(stmt, ast.AnnAssign)
                          and isinstance(stmt.target, ast.Name)
                          and stmt.target.id == "update_manifest"):
                        value_node = stmt.value
                    if value_node is None:
                        continue
                    try:
                        value = ast.literal_eval(value_node)
                    except Exception:
                        continue
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


def _parse_raw_base_url(raw_base_url):
    """update_manifest.raw_base_url에서 (host, owner, repo, branch, subpath) 추출.
    GitHub raw.githubusercontent.com과 Gitea raw 경로(/raw/branch/<branch>) 둘 다
    지원한다. subpath가 있으면(=monorepo 서브디렉토리) 릴리즈 기준이 플러그인과
    안 맞을 수 있어 호출부에서 추적 대상에서 제외한다."""
    url = str(raw_base_url or "").strip().rstrip("/")
    if not url:
        return None

    m = re.match(r"^https?://([^/]+)/([^/]+)/([^/]+)/raw/(?:branch/)?([^/]+)(/.*)?$", url)
    if m:
        host, owner, repo, branch, rest = m.group(1), m.group(2), m.group(3), m.group(4), (m.group(5) or "")
        return host, owner, repo, branch, rest.strip("/")

    m = re.match(r"^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)(/.*)?$", url)
    if m:
        owner, repo, seg3, rest = m.group(1), m.group(2), m.group(3), (m.group(4) or "")
        if seg3 == "refs" and rest.startswith("/heads/"):
            parts = rest.split("/")
            if len(parts) >= 3:
                return "github.com", owner, repo, parts[2], "/".join(parts[3:]).strip("/")
        return "github.com", owner, repo, seg3, rest.strip("/")

    return None


def _validate_plugin_source(plugin_dir, detected_id):
    """설치 대상 플러그인 소스 정적 검증 (코드 실행 없음 — AST/파일 스캔만).
    개발 가이드 규격 기반. plugin_manager의 검증 항목과 동일한 기준을 쓴다.

    반환: (성공 여부, 체크 결과 리스트 [{'name','ok','detail','warn'?}])
    """
    if os.path.basename(os.path.normpath(plugin_dir)) == "__pycache__":
        return False, []

    checks = []
    base_names = ("base.py", "__init__.py")
    manifest_files, manifest = _extract_update_manifest_files(plugin_dir)

    # 1. VERSION 파일 검사 (update_manifest 선언 시 필수, 미선언 시 경고만)
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
        checks.append({"name": "VERSION", "ok": vfile_ok,
                        "detail": (vdetail if vfile_ok else "update_manifest 선언 시 VERSION 필수 — " + vdetail)})
    else:
        checks.append({"name": "VERSION", "ok": True, "warn": not vfile_ok,
                        "detail": vdetail if vfile_ok else "경고: " + vdetail + " (업데이트 체크 불가)"})

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
    cross_plugin_deps = set()  # plugins.metadata.<다른 플러그인 id>를 직접 import하는 경우

    for fname in py_files:
        fpath = os.path.join(plugin_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            tree = ast.parse(content, filename=fpath)
        except SyntaxError:
            forbidden_hits.append("%s: 파이썬 구문 오류" % fname)
            continue

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
                    elif a.name.startswith("plugins.metadata."):
                        parts = a.name.split(".")
                        if len(parts) >= 3 and parts[2] not in ("base", detected_id):
                            cross_plugin_deps.add(parts[2])
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    forbidden_hits.append("%s: subprocess import 발견" % fname)
                elif node.module and node.module.startswith("plugins.metadata."):
                    parts = node.module.split(".")
                    if len(parts) >= 3 and parts[2] not in ("base", detected_id):
                        cross_plugin_deps.add(parts[2])
            elif isinstance(node, ast.keyword) and node.arg == "shell":
                try:
                    if ast.literal_eval(node.value) is True:
                        forbidden_hits.append("%s: shell=True 사용" % fname)
                except Exception:
                    pass

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            try:
                bases = [ast.unparse(b) for b in node.bases]
            except Exception:
                bases = []

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
        checks.append({"name": "소스", "ok": False, "detail": "BaseMetadataProvider 상속 클래스를 찾을 수 없습니다"})
    else:
        checks.append({"name": "소스", "ok": True, "detail": "%d개 .py 파일, BaseMetadataProvider 클래스 발견" % len(py_files)})

    if class_id is not None:
        if str(class_id).strip() == str(detected_id).strip():
            checks.append({"name": "클래스 id", "ok": True, "detail": class_id})
        else:
            checks.append({"name": "클래스 id", "ok": False,
                            "detail": "코드 내 id='%s' \u2260 감지된 id='%s' — 설치 후 목록에 표시되지 않을 수 있습니다"
                                      % (class_id, detected_id)})
    elif provider_found:
        checks.append({"name": "클래스 id", "ok": False, "detail": "플러그인 클래스에 id 속성이 없습니다"})
    else:
        checks.append({"name": "클래스 id", "ok": False, "detail": "클래스를 찾을 수 없어 검사 불가"})

    if provider_found:
        missing_fields = [f for f in ("name", "is_searchable", "config_schema") if f not in cls_attrs]
        checks.append({"name": "필수 필드", "ok": not missing_fields,
                        "detail": ("클래스에 없음: " + ", ".join(missing_fields)) if missing_fields
                                  else "name/is_searchable/config_schema 확인"})
        missing_methods = [m for m, ok in (("search", has_search), ("apply", has_apply)) if not ok]
        checks.append({"name": "필수 메서드", "ok": not missing_methods,
                        "detail": ("구현 안 됨: " + ", ".join(missing_methods)) if missing_methods
                                  else "search/apply 확인"})
    else:
        checks.append({"name": "필수 필드", "ok": False, "detail": "클래스 없음"})
        checks.append({"name": "필수 메서드", "ok": False, "detail": "클래스 없음"})

    checks.append({"name": "금지 패턴", "ok": not forbidden_hits,
                    "detail": "; ".join(forbidden_hits[:3]) if forbidden_hits else "eval/exec/subprocess 없음"})

    # 다른 플러그인 모듈(plugins.metadata.<다른 id>)을 직접 import하는 경우 —
    # 그 다른 플러그인이 이 서버에 설치돼 있지 않으면 설치 자체는 성공해도
    # 코어가 이 모듈을 로드하는 시점에 "No module named 'plugins.metadata.X'"로
    # 조용히 실패한다. 설치 전에 미리 걸러내 훨씬 명확한 원인을 알려준다.
    missing_deps = sorted(dep for dep in cross_plugin_deps if not _is_installed(dep))
    if missing_deps:
        checks.append({"name": "플러그인 간 의존성", "ok": False,
                        "detail": (
                            "이 플러그인은 다른 플러그인(plugins.metadata.%s)을 직접 "
                            "import하는데, 이 서버에 설치돼 있지 않습니다. 먼저 해당 "
                            "플러그인을 설치한 뒤 다시 시도해주세요." % ", plugins.metadata.".join(missing_deps)
                        )})
    elif cross_plugin_deps:
        checks.append({"name": "플러그인 간 의존성", "ok": True,
                        "detail": "필요한 다른 플러그인(%s) 전부 설치되어 있음" % ", ".join(sorted(cross_plugin_deps))})
    else:
        checks.append({"name": "플러그인 간 의존성", "ok": True, "detail": "다른 플러그인에 대한 직접 의존성 없음"})

    if os.path.isfile(os.path.join(plugin_dir, "__init__.py")):
        checks.append({"name": "__init__.py", "ok": True, "detail": "확인"})
    else:
        checks.append({"name": "__init__.py", "ok": True, "warn": True, "detail": "경고: __init__.py 없음 (폴백 로드 사용)"})

    symlinks = []
    try:
        for root_dir, dirs, files in os.walk(plugin_dir):
            for entry in dirs + files:
                p = os.path.join(root_dir, entry)
                if os.path.islink(p):
                    symlinks.append(os.path.relpath(p, plugin_dir))
    except Exception:
        pass
    checks.append({"name": "심볼릭 링크", "ok": not symlinks,
                    "detail": ("플러그인 폴더 내 심볼릭 링크 금지: " + ", ".join(symlinks[:3])) if symlinks else "없음"})

    if "category_tab" in cls_attrs:
        ui_files = {f: os.path.isfile(os.path.join(plugin_dir, f)) for f in ("index.html", "script.js", "style.css")}
        missing_ui = [f for f, ok in ui_files.items() if not ok]
        checks.append({"name": "UI 번들", "ok": not missing_ui,
                        "detail": ("category_tab 선언 시 필수: " + ", ".join(missing_ui)) if missing_ui
                                  else "index/script/style 확인"})
    else:
        checks.append({"name": "UI 번들", "ok": True, "detail": "미선언"})

    all_ok = all(c.get("ok") for c in checks)
    return all_ok, checks


def _install_from_archive(archive_data_b64, filename, db_type):
    """업로드된 압축 파일(base64, zip/tar 계열/7z)로 플러그인을 설치한다.
    1) base64 디코드 → 파일명 확장자로 형식 판별 → 임시 폴더에 안전하게 압축
       해제(경로 이탈/개수/용량 검증 — 형식별로 _extract_archive_safe에 위임)
    2) 플러그인 루트·ID 지능 탐색 + ID 형식·예약어 검증
    3) 정적 소스 검증(코드 실행 없음) — 실패 시 설치 중단(기존 폴더 미변경)
    4) 검증 통과 후에만 기존 폴더 교체
    5) update_manifest.raw_base_url이 유효하면(GitHub 루트 또는 Gitea, monorepo
       서브디렉토리 아님) github.txt 레지스트리에 백필 등록 — 설치 방식과 무관하게
       이후에도 계속 업데이트를 추적할 수 있도록 한다. 없으면 로컬 플러그인으로 남는다.
    6) 활성화 + 핫 리로드 + 실제 로드 여부 재확인(실패 시 자동 롤백)
    """
    if not archive_data_b64:
        return False, "압축 파일 데이터가 누락되었습니다."
    if "," in archive_data_b64:
        archive_data_b64 = archive_data_b64.split(",", 1)[1]  # data:...;base64, 접두어 제거

    archive_kind = _detect_archive_kind(filename)
    if not archive_kind:
        return False, (
            "지원하지 않는 압축 형식입니다: %s (zip, tar/tar.gz/tar.bz2/tar.xz, 7z만 지원)"
            % (filename or "(파일명 없음)")
        )

    try:
        archive_bytes = base64.b64decode(archive_data_b64)
    except Exception as exc:
        return False, "압축 파일 데이터를 해석하지 못했습니다: %s" % exc

    tmp_dir = tempfile.mkdtemp(prefix="plugin_board_archive_")
    try:
        archive_path = os.path.join(tmp_dir, "upload_" + (filename or "archive"))
        with open(archive_path, "wb") as f:
            f.write(archive_bytes)

        extract_dir = os.path.join(tmp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            _extract_archive_safe(archive_path, extract_dir, filename)
        except (zipfile.BadZipFile, tarfile.ReadError):
            return False, "올바른 압축 파일 형식이 아닙니다(%s로 인식됨)." % archive_kind
        except Exception as exc:
            return False, "압축 해제에 실패했습니다: %s" % exc

        plugin_root = _find_plugin_root_dir(extract_dir)
        plugin_id = _detect_plugin_id_from_dir(plugin_root, fallback_name=filename)
        if not plugin_id:
            return False, "플러그인 ID를 식별하지 못했습니다. (BaseMetadataProvider 클래스 또는 VERSION 파일 필요)"

        if not _PLUGIN_ID_RE.match(plugin_id):
            return False, "유효하지 않은 플러그인 ID입니다 (영문/숫자/언더바/하이픈만 허용): %s" % plugin_id
        if plugin_id in ("base.py", "base", "__pycache__", "plugin_manager", "plugin_board"):
            return False, "시스템 예약어 또는 핵심 플러그인은 덮어쓸 수 없습니다: %s" % plugin_id

        source_ok, source_checks = _validate_plugin_source(plugin_root, plugin_id)
        if not source_ok:
            failed_items = ["- %s: %s" % (c["name"], c["detail"]) for c in source_checks if not c.get("ok")]
            return False, (
                "플러그인 검증 실패 — 설치를 중단했습니다 (기존 폴더는 변경되지 않음):\n"
                + "\n".join(failed_items)
            )

        try:
            dest_dir = _safe_join(_plugins_metadata_dir(), plugin_id)
        except ValueError as exc:
            return False, str(exc)

        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.copytree(
            plugin_root, dest_dir,
            ignore=shutil.ignore_patterns(".git", ".github", "__pycache__", "*.pyc", "__MACOSX", ".DS_Store"),
        )

        for cache in (_DESC_CACHE, _VERSION_CACHE):
            for key in [k for k in cache if k.endswith("/" + plugin_id)]:
                cache.pop(key, None)

        _toggle_plugin_enabled(plugin_id, "1", db_type)
        _try_hot_reload(plugin_id)

        if not _verify_plugin_loaded(plugin_id):
            shutil.rmtree(dest_dir, ignore_errors=True)
            return False, (
                "검증 실패: '%s' 플러그인이 설치 후 로드되지 않았습니다. "
                "(클래스 id와 폴더명이 일치하는지 확인 필요) — 설치 폴더를 삭제했습니다." % plugin_id
            )

        # update_manifest가 있고 raw_base_url이 GitHub 루트(또는 Gitea)를 가리키면,
        # 설치 방식(zip)과 무관하게 github.txt 레지스트리에 등록해 이후에도 계속
        # 업데이트를 추적한다. monorepo 서브디렉토리는 릴리즈 기준이 안 맞아 제외.
        # 2차 로드 검증을 통과한 뒤에만 기록한다 — 검증 실패로 롤백된 설치가
        # 레지스트리에 남아 있는(존재하지 않는 플러그인을 가리키는) 상태를 방지한다.
        try:
            files_clean, manifest = _extract_update_manifest_files(dest_dir)
            raw_base_url = str((manifest or {}).get("raw_base_url") or "").strip().rstrip("/")
            if files_clean and raw_base_url:
                parsed = _parse_raw_base_url(raw_base_url)
                if parsed and not parsed[4]:  # subpath가 없을 때만
                    host, owner, repo, _branch, _sub = parsed
                    _remember_repo_install("https://%s/%s/%s" % (host, owner, repo))
        except Exception:
            pass
        _save_disk_cache()

        passed = [c["name"] for c in source_checks if c.get("ok") and not c.get("warn")]
        warns = [c["detail"] for c in source_checks if c.get("warn")]
        new_version = _local_version(plugin_id) or "?"
        result_msg = (
            "압축 파일(%s)을 통해 '%s' 플러그인이 성공적으로 설치 및 활성화되었습니다! "
            "(버전 v%s, 검증 통과: %s)" % (archive_kind, plugin_id, new_version, ", ".join(passed))
        )
        if warns:
            result_msg += " 경고: " + "; ".join(warns)
        return True, result_msg
    except (zipfile.BadZipFile, tarfile.ReadError):
        return False, "올바른 압축 파일 형식이 아닙니다."
    except Exception as exc:
        return False, "압축 파일 플러그인 설치 중 오류가 발생했습니다: %s" % exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _detect_plugin_id_from_dir(plugin_dir, fallback_name=None):
    """VERSION의 id/plugin_id → 코드 내 id="..." → 폴더 이름 → zip 파일명 순으로
    plugin_id를 결정한다(AST로만 읽으며 코드를 실행하지 않음)."""
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
        for fname in sorted(os.listdir(plugin_dir)):
            if fname.endswith(".py") and fname not in ("__init__.py", "base.py"):
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
                                if isinstance(target, ast.Name) and target.id == "id":
                                    value_node = stmt.value
                                    break
                        elif (isinstance(stmt, ast.AnnAssign)
                              and isinstance(stmt.target, ast.Name) and stmt.target.id == "id"):
                            value_node = stmt.value
                        if value_node is None:
                            continue
                        try:
                            value = ast.literal_eval(value_node)
                        except Exception:
                            continue
                        if isinstance(value, str) and value.strip() and _PLUGIN_ID_RE.match(value.strip()):
                            return value.strip()
    except Exception:
        pass

    folder_name = os.path.basename(os.path.normpath(plugin_dir))
    if folder_name and folder_name.lower() not in ("temp", "tmp") and not folder_name.lower().startswith(
        ("plugin_board_zip", "extract", "tmp")
    ):
        return folder_name

    if fallback_name:
        clean = re.sub(r"\.zip$", "", str(fallback_name), flags=re.IGNORECASE)
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", clean).strip("_")
        if clean:
            return clean

    return ""


def _verify_plugin_loaded(plugin_id):
    """2차 검증 — 코어가 실제로 이 플러그인을 로드했는지 확인한다.
    확인 자체가 불가능한 경우도 안전하게 '로드 실패'로 간주한다(fail-closed)."""
    try:
        from services.metadata_factory import MetadataFactory
        providers = MetadataFactory.get_available_providers()
        return any(str(p.get("id")) == plugin_id for p in providers)
    except Exception:
        return False


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
        except urllib.error.HTTPError as exc:
            last_error = _github_api_error_message(exc, bool(token))
        except Exception as exc:
            last_error = str(exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return False, "설치/업데이트 실패: %s" % (last_error or "알 수 없는 오류")


def _install_or_update_gitea(host, owner, repo, gitea_cfg, scheme="https"):
    """Gitea 저장소를 설치/업데이트한다. GitHub용 _install_or_update와 동일한
    전체 재다운로드 방식(검증 후 폴더 교체)을 쓰되, 다운로드/조회 경로만
    Gitea API로 바꾼 버전이다."""
    _validate_plugin_id(repo)

    desc_info = _gitea_fetch_description_info(host, owner, repo, gitea_cfg, scheme)
    default_branch = desc_info.get("default_branch")

    last_error = None
    for branch in _candidate_branches(default_branch):
        zip_path_on_server = "/api/v1/repos/%s/%s/archive/%s.zip" % (owner, repo, branch)
        tmp_dir = tempfile.mkdtemp(prefix="plugin_board_gitea_")
        try:
            zip_path = os.path.join(tmp_dir, "src.zip")
            _gitea_download_zip(host, zip_path_on_server, zip_path, gitea_cfg, scheme)

            extract_dir = os.path.join(tmp_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            _extract_zip_safe(zip_path, extract_dir)
            src_root = _find_extracted_root(extract_dir)

            module_py = _find_module_file(src_root, repo)
            if not module_py:
                return False, (
                    "'%s.py'(또는 '%s.py') 파일을 찾지 못했습니다 — BookOasis 플러그인 "
                    "저장소가 맞는지, 메인 모듈 파일명이 저장소 이름과 같은지(하이픈은 "
                    "언더스코어로 바꿔서도 확인함) 확인해주세요." % (repo, repo.replace("-", "_"))
                )

            base_dir = _plugins_metadata_dir()
            target_dir = _safe_join(base_dir, repo)

            if os.path.isdir(target_dir):
                shutil.rmtree(target_dir)
            shutil.copytree(src_root, target_dir)

            key = "gitea:%s/%s/%s" % (host, owner, repo)
            _DESC_CACHE.pop(key, None)
            _VERSION_CACHE.pop(key, None)
            _save_disk_cache()
            _try_hot_reload(repo)

            new_version = _local_version(repo) or "?"
            return True, "'%s' 설치/업데이트 완료 (Gitea %s, 브랜치: %s, 버전: v%s, 저장소 전체 교체)" % (
                repo, host, branch, new_version,
            )
        except urllib.error.HTTPError as exc:
            hint = " (인증 정보를 확인해주세요)" if exc.code in (401, 403) else ""
            last_error = "HTTP %s%s" % (exc.code, hint)
        except Exception as exc:
            last_error = str(exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return False, "설치/업데이트 실패: %s" % (last_error or "알 수 없는 오류")


def _install_or_update_from_url(url, token):
    """URL의 호스트를 보고 GitHub/Gitea 중 맞는 설치 엔진으로 위임한다.
    URL에 https://아이디:비밀번호@host/... (또는 https://토큰@host/...) 형식으로
    자격증명이 직접 포함돼 있으면 그 값으로 인증한다. 서버별 전역 설정을 따로
    두지 않으므로 몇 개의 Gitea 서버든, GitHub 계정이든 URL 하나로 자유롭게
    설치할 수 있다. 설치에 성공하면 **자격증명이 담긴 URL 그대로**(정제하지
    않고) github.txt에 기록해, 이후 대시보드에서 업데이트를 확인할 때도 같은
    자격증명을 계속 재사용한다."""
    clean_url, url_username, url_password = _extract_url_credentials(url)
    host, owner, repo = _parse_repo_url(clean_url)
    if not host or not owner or not repo:
        return False, "Git 저장소 주소를 해석하지 못했습니다: %s" % url

    if _is_github_host(host):
        effective_token = url_password or url_username or token
        ok, msg = _install_or_update(owner, repo, effective_token)
    else:
        gitea_cfg = _effective_gitea_cfg(url)
        scheme = _url_scheme(clean_url)  # http로 준 주소는 http로 그대로 설치(523 방지)
        ok, msg = _install_or_update_gitea(host, owner, repo, gitea_cfg, scheme)

    if ok:
        # 다음 업데이트 확인 때도 같은 인증 정보를 쓸 수 있도록, 자격증명이
        # 담긴 원본 URL 그대로 레지스트리에 기록한다(설치에 쓴 실제 URL 기준).
        _remember_repo_install(url)
    return ok, msg


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

        # 설치/업데이트/삭제/활성화·비활성화/설정 조회는 관리자만 할 수 있게 한다.
        # 화면(설정 버튼)에서는 이미 숨겨두지만, API를 직접 호출하는 우회까지
        # 막기 위해 백엔드에서도 동일하게 확인한다(api/auth.py의 admin_required와
        # 같은 기준). refresh_list는 카드 목록만 새로고침하는 무해한 동작이라
        # 제외한다.
        if action in ("install_git", "update", "toggle", "delete", "get_config", "install_zip") and not _is_admin_session():
            return False, "관리자만 사용할 수 있는 기능입니다."

        if action == "install_zip":
            # 액션 이름은 하위 호환을 위해 유지하지만, zip 외에 tar 계열(.tar/.tar.gz/
            # .tar.bz2/.tar.xz)과 7z(라이브러리가 있으면)도 파일명 확장자로 판별해 처리한다.
            zip_data = str(item_data.get("zip_data", "")).strip()
            filename = str(item_data.get("filename", "")).strip()
            if not zip_data:
                return False, "zip_data가 필요합니다."
            return _install_from_archive(zip_data, filename, db_type)

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
            # GitHub Topics 검색 캐시와, 설치된 버전 vs 최신 버전 비교(has_update)에
            # 쓰이는 캐시를 모두 강제로 비운다 — "목록 새로고침"을 눌렀는데도
            # 최대 1시간(캐시 TTL) 동안 옛날 결과가 그대로 남는 걸 막기 위함이다.
            _TOPIC_CACHE.clear()
            _VERSION_CACHE.clear()
            _DESC_CACHE.clear()
            _save_disk_cache()
            return True, "플러그인 목록과 버전 정보를 새로 불러옵니다."

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
            if not git_url and plugin_id:
                # git_url 없이 plugin_id만 온 경우(업데이트 버튼 등), github.txt
                # 레지스트리(GitHub/Gitea 어느 쪽이든, 자격증명이 담겨 있을 수 있음)에서
                # 대응하는 주소를 찾는다.
                match = next(
                    (u for u in _load_github_registry() if _parse_repo_url(u)[2] == plugin_id),
                    None,
                )
                if match:
                    git_url = match

            if not git_url:
                return False, "Git 저장소 정보를 확인할 수 없습니다."

            return _install_or_update_from_url(git_url, token)

        return False, "지원하지 않는 액션입니다: %s" % action

    # ------------------------------------------------------------------
    # 카테고리 풀페이지 탭이 script.js를 통해 호출하는 데이터 엔드포인트.
    # 카드로 보여줄 저장소 목록 자체를 GitHub Topics 검색으로 매 호출마다
    # (캐시 만료 시) 모으고, 각 저장소의 최신 설명·토픽·버전도 GitHub에서
    # 가져온다. plugins/metadata 디렉토리를 직접 확인해 설치 여부·업데이트 필요
    # 여부·활성화 상태·설정 보유 여부까지 함께 반환한다.
    # ------------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        token = cfg.get("GITHUB_TOKEN") or None
        auto_update_enabled = bool(cfg.get("AUTO_UPDATE_ENABLED"))
        is_admin = _is_admin_session()

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

        # plugin_board 자기 자신은 GitHub Topics 검색 결과와 무관하게 항상
        # 별도로 조회해 카드 목록 맨 앞에 고정한다("미검수" 표시 없이, 개발
        # 중인 버전도 항상 카드+업데이트 버튼으로 다룰 수 있도록).
        self_item = _fetch_repo_entry(SELF_REPO_URL, token, is_enabled_fn)
        curated_ids = {self_item["id"]}

        # GitHub Topics 검색이 카드 목록의 유일한 수집 경로다. 검증 없이 자동
        # 노출되므로 "미검수" 표시를 유지한다.
        extra_topics_raw = str(cfg.get("EXTRA_DISCOVERY_TOPICS") or "").strip()
        extra_topics = [t.strip() for t in extra_topics_raw.split(",") if t.strip()]
        all_topics = list(dict.fromkeys(DISCOVERY_TOPICS + extra_topics))  # 순서 유지 + 중복 제거

        discovered_items = []
        try:
            topic_repos = _fetch_repos_by_topic(all_topics, token)
        except Exception:
            topic_repos = []

        # 검색 직후 _TOPIC_CACHE에 남은 타임스탬프를 그대로 읽어와, "마지막으로
        # 실제 검색한 시각"을 화면에 알려준다(캐시가 살아있어 재요청을 안 한
        # 경우에도 이전 검색 시각이 남아있으므로 정확하다).
        topic_cache_entry = _TOPIC_CACHE.get(_topic_cache_key(all_topics))
        topic_search_at = topic_cache_entry[0] if topic_cache_entry else None

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

        # 직접 설치 이력(github.txt) — GitHub Topics로도 발견되지 않았지만, 이
        # 서버에서 Git URL로 직접 설치했던 저장소는 여기서 계속 추적한다(검색
        # 결과 유무와 무관하게 업데이트 확인을 이어가기 위함).
        registry_items = []
        seen_registry_ids = set()
        excluded_for_registry = curated_ids | discovered_ids
        for url in _load_github_registry():
            _, owner, repo = _parse_repo_url(url)  # 호스트 무관(GitHub/Gitea 둘 다 처리)
            if not owner or not repo:
                continue
            if repo in excluded_for_registry or repo in seen_registry_ids:
                continue
            item = _fetch_repo_entry(url, token, is_enabled_fn)
            item["user_registered"] = True
            seen_registry_ids.add(repo)
            registry_items.append(item)

        local_items = _scan_uncurated_installed(
            curated_ids | discovered_ids | seen_registry_ids, is_enabled_fn
        )
        _save_disk_cache()  # 이번 요청에서 새로 채워진 캐시를 재시작에도 살아남도록 저장
        return {
            "success": True,
            "items": [self_item] + discovered_items + registry_items + local_items,
            "auto_update_enabled": auto_update_enabled,
            "is_admin": is_admin,
            "topic_search_at": topic_search_at,  # 초 단위 epoch, 검색 이력이 전혀 없으면 None
            "plugin_board_version": self_item.get("installed_version"),  # 헤더 제목 옆 버전 표기용
        }
