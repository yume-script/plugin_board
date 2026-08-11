# -*- coding: utf-8 -*-
"""
plugin_board — BookOasis 카테고리 탭 플러그인

이 플러그인은 검색/메타데이터 적용 기능이 없는 순수 안내용(category_tab) 플러그인입니다.
좌측 사이드바에 "플러그인 목록장" 탭을 추가하고, 직접 만든 BookOasis 플러그인
저장소 목록을 색인 카드 형태로 보여줍니다.

가이드 문서(플러그인 개발 가이드 §3, §5)의 계약을 따릅니다:
- 필수: search(), apply()
- 선택: category_tab, get_dashboard_data(), update_manifest
"""

from plugins.metadata.base import BaseMetadataProvider


# 카드에 표시할 플러그인 목록. 새 플러그인을 추가할 때는 이 리스트에
# 항목을 하나 추가하기만 하면 됩니다 (index.html/script.js 수정 불필요).
PLUGIN_ENTRIES = [
    {
        "id": "naverkakaoridi",
        "owner": "javara999",
        "title": "통합 웹툰·웹소설 검색",
        "type": "search",
        "type_label": "검색형 메타데이터",
        "desc": (
            "네이버웹툰·네이버시리즈·카카오웹툰·카카오페이지·리디·노벨피아 6개 소스를 "
            "한 번에 검색해 웹툰·웹소설 메타데이터를 도서에 적용합니다."
        ),
        "tags": ["검색형 메타데이터", "웹툰 · 웹소설"],
        "features": [
            "소스 6종 통합 검색, SOURCES 설정으로 선택 조회",
            "시리즈 전체에 표지·평점 자동 전파",
            "권/화별 고유 표지 해시로 영구 삭제 후에도 보존",
        ],
        "version_label": "v1.4.3",
        "url": "https://github.com/javara999/naverkakaoridi",
    },
    {
        "id": "achievements",
        "owner": "colaiuta77",
        "title": "독서 업적",
        "type": "tab",
        "type_label": "카테고리 탭 UI",
        "desc": (
            "저장된 독서 진행 기록을 이용해 사용자별 업적·배지·연속 독서와 "
            "다음 목표를 사이드바 전용 탭에서 보여줍니다."
        ),
        "tags": ["카테고리 탭 UI", "독서 기록"],
        "features": [
            "완독·페이지·연속 독서·오디오북 등 업적 22개",
            "달성 · 진행 중 · 잠김 상태 필터 제공",
            "Redis pending 진행률까지 병합해 실시간 반영",
        ],
        "version_label": "v1.1.0",
        "url": "https://github.com/colaiuta77/achievements",
    },
    {
        "id": "pixiv_ranking",
        "owner": "yume-script",
        "title": "Pixiv 랭킹",
        "type": "tab",
        "type_label": "카테고리 탭 UI",
        "desc": (
            "픽시브 일간·주간·월간·신인·오리지널 등 랭킹을 카테고리 풀페이지 탭에 "
            "카드 형태로 보여주는 전용 뷰어입니다. 검색·적용 기능은 없습니다."
        ),
        "tags": ["카테고리 탭 UI", "Pixiv"],
        "features": [
            "콘텐츠 타입·랭킹 모드를 화면 상단 드롭다운으로 즉시 전환",
            "썸네일을 서버가 대신 받아 403 문제 우회",
            "단계별 로그로 로드 상태를 콘솔·서버 양쪽에서 확인",
        ],
        "version_label": "VERSION 파일 관리",
        "url": "https://github.com/yume-script/pixiv_ranking",
    },
    {
        "id": "unified_book",
        "owner": "yume-script",
        "title": "통합 도서 검색",
        "type": "search",
        "type_label": "검색형 메타데이터",
        "desc": (
            "알라딘·국립중앙도서관(Seoji)·구글 도서 데이터를 스레드 풀로 병렬 조회해 "
            "높은 신뢰도의 도서 메타데이터를 완성합니다. 네이버 API는 지원이 종료되었습니다."
        ),
        "tags": ["검색형 메타데이터", "도서 · ISBN"],
        "features": [
            "ISBN·제목·저자 축과 소스를 조합해 병렬 검색",
            "파일 판권지 직접 파싱 + AI 판독 백업",
            "title_alias로 원본 파일명 제목을 보호하며 저장",
        ],
        "version_label": "3-Source Merge",
        "url": "https://github.com/yume-script/unified_book",
    },
]


class PluginBoardMetadataProvider(BaseMetadataProvider):
    id = "plugin_board"
    name = "플러그인 목록장"
    is_searchable = False
    config_schema = []  # 별도 설정 없음

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
    # 카테고리 풀페이지 탭이 script.js를 통해 호출하는 데이터 엔드포인트
    # ------------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        return {"success": True, "items": PLUGIN_ENTRIES}
