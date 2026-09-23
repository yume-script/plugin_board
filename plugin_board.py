# -*- coding: utf-8 -*-
"""
plugin_board — BookOasis 카테고리 탭 플러그인

좌측 사이드바에 "플러그인게시판" 탭을 추가하고, BookOasis 플러그인 저장소 목록을
색인 카드 형태로 보여준다. 카드로 보여줄 저장소 목록 자체는 GitHub Topics 검색
(`bookoasis-plugin` 토픽)으로 실시간 수집한다 — 별도로 관리하는 큐레이션 목록
파일이 없으므로, 새 플러그인 저장소는 그 저장소에 토픽만 달면 자동으로 카드에
나타난다.

이 버전부터는 외부 plugin_manager 플러그인 없이도 카드에서 바로 "신규설치"/"업데이트"를
수행할 수 있다. 설치 방식은 madnite1/plugin_manager가 쓰는 것과 동일한 "git 바이너리
없이 GitHub codeload(zip) 소스를 받는다"는 원리만 가져왔을 뿐, 파일 선별 방식은 다르다.
[PATCH-2] update_manifest.files 화이트리스트로 파일을 골라내지 않으며, 압축 해제된
소스 전체로 plugins/metadata/{repo}/ 폴더를 통째로 교체하는 "전체 재다운로드" 방식이다.
AST 추출은 (a) 이미 설치된 플러그인의 name/is_searchable/category_tab 등 표시용
메타데이터를 읽는 _read_local_class_attrs()와, (b) 설치 대상 소스가 실제 BookOasis
플러그인 구조를 갖췄는지 정적 검증하는 _validate_plugin_source()에서만 코드 실행 없이
쓰인다 — update_manifest.files를 설치 대상 파일 선별에 쓰는 곳은 없다.
[PATCH-3] Git/Gitea URL로 설치·업데이트하는 경로(_install_or_update /
_install_or_update_gitea)는 원래 "저장소 이름과 같은 .py 파일이 있는가"만 확인하고
바로 폴더를 교체했다 — 압축 파일 업로드 설치(_install_from_archive)에 이미 적용돼
있던 _validate_plugin_source() 정적 검증(금지 패턴, 클래스 구조, 필수 필드/메서드 등)을
거치지 않는 더 느슨한 경로였다. GitHub Topics로 발견되거나 "Git 저장소 URL 설치"
패널로 직접 입력된 저장소는 운영자가 사전 검수한 목록이 아니므로, 이 버전부터는 두
설치 경로 모두 동일한 정적 검증을 통과해야만 폴더를 교체한다.
(참고: https://github.com/madnite1/plugin_manager)
[PATCH-4] 플러그인 개발 가이드(1.1.1+) 기준 정비:
- 관리자 판별을 fail-closed로 변경(세션 role을 확인할 수 없으면 비관리자로 간주).
- 카드 버튼 액션을 문서화된 범용 RPC 경로(run_context_menu_action,
  /api/media/context-menu/book/plugins/action)로 이전. apply()는 하위 호환용으로만 유지.
- 설치 폴더명과 클래스 id를 분리해서 다룬다. 신규 설치 폴더는 클래스 id 기준으로
  만들고, 활성화 키(PLUGIN_ENABLED_{id})·설정 키·로드 검증은 항상 클래스 id로 조회한다.
- 설치 시점 id 충돌 감지(가이드 §1) — 다른 폴더가 같은 클래스 id를 쓰거나, 같은
  폴더를 다른 저장소가 점유하고 있으면 설치를 거부한다.
- 폴더 교체를 스테이징 → 백업 → 교체 → 로드 검증 → (실패 시) 백업 복원 흐름으로 통일.
- 정적 검증을 가이드 §2-5(프로세스 실행 차단: subprocess, os.system/popen/exec*/spawn*,
  ALLOW_PLUGIN_SUBPROCESS 예외)에 맞추고, 가이드상 필수가 아닌 항목은 경고로 낮춤.
- 분류를 dashboard_widget(플러그인 데스크)/home_widget(홈 화면)/상세 확장 계약으로 구분.
- 캐시를 코어 제공 플러그인 캐시(self.cache_get/cache_set, Redis)로 워커 간 공유하고,
  디스크 캐시는 plugins/data/plugin_board/ 아래로 옮겨 자기 업데이트에도 유지.
[PATCH-5] 플러그인별 HISTORY:
- 이 서버 기록: 설치·업데이트·롤백·실패·삭제·활성화 변경을 plugins/data/plugin_board/
  history.jsonl에 남긴다(버전 전후, 출처, 수동/자동, 실행 관리자, 변경 파일 요약).
- 변경 내용: 저장소의 HISTORY.md/CHANGELOG.md/CHANGES.md에서 설치 버전 이후 구간을
  잘라 보여주고, 파일이 없으면 GitHub/Gitea Releases 본문으로 폴백한다.
  카드 목록 조회 때는 호출하지 않고 사용자가 "이력"을 열 때만 가져온다(rate limit 절약).
[PATCH-6] Gitea 서버 설정 개편:
- GITEA_TOKENS를 서버별 {주소(스킴·포트 포함), 아이디, 비밀번호, 읽기 토큰} JSON 목록으로
  저장한다(구버전 "호스트:토큰" 문자열도 계속 읽으며, host:port 형식도 올바르게 해석).
- 자격증명 없는 Gitea 주소로 설치·주소 변경을 요청하면 저장된 계정으로 자동 인증하고,
  레지스트리에는 https://아이디:비밀번호@호스트/... 형태로 등록한다(API 호출은 토큰 우선).
  설정에서 비밀번호를 바꾸면 레지스트리의 자동 등록 주소도 함께 갱신한다.
- 토픽 검색이 서버별 스킴(http/https)을 따르고, 캐시 키에 인증 정보를 포함한다.
- 인증 없이 검색해 결과가 0개인 서버는 "비공개 저장소가 안 보일 수 있음" 안내 카드를 띄운다.
- 서버별 연결 테스트(test_gitea): 접속·토큰·아이디/비밀번호·토픽 검색 결과를 단계별로 진단.
[PATCH-7] Gitea 소유자 단위 발견:
- 개인 Gitea 서버의 저장소는 토픽이 없는 경우가 많아, 토픽 검색만으로는 설치한 것만 보였다.
  서버별 "소유자" 목록(설정) + 이 서버에서 설치한 적 있는 소유자의 저장소를 모두 조회해
  VERSION 파일("plugin version")이 있는 저장소를 플러그인으로 인식한다(비공개 포함).
- 발견 카드 개수 상한을 GitHub 토픽 결과(30개)에만 적용하고, Gitea는 서버당 100개로 분리.
[PATCH-8] 토픽 검색 결과 누락 수정:
- 기본 토픽만으로 30개 상한을 넘으면서, 추가 발견 토픽·카탈로그 토픽 결과가 병렬 도착 순서에
  따라 잘려 나가던 문제. VERSION 파일 필터를 통과한 저장소는 노이즈가 아니므로 상한을 200개로
  올리고, 결과 순서를 설정 순서(카탈로그 → 추가 발견 → 기본 토픽)로 고정했다.
- GitHub Search API를 per_page=100, 토픽당 최대 3페이지까지 조회(50개 넘는 토픽 대비).
- 응답에 실제로 검색한 토픽 목록(searched_topics)을 실어 화면에 표시한다.
[PATCH-9] Gitea 서버에도 같은 기준 적용:
- 토픽 검색·소유자 스캔을 X-Total-Count 헤더 기준으로 끝까지 페이지 조회(Gitea는 서버 설정
  MAX_RESPONSE_ITEMS 때문에 limit을 크게 줘도 보통 50개씩만 돌려준다).
- 토픽 결과를 설정 순서(카탈로그 → 추가 발견 → 기본)대로 병합하고, 서버당 상한을 200개로 올림.
- 같은 이름의 저장소가 GitHub와 Gitea에 모두 있을 때, 이 서버가 Gitea 쪽에서 설치했으면
  Gitea 카드를 남긴다(예전에는 GitHub 카드가 먼저 자리를 차지해 Gitea 카드가 조용히 버려졌다).

가이드 문서(플러그인 개발 가이드 §3, §6)의 계약을 따른다:
- 필수: search(), apply()
- 선택: category_tab, get_dashboard_data(), update_manifest,
        get_context_menu_items()/run_context_menu_action() (범용 RPC 용도)
"""

