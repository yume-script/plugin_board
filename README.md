# 플러그인 목록장 (plugin_board)

BookOasis 좌측 사이드바에 전용 카테고리 탭을 추가해, 직접 만든 BookOasis 플러그인
저장소를 색인 카드 형태로 보여주는 플러그인입니다. 카드에서 바로 **신규설치 / 업데이트**를
수행할 수 있으며, 외부 플러그인(plugin_manager 등) 없이 **완전히 독립적으로** 동작합니다.

## 버전 및 호환 정보

| 항목      | 값                                            |
| ------- | --------------------------------------------- |
| 플러그인 버전 | `2.0.0`                                       |
| 플러그인 ID | `plugin_board`                                |
| 클래스     | `PluginBoardMetadataProvider`                 |
| 모듈      | `plugins.metadata.plugin_board.plugin_board`  |
| 유형      | 카테고리 풀페이지 탭 + 자체 설치/업데이트 엔진 내장              |
| 외부 의존성  | 없음 (plugin_manager 불필요)                       |

이 플러그인은 BookOasis의 권장 폴더형 플러그인 구조를 사용하며, 전역 테마 CSS 변수
(`var(--app-*)`)로 스타일을 구성해 8종 대시보드 테마와 자동으로 동기화됩니다.

## 동작 방식

### 1. 카드 정보 — GitHub에서 실시간 조회

카드 내용(제목·설명·최신 버전)은 코드에 직접 적어두지 않습니다. `plugin_board.py`의
`GITHUB_REPOS`에는 **GitHub 저장소 주소만** 저장하고, 화면을 열 때마다(`get_dashboard_data`
호출 시) GitHub에서 실시간으로 가져옵니다.

| 가져오는 값 | 조회 위치 | 비고 |
| --- | --- | --- |
| 설명, 토픽(태그) | GitHub 저장소 API (`api.github.com`) | 시간당 60회 무인증 한도 |
| 최신 버전 | 저장소의 `VERSION` 파일 (`raw.githubusercontent.com`) | 이 가이드의 자동 업데이트 규격을 따르는 저장소라면 인증 없이 무제한 |

조회 결과는 1시간 캐시됩니다. API 조회가 실패해도(예: rate limit) `VERSION` 파일만은
`main`/`master` 브랜치로 재시도해 최대한 버전 정보를 채우고, 카드에는 붉은 테두리로
조회 실패 사실을 표시합니다.

### 2. 설치 여부 — 서버 파일시스템을 직접 확인

`plugin_board.py`는 자기 자신도 `plugins/metadata/plugin_board/`에 위치한다는 점을
이용해, **부모 디렉토리(`plugins/metadata/`)를 직접 조회**해서 각 카드가 이 서버에
이미 설치되어 있는지, 설치돼 있다면 어떤 버전인지 판단합니다. 외부 플러그인 조회 없이
파일시스템만 보므로 plugin_manager가 없어도 정상 동작합니다.

- 설치 여부: `plugins/metadata/{repo}/` 폴더 존재 여부
- 설치된 버전: 그 폴더의 `VERSION` 파일
- 업데이트 필요 여부: 설치된 버전과 GitHub의 최신 버전을 비교(`x.y.z` 형식 기준)

### 3. GITHUB_REPOS에 없지만 서버에 설치된 플러그인도 같은 그리드에 표시

`plugins/metadata/` 디렉토리를 스캔해서, `GITHUB_REPOS`에 등록하지 않았지만 이미
설치되어 있는 모든 메타데이터 플러그인을 찾아 **같은 카드 그리드에 함께** 보여줍니다
(별도 섹션 없음). GitHub 저장소 주소를 모르므로 이 카드들은:

- 설치된 `{plugin_id}.py`에서 `name`/`is_searchable`/`category_tab`을 AST로만 읽어
  표시 이름과 분류(검색형/카테고리 탭)를 최대한 정확히 추정합니다.
- GitHub 설명·최신 버전·업데이트 확인은 제공하지 않으며, 카드에 "GitHub 미등록" 태그와
  안내 문구만 표시됩니다.
- GitHub 링크·설치/업데이트 버튼은 표시되지 않고(이미 설치되어 있으므로) 초록색
  `설치됨` 배지만 표시됩니다.
- `plugin_board` 자기 자신은 이 스캔에서 제외됩니다.

이 저장소를 나중에 `GITHUB_REPOS`에 추가하면, 다음 로드부터는 일반 큐레이션 카드로
승격되어 설명·최신 버전·업데이트 확인이 모두 활성화됩니다.

### 4. 신규설치 / 업데이트 — 자체 내장 엔진 (git 불필요)

각 카드 버튼은 상태에 따라 자동으로 바뀝니다.

