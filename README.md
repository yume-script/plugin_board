# 플러그인 목록장 (plugin_board)

BookOasis 좌측 사이드바에 전용 카테고리 탭을 추가해, 직접 만든 BookOasis 플러그인 저장소를
색인 카드 형태로 보여주는 안내용(category_tab) 플러그인입니다. 검색/메타데이터 적용 기능은
제공하지 않습니다.

## 버전 및 호환 정보

| 항목      | 값                                    |
| ------- | ------------------------------------ |
| 플러그인 버전 | `1.0.0`                              |
| 플러그인 ID | `plugin_board`                       |
| 클래스     | `PluginBoardMetadataProvider`        |
| 모듈      | `plugins.metadata.plugin_board.plugin_board` |
| 유형      | 카테고리 풀페이지 탭 (검색/적용 미지원)              |

이 플러그인은 BookOasis의 권장 폴더형 플러그인 구조를 사용하며, 전역 테마 CSS 변수
(`var(--app-*)`)로 스타일을 구성해 8종 대시보드 테마와 자동으로 동기화됩니다.

## 주요 기능

- 좌측 사이드바 `플러그인 목록장` 카테고리 탭에 전체 플러그인 목록 카드 표시
- `검색형 메타데이터` / `카테고리 탭 UI` 분류 필터
- GitHub 저장소로 바로 이동하는 링크 버튼
- 목록 데이터는 `plugin_board.py`의 `PLUGIN_ENTRIES` 한 곳에서만 관리 (HTML/JS 수정 불필요)

## 설치

최종 폴더 구조는 다음과 같습니다.

```
plugins/metadata/plugin_board/
├── __init__.py
├── plugin_board.py
├── README.md
├── VERSION
├── index.html
├── style.css
└── script.js
```

1. 위 폴더를 서버의 `plugins/metadata/plugin_board/`에 그대로 배치합니다.
2. BookOasis 서버를 재시작합니다.
3. 환경설정 > 플러그인 설정에서 `플러그인 목록장`을 활성화합니다.
4. 좌측 사이드바의 `플러그인 목록장` 카테고리를 확인합니다.

## 새 플러그인 카드 추가하기

`plugin_board.py`의 `PLUGIN_ENTRIES` 리스트에 항목을 하나 추가하면 됩니다.

```python
{
    "id": "my_plugin",
    "owner": "github-id",
    "title": "표시 제목",
    "type": "search",          # "search" 또는 "tab"
    "type_label": "검색형 메타데이터",
    "desc": "한두 문장 설명",
    "tags": ["태그1", "태그2"],
    "features": ["특징 1", "특징 2", "특징 3"],
    "version_label": "v1.0.0",
    "url": "https://github.com/github-id/my_plugin",
},
```

## 자동 업데이트

`update_manifest`에 GitHub raw 기반 업데이트 계약이 선언되어 있습니다.
`raw_base_url`의 `<org>/<repo>/<branch>`를 실제 저장소 경로로 바꾼 뒤, GitHub의
`VERSION`이 로컬보다 높을 때만 환경설정 화면의 샘플 업데이트 버튼으로 갱신됩니다.

## 제한 사항

- 검색/메타데이터 적용을 지원하지 않는 순수 안내용 플러그인입니다(`is_searchable = False`).
- 목록 데이터는 정적입니다 — DB를 조회하지 않고 `PLUGIN_ENTRIES`에 정의된 값만 반환합니다.