import ast
import base64
import concurrent.futures
import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
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

    [PATCH-4] fail-closed — role을 확인할 수 없거나(세션에 role이 없음, 요청
    컨텍스트 밖, 예외 발생) 값이 admin이 아니면 항상 False다. 이 플러그인의
    액션은 임의 코드 설치와 같은 위험한 동작이라, 판단이 불확실할 때 관리자로
    간주하면 안 된다(가이드의 admin_only·ADD_PLUGIN 게이트와 같은 방향)."""
    try:
        from flask import session
        return session.get("role") == "admin"
    except Exception:
        return False


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
# [PATCH-8] 예전 상한(30)은 기본 토픽 결과만으로도 넘쳐, 설정한 추가/카탈로그 토픽 결과가
# 잘려 나갔다. 카드는 VERSION 파일이 확인된 저장소만 되므로 상한은 안전장치로만 둔다.
_MAX_DISCOVERED_ITEMS = 200
_GITHUB_SEARCH_PAGES = 3  # 토픽당 최대 3페이지(100개씩)
# [PATCH-7] Gitea 서버는 VERSION 파일이 있는 저장소만 카드가 되므로(소유자 스캔 포함) 노이즈가
# 적다. GitHub 토픽 상한(30)에 섞여 잘리지 않도록 서버별로 따로 센다.
_MAX_GITEA_ITEMS_PER_HOST = 200
_GITEA_SEARCH_MAX_PAGES = 6  # 검색 1건당 최대 6페이지(서버 설정상 보통 50개씩) = 300개

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

# [PATCH-4] 가이드 §5/§5-1: dashboard_widget은 [플러그인] 공통 데스크용이고, 실제
# 홈 화면 위젯은 home_widget이다. 둘을 같은 "홈화면 위젯"으로 묶지 않는다.
TYPE_LABELS = {
    "search": "검색형 메타데이터",
    "tab": "카테고리 탭 UI",
    "home": "홈 화면 위젯",
    "desk": "플러그인 데스크 위젯",
    "detail": "도서 상세 확장",
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
# [PATCH-4] 캐시 파일을 플러그인 폴더(plugins/metadata/plugin_board/) 밖의
# plugins/data/plugin_board/cache.json으로 옮겼다. 플러그인 폴더는 자기 업데이트 때
# 통째로 교체되므로, 그 안에 두면 업데이트할 때마다 캐시가 날아갔다.
_PLUGIN_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_PLUGIN_SELF_DIR))), "data", "plugin_board"
)
_CACHE_FILE = os.path.join(_PLUGIN_DATA_DIR, "cache.json")
_LEGACY_CACHE_FILE = os.path.join(_PLUGIN_SELF_DIR, ".cache.json")

# 코어 제공 플러그인 캐시(Redis)에 저장할 키. gunicorn 워커가 여러 개면 모듈 전역
# dict는 워커마다 따로 놀기 때문에, 이 공유 캐시로 워커 간 결과를 맞춘다.
# Redis가 없는 배포에서는 코어가 자동으로 캐시 미스로 동작하므로 디스크 캐시만 쓰인다.
_SHARED_CACHE_KEY = "state_v1"
_SHARED_CACHE_TTL = 86400


def _cache_snapshot():
    return {
        "desc": {k: [ts, v] for k, (ts, v) in _DESC_CACHE.items()},
        "version": {k: [ts, v] for k, (ts, v) in _VERSION_CACHE.items()},
        "topic": {k: [ts, v] for k, (ts, v) in _TOPIC_CACHE.items()},
    }


def _merge_cache_snapshot(data):
    """스냅샷을 메모리 캐시에 병합한다. 같은 키면 타임스탬프가 더 최근인 쪽을 유지한다."""
    if not isinstance(data, dict):
        return
    for section, target in (("desc", _DESC_CACHE), ("version", _VERSION_CACHE), ("topic", _TOPIC_CACHE)):
        for k, pair in (data.get(section) or {}).items():
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            try:
                ts = float(pair[0])
            except (TypeError, ValueError):
                continue
            current = target.get(k)
            if current is None or current[0] < ts:
                target[k] = (ts, pair[1])


def _save_disk_cache():
    try:
        os.makedirs(_PLUGIN_DATA_DIR, exist_ok=True)
        # 워커마다 다른 임시 파일명을 써서 동시 저장 시 서로의 임시 파일을 덮지 않게 한다
        tmp_path = "%s.%d.tmp" % (_CACHE_FILE, os.getpid())
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_cache_snapshot(), f)
        os.replace(tmp_path, _CACHE_FILE)
    except Exception:
        pass


def _load_shared_cache(provider):
    try:
        raw = provider.cache_get(_SHARED_CACHE_KEY)
        if raw:
            _merge_cache_snapshot(json.loads(raw))
    except Exception:
        pass


def _save_shared_cache(provider):
    try:
        provider.cache_set(_SHARED_CACHE_KEY, json.dumps(_cache_snapshot()), ttl=_SHARED_CACHE_TTL)
    except Exception:
        pass


def _clear_shared_cache(provider):
    try:
        provider.cache_delete(_SHARED_CACHE_KEY)
    except Exception:
        pass


def _reset_disk_cache():
    """.cache.json 파일 자체를 삭제하고, 메모리에 있는 캐시(GitHub 설명·버전·
    Topics 검색 결과)도 모두 비운다. "목록 새로고침"(refresh_list)도 메모리
    캐시를 비우고 빈 상태를 다시 저장하긴 하지만, 캐시 파일 자체가 깨졌거나
    (예: JSON 파싱에 실패해 매 시작마다 조용히 무시되고 있지만 겉으로는
    알아채기 어려운 경우) 뭔가 목록이 꼬여 원인을 좁히기 어려울 때는, 파일을
    통째로 지우고 완전히 새로 시작하는 편이 더 확실하다."""
    _TOPIC_CACHE.clear()
    _VERSION_CACHE.clear()
    _DESC_CACHE.clear()
    try:
        for path in (_CACHE_FILE, _LEGACY_CACHE_FILE):
            if os.path.isfile(path):
                os.remove(path)
    except Exception as exc:
        return False, "캐시 파일 삭제에 실패했습니다: %s" % exc
    return True, "캐시 파일(cache.json)과 공유 캐시를 삭제하고 초기화했습니다. 목록을 새로 불러옵니다."


def _load_disk_cache():
    # 새 위치를 우선 읽고, 없으면 구버전 위치(.cache.json)에서 한 번 이관한다
    for path in (_CACHE_FILE, _LEGACY_CACHE_FILE):
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                _merge_cache_snapshot(json.load(f))
            return
        except Exception:
            continue  # 손상된 캐시 파일은 조용히 무시하고 콜드 스타트로 진행


_load_disk_cache()  # 모듈이 처음 임포트될 때(서버 시작 시) 1회 복원

# 설치 폴더명(파일시스템 경로)으로 허용하는 형식. 폴더 조작은 전부 이 규칙을 거친다.
_PLUGIN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
# 클래스 id로 허용하는 형식 — 가이드 §1의 `<네임스페이스>.<이름>`(예: leeyj.spotify_mood)
# 표기를 위해 점(.)을 추가로 허용한다. 폴더명과 달리 경로로 쓰이지 않으며, 설정 키
# (PLUGIN_ENABLED_{id}/PLUGIN_CONFIG_{id}) 조회에만 쓰인다.
_CLASS_ID_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9_.-]*[a-zA-Z0-9_-])?$")


def _is_valid_class_id(value):
    value = str(value or "").strip()
    return bool(_CLASS_ID_RE.match(value)) and ".." not in value
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


def _parse_version_json(text):
    """VERSION 파일 내용을 JSON으로 파싱한다. 표준 형식은 중괄호로 감싼 JSON
    객체(예: {"plugin version": "2.47.2"})지만, 중괄호 없이 키:값 한 줄만 적은
    형태(예: "plugin version": "0.1.3")도 관대하게 허용한다 — 실수로 감싸는
    중괄호를 빠뜨린 VERSION 파일이 실제로 종종 보이기 때문이다. 반환값은
    (파싱된 dict, 관대한_형식으로_구제했는지) 튜플이며, 어느 쪽으로도 파싱에
    실패하면 표준 형식 시도에서 난 예외를 그대로 올린다(호출부의 기존
    except 처리가 이전과 동일하게 동작하도록)."""
    try:
        return json.loads(text), False
    except (ValueError, TypeError) as exc:
        stripped = (text or "").strip().rstrip(",")
        if stripped.startswith("{") and stripped.endswith("}"):
            raise  # 이미 중괄호로 감싼 형태인데 실패한 거라면 다른 문법 오류이니 그대로 올린다
        try:
            data = json.loads("{" + stripped + "}")
        except Exception:
            raise exc  # 구제 시도도 실패하면 원래(표준 형식) 예외를 올린다
        return data, True


def _http_get_json(url, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url, token=None):
    req = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return resp.read().decode("utf-8")


_REPO_URL_RE = re.compile(r"^https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?/?$")

# 스킴 뒤 슬래시가 실수로 3개 이상 붙은 경우("https:///user:pass@host/...")를
# 표준 형태("https://")로 바로잡는다. 이런 오타가 있으면 urlsplit이 netloc을
# 아예 빈 문자열로 처리해버려 host/owner/repo뿐 아니라 자격증명(username/
# password)까지 통째로 인식하지 못하게 된다 — 특히 Gitea처럼 자격증명이 꼭
# 필요한 경우 등록 자체가 조용히 실패하므로, 흔히 나올 수 있는 이 오타 하나는
# 입력 단계에서 바로잡아준다. 스킴 직후의 슬래시 뭉치만 정규화하고 그 뒤의
# 경로·자격증명 문자열은 전혀 건드리지 않는다.
_SCHEME_SLASHES_RE = re.compile(r"^(https?):/{2,}", re.IGNORECASE)


def _normalize_repo_url(url):
    """스킴 뒤 슬래시 개수만 'https://' 형태로 정규화한다(그 외 문자열은 그대로)."""
    s = (url or "").strip()
    return _SCHEME_SLASHES_RE.sub(lambda m: m.group(1).lower() + "://", s)


def _extract_url_credentials(url):
    """URL에 https://user:pass@host/... 형식으로 자격증명이 직접 포함돼 있으면
    분리해 (자격증명이 제거된_URL, username, password)로 반환한다. 없으면
    (정규화된 url, None, None). 저장소 카드 링크·github.txt 레지스트리에는 항상
    이 함수로 정제한 URL만 남겨서 비밀번호가 그대로 노출되지 않도록 한다."""
    normalized = _normalize_repo_url(url)
    try:
        parsed = urllib.parse.urlsplit(normalized)
        if not parsed.username and not parsed.password:
            return normalized, None, None
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += ":%d" % parsed.port
        clean = urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        username = urllib.parse.unquote(parsed.username) if parsed.username else None
        password = urllib.parse.unquote(parsed.password) if parsed.password else None
        return clean, username, password
    except Exception:
        return normalized, None, None


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
    m = re.match(r"^(https?)://", _normalize_repo_url(url), re.IGNORECASE)
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
def _normalize_gitea_server(raw_host, scheme=None):
    """'https://git.example.com:3000/경로' 같은 입력에서 (스킴, 호스트[:포트])를 뽑는다.
    호스트는 소문자로 정규화한다. 스킴이 없으면 인자 scheme, 그것도 없으면 https."""
    text = str(raw_host or "").strip()
    m = re.match(r"^([a-z][a-z0-9+.-]*)://", text, re.IGNORECASE)
    if m:
        scheme = scheme or m.group(1).lower()
        text = text[m.end():]
    text = text.split("/")[0].split("@")[-1].strip().lower()
    scheme = (scheme or "https").lower()
    if scheme not in ("http", "https"):
        scheme = "https"
    return scheme, text


def _parse_gitea_tokens_cfg(raw):
    """GITEA_TOKENS 설정값을 {호스트(소문자, 포트 포함): {scheme, username, password,
    token}} 딕셔너리로 파싱한다.

    [PATCH-6] 새 형식은 JSON 목록이다:
        [{"host": "gitea.example.com", "scheme": "https", "username": "...",
          "password": "...", "token": "..."}]
    아이디/비밀번호와 읽기 토큰을 한 서버에 함께 저장할 수 있고, 주소만 있는 항목도
    허용한다(http 전용 서버를 토픽 검색 대상에 넣고 싶을 때 등).

    구버전 콤마 문자열 형식("호스트:토큰", "호스트:아이디:비밀번호")도 계속 읽는다.
    이때 호스트 바로 뒤 조각이 숫자면 포트로 해석한다("git.example.com:3000:토큰").
    형식이 맞지 않는 항목은 조용히 건너뛴다(설정 파싱 실패로 전체 기능이 죽으면 안 됨)."""
    result = {}
    if not raw:
        return result

    items = None
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        text = str(raw).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                items = parsed if isinstance(parsed, list) else []
            except ValueError:
                items = []

    if items is not None:
        for item in items:
            if not isinstance(item, dict):
                continue
            scheme, host = _normalize_gitea_server(item.get("host"), item.get("scheme"))
            if not host:
                continue
            entry = {"scheme": scheme}
            for key in ("username", "password", "token"):
                val = str(item.get(key) or "").strip()
                if val:
                    entry[key] = val
            owners = item.get("owners")
            if isinstance(owners, str):
                owners = owners.split(",")
            owners = [str(o).strip().strip("/") for o in (owners or []) if str(o).strip().strip("/")]
            if owners:
                entry["owners"] = list(dict.fromkeys(owners))
            result[host] = entry
        return result

    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        scheme, rest_text = "https", chunk
        m = re.match(r"^(https?)://", chunk, re.IGNORECASE)
        if m:
            scheme, rest_text = m.group(1).lower(), chunk[m.end():]
        parts = rest_text.split(":")
        host = parts[0].strip().lower()
        rest = [x.strip() for x in parts[1:]]
        if rest and rest[0].isdigit():
            host = "%s:%s" % (host, rest.pop(0))
        if not host:
            continue
        if len(rest) == 1 and rest[0]:
            result[host] = {"scheme": scheme, "token": rest[0]}
        elif len(rest) == 2 and rest[0] and rest[1]:
            result[host] = {"scheme": scheme, "username": rest[0], "password": rest[1]}
        # 그 외(비밀번호에 콜론이 들어간 경우 등)는 형식이 불분명해 건너뛴다 —
        # 이런 값은 새 JSON 형식(설정 화면에서 저장)으로 다시 등록하면 된다.
    return result


def _effective_gitea_cfg(url, configured_tokens=None):
    """이 URL로 Gitea에 접근할 때 쓸 인증 정보를 정한다.

    - URL에 아이디:비밀번호가 있고, 그 아이디가 설정(Gitea 서버)에 저장된 이 호스트의
      아이디와 같으면 [PATCH-6] "자동 삽입된 자격증명"으로 보고 **설정값을 기준으로**
      인증한다(읽기 토큰이 있으면 토큰 우선, 없으면 설정의 최신 비밀번호). 그래서 설정에서
      비밀번호를 바꿔도 레지스트리에 박힌 옛 비밀번호 때문에 실패하지 않는다.
    - 그 외에 URL에 자격증명이 있으면 그것을 최우선으로 쓴다(사용자가 직접 넣은 값).
    - URL에 자격증명이 없으면 설정에 저장된 이 호스트의 항목으로 폴백한다.

    "source" 필드는 실제로 어느 자격증명이 적용됐는지를 나타낸다 — 인증 실패 시
    오류 메시지에서 원인을 바로 짚어주기 위함이다."""
    _, username, password = _extract_url_credentials(url)
    host = (_parse_repo_url(url)[0] or "").lower()
    entry = (configured_tokens or {}).get(host) if host else None

    if username and password:
        if entry and entry.get("username") == username:
            cfg = _gitea_cfg_from_tokens_entry(entry)
            cfg["source"] = "config_auto"
            return cfg
        return {"token": None, "username": username, "password": password, "source": "url_basic"}
    if username:  # https://TOKEN@host/owner/repo 형태(토큰만 있는 경우)
        if entry and entry.get("token") == username:
            cfg = _gitea_cfg_from_tokens_entry(entry)
            cfg["source"] = "config_auto"
            return cfg
        return {"token": username, "username": None, "password": None, "source": "url_token"}
    if entry:
        return _gitea_cfg_from_tokens_entry(entry)
    return {"token": None, "username": None, "password": None, "source": "none"}


def _inject_gitea_credentials(url, configured_tokens):
    """[PATCH-6] 자격증명 없는 Gitea 주소에, 설정에 저장된 이 호스트의 계정을 넣은
    주소를 만든다. 아이디/비밀번호가 있으면 https://아이디:비밀번호@호스트/...,
    읽기 토큰만 있으면 https://토큰@호스트/... 형태. GitHub 주소, 이미 자격증명이 있는
    주소, 설정에 없는 호스트는 그대로 돌려준다.
    반환: (주소, 자동 삽입 여부)"""
    clean_url, username, password = _extract_url_credentials(url)
    if username or password:
        return url, False
    host, _owner, _repo = _parse_repo_url(clean_url)
    if not host or _is_github_host(host):
        return url, False
    entry = (configured_tokens or {}).get(host.lower())
    if not entry:
        return url, False
    if entry.get("username") and entry.get("password"):
        userinfo = "%s:%s" % (urllib.parse.quote(entry["username"], safe=""),
                              urllib.parse.quote(entry["password"], safe=""))
    elif entry.get("token"):
        userinfo = urllib.parse.quote(entry["token"], safe="")
    else:
        return url, False
    parts = urllib.parse.urlsplit(clean_url)
    injected = urllib.parse.urlunsplit(
        (parts.scheme, "%s@%s" % (userinfo, parts.netloc), parts.path, parts.query, parts.fragment)
    )
    return injected, True


def _sync_registry_credentials(configured_tokens):
    """[PATCH-6] 설정(Gitea 서버)에 계정이 저장된 호스트의 레지스트리 주소를 최신
    자격증명으로 맞춘다. 자격증명 없이 등록돼 있던 주소에는 계정을 넣고, 같은 아이디로
    자동 등록된 주소는 비밀번호가 바뀌었으면 갱신한다. 사용자가 다른 아이디로 직접 넣은
    주소는 건드리지 않는다. 바뀐 항목이 있을 때만 파일을 다시 쓴다."""
    if not configured_tokens:
        return 0
    entries = _load_github_registry_entries()
    changed = 0
    new_entries = []
    for pid, url in entries:
        new_url = url
        clean_url, username, password = _extract_url_credentials(url)
        host = (_parse_repo_url(clean_url)[0] or "").lower()
        entry = configured_tokens.get(host) if host and not _is_github_host(host) else None
        if entry:
            if not username and not password:
                new_url, _ = _inject_gitea_credentials(clean_url, configured_tokens)
            elif (username and password and entry.get("username") == username
                  and entry.get("password") and entry.get("password") != password):
                new_url, _ = _inject_gitea_credentials(clean_url, configured_tokens)
        if new_url != url:
            changed += 1
        new_entries.append((pid, new_url))
    if changed:
        _save_github_registry_entries(new_entries)
    return changed


_GITEA_AUTH_SOURCE_LABEL = {
    "config_auto": "설정(Gitea 서버)에 저장된 계정(주소에 자동 포함됨)",
    "url_basic": "등록된 주소에 포함된 아이디:비밀번호",
    "url_token": "등록된 주소에 포함된 토큰",
    "config_token": "설정(GITEA_TOKENS)에 등록한 토큰",
    "config_basic": "설정(GITEA_TOKENS)에 등록한 아이디/비밀번호",
    "none": "인증 정보 없음(공개 저장소로 간주하고 시도)",
}


def _gitea_auth_error_hint(gitea_cfg):
    """401/403 오류 메시지에 덧붙일 안내문. 어떤 자격증명이 실제로 시도됐는지
    밝혀서, "GITEA_TOKENS를 등록했는데도 안 된다"는 흔한 혼란(사실은 URL에
    박힌 옛 자격증명이 우선 적용돼 GITEA_TOKENS가 아예 시도되지 않은 경우가
    많음)을 바로 알아챌 수 있게 한다."""
    source = (gitea_cfg or {}).get("source", "none")
    label = _GITEA_AUTH_SOURCE_LABEL.get(source, "알 수 없는 인증 정보")
    if source in ("url_basic", "url_token"):
        return (
            "(%s(으)로 인증을 시도했지만 실패했습니다. 이 주소가 우선 적용되므로 "
            "설정에 GITEA_TOKENS를 등록해뒀어도 그쪽은 시도되지 않습니다 — 비밀번호/토큰이 "
            "바뀌었거나 서버가 더 이상 이 인증 방식을 지원하지 않을 수 있습니다(Gitea 1.23+는 "
            "Basic Auth 지원이 폐지됨). 카드의 '✏️ Git 주소 변경'으로 자격증명 없이 순수 "
            "주소만 다시 등록하면, 이후 GITEA_TOKENS에 등록한 항목이 대신 적용됩니다.)" % label
        )
    if source in ("config_token", "config_basic", "config_auto"):
        return (
            "(%s(으)로 인증을 시도했지만 실패했습니다. 정보가 만료됐거나 저장소에 대한 "
            "읽기 권한이 없을 수 있습니다 — 설정의 Gitea 서버 '연결 테스트'로 확인해주세요.)" % label
        )
    return "(이 저장소는 인증 없이는 접근할 수 없습니다 — 설정의 'Gitea 서버'에 이 서버의 아이디/비밀번호 또는 읽기 토큰을 등록하면 자동으로 적용됩니다.)"


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


def _gitea_search_paged(host, path, gitea_cfg, scheme="https", max_pages=None):
    """[PATCH-9] Gitea 저장소 검색(/api/v1/repos/search)을 끝까지 페이지 조회한다.
    Gitea는 limit을 크게 줘도 서버 설정(MAX_RESPONSE_ITEMS, 기본 50)만큼만 돌려주므로,
    응답 헤더 X-Total-Count(전체 개수)를 기준으로 다 모을 때까지 page를 넘긴다.
    헤더가 없는 구버전 서버는 빈 페이지가 나올 때까지 넘긴다."""
    max_pages = max_pages or _GITEA_SEARCH_MAX_PAGES
    sep = "&" if "?" in path else "?"
    items = []
    total = None
    for page in range(1, max_pages + 1):
        req = urllib.request.Request(
            "%s://%s%s%slimit=50&page=%d" % (scheme, host, path, sep, page), headers=_gitea_headers(gitea_cfg)
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            if total is None:
                try:
                    total = int(resp.headers.get("X-Total-Count") or "")
                except ValueError:
                    total = None
            data = json.loads(resp.read().decode("utf-8"))
        batch = (data or {}).get("data") or []
        items.extend(batch)
        if not batch or (total is not None and len(items) >= total):
            break
    return items


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
            "tags": data.get("topics") or [],
            "url": data.get("html_url") or fallback_url,
            "default_branch": data.get("default_branch"),
            "stars": data.get("stars_count"),
            "pushed_at": data.get("updated_at"),  # Gitea 저장소 API의 마지막 갱신 시각(ISO 8601)
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        hint = " " + _gitea_auth_error_hint(gitea_cfg) if exc.code in (401, 403) else ""
        info = {
            "desc": "Gitea API 호출 오류 (HTTP %s)%s" % (exc.code, hint),
            "tags": [], "url": fallback_url, "default_branch": None, "stars": None, "pushed_at": None, "error": True,
        }
    except Exception as exc:
        info = {
            "desc": "Gitea 저장소 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [], "url": fallback_url, "default_branch": None, "stars": None, "pushed_at": None, "error": True,
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
            data, _lenient = _parse_version_json(text)
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
    대상에 남도록 한다.

    파일 형식: 한 줄에 "plugin_id<TAB>url". plugin_id(=설치 폴더 이름)를 1차
    키로 삼아, 저장소가 다른 owner/호스트로 옮겨가거나 이름이 바뀌어도 같은
    plugin_id 항목의 url만 갱신하면 계속 추적할 수 있도록 한다(구버전에서
    쓰던 "url만 한 줄에 하나" 형식도 하위 호환으로 계속 읽을 수 있다 — 이
    경우 plugin_id는 그 url을 파싱해 얻은 저장소 이름으로 간주한다)."""
    return os.path.join(_plugins_root_dir(), "data", "plugin_board", "github.txt")


def _load_github_registry_entries():
    """github.txt를 (plugin_id, url) 튜플 목록으로 읽는다. 새 형식
    "plugin_id<TAB>url"과, 하위 호환을 위한 구 형식(URL 한 줄)을 함께
    처리한다 — 구 형식 줄은 URL을 파싱해 얻은 저장소 이름을 plugin_id로
    간주한다(파싱조차 안 되면 그 줄은 건너뛴다). 파일이 없거나 읽기에
    실패하면 빈 목록을 반환한다(레지스트리는 성능/편의용 부가 기능이라
    실패해도 플러그인 동작 자체를 막지 않는다)."""
    path = _github_registry_path()
    if not os.path.isfile(path):
        return []
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]
    except Exception:
        return []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            plugin_id, url = line.split("\t", 1)
            plugin_id = plugin_id.strip()
            url = url.strip()
        else:
            url = line
            _, _, plugin_id = _parse_repo_url(url)
        if plugin_id and url:
            entries.append((plugin_id, url))
    return entries


def _save_github_registry_entries(entries):
    """(plugin_id, url) 목록을 github.txt에 "plugin_id<TAB>url" 형식으로
    저장한다. 기록 실패는 예외를 조용히 무시한다(부가 기능일 뿐 설치/삭제
    자체를 막을 이유가 아니다)."""
    try:
        path = _github_registry_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = ["%s\t%s" % (pid, url) for pid, url in entries]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        try:
            # URL에 자격증명이 담길 수 있으므로 소유자만 읽을 수 있게 제한한다
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def _load_github_registry():
    """하위 호환용 — URL 목록만 필요한 호출부를 위해 (plugin_id, url) 중
    url만 뽑아서 반환한다."""
    return [url for _pid, url in _load_github_registry_entries()]


def _remember_repo_install(url, plugin_id=None):
    """설치/업데이트에 성공한 저장소 주소(GitHub든 Gitea든)를 github.txt에
    기록한다. URL에 자격증명(https://아이디:비밀번호@host/...)이 담겨 있으면
    그대로(정제하지 않고) 저장한다 — 이후 대시보드에서 업데이트를 확인할 때도
    같은 자격증명으로 계속 인증하기 위함이다(도메인/계정마다 별도 설정을 두지
    않고, URL 저장 자체가 곧 인증 정보 저장이 되는 방식).

    plugin_id(=설치 폴더 이름)를 1차 키로 삼아 기록한다 — 지정하지 않으면
    url을 파싱해 얻은 저장소 이름을 그대로 쓴다(설치 직후 호출하는 기존
    호출부와 동일하게 동작). 이미 같은 plugin_id가 등록돼 있으면 최신 URL로
    교체한다 — 처음엔 자격증명 없이 설치했다가 나중에 자격증명이 담긴 URL로
    다시 설치하면, 그 최신 URL로 갱신되어야 계속 인증이 유지된다. 기록 실패는
    설치 자체를 막을 이유가 아니므로 예외를 조용히 무시한다."""
    try:
        if plugin_id is None:
            _, _, plugin_id = _parse_repo_url(url)
        if not plugin_id:
            return
        entries = _load_github_registry_entries()
        new_entries = []
        replaced = False
        for pid, existing_url in entries:
            if pid == plugin_id:
                new_entries.append((plugin_id, url))
                replaced = True
            else:
                new_entries.append((pid, existing_url))
        if not replaced:
            new_entries.append((plugin_id, url))
        _save_github_registry_entries(new_entries)
    except Exception:
        pass


def _update_registered_repo_url(plugin_id, new_url):
    """이미 추적 중인 plugin_id의 등록 Git 주소를 새 URL로 바꾼다. 저장소가
    다른 owner나 호스트로 옮겨갔거나(이름은 그대로) 아예 새 주소로 다시
    올라온 경우, 재설치 없이 "이 plugin_id는 이제 이 URL을 본다"고만
    갱신하고 싶을 때 쓴다. 새 URL이 유효한 저장소 주소 형식인지만 확인하고
    실제로 그 주소에 접근 가능한지는 확인하지 않는다(다음 '업데이트' 클릭
    시 자연히 확인된다). 아직 레지스트리에 없던 plugin_id라면 새로 추가한다."""
    try:
        _validate_plugin_id(plugin_id)
    except ValueError as exc:
        return False, str(exc)

    host, owner, repo = _parse_repo_url(new_url)
    if not host or not owner or not repo:
        return False, "Git 저장소 주소를 해석하지 못했습니다: %s" % _scrub_credentials(new_url)

    # 주소가 바뀌면(자격증명만 바뀐 경우 포함) 예전 주소로 실패했던 결과가
    # 캐시에 최대 24시간 남아있을 수 있다 — 예를 들어 URL에 박힌 옛 자격증명
    # 때문에 401이 났던 걸 캐시가 기억한 채로, 자격증명을 뺀 새 주소로 바꿔도
    # 같은 host/owner/repo라는 이유로 그 실패가 그대로 재사용된다. 바뀐 주소로
    # 즉시 다시 확인되도록 관련 캐시를 지운다.
    cache_key = ("%s/%s" % (owner, repo)) if _is_github_host(host) else ("gitea:%s/%s/%s" % (host, owner, repo))
    _DESC_CACHE.pop(cache_key, None)
    _VERSION_CACHE.pop(cache_key, None)

    _remember_repo_install(new_url, plugin_id=plugin_id)
    return True, "'%s'의 등록된 Git 주소를 갱신했습니다. '업데이트' 버튼으로 새 주소에서 최신 상태를 확인해보세요." % plugin_id


def _unregister_repo(plugin_id):
    """github.txt에서 plugin_id 항목만 제거한다. 설치된 플러그인 파일
    (plugins/metadata/{plugin_id})은 전혀 건드리지 않는다 — 원본 저장소가
    삭제/이전되어 더 이상 업데이트를 추적할 수 없을 때, 지금 설치된 버전은
    그대로 남겨두고 "더 이상 이 주소로 업데이트를 확인하지 않는다"는 것만
    표시하고 싶은 경우에 쓴다."""
    try:
        _validate_plugin_id(plugin_id)
    except ValueError as exc:
        return False, str(exc)

    entries = _load_github_registry_entries()
    remaining = [(pid, url) for pid, url in entries if pid != plugin_id]
    if len(remaining) == len(entries):
        return False, "등록된 Git 주소 목록에 '%s'가 없습니다." % plugin_id

    _save_github_registry_entries(remaining)
    return True, (
        "'%s'의 등록된 Git 주소를 목록에서 제거했습니다. 설치된 플러그인 파일은 "
        "그대로 유지됩니다(더 이상 이 주소로 업데이트를 확인하지 않습니다)." % plugin_id
    )


def _is_installed(plugin_id):
    return os.path.isdir(os.path.join(_plugins_metadata_dir(), plugin_id))


def _has_settings_ui(plugin_id):
    """settings.html이 있으면 config_schema가 비어 있어도 커스텀 설정 화면을
    제공하는 것이므로, 환경설정(⚙) 버튼 노출 여부 판단에 함께 사용한다."""
    return os.path.isfile(
        os.path.join(_plugins_metadata_dir(), plugin_id, "settings.html")
    )


def _local_version(plugin_id):
    return _version_in_dir(os.path.join(_plugins_metadata_dir(), plugin_id))


def _version_in_dir(plugin_dir):
    version_file = os.path.join(plugin_dir, "VERSION")
    if not os.path.isfile(version_file):
        return None
    try:
        with open(version_file, "r", encoding="utf-8") as f:
            data, _lenient = _parse_version_json(f.read())
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