| 상태 | 버튼 |
| --- | --- |
| 설치 안 됨 | `신규설치` |
| 설치됨 + 업데이트 있음 | `업데이트` (+ "업데이트 가능" 태그) |
| 설치됨 + 최신 버전 | 초록색 `설치됨` 배지 (버튼 없음) |

버튼 클릭 시 [madnite1/plugin_manager](https://github.com/madnite1/plugin_manager)가
쓰는 것과 동일한 원리로 서버에서 처리합니다(참고해 자체 구현).

1. GitHub `codeload.github.com`에서 저장소 소스를 zip으로 다운로드 (git 바이너리 불필요)
2. 임시 디렉토리에 압축 해제 (Zip Slip 방지 검증 포함)
3. 대상 플러그인의 `{repo}.py`에서 `update_manifest` 딕셔너리를 **AST로만** 추출
   — 소스 코드를 import/exec 하지 않으므로 클론된 코드가 그 자리에서 실행되지 않습니다
4. `update_manifest.files`에 명시된 파일만 골라 `plugins/metadata/{repo}/`로 복사
   (경로 이탈·존재하지 않는 파일 등은 사전 검증 후 거부)
5. 가능하면 코어의 hot reload(`services.metadata_factory.MetadataFactory.hot_reload_plugin`)를
   시도해 서버 재시작 없이 즉시 반영 (실패해도 설치 자체는 이미 완료된 상태)

`update_manifest`가 없는 저장소(가이드 규격을 따르지 않는 저장소)는 안전을 위해 설치를
거부합니다.

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
5. 좌측 사이드바의 `플러그인 목록장` 카테고리에서 카드별로 `신규설치`/`업데이트`를 사용합니다.

## 설정

| 키             | UI 유형     | 필수 | 설명                                             |
| ------------- | --------- | -- | ------------------------------------------------ |
| `GITHUB_TOKEN` | password | 선택 | GitHub Personal Access Token. 설명/토픽 조회(`api.github.com`)의 무인증 한도(60/시간)를 늘리는 용도. 설치용 zip 다운로드(`codeload.github.com`)는 공개 저장소라면 토큰 없이도 동작 |

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
수정할 필요가 없습니다. 새로 추가한 저장소는 미설치 상태로 인식되어 카드에 `신규설치`
버튼이 표시됩니다.

**전제 조건**: 대상 저장소의 메인 모듈 파일명이 저장소 이름과 같아야 합니다
(예: `pixiv_ranking` 저장소 → `pixiv_ranking.py`). 이 가이드가 예시로 제시하는 폴더형
플러그인 구조(`my_plugin/my_plugin.py`)를 따르는 저장소라면 대부분 해당됩니다.

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

## 자동 업데이트 (plugin_board 자기 자신)

`update_manifest`에 GitHub raw 기반 업데이트 계약이 선언되어 있습니다.
`raw_base_url`의 `<org>/<repo>/<branch>`를 실제 저장소 경로로 바꾼 뒤, GitHub의
`VERSION`이 로컬보다 높을 때만 환경설정 화면의 샘플 업데이트 버튼으로 갱신됩니다.
(이 계약은 plugin_board 자신을 업데이트하는 용도이며, §4의 자체 엔진과는 별개입니다.)

## 보안 관련 설계 메모

- **경로 이탈 방지**: 설치 대상 경로(`_safe_join`)와 zip 압축 해제(`_extract_zip_safe`)
  모두 결과 경로가 `plugins/metadata/` 하위인지 매번 검증합니다.
- **플러그인 ID 검증**: 저장소 이름은 영문·숫자·`_`·`-`만 허용합니다.
- **코드 비실행 원칙**: `update_manifest`는 AST 파싱(`ast.literal_eval`)으로만 읽고,
  다운로드한 소스는 설치 전 단계에서 한 번도 import/exec 되지 않습니다.
- **화이트리스트 복사**: `update_manifest.files`에 명시된 파일만 복사하며, 존재하지
  않는 파일이나 상위 경로(`..`)가 섞여 있으면 설치 전체를 거부합니다.

## 제한 사항

- 검색/메타데이터 적용은 지원하지 않는 안내·설치용 플러그인입니다(`is_searchable = False`).
- GitHub API 무인증 한도(60회/시간)를 서버 전체가 공유합니다. `GITHUB_TOKEN` 설정을 권장합니다.
- 기능 목록(`features`)은 GitHub API로 자동 추출하지 않으므로 기본적으로 비어 있습니다.
- 업데이트 시 기존에 설치된 파일 중 새 `update_manifest.files` 목록에서 빠진 파일은
  삭제되지 않고 그대로 남습니다(덮어쓰기만 수행).
