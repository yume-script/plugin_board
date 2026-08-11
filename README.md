# 플러그인 목록장 (plugin_board)

BookOasis 좌측 사이드바에 전용 카테고리 탭을 추가해, 직접 만든 BookOasis 플러그인
저장소를 색인 카드 형태로 보여주는 안내용(category_tab) 플러그인입니다. 검색/메타데이터
적용 기능은 제공하지 않습니다.

## 버전 및 호환 정보

| 항목      | 값                                            |
| ------- | --------------------------------------------- |
| 플러그인 버전 | `1.0.0`                                       |
| 플러그인 ID | `plugin_board`                                |
| 클래스     | `PluginBoardMetadataProvider`                 |
| 모듈      | `plugins.metadata.plugin_board.plugin_board`  |
| 유형      | 카테고리 풀페이지 탭 (검색/적용 미지원)                       |

이 플러그인은 BookOasis의 권장 폴더형 플러그인 구조를 사용하며, 전역 테마 CSS 변수
(`var(--app-*)`)로 스타일을 구성해 8종 대시보드 테마와 자동으로 동기화됩니다.

## 동작 방식

카드 내용(제목·설명·최신 버전)은 코드에 직접 적어두지 않습니다. `plugin_board.py`의
`GITHUB_REPOS`에는 **GitHub 저장소 주소만** 저장하고, 화면을 열 때마다(`get_dashboard_data`
호출 시) GitHub에서 실시간으로 가져옵니다.

| 가져오는 값 | 조회 위치 | 비고 |
| --- | --- | --- |
| 설명, 토픽(태그) | GitHub 저장소 API (`api.github.com`) | 시간당 60회 무인증 한도 |
| 최신 버전 | 저장소의 `VERSION` 파일 (`raw.githubusercontent.com`) | 이 가이드의 자동 업데이트 규격을 따르는 저장소라면 인증 없이 무제한 |

조회 결과는 1시간 동안 메모리에 캐시되며(`_CACHE_TTL_SECONDS`), 캐시가 만료되기 전까지는
같은 값을 재사용해 GitHub API 한도를 아낍니다. API 조회가 실패해도(예: rate limit)
`VERSION` 파일만은 `main`/`master` 브랜치로 재시도해 최대한 버전 정보를 채우고, 카드에는
붉은 테두리로 조회 실패 사실을 표시합니다.

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
4. (선택) `GitHub Personal Access Token`을 입력하면 API 호출 한도가 늘어납니다.
5. 좌측 사이드바의 `플러그인 목록장` 카테고리를 확인합니다.

## 설정

| 키             | UI 유형     | 필수 | 설명                                             |
| ------------- | --------- | -- | ------------------------------------------------ |
| `GITHUB_TOKEN` | password | 선택 | GitHub Personal Access Token. 미입력 시 무인증 한도(60/시간)로 조회 |

## 새 저장소 추가하기

`plugin_board.py`의 `GITHUB_REPOS` 리스트에 GitHub 주소만 한 줄 추가하면 됩니다.

```python
GITHUB_REPOS = [
    "https://github.com/javara999/naverkakaoridi",
    "https://github.com/colaiuta77/achievements",
    "https://github.com/yume-script/pixiv_ranking",
    "https://github.com/yume-script/unified_book",
    "https://github.com/새로운-계정/새로운-저장소",   # 추가
]
```

서버 재시작(또는 1시간 캐시 만료) 후 자동으로 카드가 나타납니다. `index.html`/`script.js`는
수정할 필요가 없습니다.

### 분류(검색형 메타데이터 / 카테고리 탭 UI) 지정 — 선택 사항

GitHub API·README만으로는 저장소가 "검색형 메타데이터"인지 "카테고리 탭 UI"인지 자동으로
구분할 수 없습니다. 상단 필터 버튼에서 구분해서 보고 싶다면 `TYPE_OVERRIDES`에
`"owner/repo": "search"` 또는 `"tab"`을 추가하세요. 지정하지 않으면 화면에 "기타"로
표시되며, 필터 버튼도 실제 데이터에 존재하는 분류만 자동으로 생성됩니다.

```python
TYPE_OVERRIDES = {
    "javara999/naverkakaoridi": "search",
    "새로운-계정/새로운-저장소": "tab",   # 추가 (생략 가능)
}
```

## 자동 업데이트

`update_manifest`에 GitHub raw 기반 업데이트 계약이 선언되어 있습니다.
`raw_base_url`의 `<org>/<repo>/<branch>`를 실제 저장소 경로로 바꾼 뒤, GitHub의
`VERSION`이 로컬보다 높을 때만 환경설정 화면의 샘플 업데이트 버튼으로 갱신됩니다.

## 제한 사항

- 검색/메타데이터 적용을 지원하지 않는 순수 안내용 플러그인입니다(`is_searchable = False`).
- GitHub API 무인증 한도(60회/시간)를 서버 전체가 공유합니다. 다른 플러그인이나 서버
  프로세스도 같은 IP로 GitHub API를 호출한다면 `GITHUB_TOKEN` 설정을 권장합니다.
- 기능 목록(`features`)은 GitHub API로 자동 추출하지 않으므로 기본적으로 비어 있습니다.