def _find_provider_module(plugin_dir):
    """폴더명과 같은 이름의 모듈 파일이 없을 때(예: 폴더 spotify-mood, 파일
    leeyj_spotify_mood.py) BaseMetadataProvider를 상속한 클래스가 있는 .py를 찾는다."""
    try:
        fnames = sorted(os.listdir(plugin_dir))
    except Exception:
        return None
    for fname in fnames:
        if not fname.endswith(".py") or fname in ("__init__.py", "base.py"):
            continue
        fpath = os.path.join(plugin_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                src = f.read()
        except Exception:
            continue
        if "BaseMetadataProvider" in src and re.search(r"^class\s", src, re.M):
            return fpath
    return None


def _read_local_class_attrs(plugin_id):
    """설치된 플러그인의 메인 .py에서 name/id/is_searchable/category_tab 등
    주요 클래스 속성을 AST로만(코드 실행 없이) 읽어온다. GitHub Topics
    검색으로 아직 발견되지 않았거나 검색 결과가 부실한 플러그인의 표시
    이름·분류를 최대한 정확히 추정하는 데 사용한다.

    [PATCH-4] 가이드 1.0.8~1.1.1의 선언형 계약(home_widget, detail_sidebar_widget,
    smart_recommend_widget, detail_view, admin_only)도 함께 읽는다. 위젯 여부는
    이제 이 선언들로만 판단한다 — get_dashboard_data()는 plugin_board처럼 데이터
    엔드포인트로만 쓰는 플러그인도 구현하므로 위젯 여부의 신호가 아니다.
    파일 mtime 기준으로 결과를 캐시해 카드마다 반복 파싱하지 않는다.
    인자는 설치 폴더명이다."""
    plugin_dir = os.path.join(_plugins_metadata_dir(), plugin_id)
    path = _find_module_file(plugin_dir, plugin_id) or _find_provider_module(plugin_dir)
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _LOCAL_ATTRS_CACHE.get(path)
    if cached and cached[0] == mtime:
        return dict(cached[1])
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except Exception:
        return {}

    wanted = {
        "name", "id", "is_searchable", "category_tab", "dashboard_widget", "config_schema",
        "home_widget", "detail_sidebar_widget", "smart_recommend_widget", "detail_view",
        "admin_only",
    }
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
    _LOCAL_ATTRS_CACHE[path] = (mtime, dict(attrs))
    return attrs


_LOCAL_ATTRS_CACHE = {}  # {module_path: (mtime, attrs)}


def _classify_attrs(attrs):
    """클래스 속성(AST로 읽은 값)으로 카드 분류를 정한다. 여러 계약을 동시에
    선언한 플러그인은 아래 우선순위의 첫 항목으로 분류한다."""
    if attrs.get("is_searchable"):
        return "search"
    if attrs.get("category_tab"):
        return "tab"
    if attrs.get("home_widget"):
        return "home"
    if attrs.get("dashboard_widget"):
        return "desk"
    if any(attrs.get(k) for k in ("detail_view", "detail_sidebar_widget", "smart_recommend_widget")):
        return "detail"
    return "other"


def _describe_local(folder, default_type="other"):
    """설치된 폴더에서 카드 표시용 정보를 한 번에 뽑는다. 예전에는 같은 분류 코드가
    카드 빌더 5곳에 복사돼 있었다."""
    attrs = _read_local_class_attrs(folder)
    plugin_type = _classify_attrs(attrs)
    if plugin_type == "other":
        plugin_type = default_type
    return {
        "type": plugin_type,
        "tab_order": _extract_tab_order(attrs.get("category_tab")),
        "has_config": bool(attrs.get("config_schema")) or _has_settings_ui(folder),
        "title": attrs.get("name") or folder,
        "class_id": _class_id_for_folder(folder),
        "admin_only": bool(attrs.get("admin_only")),
    }


def _class_id_for_folder(folder):
    """설치 폴더의 클래스 id를 반환한다(못 읽으면 폴더명). 코어는 활성화/설정 키를
    클래스 id로 만들기 때문에, 폴더명과 다를 수 있는 경우를 여기서 흡수한다."""
    try:
        cid = _read_local_class_attrs(folder).get("id")
    except Exception:
        cid = None
    if isinstance(cid, str) and _is_valid_class_id(cid):
        return cid.strip()
    return folder


def _name_variants(name):
    name = str(name or "").strip()
    out = []
    for v in (name, name.replace("-", "_"), name.replace("_", "-")):
        if v and v not in out:
            out.append(v)
    return out


def _resolve_installed_folder(name):
    """저장소 이름(또는 클래스 id)으로 실제 설치 폴더를 찾는다. 저장소는 하이픈,
    폴더/클래스 id는 언더스코어인 경우가 흔해 두 표기를 함께 시도하고, 그래도
    없으면 클래스 id가 일치하는 폴더를 찾는다. 없으면 None."""
    for v in _name_variants(name):
        if _PLUGIN_ID_RE.match(v) and _is_installed(v):
            return v
    if _is_valid_class_id(name):
        return _find_folder_by_class_id(name)
    return None


def _find_folder_by_class_id(class_id, exclude=None):
    """plugins/metadata 아래에서 클래스 id가 class_id인 폴더를 찾는다(exclude 폴더 제외)."""
    base_dir = _plugins_metadata_dir()
    try:
        entries = sorted(os.listdir(base_dir))
    except Exception:
        return None
    for entry in entries:
        if entry == exclude or entry.startswith((".", "__")):
            continue
        if not _PLUGIN_ID_RE.match(entry) or not os.path.isdir(os.path.join(base_dir, entry)):
            continue
        cid = _read_local_class_attrs(entry).get("id")
        if isinstance(cid, str) and cid.strip() == class_id:
            return entry
    return None


def _extract_tab_order(category_tab):
    """category_tab 선언에서 order 값만 안전하게 뽑아낸다. category_tab이
    없거나(검색형 메타데이터 등) order를 안 적었거나, order 값이 정수/실수가
    아니면 None을 반환한다 — 카드에는 순서를 아예 표시하지 않는다."""
    if not isinstance(category_tab, dict):
        return None
    order = category_tab.get("order")
    if isinstance(order, bool) or not isinstance(order, (int, float)):
        return None
    return int(order)


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
        local = _describe_local(entry)

        # 원격 저장소 정보가 없는(로컬 전용) 플러그인이라 GitHub/Gitea의 마지막
        # 푸시 시각을 알 수 없다. 대신 설치 폴더의 마지막 수정 시각을 "최종
        # 업데이트"의 근사치로 사용한다(파일 교체 방식 설치·업데이트 특성상,
        # 폴더가 통째로 새로 채워질 때마다 이 시각도 함께 갱신된다).
        try:
            local_pushed_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(full_path))
            )
        except Exception:
            local_pushed_at = None

        items.append({
            "id": entry,
            "class_id": local["class_id"],
            "owner": "",
            "title": local["title"],
            "type": local["type"],
            "type_label": TYPE_LABELS.get(local["type"], TYPE_LABELS["other"]),
            "desc": "",
            "tags": [],
            "features": [],
            "version_label": ("v" + version) if version else "—",
            "url": None,
            "error": False,
            "installed": True,
            "installed_version": version,
            "has_update": False,
            "has_config": local["has_config"],
            "enabled": is_enabled_fn(entry),
            "admin_only": local["admin_only"],
            "local_only": True,
            "tab_order": local["tab_order"],
            "pushed_at": local_pushed_at,
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
            data, _lenient = _parse_version_json(_http_get_text(raw_url, token))
            version = data.get("plugin version")
            if version:
                return str(version)
        except Exception:
            continue
    return None


def _fetch_description_info(owner, repo, token):
    """GitHub 저장소 API(설명·토픽·default_branch)만 조회해 24시간 캐시한다.
    이 정보는 저장소 관리자가 바꾸지 않는 한 거의 변하지 않으므로 길게 캐시해
    api.github.com 호출 자체를 줄인다.

    저장소가 다른 이름/owner로 이름이 바뀐(rename) 경우, GitHub는 예전
    owner/repo로 조회해도 새 이름의 정보를 그대로 돌려준다(내부적으로
    리다이렉트). 응답의 full_name이 우리가 조회한 owner/repo와 다르면 그
    새 이름을 canonical_owner/canonical_repo로 함께 반환한다 — 호출부가
    "이 주소는 사실 다른 카드와 같은 저장소를 가리킨다"는 걸 알아채고 중복
    표시·낡은 등록 주소를 정리하는 데 쓴다."""
    key = owner + "/" + repo
    cached = _DESC_CACHE.get(key)
    # canonical_owner/repo 필드는 이후에 추가된 것이라, 그 이전에 저장된
    # 캐시(메모리든 .cache.json 디스크 캐시든)는 이 키 자체가 없다. 필드가
    # 없는 옛 캐시를 그대로 신뢰하면 이름이 바뀐 저장소를 영영 감지하지
    # 못하므로(24시간 TTL이 남아있는 동안, 심지어 서버 재시작 후에도), 이
    # 필드가 있는 캐시만 유효한 것으로 인정하고 없으면 다시 조회한다.
    if cached and (time.time() - cached[0]) < _DESC_CACHE_TTL_SECONDS and "canonical_owner" in cached[1]:
        return cached[1]

    try:
        api_data = _http_get_json(
            "https://api.github.com/repos/%s/%s" % (owner, repo), token
        )
        full_name = api_data.get("full_name") or ""
        canonical_owner, _, canonical_repo = full_name.partition("/")
        if not canonical_owner or not canonical_repo or (
            canonical_owner.lower() == owner.lower() and canonical_repo.lower() == repo.lower()
        ):
            canonical_owner, canonical_repo = None, None  # 이름이 바뀌지 않은 경우
        info = {
            "desc": api_data.get("description") or "(GitHub에 등록된 설명이 없습니다)",
            "tags": api_data.get("topics") or [],
            "url": api_data.get("html_url") or ("https://github.com/%s/%s" % (owner, repo)),
            "default_branch": api_data.get("default_branch"),
            "stars": api_data.get("stargazers_count"),
            "pushed_at": api_data.get("pushed_at"),  # 마지막 코드 푸시 시각(ISO 8601) — 별점/이슈 활동과 무관하게 실제 코드가 마지막으로 바뀐 시점
            "canonical_owner": canonical_owner,
            "canonical_repo": canonical_repo,
            "error": False,
        }
    except urllib.error.HTTPError as exc:
        info = {
            "desc": _github_api_error_message(exc, bool(token)),
            "tags": [],
            "url": "https://github.com/%s/%s" % (owner, repo),
            "default_branch": None,
            "stars": None,
            "pushed_at": None,
            "canonical_owner": None,
            "canonical_repo": None,
            "error": True,
        }
    except Exception as exc:
        info = {
            "desc": "GitHub 정보를 불러오지 못했습니다 (%s)" % exc,
            "tags": [],
            "url": "https://github.com/%s/%s" % (owner, repo),
            "default_branch": None,
            "stars": None,
            "pushed_at": None,
            "canonical_owner": None,
            "canonical_repo": None,
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
        "pushed_at": desc_info.get("pushed_at"),
        "canonical_owner": desc_info.get("canonical_owner"),
        "canonical_repo": desc_info.get("canonical_repo"),
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
    달린 공개 저장소를 찾는다. 토픽이 여러 개(기본 발견 토픽 + 추가 발견
    토픽 + 카탈로그 토픽)면 동시에 병렬로 조회한다 — 예전에는 토픽마다
    순차로 호출해서 토픽 개수만큼 지연이 그대로 누적됐다(캐시가 만료되는
    1시간마다의 첫 로딩이 토픽을 늘릴수록 계속 느려지는 원인이었다). 토픽
    하나가 실패해도 나머지는 계속 반영하며, 전체 결과는 1시간 캐시한다
    (Search API는 분당 요청 제한이 따로 있어 아껴 써야 한다)."""
    topics = [t.strip() for t in topics if t and t.strip()]
    if not topics:
        return []

    cache_key = _topic_cache_key(topics)
    now = time.time()
    cached = _TOPIC_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _TOPIC_CACHE_TTL_SECONDS:
        return cached[1]

    def _fetch_one(topic):
        query = urllib.parse.quote("topic:%s" % topic, safe="")
        items = []
        for page in range(1, _GITHUB_SEARCH_PAGES + 1):
            url = "https://api.github.com/search/repositories?q=%s&per_page=100&page=%d" % (query, page)
            data = _http_get_json(url, token)
            batch = data.get("items", []) or []
            items.extend(batch)
            if len(batch) < 100 or len(items) >= int(data.get("total_count") or 0):
                break
        return items

    per_topic = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(topics))) as executor:
        future_map = {executor.submit(_fetch_one, topic): topic for topic in topics}
        for future in concurrent.futures.as_completed(future_map):
            try:
                per_topic[future_map[future]] = future.result()
            except Exception:
                continue  # 토픽 하나가 실패해도 나머지 토픽 검색 결과는 계속 반영한다

    # [PATCH-8] 병렬 도착 순서가 아니라 호출부가 준 토픽 순서대로 합친다 — 결과 순서가
    # 요청마다 흔들리지 않고, 설정한 토픽(카탈로그/추가 발견)이 앞에 온다.
    seen = {}
    for topic in topics:
        for repo_json in per_topic.get(topic) or []:
            full_name = repo_json.get("full_name")
            if full_name and full_name not in seen:
                seen[full_name] = repo_json

    results = list(seen.values())
    _TOPIC_CACHE[cache_key] = (now, results)
    return results


def _gitea_cfg_from_tokens_entry(entry):
    """설정(Gitea 서버) 항목을 _gitea_headers()가 바로 쓸 수 있는 gitea_cfg로 바꾼다.
    토큰과 아이디/비밀번호가 함께 있으면 둘 다 담아두고, 헤더는 토큰을 우선 쓴다."""
    if not entry:
        return {"token": None, "username": None, "password": None, "source": "none"}
    token = entry.get("token") or None
    username = entry.get("username") or None
    password = entry.get("password") or None
    if token:
        source = "config_token"
    elif username and password:
        source = "config_basic"
    else:
        source = "none"
    return {"token": token, "username": username, "password": password, "source": source}


def _gitea_auth_fingerprint(gitea_cfg):
    """캐시 키용 인증 식별자 — 인증 정보가 바뀌면(토큰 추가 등) 이전 검색 결과를
    재사용하지 않도록 한다. 비밀값 자체는 키에 넣지 않고 해시만 쓴다."""
    cfg = gitea_cfg or {}
    raw = "%s|%s|%s" % (cfg.get("token") or "", cfg.get("username") or "", cfg.get("password") or "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10] if raw != "||" else "anon"


def _fetch_gitea_repos_by_topic(host, gitea_cfg, scheme, topics):
    """Gitea 저장소 검색 API(`GET /repos/search?q=<토픽>&topic=true`)로 지정된
    토픽이 달린 저장소를 찾는다. GitHub Topics와 달리 전역 검색 대상이 없어
    "어느 서버를 검색할지"부터 알아야 하므로, GITEA_TOKENS에 등록해둔 서버만
    대상으로 한다(신뢰 여부를 이미 표시한 서버이기도 하다). 토픽별 병렬 조회·
    1시간 캐시는 GitHub 쪽과 동일하다. 캐시 키에 호스트를 포함해 서버별로
    독립적으로 캐시된다."""
    topics = [t.strip() for t in topics if t and t.strip()]
    if not topics:
        return []

    cache_key = "gitea:%s://%s:%s:%s" % (scheme, host, _gitea_auth_fingerprint(gitea_cfg), _topic_cache_key(topics))
    now = time.time()
    cached = _TOPIC_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _TOPIC_CACHE_TTL_SECONDS:
        return cached[1]

    def _fetch_one(topic):
        query = urllib.parse.quote(topic, safe="")
        return _gitea_search_paged(host, "/api/v1/repos/search?q=%s&topic=true" % query, gitea_cfg, scheme)

    per_topic = {}
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(topics))) as executor:
        future_map = {executor.submit(_fetch_one, topic): topic for topic in topics}
        for future in concurrent.futures.as_completed(future_map):
            topic = future_map[future]
            try:
                per_topic[topic] = future.result()
            except Exception as exc:
                errors.append("%s: %s" % (topic, exc))
                continue  # 토픽 하나만 실패했다면 나머지 토픽 결과는 계속 반영한다

    # [PATCH-9] 도착 순서가 아니라 설정 순서대로 병합(GitHub 쪽과 같은 규칙)
    seen = {}
    for topic in topics:
        for repo_json in per_topic.get(topic) or []:
            full_name = repo_json.get("full_name") or (
                "%s/%s" % ((repo_json.get("owner") or {}).get("login", ""), repo_json.get("name", ""))
            )
            if full_name and full_name not in seen:
                seen[full_name] = repo_json

    results = list(seen.values())
    if not results and errors and len(errors) == len(topics):
        # 토픽을 하나도 성공하지 못했다 — "정말로 결과가 없다"와 "검색 자체가
        # 실패했다"를 구분하지 않고 조용히 빈 목록을 돌려주면(예전 동작),
        # 인증 실패나 API 경로 문제 같은 진짜 원인이 영원히 보이지 않게 된다.
        # 예외를 그대로 올려 호출부가 에러 카드로 표시할 수 있게 하고,
        # 실패를 "빈 결과"로 캐시해 문제를 1시간 동안 숨기지도 않는다.
        raise RuntimeError(errors[0])

    _TOPIC_CACHE[cache_key] = (now, results)
    return results


def _gitea_owner_id(host, owner, gitea_cfg, scheme):
    """소유자(사용자 또는 조직) 이름으로 Gitea 내부 id를 얻는다."""
    quoted = urllib.parse.quote(owner, safe="")
    for path in ("/api/v1/users/%s" % quoted, "/api/v1/orgs/%s" % quoted):
        try:
            data = _gitea_get_json(host, path, gitea_cfg, scheme)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        if isinstance(data, dict) and data.get("id") is not None:
            return data["id"]
    return None


def _gitea_list_owner_repos_uncached(host, owner, gitea_cfg, scheme):
    """소유자의 저장소를 저장소 검색 API(uid + exclusive)로 모두 가져온다. 이 방식은
    인증한 계정이 볼 수 있는 비공개 저장소(협업자 권한 포함)까지 돌려준다 —
    /users/{owner}/repos는 본인 계정이 아니면 비공개 저장소를 빼고 돌려주기 때문이다."""
    uid = _gitea_owner_id(host, owner, gitea_cfg, scheme)
    if uid is None:
        raise RuntimeError("소유자 '%s'를 찾을 수 없습니다" % owner)
    return _gitea_search_paged(host, "/api/v1/repos/search?uid=%s&exclusive=true" % uid, gitea_cfg, scheme)


def _fetch_gitea_repos_by_owner(host, gitea_cfg, scheme, owners):
    """[PATCH-7] 지정한 소유자들의 저장소를 모두 모은다(1시간 캐시, 인증 정보별로 분리).
    소유자 하나가 실패해도 나머지 결과는 반영하고, 전부 실패하면 예외를 올린다."""
    owners = [o for o in dict.fromkeys(owners or []) if o]
    if not owners:
        return []
    cache_key = "gitea-owner:%s://%s:%s:%s" % (
        scheme, host, _gitea_auth_fingerprint(gitea_cfg), ",".join(sorted(o.lower() for o in owners))
    )
    now = time.time()
    cached = _TOPIC_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _TOPIC_CACHE_TTL_SECONDS:
        return cached[1]

    seen = {}
    errors = []
    for owner in owners:
        try:
            for repo_json in _gitea_list_owner_repos_uncached(host, owner, gitea_cfg, scheme):
                full_name = repo_json.get("full_name")
                if full_name and full_name not in seen:
                    seen[full_name] = repo_json
        except Exception as exc:
            errors.append("%s: %s" % (owner, exc))
    results = list(seen.values())
    if not results and errors and len(errors) == len(owners):
        raise RuntimeError(errors[0])
    _TOPIC_CACHE[cache_key] = (now, results)
    return results


def _fetch_gitea_repos_for_host(host, gitea_cfg, scheme, topics, owners):
    """토픽 검색 결과와 소유자 스캔 결과를 합친다(full_name 기준 중복 제거).
    한쪽만 실패하면 다른 쪽 결과를 그대로 쓰고, 둘 다 실패해야 예외를 올린다."""
    merged = {}
    errors = []
    for fetch in (
        lambda: _fetch_gitea_repos_by_topic(host, gitea_cfg, scheme, topics),
        lambda: _fetch_gitea_repos_by_owner(host, gitea_cfg, scheme, owners),
    ):
        try:
            for repo_json in fetch() or []:
                full_name = repo_json.get("full_name") or (
                    "%s/%s" % ((repo_json.get("owner") or {}).get("login", ""), repo_json.get("name", ""))
                )
                merged.setdefault(full_name, repo_json)
        except Exception as exc:
            errors.append(str(exc))
    if not merged and errors and (len(errors) == 2 or not owners):
        raise RuntimeError(errors[0])
    return list(merged.values())


def _build_gitea_discovered_item(host, repo_json, remote_version, is_enabled_fn, excluded_ids):
    """Gitea 토픽 검색 결과 하나를 카드 항목으로 변환한다. GitHub 발견 카드
    (_build_discovered_item)와 동일한 모양으로 만들어, 같은 "토픽 발견(미검수)"
    묶음에 자연스럽게 섞여 표시되게 한다. remote_version은 _gitea_fetch_version()
    이 돌려주는 순수 버전 문자열(또는 None)이다."""
    owner_login = ((repo_json.get("owner") or {}).get("login")) or ""
    repo_name = repo_json.get("name") or ""
    if not owner_login or not repo_name or repo_name in excluded_ids:
        return None

    key = owner_login + "/" + repo_name
    # [PATCH-4] 저장소 이름과 설치 폴더명이 다를 수 있다(하이픈↔언더스코어, 클래스 id
    # 기준 폴더 등). 실제 설치 폴더를 찾아 그 폴더를 카드 id로 쓴다.
    folder = _resolve_installed_folder(repo_name)
    if folder and folder in excluded_ids:
        return None
    installed = folder is not None
    local_id = folder or repo_name
    installed_version = _local_version(folder) if installed else None
    plugin_type = TYPE_OVERRIDES.get(key, "other")
    has_config = False
    title = repo_name
    tab_order = None
    class_id = repo_name
    admin_only = False
    if installed:
        local = _describe_local(folder, default_type=plugin_type)
        plugin_type, tab_order, has_config = local["type"], local["tab_order"], local["has_config"]
        title, class_id, admin_only = local["title"], local["class_id"], local["admin_only"]

    version_label = ("v" + remote_version) if remote_version else "—"

    return {
        "id": local_id,
        "class_id": class_id,
        "admin_only": admin_only,
        "owner": owner_login,
        "title": title,
        "type": plugin_type,
        "type_label": TYPE_LABELS.get(plugin_type, TYPE_LABELS["other"]),
        "desc": repo_json.get("description") or "(등록된 설명이 없습니다)",
        "tags": repo_json.get("topics") or [],
        "features": [],
        "version_label": version_label,
        "url": repo_json.get("html_url") or ("https://%s/%s" % (host, key)),
        "stars": repo_json.get("stars_count"),
        "pushed_at": repo_json.get("updated_at"),
        "error": False,
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(local_id) if installed else None,
        "discovered": True,
        "tab_order": tab_order,
        "gitea": True,
    }


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
    # [PATCH-4] 저장소 이름과 설치 폴더명이 다를 수 있다(하이픈↔언더스코어, 클래스 id
    # 기준 폴더 등). 실제 설치 폴더를 찾아 그 폴더를 카드 id로 쓴다.
    folder = _resolve_installed_folder(repo_name)
    if folder and folder in excluded_ids:
        return None
    installed = folder is not None
    local_id = folder or repo_name
    installed_version = _local_version(folder) if installed else None
    plugin_type = TYPE_OVERRIDES.get(key, "other")
    has_config = False
    title = repo_name
    tab_order = None
    class_id = repo_name
    admin_only = False
    if installed:
        local = _describe_local(folder, default_type=plugin_type)
        plugin_type, tab_order, has_config = local["type"], local["tab_order"], local["has_config"]
        title, class_id, admin_only = local["title"], local["class_id"], local["admin_only"]

    remote_version = version_info["remote_version"] if version_info else None
    version_label = version_info["version_label"] if version_info else "—"

    return {
        "id": local_id,
        "class_id": class_id,
        "admin_only": admin_only,
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
        "pushed_at": repo_json.get("pushed_at"),
        "error": bool(version_info and version_info.get("error")),
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(local_id) if installed else None,
        "discovered": True,
        "tab_order": tab_order,
    }


def _fetch_repo_entry(url, token, is_enabled_fn, preloaded_info=None, plugin_id_override=None, gitea_tokens=None):
    """url에서 얻은 원격 정보(설명·버전 등)로 카드를 만들되, 로컬 설치 여부·
    버전·활성화 상태는 plugin_id_override가 주어지면 그 값을(설치 폴더명
    기준으로) 우선 사용한다 — 등록된 Git 주소의 저장소 이름이 바뀌었어도
    실제 설치된 폴더는 이전 plugin_id 그대로일 수 있기 때문이다(레지스트리
    항목 조회 시 사용, 신규설치 미리보기에는 override 없이 그대로 repo를 씀).
    gitea_tokens는 설정에 등록해둔 {호스트: 토큰} 딕셔너리로, URL 자체에
    자격증명이 없는 Gitea 저장소를 조회할 때 폴백으로 쓰인다."""
    host, owner, repo = _parse_repo_url(url)
    if not host or not owner or not repo:
        pid = plugin_id_override or url
        return {
            "id": pid, "owner": "", "title": pid, "type": "other",
            "type_label": TYPE_LABELS["other"],
            "desc": "저장소 주소를 해석하지 못했습니다.",
            "tags": [], "features": [], "version_label": "—",
            "url": url, "error": True,
            "installed": _is_installed(pid) if plugin_id_override else False,
            "installed_version": (_local_version(pid) if plugin_id_override and _is_installed(pid) else None),
            "has_update": False,
            "has_config": False, "enabled": None,
        }

    if not _is_github_host(host):
        # GitHub가 아닌 모든 호스트는 Gitea 호환 API로 시도한다(서버별 허용
        # 목록 없음 — URL에 담긴 자격증명 또는 설정에 등록된 GITEA_TOKENS로 인증).
        gitea_cfg = _effective_gitea_cfg(url, gitea_tokens)
        scheme = _url_scheme(url)  # http로 준 주소는 http로 그대로 조회(523 방지)
        return _fetch_gitea_repo_entry(
            host, owner, repo, is_enabled_fn, gitea_cfg, scheme,
            plugin_id_override=plugin_id_override,
        )

    local_id = plugin_id_override or repo
    key = owner + "/" + repo
    plugin_type = TYPE_OVERRIDES.get(key, "other")
    if not plugin_id_override:
        local_id = _resolve_installed_folder(repo) or repo
    installed = _is_installed(local_id)
    installed_version = _local_version(local_id) if installed else None
    has_config = False
    title = local_id
    tab_order = None
    class_id = local_id
    admin_only = False
    if installed:
        # 이미 설치되어 있다면 실제 소스에서 분류·설정 여부·표시 이름을 더 정확히 추정
        local = _describe_local(local_id, default_type=plugin_type)
        plugin_type, tab_order, has_config = local["type"], local["tab_order"], local["has_config"]
        title, class_id, admin_only = local["title"], local["class_id"], local["admin_only"]

    # 병렬로 미리 가져온 원격 정보가 있으면 그걸 쓰고, 없으면(단건 호출 등) URL에
    # 담긴 자격증명을 우선 적용해(없으면 GITHUB_TOKEN 설정으로 폴백) 직접 조회
    if preloaded_info is not None:
        info = preloaded_info
    else:
        info = _fetch_remote_info(owner, repo, _effective_github_token(url, token))
    remote_version = info["remote_version"]

    item = {
        "id": local_id,
        "class_id": class_id,
        "admin_only": admin_only,
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
        "pushed_at": info.get("pushed_at"),
        "error": info["error"],
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(local_id) if installed else None,
        "canonical_owner": info.get("canonical_owner"),
        "canonical_repo": info.get("canonical_repo"),
        "tab_order": tab_order,
    }
    return item


def _fetch_gitea_repo_entry(host, owner, repo, is_enabled_fn, gitea_cfg, scheme="https", plugin_id_override=None):
    """GitHub 카드와 동일한 형태의 item dict를 Gitea API로 채워 만든다.
    plugin_id_override 의미는 _fetch_repo_entry와 동일하다."""
    local_id = plugin_id_override or repo
    key = owner + "/" + repo
    plugin_type = TYPE_OVERRIDES.get(key, "other")
    if not plugin_id_override:
        local_id = _resolve_installed_folder(repo) or repo
    installed = _is_installed(local_id)
    installed_version = _local_version(local_id) if installed else None
    has_config = False
    title = local_id
    tab_order = None
    class_id = local_id
    admin_only = False
    if installed:
        # 이미 설치되어 있다면 실제 소스에서 분류·설정 여부·표시 이름을 더 정확히 추정
        local = _describe_local(local_id, default_type=plugin_type)
        plugin_type, tab_order, has_config = local["type"], local["tab_order"], local["has_config"]
        title, class_id, admin_only = local["title"], local["class_id"], local["admin_only"]

    desc_info = _gitea_fetch_description_info(host, owner, repo, gitea_cfg, scheme)
    version_info = _gitea_fetch_version_info(
        host, owner, repo, desc_info.get("default_branch"), gitea_cfg, scheme
    )
    remote_version = version_info["remote_version"]

    return {
        "id": local_id,
        "class_id": class_id,
        "admin_only": admin_only,
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
        "pushed_at": desc_info.get("pushed_at"),
        "error": desc_info["error"] or version_info["error"],
        "installed": installed,
        "installed_version": installed_version,
        "has_update": installed and _remote_is_newer(installed_version, remote_version),
        "has_config": has_config,
        "enabled": is_enabled_fn(local_id) if installed else None,
        "gitea": True,
        "tab_order": tab_order,
    }


# ========================================================================
# 설치/업데이트 엔진 — git 바이너리·plugin_manager 없이 codeload zip으로 처리
# (madnite1/plugin_manager와 동일한 원리: 릴리즈 대신 브랜치 우선순위. 파일
#  선별은 하지 않고 검증 통과 시 폴더 전체를 교체한다 — 모듈 상단 docstring
#  [PATCH-2]/[PATCH-3] 참고)
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

    # py7zr은 심볼릭 링크를 실제 링크로 복원할 수 있다 — tar와 같은 기준으로 거부한다
    for root_dir, dirs, files in os.walk(extract_dir):
        for entry in dirs + files:
            if os.path.islink(os.path.join(root_dir, entry)):
                raise ValueError(
                    "보안 경고: 압축 파일 안에 심볼릭 링크가 포함되어 있어 거부합니다: %s" % entry
                )


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


_OS_PROCESS_FUNCS = {"system", "popen", "fork", "forkpty"}


def _is_os_process_call(attr):
    """os 모듈 함수 중 외부 프로세스를 띄우는 것인지(가이드 §2-5 기준)."""
    attr = str(attr or "")
    return attr in _OS_PROCESS_FUNCS or attr.startswith(("exec", "spawn", "posix_spawn"))


def _allow_plugin_subprocess():
    """서버 환경변수 ALLOW_PLUGIN_SUBPROCESS가 true/1/yes/on(대소문자 무관)이면
    플러그인 설치 시 subprocess import를 허용한다. 기본값은 차단이다 — 이 값을
    설정하지 않은 서버는 이전과 동일하게 subprocess를 쓰는 플러그인의 설치를
    막는다. 플러그인 설정이 아니라 서버 환경변수인 이유: 관리자 개개인이 아니라
    서버 운영자가 내리는 신뢰 판단이라, 웹 UI의 플러그인별 설정과는 분리해
    서버를 직접 관리하는 사람만 바꿀 수 있게 한다."""
    return str(os.environ.get("ALLOW_PLUGIN_SUBPROCESS", "")).strip().lower() in ("1", "true", "yes", "on")


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
    vfile_lenient = False  # 중괄호 없이 "plugin version": "..." 형태만 있어 구제 파싱한 경우
    vdetail = ""
    if os.path.isfile(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as f:
                vdata, vfile_lenient = _parse_version_json(f.read())
            vkey = vdata.get("plugin version") or vdata.get("version")
            if vkey:
                vfile_ok = True
                vdetail = "버전 %s" % vkey
                if vfile_lenient:
                    vdetail += " (중괄호 없이 적혀 있어 관대하게 파싱함 — 표준 형식({\"plugin version\": \"%s\"})을 권장합니다)" % vkey
            else:
                vdetail = "'plugin version' 키가 없습니다 (업데이트 체크 불가)"
        except Exception:
            vdetail = "VERSION 형식이 표준 JSON이 아닙니다 (업데이트 체크 불가)"
    else:
        vdetail = "VERSION 파일 없음"

    if manifest_files:
        checks.append({"name": "VERSION", "ok": vfile_ok, "warn": vfile_ok and vfile_lenient,
                        "detail": (vdetail if vfile_ok else "update_manifest 선언 시 VERSION 필수 — " + vdetail)})
    else:
        checks.append({"name": "VERSION", "ok": True, "warn": (not vfile_ok) or vfile_lenient,
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
    subprocess_hits = []  # subprocess만 따로 모은다 — ALLOW_PLUGIN_SUBPROCESS로 예외 허용 가능
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
                    forbidden_hits.append("%s: %s() 호출 발견(plugin_board 자체 정책)" % (fname, fn.id))
                elif (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                      and fn.value.id == "os" and _is_os_process_call(fn.attr)):
                    # [PATCH-4] 가이드 §2-5: os.system/popen/exec*/spawn*는 subprocess와
                    # 같은 "프로세스 실행"으로 취급한다(ALLOW_PLUGIN_SUBPROCESS로만 허용).
                    # 예전에는 모듈을 확인하지 않아 platform.system() 같은 무해한 호출도
                    # 금지 패턴으로 오탐했고, 반대로 os.exec*/os.spawn*은 놓쳤다.
                    subprocess_hits.append("%s: os.%s() 호출 발견" % (fname, fn.attr))
            elif isinstance(node, ast.ImportFrom) and node.module == "os":
                for a in node.names:
                    if _is_os_process_call(a.name):
                        subprocess_hits.append("%s: from os import %s 발견" % (fname, a.name))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "subprocess" or a.name.startswith("subprocess."):
                        subprocess_hits.append("%s: subprocess import 발견" % fname)
                    elif a.name.startswith("plugins.metadata."):
                        parts = a.name.split(".")
                        if len(parts) >= 3 and parts[2] not in ("base", detected_id):
                            cross_plugin_deps.add(parts[2])
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    subprocess_hits.append("%s: subprocess import 발견" % fname)
                elif node.module and node.module.startswith("plugins.metadata."):
                    parts = node.module.split(".")
                    if len(parts) >= 3 and parts[2] not in ("base", detected_id):
                        cross_plugin_deps.add(parts[2])
            elif isinstance(node, ast.keyword) and node.arg == "shell":
                try:
                    if ast.literal_eval(node.value) is True:
                        forbidden_hits.append("%s: shell=True 사용(plugin_board 자체 정책)" % fname)
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
                        elif t.id in ("category_tab", "update_manifest", "dashboard_widget",
                                      "home_widget", "detail_view", "detail_sidebar_widget",
                                      "smart_recommend_widget"):
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

    if class_id is not None and not _is_valid_class_id(class_id):
        checks.append({"name": "클래스 id", "ok": False,
                        "detail": "클래스 id='%s' 형식이 올바르지 않습니다(영문/숫자/._- 만 허용)" % class_id})
    elif class_id is not None:
        class_id_str = str(class_id).strip()
        detected_id_str = str(detected_id).strip()
        if class_id_str == detected_id_str:
            checks.append({"name": "클래스 id", "ok": True, "detail": class_id})
        elif class_id_str.replace("-", "_") == detected_id_str.replace("-", "_"):
            # 저장소 이름은 관례상 하이픈을 쓰고(예: bookoasis-m3u-player), 파이썬
            # 식별자는 하이픈을 쓸 수 없어 클래스 id를 언더스코어로 짓는 경우가
            # 흔하다(예: bookoasis_m3u_player). 표기 차이일 뿐 실질적으로 같은
            # id이므로 이 차이만으로는 설치를 막지 않고 통과시키되, 코어가 이
            # 값을 그대로 참조하는 곳(목록 표시 등)이 있을 수 있어 경고로 남긴다.
            checks.append({
                "name": "클래스 id", "ok": True, "warn": True,
                "detail": (
                    "경고: 코드 내 id='%s'와 감지된 id='%s'가 하이픈/언더스코어 표기만 "
                    "달라 임시로 통과시켰습니다 — 코어가 이 값을 그대로 참조하는 곳이 "
                    "있다면 목록에 정상적으로 안 보일 수 있으니, 가능하면 플러그인 "
                    "코드의 id를 '%s'로 맞춰주세요." % (class_id, detected_id, detected_id)
                ),
            })
        else:
            # [PATCH-4] 폴더명과 클래스 id를 분리해서 다루므로(활성화·설정 키는 항상
            # 클래스 id로 조회) 불일치 자체는 더 이상 설치 실패 사유가 아니다.
            # 네임스페이스 id(leeyj.spotify_mood)처럼 폴더명으로 쓸 수 없는 id가 대표적이다.
            checks.append({"name": "클래스 id", "ok": True, "warn": True,
                            "detail": "경고: 코드 내 id='%s'를 설치 폴더 '%s'에 설치합니다 — 설정·활성화 "
                                      "상태는 클래스 id 기준으로 관리됩니다." % (class_id, detected_id)})
    elif provider_found:
        checks.append({"name": "클래스 id", "ok": False, "detail": "플러그인 클래스에 id 속성이 없습니다"})
    else:
        checks.append({"name": "클래스 id", "ok": False, "detail": "클래스를 찾을 수 없어 검사 불가"})

    if provider_found:
        # [PATCH-4] 가이드 §3의 필수 계약은 search/apply뿐이다. name/is_searchable/
        # config_schema는 권장 필드라 없으면 경고만 남긴다(베이스 클래스 기본값 사용).
        missing_fields = [f for f in ("name", "is_searchable", "config_schema") if f not in cls_attrs]
        checks.append({"name": "권장 필드", "ok": True, "warn": bool(missing_fields),
                        "detail": ("경고: 클래스에 직접 선언되지 않음(기본값 사용): " + ", ".join(missing_fields))
                                  if missing_fields else "name/is_searchable/config_schema 확인"})
        missing_methods = [m for m, ok in (("search", has_search), ("apply", has_apply)) if not ok]
        checks.append({"name": "필수 메서드", "ok": not missing_methods,
                        "detail": ("구현 안 됨: " + ", ".join(missing_methods)) if missing_methods
                                  else "search/apply 확인"})
    else:
        checks.append({"name": "권장 필드", "ok": False, "detail": "클래스 없음"})
        checks.append({"name": "필수 메서드", "ok": False, "detail": "클래스 없음"})

    checks.append({"name": "금지 패턴", "ok": not forbidden_hits,
                    "detail": "; ".join(forbidden_hits[:3]) if forbidden_hits else "eval/exec/shell=True 없음"})

    if subprocess_hits:
        if _allow_plugin_subprocess():
            # 서버가 ALLOW_PLUGIN_SUBPROCESS=true로 명시적으로 허용한 경우에만
            # 통과시킨다 — 기본값은 여전히 차단이며, 통과하더라도 설치 결과
            # 메시지에 경고로 남겨 관리자가 알아챌 수 있게 한다.
            checks.append({
                "name": "프로세스 실행", "ok": True, "warn": True,
                "detail": (
                    "경고: subprocess를 사용합니다(%s) — 서버 환경변수 "
                    "ALLOW_PLUGIN_SUBPROCESS=true로 허용되어 있어 설치를 통과시켰습니다. "
                    "이 플러그인이 실제로 외부 명령을 실행한다는 뜻이니, 신뢰할 수 있는 "
                    "출처인지 다시 한번 확인하세요." % "; ".join(subprocess_hits[:3])
                ),
            })
        else:
            checks.append({
                "name": "프로세스 실행", "ok": False,
                "detail": (
                    "%s — 서버 환경변수 ALLOW_PLUGIN_SUBPROCESS=true를 설정하면 설치를 "
                    "허용할 수 있습니다(기본값은 차단)." % "; ".join(subprocess_hits[:3])
                ),
            })
    else:
        checks.append({"name": "프로세스 실행", "ok": True, "detail": "subprocess/os.system·popen·exec*·spawn* 없음"})

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
        missing_ui = [f for f in ("index.html", "script.js") if not os.path.isfile(os.path.join(plugin_dir, f))]
        no_css = not os.path.isfile(os.path.join(plugin_dir, "style.css"))
        checks.append({"name": "UI 번들", "ok": not missing_ui, "warn": (not missing_ui) and no_css,
                        "detail": ("category_tab 선언 시 필수: " + ", ".join(missing_ui)) if missing_ui
                                  else ("경고: style.css 없음" if no_css else "index/script/style 확인")})
    else:
        checks.append({"name": "UI 번들", "ok": True, "detail": "미선언"})

    if "detail_view" in cls_attrs:
        missing_dv = [f for f in ("detail/index.html", "detail/script.js")
                      if not os.path.isfile(os.path.join(plugin_dir, *f.split("/")))]
        checks.append({"name": "상세 화면 번들", "ok": not missing_dv,
                        "detail": ("detail_view 선언 시 필수: " + ", ".join(missing_dv)) if missing_dv
                                  else "detail/index.html·script.js 확인"})

    all_ok = all(c.get("ok") for c in checks)
    return all_ok, checks


def _install_from_archive(archive_data_b64, filename, db_type, gitea_tokens=None):
    """업로드된 압축 파일(base64, zip/tar 계열/7z)로 플러그인을 설치한다.
    1) base64 디코드 → 파일명 확장자로 형식 판별 → 임시 폴더에 안전하게 압축
       해제(경로 이탈/개수/용량 검증 — 형식별로 _extract_archive_safe에 위임)
    2) 플러그인 루트 탐색 + [PATCH-4] 설치 폴더/클래스 id 결정과 id 충돌 검사
    3) 정적 소스 검증(코드 실행 없음) — 실패 시 설치 중단(기존 폴더 미변경)
    4) 검증 통과 후에만 스테이징 → 백업 → 교체(로드 실패 시 백업 복원)
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
        folder_hint = _detect_plugin_id_from_dir(plugin_root, fallback_name=filename)

        # update_manifest.raw_base_url이 GitHub 루트(또는 Gitea)를 가리키면 그 저장소를
        # 이 압축 파일의 출처로 본다 — id 충돌 판단(다른 저장소가 같은 폴더를 점유했는지)과
        # 설치 후 업데이트 추적(github.txt 등록)에 함께 쓴다. monorepo 서브디렉토리는 제외.
        source_url = None
        try:
            files_clean, manifest = _extract_update_manifest_files(plugin_root)
            raw_base_url = str((manifest or {}).get("raw_base_url") or "").strip().rstrip("/")
            if files_clean and raw_base_url:
                parsed = _parse_raw_base_url(raw_base_url)
                if parsed and not parsed[4]:  # subpath가 없을 때만
                    host, owner, repo, _branch, _sub = parsed
                    source_url = "https://%s/%s/%s" % (host, owner, repo)
        except Exception:
            source_url = None

        ok, msg, folder = _install_from_source_dir(
            plugin_root, folder_hint, None, source_url, db_type,
            "압축 파일 %s" % archive_kind,
            ignore=shutil.ignore_patterns(".git", ".github", "__pycache__", "*.pyc", "__MACOSX", ".DS_Store"),
        )
        if not ok:
            return False, msg

        # 2차 로드 검증까지 통과한 뒤에만 기록한다 — 롤백된 설치가 레지스트리에 남지 않도록.
        if source_url:
            registered_url, _injected = _inject_gitea_credentials(source_url, gitea_tokens)
            _remember_repo_install(registered_url, plugin_id=folder)
        return True, msg
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
                vdata, _lenient = _parse_version_json(f.read())
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
        clean = re.sub(r"\.(zip|7z|tar|tgz|tbz2|txz|tar\.gz|tar\.bz2|tar\.xz)$", "",
                       str(fallback_name), flags=re.IGNORECASE)
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", clean).strip("_")
        if clean:
            return clean

    return ""


def _verify_plugin_loaded(class_id):
    """2차 검증 — 코어가 실제로 이 플러그인(클래스 id 기준)을 로드했는지 확인한다.
    반환: True(로드됨) / False(로드 안 됨) / None(코어 내부 API를 쓸 수 없어 판단 불가).
    [PATCH-4] 예전에는 판단 불가도 False로 취급해, hot reload가 없는 코어에서는
    정상 설치까지 롤백(삭제)되는 문제가 있었다."""
    try:
        from services.metadata_factory import MetadataFactory
        providers = MetadataFactory.get_available_providers()
    except Exception:
        return None
    try:
        return any(str(p.get("id")) == str(class_id) for p in providers)
    except Exception:
        return None


def _candidate_branches(default_branch):
    branches = []
    for b in (default_branch, "main", "master"):
        if b and b not in branches:
            branches.append(b)
    return branches


def _try_hot_reload(*plugin_ids):
    """가능하면 코어의 hot reload를 호출해 서버 재시작 없이 즉시 반영을 시도한다.
    코어가 인자를 클래스 id로 받는지 폴더명으로 받는지 문서화돼 있지 않아, 둘이
    다르면 둘 다 시도한다. 한 번이라도 호출에 성공하면 True, 코어에 해당 기능이
    없거나 전부 실패하면 False. (문서화되지 않은 코어 내부 API라 실패해도 설치
    자체는 유지한다.)"""
    try:
        from services.metadata_factory import MetadataFactory
    except Exception:
        return False
    if not hasattr(MetadataFactory, "hot_reload_plugin"):
        return False
    ok = False
    seen = set()
    for pid in plugin_ids:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        try:
            MetadataFactory.hot_reload_plugin(pid)
            ok = True
        except Exception:
            pass
    return ok


def _toggle_plugin_enabled(plugin_id, enabled_val, db_type, reload=True):
    """madnite1/plugin_manager와 동일하게 코어의 PluginService를 그대로 사용해
    활성화/비활성화 상태를 변경한다. plugin_id는 설치 폴더명이며, 코어에는
    [PATCH-4] 클래스 id로 변환해서 넘긴다(코어의 PLUGIN_ENABLED_{id} 키는 클래스 id 기준)."""
    try:
        _validate_plugin_id(plugin_id)
    except ValueError as exc:
        return False, str(exc)

    class_id = _class_id_for_folder(plugin_id) if _is_installed(plugin_id) else plugin_id
    if plugin_id == "plugin_board" or class_id == "plugin_board":
        return False, "plugin_board 자기 자신은 이 화면에서 비활성화할 수 없습니다."

    try:
        from services.plugin_service import PluginService
    except Exception as exc:
        return False, "코어 PluginService를 사용할 수 없습니다 (%s)" % exc

    try:
        ok, err = PluginService.toggle_plugin_enabled(db_type, class_id, str(enabled_val))
        if not ok:
            return False, err or "상태 변경에 실패했습니다."
    except Exception as exc:
        return False, "상태 변경 중 오류가 발생했습니다: %s" % exc

    if reload:
        _try_hot_reload(class_id, plugin_id)
    status_text = "활성화" if str(enabled_val) == "1" else "비활성화"
    return True, "'%s' 상태가 '%s'로 변경되었습니다." % (plugin_id, status_text)


def _delete_plugin(plugin_id):
    """plugins/metadata/{plugin_id} 폴더와, 있다면 plugins/data/{plugin_id}
    폴더(플러그인이 남긴 데이터)까지 함께 삭제한다. 폴더명과 클래스 id가 다르면
    plugins/data/{클래스 id}도 함께 정리한다. 모든 경로는 각자의 루트
    (plugins/metadata, plugins/data) 경계 안에 있는지 검증한 뒤에만 삭제한다."""
    if plugin_id == "plugin_board":
        return False, "plugin_board 자기 자신은 이 화면에서 삭제할 수 없습니다."

    try:
        _validate_plugin_id(plugin_id)
        target_dir = _safe_join(_plugins_metadata_dir(), plugin_id)
    except ValueError as exc:
        return False, str(exc)

    if not os.path.isdir(target_dir):
        return False, "존재하지 않는 플러그인입니다: %s" % plugin_id

    class_id = _class_id_for_folder(plugin_id)
    if class_id == "plugin_board":
        return False, "plugin_board 자기 자신은 이 화면에서 삭제할 수 없습니다."
    deleted_version = _local_version(plugin_id)

    data_root = os.path.join(_plugins_root_dir(), "data")
    data_dirs = []
    for name in (plugin_id, class_id):
        if name and _PLUGIN_ID_RE.match(name) and name != "plugin_board":
            try:
                d = _safe_join(data_root, name)
            except ValueError:
                continue
            if d not in data_dirs:
                data_dirs.append(d)

    try:
        shutil.rmtree(target_dir)
    except Exception as exc:
        return False, "삭제 실패: %s" % exc

    # 메타데이터 폴더 삭제가 이미 성공한 뒤이므로, 데이터 폴더 삭제가 실패해도
    # (예: 권한 문제) 전체 삭제 자체를 실패로 처리하지 않고 메시지에만 알린다.
    data_dir_warning = ""
    for d in data_dirs:
        if os.path.isdir(d):
            try:
                shutil.rmtree(d)
            except Exception as exc:
                data_dir_warning += " (경고: 데이터 폴더 %s 삭제 실패: %s)" % (os.path.basename(d), exc)

    _DESC_CACHE.clear()  # 삭제된 플러그인이 GitHub 캐시에 남아 잘못된 정보를 주지 않도록
    _VERSION_CACHE.clear()
    _save_disk_cache()
    _try_hot_reload(class_id, plugin_id)

    # 삭제된 plugin_id의 github.txt 등록도 함께 제거한다 — 파일은 이미 지워졌는데
    # 등록만 남아있으면 죽은 주소로 계속 업데이트를 시도하게 된다.
    _unregister_repo(plugin_id)
    _record_history("delete", plugin_id, class_id, from_version=deleted_version,
                    message=data_dir_warning.strip() or None)

    return True, "'%s' 플러그인이 삭제되었습니다.%s" % (plugin_id, data_dir_warning)


# ========================================================================
# [PATCH-6] Gitea 서버 연결 테스트
# ========================================================================
def _gitea_http_error_detail(exc, what):
    code = getattr(exc, "code", None)
    if code == 401:
        return "%s 인증 실패(401)" % what
    if code == 403:
        return "%s 권한 부족(403)" % what
    if code == 404:
        return "%s 경로를 찾을 수 없음(404)" % what
    return "%s 오류: %s" % (what, exc)


def _test_gitea_server(params, configured_tokens, topics):
    """설정 화면의 '연결 테스트'. 화면에 입력된(아직 저장 전일 수 있는) 값으로
    ① 서버 접속 ② 읽기 토큰 ③ 아이디/비밀번호 ④ 토픽 검색(인증 전후 비교)을 차례로
    확인해 단계별 결과를 돌려준다. 입력칸이 비어 있으면 저장된 값을 쓴다.
    반환: {"host", "scheme", "checks": [{label, status: ok|warn|fail|skip, detail}], "repos": [...]}"""
    scheme, host = _normalize_gitea_server(params.get("host"), params.get("scheme") or None)
    saved = (configured_tokens or {}).get(host) or {}
    if not params.get("scheme") and saved.get("scheme"):
        scheme = saved["scheme"]
    token = str(params.get("token") or "").strip() or saved.get("token")
    username = str(params.get("username") or "").strip() or saved.get("username")
    password = str(params.get("password") or "").strip() or saved.get("password")

    checks = []
    report = {"host": host, "scheme": scheme, "checks": checks, "repos": [], "topics": list(topics)}
    if not host:
        checks.append({"label": "서버 주소", "status": "fail", "detail": "주소를 입력해주세요."})
        return report

    # ① 접속
    try:
        ver = _gitea_get_json(host, "/api/v1/version", None, scheme)
        checks.append({"label": "서버 접속", "status": "ok",
                       "detail": "%s://%s — Gitea %s" % (scheme, host, (ver or {}).get("version", "?"))})
    except Exception as exc:
        hint = ""
        if scheme == "https":
            hint = " (http로만 서비스하는 서버라면 주소를 http://로 입력해보세요)"
        checks.append({"label": "서버 접속", "status": "fail",
                       "detail": "%s://%s 에 접속하지 못했습니다: %s%s" % (scheme, host, exc, hint)})
        return report

    # ② 읽기 토큰
    token_ok = False
    if token:
        try:
            me = _gitea_get_json(host, "/api/v1/user", {"token": token}, scheme)
            token_ok = True
            checks.append({"label": "읽기 토큰", "status": "ok",
                           "detail": "유효함 — 계정 %s" % (me or {}).get("login", "?")})
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # 사용자 정보(read:user) 권한이 없을 뿐 토큰 자체는 유효할 수 있다 — 아래 검색으로 판단
                token_ok = True
                checks.append({"label": "읽기 토큰", "status": "warn",
                               "detail": "토큰은 인식됐지만 사용자 정보 조회 권한이 없습니다(403). "
                                         "저장소 읽기 권한이 있으면 아래 검색은 정상 동작합니다."})
            else:
                checks.append({"label": "읽기 토큰", "status": "fail",
                               "detail": _gitea_http_error_detail(exc, "토큰") +
                                         " — 토큰이 잘못됐거나 만료·폐기됐을 수 있습니다."})
        except Exception as exc:
            checks.append({"label": "읽기 토큰", "status": "fail", "detail": str(exc)})
    else:
        checks.append({"label": "읽기 토큰", "status": "skip", "detail": "입력되지 않음"})

    # ③ 아이디/비밀번호
    basic_ok = False
    if username and password:
        try:
            me = _gitea_get_json(host, "/api/v1/user", {"username": username, "password": password}, scheme)
            basic_ok = True
            checks.append({"label": "아이디/비밀번호", "status": "ok",
                           "detail": "로그인 성공 — 계정 %s" % (me or {}).get("login", username)})
        except urllib.error.HTTPError as exc:
            checks.append({"label": "아이디/비밀번호", "status": "fail",
                           "detail": _gitea_http_error_detail(exc, "아이디/비밀번호") +
                                     " — 비밀번호가 틀렸거나, 계정에 2단계 인증이 켜져 있거나, 서버가 "
                                     "API의 비밀번호 인증을 막아둔 경우입니다. 이때는 읽기 토큰을 등록하세요."})
        except Exception as exc:
            checks.append({"label": "아이디/비밀번호", "status": "fail", "detail": str(exc)})
    elif username or password:
        checks.append({"label": "아이디/비밀번호", "status": "fail", "detail": "아이디와 비밀번호를 모두 입력해주세요."})
    else:
        checks.append({"label": "아이디/비밀번호", "status": "skip", "detail": "입력되지 않음"})

    # ④ 토픽 검색 — 실제 검색은 토큰 우선(대시보드와 같은 규칙), 인증 없는 결과와 비교
    def search(cfg):
        found = {}
        for topic in topics:
            path = "/api/v1/repos/search?q=%s&topic=true" % urllib.parse.quote(topic, safe="")
            for repo_json in _gitea_search_paged(host, path, cfg, scheme):
                name = repo_json.get("full_name") or repo_json.get("name")
                if name:
                    found[name] = bool(repo_json.get("private"))
        return found

    auth_cfg = None
    if token and token_ok:
        auth_cfg = {"token": token}
    elif username and password and basic_ok:
        auth_cfg = {"username": username, "password": password}

    try:
        anon = search(None)
    except Exception as exc:
        anon = None
        checks.append({"label": "토픽 검색(인증 없음)", "status": "warn", "detail": str(exc)})

    topics_text = ", ".join(topics)
    if auth_cfg:
        try:
            found = search(auth_cfg)
            report["repos"] = [{"name": n, "private": p} for n, p in sorted(found.items())]
            private_count = sum(1 for p in found.values() if p)
            if found:
                checks.append({"label": "토픽 검색", "status": "ok",
                               "detail": "토픽(%s)이 달린 저장소 %d개 발견 — 비공개 %d개, 인증 없이는 %s개" % (
                                   topics_text, len(found), private_count,
                                   "?" if anon is None else len(anon))})
            else:
                checks.append({"label": "토픽 검색", "status": "warn",
                               "detail": "인증은 됐지만 토픽(%s)이 달린 저장소가 없습니다. 저장소 설정 → "
                                         "토픽에 해당 토픽을 추가했는지, 이 계정에 저장소 읽기 권한이 "
                                         "있는지 확인해주세요." % topics_text})
        except urllib.error.HTTPError as exc:
            checks.append({"label": "토픽 검색", "status": "fail",
                           "detail": _gitea_http_error_detail(exc, "저장소 검색") +
                                     " — 토큰이라면 repository 읽기 권한으로 다시 발급해주세요."})
        except Exception as exc:
            checks.append({"label": "토픽 검색", "status": "fail", "detail": str(exc)})
    elif anon is not None:
        report["repos"] = [{"name": n, "private": p} for n, p in sorted(anon.items())]
        checks.append({"label": "토픽 검색", "status": "warn" if not anon else "ok",
                       "detail": "인증 없이 검색 — 공개 저장소 %d개. 비공개 저장소는 계정이나 토큰이 "
                                 "있어야 보입니다." % len(anon)})

    # ⑤ [PATCH-7] 소유자 스캔 — 입력한 소유자 + 이 서버에서 설치한 적 있는 소유자
    owners = params.get("owners")
    if isinstance(owners, str):
        owners = owners.split(",")
    owners = [str(o).strip().strip("/") for o in (owners or saved.get("owners") or []) if str(o).strip()]
    for _pid, _url in _load_github_registry_entries():
        h, o, _r = _parse_repo_url(_url)
        if h and h.lower() == host and o and o not in owners:
            owners.append(o)
    scan_cfg = auth_cfg
    for owner in owners:
        try:
            repos = _gitea_list_owner_repos_uncached(host, owner, scan_cfg, scheme)
        except Exception as exc:
            checks.append({"label": "소유자 %s" % owner, "status": "fail", "detail": str(exc)})
            continue
        specs = [(r.get("name"), r.get("default_branch"), bool(r.get("private"))) for r in repos if r.get("name")]
        plugins = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_gitea_fetch_version, host, owner, name, br, scan_cfg, scheme): (name, priv)
                    for name, br, priv in specs[:120]}
            for fut in concurrent.futures.as_completed(futs):
                name, priv = futs[fut]
                try:
                    if fut.result():
                        plugins.append((name, priv))
                except Exception:
                    pass
        private_total = sum(1 for _n, _b, priv in specs if priv)
        status = "ok" if plugins else "warn"
        detail = "저장소 %d개(비공개 %d개) 중 VERSION 파일이 있는 플러그인 %d개" % (
            len(specs), private_total, len(plugins))
        if not scan_cfg:
            detail += " — 인증 없이 조회해 비공개 저장소는 빠졌을 수 있습니다"
        checks.append({"label": "소유자 %s" % owner, "status": status, "detail": detail})
        for name, priv in sorted(plugins):
            full = "%s/%s" % (owner, name)
            if not any(r["name"] == full for r in report["repos"]):
                report["repos"].append({"name": full, "private": priv})
    return report


# ========================================================================
# [PATCH-5] 이 서버의 설치/업데이트 이력(HISTORY)
# ========================================================================
_HISTORY_FILE = os.path.join(_PLUGIN_DATA_DIR, "history.jsonl")
_HISTORY_MAX_LINES = 3000
_HISTORY_TRIM_BYTES = 2 * 1024 * 1024
_HISTORY_LOCK = threading.Lock()
# 요청 단위 문맥(수동/자동 여부, 이번 요청에서 이미 기록했는지). 요청마다
# _dispatch_apply가 초기화한다.
_HISTORY_CTX = threading.local()
_DIFF_MAX_FILE_BYTES = 512 * 1024
_DIFF_MAX_LIST = 60
_CREDENTIAL_IN_URL_RE = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)


def _scrub_credentials(text):
    """메시지에 섞여 들어온 URL 자격증명(https://user:pass@...)을 가린다."""
    return _CREDENTIAL_IN_URL_RE.sub(r"\1***@", str(text or ""))


def _history_actor():
    try:
        from flask import session
        actor = session.get("username") or session.get("user_id")
        return str(actor) if actor is not None else None
    except Exception:
        return None


def _record_history(action, folder=None, class_id=None, result="success", from_version=None,
                    to_version=None, origin=None, message=None, files=None):
    """이력 한 건을 history.jsonl에 추가한다. 기록 실패는 본 동작을 막지 않는다."""
    entry = {
        "ts": int(time.time()),
        "action": action,
        "folder": folder,
        "class_id": class_id,
        "result": result,
        "from_version": from_version,
        "to_version": to_version,
        "origin": _scrub_credentials(origin) if origin else None,
        "mode": getattr(_HISTORY_CTX, "mode", "manual"),
        "user": _history_actor(),
        "message": _scrub_credentials(message)[:600] if message else None,
        "files": files,
    }
    entry = {k: v for k, v in entry.items() if v is not None}
    _HISTORY_CTX.recorded = True
    try:
        with _HISTORY_LOCK:
            os.makedirs(_PLUGIN_DATA_DIR, exist_ok=True)
            with open(_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if os.path.getsize(_HISTORY_FILE) > _HISTORY_TRIM_BYTES:
                with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-_HISTORY_MAX_LINES:]
                tmp_path = "%s.%d.tmp" % (_HISTORY_FILE, os.getpid())
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                os.replace(tmp_path, _HISTORY_FILE)
    except Exception:
        pass


def _read_history(folder=None, class_id=None, limit=200):
    """최신순으로 이력을 읽는다. folder/class_id를 주면 둘 중 하나라도 일치하는 항목만."""
    if not os.path.isfile(_HISTORY_FILE):
        return []
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    out = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if folder or class_id:
            if not ((folder and entry.get("folder") == folder)
                    or (class_id and entry.get("class_id") == class_id)):
                continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def _walk_plugin_files(root):
    files = {}
    for dirpath, dirs, fnames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".github", "libs")]
        for fname in fnames:
            if fname.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, fname)
            files[os.path.relpath(full, root).replace(os.sep, "/")] = full
    return files


def _file_digest(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text_lines(path):
    if os.path.getsize(path) > _DIFF_MAX_FILE_BYTES:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def _diff_summary(old_dir, new_dir):
    """교체 전(old)·후(new) 폴더를 비교해 추가/삭제/수정 파일과 줄 수 변화를 요약한다.
    libs/(requirements.txt로 설치되는 패키지)와 캐시 파일은 비교 대상에서 뺀다."""
    old = _walk_plugin_files(old_dir)
    new = _walk_plugin_files(new_dir)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    modified = []
    for rel in sorted(set(old) & set(new)):
        a, b = old[rel], new[rel]
        try:
            if os.path.getsize(a) == os.path.getsize(b) and _file_digest(a) == _file_digest(b):
                continue
        except OSError:
            continue
        plus = minus = None
        a_lines, b_lines = _read_text_lines(a), _read_text_lines(b)
        if a_lines is not None and b_lines is not None:
            plus = minus = 0
            for line in difflib.unified_diff(a_lines, b_lines, lineterm="", n=0):
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if line.startswith("+"):
                    plus += 1
                elif line.startswith("-"):
                    minus += 1
        modified.append({"path": rel, "added": plus, "removed": minus})
    return {
        "counts": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "added": added[:_DIFF_MAX_LIST],
        "removed": removed[:_DIFF_MAX_LIST],
        "modified": modified[:_DIFF_MAX_LIST],
    }


# ========================================================================
# [PATCH-5] 저장소의 변경 내용(changelog) 조회
# ========================================================================
_CHANGELOG_FILES = ("HISTORY.md", "CHANGELOG.md", "CHANGES.md", "history.md", "changelog.md")
_CHANGELOG_CACHE = {}  # {repo_key: (timestamp, result)}
_CHANGELOG_CACHE_TTL = 3600
_CHANGELOG_RAW_LIMIT = 20000
_CHANGELOG_BODY_LIMIT = 8000
_CHANGELOG_HEADING_RE = re.compile(r"^\s{0,3}(#{1,4})\s+(.*?)\s*#*\s*$")
_VERSION_IN_TEXT_RE = re.compile(r"v?(\d+\.\d+\.\d+)")


def _parse_changelog_sections(text):
    """마크다운 제목에 버전(예: '## [2.48.0] - 2026-09-23', '# v1.2.3')이 있는 구간을
    버전별 섹션으로 나눈다. 버전이 없는 하위 제목(### Added 등)은 본문에 포함하고,
    같은 수준 이상의 버전 없는 제목(## Unreleased 등)을 만나면 섹션을 닫는다."""
    sections = []
    current = None
    in_fence = False
    for line in (text or "").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _CHANGELOG_HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            vm = _VERSION_IN_TEXT_RE.search(m.group(2))
            if vm:
                current = {"version": vm.group(1), "title": m.group(2).strip(), "level": level, "body": []}
                sections.append(current)
                continue
            if current is not None and level <= current["level"]:
                current = None
                continue
        if current is not None:
            current["body"].append(line)
    for sec in sections:
        sec["body"] = "\n".join(sec["body"]).strip()[:_CHANGELOG_BODY_LIMIT]
        sec.pop("level", None)
    return sections


def _select_changelog_range(entries, installed_version, remote_version):
    """설치 버전 초과 ~ 원격 버전 이하 구간만 고른다. 미설치면 최근 10개,
    이미 최신이라 구간이 비면 최근 5개를 참고용으로 돌려준다(in_range=False)."""
    lo = _version_tuple(installed_version)
    hi = _version_tuple(remote_version)
    versioned = [e for e in entries if _version_tuple(e.get("version"))]
    versioned.sort(key=lambda e: _version_tuple(e["version"]), reverse=True)
    if lo is None:
        return versioned[:10], False
    picked = [
        e for e in versioned
        if _version_tuple(e["version"]) > lo and (hi is None or _version_tuple(e["version"]) <= hi)
    ]
    if picked:
        return picked, True
    return versioned[:5], False


def _fetch_changelog(url, token, gitea_tokens):
    """저장소에서 changelog 파일 → Releases 순서로 변경 내용을 가져온다(1시간 캐시).
    반환: {source: file|releases|none, file, entries[], raw, repo_url, error}"""
    clean_url, _u, _p = _extract_url_credentials(url)
    host, owner, repo = _parse_repo_url(clean_url)
    if not host or not owner or not repo:
        return {"source": "none", "entries": [], "error": "저장소 주소를 해석하지 못했습니다."}
    is_github = _is_github_host(host)
    key = ("%s/%s" % (owner, repo)) if is_github else ("gitea:%s/%s/%s" % (host, owner, repo))
    cached = _CHANGELOG_CACHE.get(key)
    if cached and time.time() - cached[0] < _CHANGELOG_CACHE_TTL:
        return cached[1]

    result = {"source": "none", "entries": [], "repo_url": clean_url}
    try:
        if is_github:
            eff_token = _effective_github_token(url, token)
            branch = _fetch_description_info(owner, repo, eff_token).get("default_branch") or "main"

            def get_file(fname):
                return _http_get_text(
                    "https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner, repo, branch, fname), eff_token
                )

            def get_releases():
                return _http_get_json(
                    "https://api.github.com/repos/%s/%s/releases?per_page=20" % (owner, repo), eff_token
                )
        else:
            gitea_cfg = _effective_gitea_cfg(url, gitea_tokens)
            scheme = _url_scheme(clean_url)
            branch = _gitea_fetch_description_info(host, owner, repo, gitea_cfg, scheme).get("default_branch") or "main"

            def get_file(fname):
                return _gitea_get_text(
                    host, "/api/v1/repos/%s/%s/raw/%s/%s" % (owner, repo, branch, fname), gitea_cfg, scheme
                )

            def get_releases():
                return _gitea_get_json(host, "/api/v1/repos/%s/%s/releases?limit=20" % (owner, repo), gitea_cfg, scheme)

        for fname in _CHANGELOG_FILES:
            try:
                text = get_file(fname)
            except Exception:
                continue
            if not text or not text.strip():
                continue
            result.update({"source": "file", "file": fname, "entries": _parse_changelog_sections(text)})
            if not result["entries"]:
                # 버전 제목 규칙을 따르지 않는 파일 — 앞부분을 그대로 보여준다
                result["raw"] = text[:_CHANGELOG_RAW_LIMIT]
            break

        if result["source"] == "none":
            try:
                releases = get_releases() or []
            except Exception:
                releases = []
            entries = []
            for rel in releases if isinstance(releases, list) else []:
                if rel.get("draft"):
                    continue
                tag = str(rel.get("tag_name") or "")
                vm = _VERSION_IN_TEXT_RE.search(tag) or _VERSION_IN_TEXT_RE.search(str(rel.get("name") or ""))
                if not vm:
                    continue
                entries.append({
                    "version": vm.group(1),
                    "title": str(rel.get("name") or tag),
                    "body": str(rel.get("body") or "").strip()[:_CHANGELOG_BODY_LIMIT],
                    "date": rel.get("published_at") or rel.get("created_at"),
                    "url": rel.get("html_url"),
                })
            if entries:
                result.update({"source": "releases", "entries": entries})
    except urllib.error.HTTPError as exc:
        result["error"] = _github_api_error_message(exc, bool(token)) if is_github else "HTTP %s" % exc.code
    except Exception as exc:
        result["error"] = str(exc)

    if not result.get("error"):
        _CHANGELOG_CACHE[key] = (time.time(), result)
    return result


# ========================================================================
# [PATCH-4] 설치 계획(폴더/클래스 id 결정 + 충돌 감지)과 원자적 폴더 교체.
# Git(GitHub/Gitea) 설치와 압축 파일 설치가 모두 이 두 함수를 공유한다.
# ========================================================================
_RESERVED_FOLDERS = ("base", "__pycache__", "plugin_manager")


def _read_class_id(plugin_dir):
    """설치 대상 소스에서 provider 클래스의 id를 AST로만(코드 실행 없이) 읽는다."""
    try:
        fnames = sorted(os.listdir(plugin_dir))
    except Exception:
        return None
    for fname in fnames:
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
                target_names = []
                if isinstance(stmt, ast.Assign):
                    target_names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    target_names = [stmt.target.id]
                if "id" not in target_names or stmt.value is None:
                    continue
                try:
                    value = ast.literal_eval(stmt.value)
                except Exception:
                    continue
                if isinstance(value, str) and _is_valid_class_id(value):
                    return value.strip()
    return None


def _registry_url_for(folder):
    return next((u for pid, u in _load_github_registry_entries() if pid == folder), None)


def _same_repo_owner(url_a, url_b):
    """두 저장소 주소가 같은 호스트·owner를 가리키는지. 판단할 수 없으면 True(막지 않음)."""
    ha, oa, _ra = _parse_repo_url(url_a)
    hb, ob, _rb = _parse_repo_url(url_b)
    if not (ha and oa and hb and ob):
        return True
    return (ha.lower(), oa.lower()) == (hb.lower(), ob.lower())


def _plan_install(src_root, repo_hint, existing_folder=None, source_url=None):
    """설치할 폴더명과 클래스 id를 정하고 가이드 §1의 id 충돌을 검사한다.
    반환: (folder, class_id, is_new, error_message)

    - 업데이트(existing_folder 지정): 기존 폴더를 그대로 쓴다(폴더명 변경 없음).
    - 이미 설치된 같은 플러그인(저장소 이름 변형 또는 같은 클래스 id)이 있으면 그 폴더.
    - 신규 설치: 클래스 id가 폴더명으로 쓸 수 있는 형식이면 클래스 id, 아니면
      (예: leeyj.spotify_mood) 저장소 이름을 폴더명으로 쓴다.
    - 다른 폴더가 같은 클래스 id를 쓰거나, 같은 폴더를 다른 저장소(호스트/owner)가
      점유하고 있으면 설치를 거부한다."""
    class_id = _read_class_id(src_root)
    if not class_id:
        return None, None, False, (
            "플러그인 클래스의 id를 읽지 못했습니다 — BaseMetadataProvider 상속 클래스에 "
            "id = \"...\" 형태의 문자열 id가 있어야 합니다."
        )

    folder = None
    if existing_folder and _PLUGIN_ID_RE.match(existing_folder) and _is_installed(existing_folder):
        folder = existing_folder
    else:
        if repo_hint:
            folder = _resolve_installed_folder(repo_hint)
        if not folder:
            folder = _find_folder_by_class_id(class_id)
        if not folder:
            if _PLUGIN_ID_RE.match(class_id):
                folder = class_id
            else:
                folder = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_hint or class_id).strip("_")

    if not folder or not _PLUGIN_ID_RE.match(folder):
        return None, None, False, "설치 폴더명을 정하지 못했습니다(영문/숫자/_- 만 허용): %r" % folder
    if folder in _RESERVED_FOLDERS or class_id in _RESERVED_FOLDERS:
        return None, None, False, "시스템 예약어 또는 핵심 플러그인은 덮어쓸 수 없습니다: %s" % folder

    # plugin_board 자신은 공식 저장소에서 온 소스로만 교체한다(동명 포크·압축 파일로
    # 관리 도구 자체를 덮어쓰는 것을 막는다).
    if folder == "plugin_board" or class_id == "plugin_board":
        if not source_url or not _same_repo_owner(source_url, SELF_REPO_URL):
            return None, None, False, "plugin_board는 공식 저장소(%s)에서만 설치·업데이트할 수 있습니다." % SELF_REPO_URL

    other = _find_folder_by_class_id(class_id, exclude=folder)
    if other:
        return None, None, False, (
            "id 충돌: 같은 id('%s')의 플러그인이 이미 '%s' 폴더에 설치되어 있습니다. "
            "기존 플러그인을 먼저 삭제하거나, 서로 다른 id를 쓰는지 확인해주세요." % (class_id, other)
        )

    is_new = not _is_installed(folder)
    if not is_new:
        existing_cid = _class_id_for_folder(folder)
        if existing_cid.replace("-", "_") != class_id.replace("-", "_"):
            return None, None, False, (
                "id 충돌: '%s' 폴더에는 다른 플러그인(id='%s')이 설치되어 있어 id='%s'로 "
                "덮어쓸 수 없습니다." % (folder, existing_cid, class_id)
            )
        if source_url and not existing_folder:
            registered = _registry_url_for(folder)
            if registered and not _same_repo_owner(registered, source_url):
                clean_registered, _u, _p = _extract_url_credentials(registered)
                return None, None, False, (
                    "id 충돌: '%s'는 다른 저장소(%s)에서 설치된 플러그인입니다. 같은 이름의 다른 "
                    "저장소로 덮어쓰지 않도록 설치를 중단했습니다. 저장소를 옮긴 것이라면 "
                    "'Git 주소 변경'을 먼저 사용해주세요." % (folder, clean_registered)
                )
    return folder, class_id, is_new, None


def _staging_dir():
    return os.path.join(_plugins_root_dir(), "data", "plugin_board", "_staging")


def _install_dir_atomically(src_root, folder, class_id, db_type, is_new, ignore=None, origin=None):
    """검증을 통과한 소스로 plugins/metadata/{folder}를 교체한다.
    스테이징에 먼저 복사 → 기존 폴더를 백업으로 이동 → 새 폴더를 이동 → (신규면)
    활성화 → hot reload → 로드 검증. 로드 검증이 명확히 실패하면 새 폴더를 지우고
    백업을 되돌린다. 스테이징은 plugins/data 아래(= plugins/metadata와 같은 볼륨일
    가능성이 높은 위치)에 둬서 이동이 가급적 rename으로 끝나게 한다.
    반환: (성공 여부, 추가 안내 문구 또는 실패 사유)"""
    target = _safe_join(_plugins_metadata_dir(), folder)
    os.makedirs(_staging_dir(), exist_ok=True)
    work = tempfile.mkdtemp(prefix="swap_", dir=_staging_dir())
    staged = os.path.join(work, "new")
    backup = os.path.join(work, "backup")
    had_backup = False
    action = "install" if is_new else "update"
    try:
        shutil.copytree(src_root, staged, ignore=ignore)
        from_version = _local_version(folder) if os.path.isdir(target) else None
        to_version = _version_in_dir(staged)
        # [PATCH-5] 교체 직전에 기존 폴더와 새 소스를 비교해 변경 파일을 요약한다
        files = None
        try:
            if os.path.isdir(target):
                files = _diff_summary(target, staged)
            else:
                files = {"counts": {"added": len(_walk_plugin_files(staged)), "removed": 0, "modified": 0}}
        except Exception:
            files = None
        if os.path.isdir(target):
            shutil.move(target, backup)
            had_backup = True
        try:
            shutil.move(staged, target)
        except Exception:
            if had_backup and not os.path.exists(target):
                shutil.move(backup, target)
            raise

        if is_new:
            _toggle_plugin_enabled(folder, "1", db_type, reload=False)
        reloaded = _try_hot_reload(class_id, folder)
        loaded = _verify_plugin_loaded(class_id)

        if reloaded and loaded is False:
            shutil.rmtree(target, ignore_errors=True)
            if had_backup:
                shutil.move(backup, target)
            _try_hot_reload(class_id, folder)
            fail_msg = (
                "'%s'(id=%s) 플러그인이 교체 후 로드되지 않아 %s. 서버 로그에서 "
                "로드 오류를 확인해주세요." % (
                    folder, class_id, "이전 버전으로 되돌렸습니다" if had_backup else "설치를 취소했습니다"
                )
            )
            _record_history(action, folder, class_id, result="rolled_back", from_version=from_version,
                            to_version=to_version, origin=origin, message=fail_msg, files=files)
            return False, fail_msg
        note = ""
        if not reloaded or loaded is None:
            note = " (코어의 즉시 반영 여부를 확인할 수 없어 서버 재시작 후 적용될 수 있습니다)"
        _record_history(action, folder, class_id, result="success", from_version=from_version,
                        to_version=to_version, origin=origin, message=note.strip(" ()") or None, files=files)
        return True, note
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _install_from_source_dir(src_root, repo_hint, existing_folder, source_url, db_type, origin_label,
                             ignore=None):
    """압축이 풀린 소스 폴더 하나를 계획 → 정적 검증 → 원자적 교체까지 처리한다.
    반환: (성공 여부, 메시지, 설치 폴더명)"""
    action = "update" if existing_folder else "install"
    to_version = _version_in_dir(src_root)
    folder, class_id, is_new, err = _plan_install(src_root, repo_hint, existing_folder, source_url)
    if err:
        _record_history(action, existing_folder or repo_hint, _read_class_id(src_root), result="failed",
                        to_version=to_version, origin=origin_label, message=err)
        return False, err, None

    source_ok, source_checks = _validate_plugin_source(src_root, folder)
    if not source_ok:
        failed_items = ["- %s: %s" % (c["name"], c["detail"]) for c in source_checks if not c.get("ok")]
        fail_msg = (
            "플러그인 검증 실패 — 설치를 중단했습니다(기존 설치는 변경되지 않음):\n"
            + "\n".join(failed_items)
        )
        _record_history("install" if is_new else "update", folder, class_id, result="failed",
                        from_version=None if is_new else _local_version(folder), to_version=to_version,
                        origin=origin_label, message=fail_msg)
        return False, fail_msg, None

    ok, note = _install_dir_atomically(src_root, folder, class_id, db_type, is_new, ignore=ignore,
                                       origin=origin_label)
    if not ok:
        return False, note, None

    for cache in (_DESC_CACHE, _VERSION_CACHE):
        for key in [k for k in cache if k.endswith("/" + folder) or (repo_hint and k.endswith("/" + repo_hint))]:
            cache.pop(key, None)
    _save_disk_cache()

    new_version = _local_version(folder) or "?"
    passed = [c["name"] for c in source_checks if c.get("ok") and not c.get("warn")]
    warns = [re.sub(r"^경고:\s*", "", c["detail"]) for c in source_checks if c.get("warn")]
    result_msg = "'%s'(id=%s) %s 완료 (%s, 버전 v%s, 검증 통과: %s)%s" % (
        folder, class_id, "신규 설치 및 활성화" if is_new else "업데이트", origin_label,
        new_version, ", ".join(passed), note,
    )
    if warns:
        result_msg += " 경고: " + "; ".join(warns)
    return True, result_msg, folder


def _install_or_update(owner, repo, token=None, db_type="general", existing_folder=None):
    """저장소 zip을 받아 검증 후 설치 폴더를 통째로 교체한다(전체 재다운로드 방식).
    [PATCH-3] 정적 검증 통과가 필수, [PATCH-4] 폴더 결정·id 충돌 감지·원자적 교체는
    _install_from_source_dir에 위임한다. 반환: (성공 여부, 메시지, 설치 폴더명)"""
    _validate_plugin_id(repo)

    # default_branch는 카드 목록을 불러올 때(_fetch_description_info, 24시간 캐시)
    # 이미 조회해둔 값을 그대로 재사용한다(무인증 rate limit 절약).
    info = _fetch_description_info(owner, repo, token)
    default_branch = info.get("default_branch")
    source_url = "https://github.com/%s/%s" % (owner, repo)

    last_error = None
    for branch in _candidate_branches(default_branch):
        zip_url = "https://codeload.github.com/%s/%s/zip/refs/heads/%s" % (owner, repo, branch)
        tmp_dir = tempfile.mkdtemp(prefix="plugin_board_")
        try:
            zip_path = os.path.join(tmp_dir, "src.zip")
            _download_zip(zip_url, zip_path, token)

            extract_dir = os.path.join(tmp_dir, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            _extract_zip_safe(zip_path, extract_dir)
            src_root = _find_extracted_root(extract_dir)

            # 최소한의 신원 확인: 저장소 이름(하이픈↔언더스코어 변형 포함) 또는 클래스
            # id와 같은 메인 모듈 파일이 있어야 BookOasis 플러그인 저장소로 간주한다.
            if not _find_module_file(src_root, repo) and not _find_module_file(src_root, _read_class_id(src_root) or repo):
                return False, (
                    "'%s.py'(또는 '%s.py') 파일을 찾지 못했습니다 — BookOasis 플러그인 "
                    "저장소가 맞는지, 메인 모듈 파일명이 저장소 이름과 같은지 확인해주세요."
                    % (repo, repo.replace("-", "_"))
                ), None

            return _install_from_source_dir(
                src_root, repo, existing_folder, source_url, db_type,
                "GitHub %s/%s, 브랜치 %s" % (owner, repo, branch),
            )
        except urllib.error.HTTPError as exc:
            last_error = _github_api_error_message(exc, bool(token))
        except Exception as exc:
            last_error = str(exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return False, "설치/업데이트 실패: %s" % (last_error or "알 수 없는 오류"), None


def _install_or_update_gitea(host, owner, repo, gitea_cfg, scheme="https", db_type="general",
                             existing_folder=None):
    """Gitea 저장소를 설치/업데이트한다. GitHub용 _install_or_update와 동일한
    전체 재다운로드 방식이며 다운로드/조회 경로만 Gitea API를 쓴다.
    반환: (성공 여부, 메시지, 설치 폴더명)"""
    _validate_plugin_id(repo)

    desc_info = _gitea_fetch_description_info(host, owner, repo, gitea_cfg, scheme)
    default_branch = desc_info.get("default_branch")
    source_url = "%s://%s/%s/%s" % (scheme, host, owner, repo)

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

            if not _find_module_file(src_root, repo) and not _find_module_file(src_root, _read_class_id(src_root) or repo):
                return False, (
                    "'%s.py'(또는 '%s.py') 파일을 찾지 못했습니다 — BookOasis 플러그인 "
                    "저장소가 맞는지, 메인 모듈 파일명이 저장소 이름과 같은지 확인해주세요."
                    % (repo, repo.replace("-", "_"))
                ), None

            return _install_from_source_dir(
                src_root, repo, existing_folder, source_url, db_type,
                "Gitea %s, 브랜치 %s" % (host, branch),
            )
        except urllib.error.HTTPError as exc:
            hint = " " + _gitea_auth_error_hint(gitea_cfg) if exc.code in (401, 403) else ""
            last_error = "HTTP %s%s" % (exc.code, hint)
        except Exception as exc:
            last_error = str(exc)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return False, "설치/업데이트 실패: %s" % (last_error or "알 수 없는 오류"), None


def _install_or_update_from_url(url, token, gitea_tokens=None, db_type="general", existing_folder=None):
    """URL의 호스트를 보고 GitHub/Gitea 중 맞는 설치 엔진으로 위임한다.
    URL에 https://아이디:비밀번호@host/... (또는 https://토큰@host/...) 형식으로
    자격증명이 직접 포함돼 있으면 그 값으로 인증한다. 없으면 gitea_tokens(설정에
    등록해둔 {호스트: 토큰})에서 이 호스트에 맞는 토큰을 찾아 폴백으로 쓴다.
    설치에 성공하면 자격증명이 담긴 URL 그대로 github.txt에 **실제 설치 폴더명**을
    키로 기록한다(파일 권한 600). existing_folder는 업데이트 대상 폴더다."""
    # [PATCH-6] 자격증명 없는 Gitea 주소면 설정에 저장된 계정을 자동으로 넣는다
    url, injected = _inject_gitea_credentials(url, gitea_tokens)
    clean_url, url_username, url_password = _extract_url_credentials(url)
    host, owner, repo = _parse_repo_url(clean_url)
    if not host or not owner or not repo:
        if re.match(r"^https?://[^/]+/[^/]+/?$", clean_url or ""):
            return False, (
                "저장소가 아니라 소유자 주소입니다(%s). 이 소유자의 플러그인을 모두 목록에 표시하려면 "
                "플러그인게시판 설정(⚙) → Gitea 서버의 '소유자'에 추가하세요. 설치는 저장소 주소"
                "(https://서버/소유자/저장소)로 해주세요." % _scrub_credentials(clean_url)
            )
        return False, "Git 저장소 주소를 해석하지 못했습니다: %s" % _scrub_credentials(url)

    if _is_github_host(host):
        effective_token = url_password or url_username or token
        ok, msg, folder = _install_or_update(
            owner, repo, effective_token, db_type=db_type, existing_folder=existing_folder
        )
    else:
        gitea_cfg = _effective_gitea_cfg(url, gitea_tokens)
        scheme = _url_scheme(clean_url)  # http로 준 주소는 http로 그대로 설치(523 방지)
        ok, msg, folder = _install_or_update_gitea(
            host, owner, repo, gitea_cfg, scheme, db_type=db_type, existing_folder=existing_folder
        )

    if ok and folder:
        _remember_repo_install(url, plugin_id=folder)
        if injected:
            msg += " (설정에 저장된 %s 계정으로 인증해 등록했습니다)" % host
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
            "key": "GITEA_TOKENS",
            "label": "Gitea 서버",
            "type": "password",
            "required": False,
            "description": (
                "비공개 저장소가 있는 Gitea 서버의 주소·아이디·비밀번호·읽기 토큰을 저장합니다. "
                "저장해두면 https://서버/소유자/저장소 처럼 자격증명 없는 주소로 설치해도 자동으로 "
                "인증하고, https://아이디:비밀번호@서버/... 형태로 등록합니다(비밀번호를 바꾸면 "
                "등록된 주소도 자동 갱신). 토픽 검색·버전 확인 같은 API 호출에는 읽기 토큰을 "
                "우선 사용하므로, 토큰은 repository 읽기 권한으로 발급하는 것을 권장합니다. "
                "주소 옆 '연결 테스트'로 접속·인증·토픽 검색 결과를 바로 확인할 수 있습니다."
            ),
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
            "key": "CATALOG_TOPIC",
            "label": "카탈로그 토픽 (선택)",
            "type": "text",
            "required": False,
            "description": (
                "이 토픽이 달린 저장소만 따로 모아보는 '카탈로그' 필터 탭을 추가합니다. "
                "예: bookoasis-catalog. 빈 값이면 카탈로그 탭이 표시되지 않습니다. 여기에 "
                "입력한 토픽은 발견 대상 토픽에도 자동으로 포함되므로(추가 발견 토픽에 "
                "따로 적지 않아도 됩니다), 'bookoasis-plugin' 토픽이 없는 저장소도 이 "
                "토픽만 달아두면 발견·카탈로그 탭 표시가 모두 가능합니다."
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
        "order": 11,
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
            "HISTORY.md",
        ],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # ------------------------------------------------------------------
    def search(self, db_type, query):
        return {"success": True, "items": []}

    # ------------------------------------------------------------------
    # [PATCH-4] 범용 플러그인 RPC — API 문서의 "도서 컨텍스트 메뉴 플러그인 액션 API"는
    # plugin_id + action_id + context를 그대로 run_context_menu_action()에 넘겨주므로,
    # 설정/관리 화면의 백엔드 호출 채널로 쓰는 것이 문서화된 표준 패턴이다
    # (예전의 /api/media/books/0/apply-metadata 우회 호출을 대체).
    # 실제 도서 우클릭 메뉴에는 아무 항목도 노출하지 않는다.
    # 이 라우트는 @login_required라 관리자 확인은 _dispatch_apply가 직접 한다.
    # ------------------------------------------------------------------
    def get_context_menu_items(self, db_type, context):
        return []

    def run_context_menu_action(self, db_type, action_id, context):
        item_data = dict(context) if isinstance(context, dict) else {}
        item_data["action"] = action_id
        try:
            ok, payload = self._dispatch_apply(db_type, 0, item_data)
        except Exception as exc:
            return {"success": False, "error": "예상치 못한 오류가 발생했습니다: %s" % exc}
        if ok:
            # get_config는 dict를 돌려준다 — 프런트는 예전과 같이 message 필드로 받는다
            return {"success": True, "message": payload}
        return {"success": False, "error": payload}

    # ------------------------------------------------------------------
    # 카드의 버튼들이 호출하는 액션 엔드포인트.
    # item_data = {
    #   "action": "install_git" | "update" | "toggle" | "delete",
    #   "plugin_id": ..., "git_url": ..., "enabled": "0" | "1"  (toggle 전용)
    # }
    # ------------------------------------------------------------------
    def apply(self, db_type, book_id, item_data):
        """하위 호환용 진입점(구버전 script.js 또는 컨텍스트 메뉴 RPC가 없는 코어).
        새 프런트는 run_context_menu_action()을 쓴다. 실제 처리는 _dispatch_apply에
        위임하고, 예상치 못한 예외가 500으로 새어나가지 않도록 안전망 역할만 한다."""
        try:
            return self._dispatch_apply(db_type, book_id, item_data)
        except Exception as exc:
            return False, "예상치 못한 오류가 발생했습니다: %s" % exc

    def _dispatch_apply(self, db_type, book_id, item_data):
        if not isinstance(item_data, dict):
            return False, "유효하지 않은 요청 데이터 형식입니다."

        action = str(item_data.get("action", "")).strip().lower()
        plugin_id = str(item_data.get("plugin_id", "")).strip()

        # [PATCH-4] 모든 액션은 관리자 전용이다. 새 RPC 경로는 @login_required라서
        # 라우트가 관리자 여부를 걸러주지 않으므로 여기서 반드시 확인한다(fail-closed).
        # refresh_list도 포함한다 — 캐시를 비우면 GitHub API 재조회가 일어나므로,
        # 비관리자가 반복 호출해 서버의 rate limit을 소진시키지 못하게 한다.
        if not _is_admin_session():
            return False, "관리자만 사용할 수 있는 기능입니다."

        # [PATCH-5] 이력 기록용 요청 문맥 — 자동 업데이트는 프런트가 auto=true로 보낸다
        _HISTORY_CTX.mode = "auto" if str(item_data.get("auto", "")).lower() in ("1", "true") else "manual"
        _HISTORY_CTX.recorded = False

        if action == "get_history":
            try:
                limit = max(1, min(int(item_data.get("limit") or 200), 1000))
            except (TypeError, ValueError):
                limit = 200
            class_id = str(item_data.get("class_id", "")).strip() or None
            if plugin_id and not class_id and _PLUGIN_ID_RE.match(plugin_id) and _is_installed(plugin_id):
                class_id = _class_id_for_folder(plugin_id)
            return True, {"entries": _read_history(plugin_id or None, class_id, limit=limit)}

        if action == "get_changelog":
            cfg = self.get_plugin_config(db_type, default={})
            token = cfg.get("GITHUB_TOKEN") or None
            gitea_tokens = _parse_gitea_tokens_cfg(cfg.get("GITEA_TOKENS"))
            url = None
            if plugin_id:
                url = _registry_url_for(plugin_id)
                if not url and plugin_id == "plugin_board":
                    url = SELF_REPO_URL
            if not url:
                url = str(item_data.get("git_url", "")).strip() or None
            if not url:
                return True, {"source": "none", "entries": [],
                              "error": "이 플러그인의 원본 저장소 주소를 알 수 없습니다(로컬 전용 플러그인)."}
            installed_version = _local_version(plugin_id) if plugin_id and _PLUGIN_ID_RE.match(plugin_id) \
                and _is_installed(plugin_id) else None
            remote_version = str(item_data.get("remote_version") or "").strip().lstrip("vV") or None
            data = dict(_fetch_changelog(url, token, gitea_tokens))
            entries, in_range = _select_changelog_range(data.get("entries") or [], installed_version, remote_version)
            data.update({
                "entries": entries,
                "in_range": in_range,
                "installed_version": installed_version,
                "remote_version": remote_version,
            })
            return True, data

        if action == "test_gitea":
            cfg = self.get_plugin_config(db_type, default={})
            extra_topics = [t.strip() for t in str(cfg.get("EXTRA_DISCOVERY_TOPICS") or "").split(",") if t.strip()]
            catalog_topic = str(cfg.get("CATALOG_TOPIC") or "").strip()
            topics = list(dict.fromkeys(([catalog_topic] if catalog_topic else []) + extra_topics + DISCOVERY_TOPICS))
            return True, _test_gitea_server(item_data, _parse_gitea_tokens_cfg(cfg.get("GITEA_TOKENS")), topics)

        if action in ("install_git", "update", "install_zip"):
            ok, msg = self._dispatch_install(db_type, action, plugin_id, item_data)
            if not ok and not getattr(_HISTORY_CTX, "recorded", False):
                # 다운로드·압축 해제처럼 설치 엔진에 들어가기 전에 실패한 경우도 남긴다
                if action == "install_zip":
                    target = str(item_data.get("filename", "")).strip() or None
                elif action == "update":
                    target = plugin_id or None
                else:
                    _h, _o, target = _parse_repo_url(str(item_data.get("git_url", "")))
                _record_history("update" if action == "update" else "install", target,
                                result="failed", origin=action, message=msg)
            return ok, msg

        return self._dispatch_other(db_type, action, plugin_id, item_data)

    def _dispatch_install(self, db_type, action, plugin_id, item_data):
        """설치 계열 액션(압축 파일 / Git URL)."""
        if action == "install_zip":
            # 액션 이름은 하위 호환을 위해 유지하지만, zip 외에 tar 계열(.tar/.tar.gz/
            # .tar.bz2/.tar.xz)과 7z(라이브러리가 있으면)도 파일명 확장자로 판별해 처리한다.
            zip_data = str(item_data.get("zip_data", "")).strip()
            filename = str(item_data.get("filename", "")).strip()
            if not zip_data:
                return False, "zip_data가 필요합니다."
            cfg = self.get_plugin_config(db_type, default={})
            return _install_from_archive(
                zip_data, filename, db_type, gitea_tokens=_parse_gitea_tokens_cfg(cfg.get("GITEA_TOKENS"))
            )

        return self._dispatch_git_install(db_type, action, plugin_id, item_data)

    def _dispatch_other(self, db_type, action, plugin_id, item_data):
        """조회·관리 계열 액션(설정 조회, 캐시, 토글, 삭제, 주소 관리)."""
        if action == "get_config":
            # /api/media/metadata/plugins/manage 응답의 config 필드만 믿지 않고,
            # 가이드 문서(§4)에 명시된 저장 위치(settings 테이블의
            # PLUGIN_CONFIG_{id}, JSON 문자열)를 DB 게이트웨이로 직접 조회한다.
            # 어떤 플러그인이 설정을 저장했는데도 /manage가 그 값을 안 돌려주는
            # 경우에 대비한 더 확실한(authoritative) 조회 경로다.
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            # 설정 키는 클래스 id 기준이다 — 폴더명이 넘어오면 클래스 id로 바꾼다
            config_id = plugin_id
            if _PLUGIN_ID_RE.match(plugin_id) and _is_installed(plugin_id):
                config_id = _class_id_for_folder(plugin_id)
            try:
                gateway = self.get_db_gateway(db_type)
            except Exception as exc:
                return False, "DB 게이트웨이를 가져오지 못했습니다: %s" % exc
            try:
                raw = gateway.get_setting("PLUGIN_CONFIG_%s" % config_id, default=None)
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
            _CHANGELOG_CACHE.clear()
            _clear_shared_cache(self)
            _save_disk_cache()
            return True, "플러그인 목록과 버전 정보를 새로 불러옵니다."

        if action == "reset_cache":
            # [신규] 목록이 이상하게 꼬여 있을 때(중복 카드, 옛 정보가 계속
            # 남는 등) 쓰는 더 강한 초기화 — 메모리 캐시만 비우는 refresh_list와
            # 달리 .cache.json 파일 자체를 지운다. 관리자 전용(위 admin 체크에
            # 이미 포함되어 있음).
            _clear_shared_cache(self)
            _CHANGELOG_CACHE.clear()
            return _reset_disk_cache()

        if action == "toggle":
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            enabled_val = str(item_data.get("enabled", "1")).strip()
            ok, msg = _toggle_plugin_enabled(plugin_id, enabled_val, db_type)
            if ok:
                _record_history("enable" if enabled_val == "1" else "disable", plugin_id,
                                _class_id_for_folder(plugin_id) if _is_installed(plugin_id) else None,
                                from_version=_local_version(plugin_id))
            return ok, msg

        if action == "delete":
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            return _delete_plugin(plugin_id)

        if action == "update_url":
            # [신규] 등록된 Git 주소가 바뀐(저장소 이름/owner/호스트 이전 등) 경우,
            # 재설치 없이 "이 plugin_id는 이제 이 URL을 본다"고만 갱신한다.
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            new_git_url = str(item_data.get("git_url", "")).strip()
            if not new_git_url:
                return False, "새 git_url이 필요합니다."
            cfg = self.get_plugin_config(db_type, default={})
            new_git_url, injected = _inject_gitea_credentials(
                new_git_url, _parse_gitea_tokens_cfg(cfg.get("GITEA_TOKENS"))
            )
            ok, msg = _update_registered_repo_url(plugin_id, new_git_url)
            if ok and injected:
                msg += " (설정에 저장된 계정을 주소에 자동으로 포함했습니다)"
            if ok:
                clean_new, _u, _p = _extract_url_credentials(new_git_url)
                _record_history("url_changed", plugin_id, message="새 주소: %s" % clean_new)
            return ok, msg

        if action == "unregister":
            # [신규] 원본 저장소가 삭제되는 등으로 더 이상 추적할 수 없을 때, 설치된
            # 플러그인 파일은 그대로 두고 github.txt 등록만 제거한다(업데이트 확인
            # 대상에서만 빠진다 — plugins/metadata의 실제 파일은 건드리지 않음).
            if not plugin_id:
                return False, "plugin_id가 필요합니다."
            ok, msg = _unregister_repo(plugin_id)
            if ok:
                _record_history("unregister", plugin_id)
            return ok, msg

        return False, "지원하지 않는 액션입니다: %s" % action

    def _dispatch_git_install(self, db_type, action, plugin_id, item_data):
        if action in ("install_git", "update"):
            cfg = self.get_plugin_config(db_type, default={})
            token = cfg.get("GITHUB_TOKEN") or None
            gitea_tokens = _parse_gitea_tokens_cfg(cfg.get("GITEA_TOKENS"))

            git_url = str(item_data.get("git_url", "")).strip()
            if not git_url and plugin_id:
                # git_url 없이 plugin_id만 온 경우(업데이트 버튼 등), github.txt
                # 레지스트리(GitHub/Gitea 어느 쪽이든, 자격증명이 담겨 있을 수 있음)에서
                # plugin_id로 등록된 주소를 찾는다. 등록 시점의 저장소 이름과 현재
                # plugin_id가 다를 수 있으므로(update_url로 갱신된 경우 등) URL을 다시
                # 파싱해 비교하지 않고, 레지스트리 자체의 1차 키(plugin_id)로 직접 찾는다.
                match = next(
                    (u for pid, u in _load_github_registry_entries() if pid == plugin_id),
                    None,
                )
                if match:
                    git_url = match
                elif plugin_id == "plugin_board":
                    # plugin_board 자신은 레지스트리에 없어도 공식 저장소로 업데이트한다
                    git_url = SELF_REPO_URL

            if not git_url:
                return False, (
                    "Git 저장소 정보를 확인할 수 없습니다. 원본 저장소 주소가 바뀌었다면 "
                    "'Git 주소 변경'으로 새 주소를 먼저 등록한 뒤 다시 시도해주세요."
                )

            # 업데이트는 카드의 plugin_id(=설치 폴더)를 그대로 교체 대상으로 지정한다.
            # 신규 설치는 폴더를 _plan_install이 클래스 id 기준으로 정한다.
            existing_folder = plugin_id if (action == "update" and plugin_id) else None
            return _install_or_update_from_url(
                git_url, token, gitea_tokens=gitea_tokens, db_type=db_type,
                existing_folder=existing_folder,
            )
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
        gitea_tokens = _parse_gitea_tokens_cfg(cfg.get("GITEA_TOKENS"))
        auto_update_enabled = bool(cfg.get("AUTO_UPDATE_ENABLED"))
        is_admin = _is_admin_session()
        _load_shared_cache(self)  # 다른 워커가 채운 캐시를 먼저 병합(Redis 미구성 시 무동작)

        try:
            gateway = self.get_db_gateway(db_type)
        except Exception:
            gateway = None

        def is_enabled_fn(plugin_id):
            # plugin_id는 설치 폴더명 — 코어의 활성화 키는 클래스 id 기준이다
            if gateway is None:
                return True
            try:
                class_id = _class_id_for_folder(plugin_id) if _is_installed(plugin_id) else plugin_id
                raw = gateway.get_setting("PLUGIN_ENABLED_%s" % class_id, default="1")
                if isinstance(raw, dict):
                    raw = raw.get("value", "1")
                return str(raw) == "1"
            except Exception:
                return True

        # plugin_board 자기 자신 조회, GitHub Topics 검색, 그리고 Gitea 서버들의
        # 토픽 검색까지 — 전부 서로 무관한 네트워크 요청이라 한꺼번에 동시에
        # 실행한다. 순차로 하면 서버 개수만큼 지연이 그대로 쌓인다(토픽 검색과
        # 같은 이유로 이미 겪었던 문제).
        extra_topics_raw = str(cfg.get("EXTRA_DISCOVERY_TOPICS") or "").strip()
        extra_topics = [t.strip() for t in extra_topics_raw.split(",") if t.strip()]
        catalog_topic = str(cfg.get("CATALOG_TOPIC") or "").strip()
        # 카탈로그 토픽은 검색 대상에도 포함시켜야, 기본 발견 토픽
        # (bookoasis-plugin)이 없이 카탈로그 토픽만 달아둔 저장소도 발견된다.
        # [PATCH-8] 설정한 토픽을 앞에 둔다(카탈로그 → 추가 발견 → 기본). 결과 병합 순서도 이를 따른다.
        all_topics = list(dict.fromkeys(([catalog_topic] if catalog_topic else []) + extra_topics + DISCOVERY_TOPICS))

        # Gitea 토픽 검색 대상 서버 = GITEA_TOKENS에 등록된 서버 + 이미 Git
        # URL로 설치/등록해둔 저장소(github.txt)의 호스트. 후자는 GITEA_TOKENS에
        # 토큰을 따로 등록해두지 않은 공개 저장소 서버라도, "이미 한 번 써본
        # (신뢰한) 서버"이므로 그 서버의 다른 플러그인도 자동으로 찾아볼 수
        # 있게 한다 — 매번 새 서버마다 토큰을 등록해야만 발견이 되는 건 아니다.
        # 인증 정보는 GITEA_TOKENS 항목이 있으면 그걸 쓰고, 없으면 등록된 URL
        # 자체에 담긴 자격증명(있다면)을, 그마저 없으면 인증 없이 시도한다.
        # [PATCH-6] 설정에 계정이 저장된 서버의 레지스트리 주소를 최신 자격증명으로 맞춘다
        if is_admin:
            try:
                _sync_registry_credentials(gitea_tokens)
            except Exception:
                pass
        registry_entries_all = _load_github_registry_entries()
        # {host: {"cfg": 인증, "scheme": http|https, "from_registry": 설치 이력이 있는 서버인지}}
        gitea_hosts_to_search = {
            host: {"cfg": _gitea_cfg_from_tokens_entry(entry), "scheme": entry.get("scheme") or "https",
                   "from_registry": False, "owners": list(entry.get("owners") or [])}
            for host, entry in gitea_tokens.items()
        }
        for _pid, _url in registry_entries_all:
            h, _o, _r = _parse_repo_url(_url)
            if not h or _is_github_host(h):
                continue
            h = h.lower()
            if h not in gitea_hosts_to_search:
                gitea_hosts_to_search[h] = {
                    "cfg": _effective_gitea_cfg(_url, gitea_tokens),
                    "scheme": _url_scheme(_url),
                    "from_registry": False,
                    "owners": [],
                }
            spec = gitea_hosts_to_search[h]
            spec["from_registry"] = True
            # [PATCH-7] 이 서버에서 설치한 적 있는 저장소의 소유자도 자동으로 스캔한다
            if _o and _o not in spec["owners"]:
                spec["owners"].append(_o)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2 + len(gitea_hosts_to_search)) as executor:
            self_future = executor.submit(
                _fetch_repo_entry, SELF_REPO_URL, token, is_enabled_fn, gitea_tokens=gitea_tokens
            )
            topics_future = executor.submit(_fetch_repos_by_topic, all_topics, token)
            gitea_topic_futures = {
                host: executor.submit(
                    _fetch_gitea_repos_for_host, host, spec["cfg"], spec["scheme"], all_topics,
                    spec.get("owners") or [],
                )
                for host, spec in gitea_hosts_to_search.items()
            }
            # plugin_board 자기 자신은 GitHub Topics 검색 결과와 무관하게 항상
            # 별도로 조회해 카드 목록 맨 앞에 고정한다("미검수" 표시 없이, 개발
            # 중인 버전도 항상 카드+업데이트 버튼으로 다룰 수 있도록).
            self_item = self_future.result()
            try:
                topic_repos = topics_future.result()
            except Exception:
                topic_repos = []
            gitea_topic_repos = {}
            gitea_topic_errors = {}
            for host, fut in gitea_topic_futures.items():
                try:
                    gitea_topic_repos[host] = fut.result()
                except Exception as exc:
                    gitea_topic_repos[host] = []
                    gitea_topic_errors[host] = str(exc)

        curated_ids = {self_item["id"]}

        # GitHub Topics 검색(+ 등록된 Gitea 서버별 토픽 검색)이 카드 목록의
        # 수집 경로다. 검증 없이 자동 노출되므로 "미검수" 표시를 유지한다.
        discovered_items = []

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
            # [PATCH-9] 이 서버가 Gitea 쪽에서 설치한 플러그인은 같은 이름의 GitHub 저장소가
            # 발견돼도 GitHub 카드로 대신하지 않는다(아래 Gitea 처리에서 카드가 만들어진다).
            gitea_tracked = set()
            for _pid, _url in registry_entries_all:
                _h, _o, _r = _parse_repo_url(_url)
                if _h and not _is_github_host(_h):
                    gitea_tracked.update(v.lower() for v in _name_variants(_pid) + _name_variants(_r))
            for repo_json in topic_repos:
                if str(repo_json.get("name") or "").lower() in gitea_tracked:
                    continue
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
                if len(discovered_items) >= _MAX_DISCOVERED_ITEMS:
                    break  # 안전장치 상한 — VERSION 필터를 통과한 저장소만 세므로 정상 목록은 잘리지 않는다
                seen_discovered_ids.add(item["id"])
                discovered_items.append(item)
        else:
            seen_discovered_ids = set()

        # Gitea 서버별 토픽 검색 결과도 같은 방식(버전 병렬 조회 → 노이즈 필터)으로
        # 처리해 같은 discovered_items 묶음에 합친다.
        for host, repo_list in gitea_topic_repos.items():
            if not repo_list:
                continue
            spec_h = gitea_hosts_to_search.get(host) or {}
            gitea_cfg_h = spec_h.get("cfg") or _gitea_cfg_from_tokens_entry(gitea_tokens.get(host))
            scheme_h = spec_h.get("scheme") or "https"
            host_item_count = 0
            version_specs_g = []
            for repo_json in repo_list:
                owner_login = ((repo_json.get("owner") or {}).get("login")) or ""
                repo_name = repo_json.get("name") or ""
                if owner_login and repo_name and repo_name not in (curated_ids | seen_discovered_ids):
                    version_specs_g.append((owner_login, repo_name, repo_json.get("default_branch")))

            version_map_g = {}
            if version_specs_g:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(version_specs_g))) as vexec:
                    vfuture_map = {
                        vexec.submit(_gitea_fetch_version_info, host, o, r, db, gitea_cfg_h, scheme_h): (o, r)
                        for (o, r, db) in version_specs_g
                    }
                    for vfut in concurrent.futures.as_completed(vfuture_map):
                        owner_repo_key = vfuture_map[vfut]
                        try:
                            version_map_g[owner_repo_key] = (vfut.result() or {}).get("remote_version")
                        except Exception:
                            version_map_g[owner_repo_key] = None

            for repo_json in repo_list:
                owner_login = ((repo_json.get("owner") or {}).get("login")) or ""
                repo_name = repo_json.get("name") or ""
                remote_version = version_map_g.get((owner_login, repo_name))
                item = _build_gitea_discovered_item(
                    host, repo_json, remote_version, is_enabled_fn, curated_ids | seen_discovered_ids
                )
                if not item:
                    continue
                if not item["installed"] and item["version_label"] == "—":
                    continue
                if host_item_count >= _MAX_GITEA_ITEMS_PER_HOST:
                    break  # 안전장치 상한 — VERSION 필터를 통과한 저장소만 센다
                host_item_count += 1
                seen_discovered_ids.add(item["id"])
                discovered_items.append(item)

        # Gitea 토픽 검색이 서버 단위로 완전히 실패했다면(인증 오류, API 경로
        # 불일치 등) "결과가 없다"와 구분되지 않게 조용히 숨기지 않고 에러
        # 카드로 노출한다 — 원인 파악이 최소한 가능해야 하므로. 관리자에게만
        # 의미 있는 정보라 admin이 아니면 카드를 만들지 않는다.
        if is_admin:
            for host, err_msg in gitea_topic_errors.items():
                discovered_items.append({
                    "id": "gitea-search-error:" + host,
                    "owner": "",
                    "title": "%s 토픽 검색 실패" % host,
                    "type": "other",
                    "type_label": TYPE_LABELS["other"],
                    "desc": "이 Gitea 서버에서 토픽 검색이 실패했습니다: %s" % err_msg,
                    "tags": [], "features": [], "version_label": "—",
                    "url": "%s://%s" % ((gitea_hosts_to_search.get(host) or {}).get("scheme", "https"), host),
                    "error": True,
                    "notice": True,
                    "installed": False, "installed_version": None, "has_update": False,
                    "has_config": False, "enabled": None,
                    "discovered": True, "gitea": True,
                })
            # [PATCH-6] 인증 없이 검색했는데 결과가 0개인 서버 — 이 서버에서 설치한 적이
            # 있으므로 플러그인이 있는 서버인데, 비공개 저장소라 안 보였을 가능성이 높다.
            # Gitea는 이 경우 오류 없이 빈 목록을 주므로 따로 알려주지 않으면 원인을 알 수 없다.
            for host, spec in gitea_hosts_to_search.items():
                if host in gitea_topic_errors or gitea_topic_repos.get(host):
                    continue
                if spec.get("from_registry") and (spec.get("cfg") or {}).get("source") == "none":
                    discovered_items.append({
                        "id": "gitea-search-hint:" + host,
                        "owner": "",
                        "title": "%s — 비공개 저장소가 검색되지 않았을 수 있음" % host,
                        "type": "other",
                        "type_label": TYPE_LABELS["other"],
                        "desc": (
                            "이 Gitea 서버를 인증 없이 조회해 공개 저장소만 확인됐고, 플러그인으로 "
                            "보이는 저장소가 하나도 없었습니다. 비공개 저장소라면 플러그인게시판 설정(⚙)의 "
                            "'Gitea 서버'에 이 서버의 아이디/비밀번호 또는 읽기 토큰을 등록한 뒤 "
                            "'연결 테스트'로 확인하고 목록을 새로고침하세요."
                        ),
                        "tags": [], "features": [], "version_label": "—",
                        "url": "%s://%s" % (spec.get("scheme", "https"), host),
                        "error": True,
                        "notice": True,
                        "installed": False, "installed_version": None, "has_update": False,
                        "has_config": False, "enabled": None,
                        "discovered": True, "gitea": True,
                    })


        discovered_ids = {it["id"] for it in discovered_items}
        # GitHub Topics 검색은 항상 저장소의 "현재(canonical)" 이름으로만 결과를
        # 준다. 이걸 (owner, repo) 키로 모아두면, 아래 레지스트리 항목이 이름이
        # 바뀐 옛 주소를 통해 같은 저장소를 가리키는지 판별할 수 있다.
        discovered_repo_keys = {
            (it["owner"].lower(), it["id"].lower())
            for it in discovered_items if it.get("owner")
        }

        # 직접 설치 이력(github.txt) — GitHub Topics로도 발견되지 않았지만, 이
        # 서버에서 Git URL로 직접 설치했던 저장소는 여기서 계속 추적한다(검색
        # 결과 유무와 무관하게 업데이트 확인을 이어가기 위함). 등록된 저장소가
        # 여러 개면 정보 조회 자체를 병렬로 한다 — 순차로 하면 등록 개수만큼
        # 지연이 그대로 누적된다(토픽 검색과 같은 이유).
        excluded_for_registry = curated_ids | discovered_ids
        registry_entries = []
        seen_registry_keys = set()
        for plugin_id_key, url in registry_entries_all:
            if not plugin_id_key or plugin_id_key in excluded_for_registry or plugin_id_key in seen_registry_keys:
                continue
            seen_registry_keys.add(plugin_id_key)
            registry_entries.append((plugin_id_key, url))

        fetched_registry_items = {}
        if registry_entries:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(8, len(registry_entries))
            ) as executor:
                future_map = {
                    executor.submit(
                        _fetch_repo_entry, url, token, is_enabled_fn,
                        plugin_id_override=plugin_id_key, gitea_tokens=gitea_tokens,
                    ): plugin_id_key
                    for plugin_id_key, url in registry_entries
                }
                for future in concurrent.futures.as_completed(future_map):
                    plugin_id_key = future_map[future]
                    try:
                        fetched_registry_items[plugin_id_key] = future.result()
                    except Exception as exc:
                        installed = _is_installed(plugin_id_key)
                        fetched_registry_items[plugin_id_key] = {
                            "id": plugin_id_key, "owner": "", "title": plugin_id_key, "type": "other",
                            "type_label": TYPE_LABELS["other"],
                            "desc": "저장소 정보를 불러오지 못했습니다 (%s)" % exc,
                            "tags": [], "features": [], "version_label": "—",
                            "url": None, "error": True,
                            "installed": installed,
                            "installed_version": (_local_version(plugin_id_key) if installed else None),
                            "has_update": False, "has_config": False, "enabled": None,
                        }

        registry_items = []
        seen_registry_ids = set()
        seen_canonical_keys = set()
        # 등록된 순서(registry_entries)를 그대로 유지해, 병렬로 가져왔더라도
        # 요청마다 카드 순서가 흔들리지 않게 한다.
        for plugin_id_key, url in registry_entries:
            # plugin_id_key(등록 시점의 1차 키)를 그대로 override로 넘겨, 이후 URL의
            # 저장소 이름이 바뀌었더라도(update_url로 갱신된 경우 등) 설치 여부·버전·
            # 활성화 상태는 항상 실제 설치 폴더(plugin_id_key) 기준으로 판단한다.
            item = fetched_registry_items[plugin_id_key]
            seen_registry_ids.add(plugin_id_key)

            # [저장소 이름 변경 감지] GitHub API는 옛 이름으로 조회해도 새 이름의
            # 정보를 그대로 돌려준다(리다이렉트). canonical_owner/repo가 채워져
            # 있다는 건 이 등록 주소가 실제로는 다른 이름으로 옮겨간 저장소를
            # 가리킨다는 뜻이다. 그 새 이름이 이미 다른 카드(발견된 카드 또는
            # 앞서 처리한 다른 레지스트리 항목)로 표시되고 있다면, 같은 저장소를
            # 두 번 보여주지 않는다.
            canonical_owner = item.get("canonical_owner")
            canonical_repo = item.get("canonical_repo")
            if canonical_owner and canonical_repo:
                canonical_key = (canonical_owner.lower(), canonical_repo.lower())
                if canonical_key in discovered_repo_keys or canonical_key in seen_canonical_keys:
                    if _is_installed(plugin_id_key):
                        # 옛 이름의 폴더가 실제로 아직 설치돼 있다면 카드 자체는
                        # 계속 보여준다(삭제 등 관리가 필요할 수 있으므로) — 다만
                        # 추적 주소만 최신 canonical 주소로 갱신해 이후에는 항상
                        # 정확한 정보를 반영하게 한다.
                        _remember_repo_install(
                            "https://github.com/%s/%s" % (canonical_owner, canonical_repo),
                            plugin_id=plugin_id_key,
                        )
                    else:
                        # 설치된 파일이 없는 유령 등록(예: 재설치 없이 저장소만
                        # 이름이 바뀐 경우) — 등록을 조용히 정리하고 중복 카드를
                        # 추가하지 않는다.
                        _unregister_repo(plugin_id_key)
                        continue
                else:
                    seen_canonical_keys.add(canonical_key)

            item["user_registered"] = True
            registry_items.append(item)

        local_items = _scan_uncurated_installed(
            curated_ids | discovered_ids | seen_registry_ids, is_enabled_fn
        )
        _save_disk_cache()  # 이번 요청에서 새로 채워진 캐시를 재시작에도 살아남도록 저장
        _save_shared_cache(self)  # 다른 워커와 공유

        all_items = [self_item] + discovered_items + registry_items + local_items
        if catalog_topic:
            # 카탈로그 토픽이 설정돼 있으면, 각 카드의 실제 GitHub 토픽 목록(tags)에
            # 그 토픽이 들어있는지로 "카탈로그" 필터 탭 소속 여부를 표시한다. 로컬
            # 전용 카드(local_items)는 원격 토픽을 조회하지 않으므로 tags가 항상
            # 비어있어 자연히 카탈로그에는 포함되지 않는다.
            catalog_topic_lower = catalog_topic.lower()
            for it in all_items:
                it["in_catalog"] = catalog_topic_lower in {t.lower() for t in (it.get("tags") or [])}
        else:
            for it in all_items:
                it["in_catalog"] = False

        return {
            "success": True,
            "items": all_items,
            "auto_update_enabled": auto_update_enabled and is_admin,
            "is_admin": is_admin,
            "topic_search_at": topic_search_at,  # 초 단위 epoch, 검색 이력이 전혀 없으면 None
            "plugin_board_version": self_item.get("installed_version"),  # 헤더 제목 옆 버전 표기용
            "catalog_topic": catalog_topic,  # 빈 문자열이면 프런트에서 "카탈로그" 탭을 숨긴다
            "searched_topics": all_topics,  # [PATCH-8] 실제로 검색한 토픽(설정 반영 확인용)
        }
