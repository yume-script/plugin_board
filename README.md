# 플러그인게시판 (plugin_board)

BookOasis 좌측 사이드바에 전용 카테고리 탭을 추가해, BookOasis 플러그인 저장소 목록을
색인 카드 형태로 보여주는 플러그인입니다. 카드에서 바로 **신규설치 / 업데이트 /
활성화·비활성화 / 환경설정 / 삭제**까지 수행할 수 있으며, 외부 플러그인(plugin_manager
등) 없이 **완전히 독립적으로** 동작합니다.

## 버전 및 호환 정보

| 항목      | 값                                            |
| ------- | --------------------------------------------- |
| 플러그인 버전 | `2.5.1`                                       |
| 플러그인 ID | `plugin_board`                                |
| 표시 이름   | 플러그인게시판                                       |
| 클래스     | `PluginBoardMetadataProvider`                 |
| 모듈      | `plugins.metadata.plugin_board.plugin_board`  |
| 유형      | 카테고리 풀페이지 탭 + 자체 설치/업데이트/관리 엔진 내장           |
| 외부 의존성  | 없음                      |

이 플러그인은 BookOasis의 권장 폴더형 플러그인 구조를 사용하며, 전역 테마 CSS 변수
(`var(--app-*)`)로 스타일을 구성해 8종 대시보드 테마와 자동으로 동기화됩니다.

## 동작 방식

### 1. 카드로 보여줄 저장소 목록 자체를 GitHub에서 실시간으로 조회

이전 버전과 달리, 카드로 보여줄 GitHub 저장소 **목록 자체**를 코드에 하드코딩하지
않습니다. 대신 아래 원격 파일을 화면을 열 때마다(`get_dashboard_data` 호출 시) 읽어옵니다.

```
https://raw.githubusercontent.com/yume-script/plugin_board/main/plugin_list.txt
```

한 줄에 GitHub 저장소 주소 하나, `#`으로 시작하는 줄은 주석으로 무시합니다.

```
https://github.com/javara999/naverkakaoridi
https://github.com/yume-script/pixiv_ranking
https://github.com/yume-script/unified_book
# 새 저장소는 이런 식으로 한 줄 추가
https://github.com/owner/new_plugin
```

**이 목록을 갱신하려면 plugin_board 코드를 다시 배포할 필요 없이, 저 GitHub 저장소의
`plugin_list.txt` 파일만 수정하면 됩니다** — 모든 BookOasis 서버가 다음 1시간 캐시
만료 시점에 자동으로 새 목록을 반영합니다.

목록 조회에 실패하면(네트워크 오류 등) 이전에 성공적으로 받아온 목록을 그대로
사용해 화면이 완전히 비지 않도록 합니다. 캐시조차 없는 첫 실행에서 조회에 실패하면
화면에 오류 메시지를 표시합니다.

### 2. 카드 정보 — 저장소별로 GitHub에서 실시간 조회

카드 내용(제목·설명·최신 버전)도 코드에 직접 적어두지 않고, 저장소별로 실시간 조회합니다.

| 가져오는 값 | 조회 위치 | 비고 |
| --- | --- | --- |
| 목록 자체 | `plugin_list.txt` (`raw.githubusercontent.com`) | 1시간 캐시, 실패 시 이전 캐시 유지 |
| 설명, 토픽(태그) | GitHub 저장소 API (`api.github.com`) | 시간당 60회 무인증 한도 |
| 최신 버전 | 저장소의 `VERSION` 파일 (`raw.githubusercontent.com`) | 이 가이드의 자동 업데이트 규격을 따르는 저장소라면 인증 없이 무제한 |

API 조회가 실패해도(예: rate limit) `VERSION` 파일만은 `main`/`master` 브랜치로
재시도해 최대한 버전 정보를 채우고, 카드에는 붉은 테두리로 조회 실패 사실을 표시합니다.

### 3. 설치 여부 — 서버 파일시스템을 직접 확인

`plugin_board.py`는 자기 자신도 `plugins/metadata/plugin_board/`에 위치한다는 점을
이용해, **부모 디렉토리(`plugins/metadata/`)를 직접 조회**해서 각 카드가 이 서버에
이미 설치되어 있는지, 설치돼 있다면 어떤 버전인지 판단합니다. 외부 플러그인 조회 없이
파일시스템만 보므로 plugin_manager가 없어도 정상 동작합니다.

- 설치 여부: `plugins/metadata/{repo}/` 폴더 존재 여부
- 설치된 버전: 그 폴더의 `VERSION` 파일
- 업데이트 필요 여부: 설치된 버전과 GitHub의 최신 버전을 비교(`x.y.z` 형식 기준)

### 4. plugin_list.txt에 없지만 서버에 설치된 플러그인도 같은 그리드에 표시

`plugins/metadata/` 디렉토리를 스캔해서, 원격 목록에 없지만 이미 설치되어 있는 모든
메타데이터 플러그인을 찾아 **같은 카드 그리드에 함께** 보여줍니다(별도 섹션 없음).
GitHub 저장소 주소를 모르므로 이 카드들은:

- 설치된 `{plugin_id}.py`에서 `name`/`is_searchable`/`category_tab`/`config_schema`를
  AST로만 읽어 표시 이름·분류·설정 보유 여부를 최대한 정확히 추정합니다.
- GitHub 설명·최신 버전·업데이트 확인은 제공하지 않습니다(별도 안내 문구 없이 조용히
  기본 정보만 표시).
- 이미 설치되어 있으므로 설치/업데이트 버튼 없이 관리 행(활성화 스위치·환경설정·삭제)만
  표시됩니다.
- `plugin_board` 자기 자신은 이 스캔에서 제외됩니다.

이 저장소를 나중에 `plugin_list.txt`에 추가하면, 다음 로드부터는 일반 큐레이션 카드로
승격되어 설명·최신 버전·업데이트 확인이 모두 활성화됩니다.

### 5. 신규설치 / 업데이트 — 전체 재다운로드 방식 (git 불필요)

각 카드 버튼은 상태에 따라 자동으로 바뀝니다.

| 상태 | 버튼 |
| --- | --- |
| 설치 안 됨 | `신규설치` |
| 설치됨 + 업데이트 있음 | `업데이트` (+ "업데이트 가능" 태그) |
| 설치됨 + 최신 버전 | 초록색 `설치됨` 배지 (버튼 없음) |

버튼 클릭 시 다음 순서로 서버에서 처리합니다. `update_manifest.files` 화이트리스트로
파일을 골라내지 않고, **검증에 성공한 새 소스로 설치 폴더 전체를 교체**하는 단순한
방식입니다.

1. GitHub `codeload.github.com`에서 저장소 소스를 zip으로 다운로드 (git 바이너리 불필요)
2. 임시 디렉토리에 압축 해제 (Zip Slip 방지 검증 포함)
3. 압축 해제된 소스에 `{repo}.py`(저장소 이름과 같은 메인 모듈 파일)가 있는지 확인
   — 최소한의 신원 확인이며, 소스 코드를 import/exec 하지는 않습니다
4. 확인에 성공한 경우에만 기존 `plugins/metadata/{repo}/`를 삭제하고, 압축 해제된
   소스 **전체**를 그 자리에 복사합니다(README·LICENSE·docs 등 부가 파일 포함).
   확인에 실패하면 기존 설치를 전혀 건드리지 않고 실패로 반환합니다.
5. 가능하면 코어의 hot reload(`services.metadata_factory.MetadataFactory.hot_reload_plugin`)를
   시도해 서버 재시작 없이 즉시 반영 (실패해도 설치 자체는 이미 완료된 상태)

`{repo}.py`가 없는 저장소(BookOasis 플러그인 구조를 따르지 않는 저장소)는 안전을 위해
설치를 거부하며, 이 경우 기존 설치는 그대로 보존됩니다.

### 6. Git 저장소 URL 설치 패널 — plugin_list.txt에 없는 저장소도 즉시 설치

화면 상단에는 `madnite1/plugin_manager`의 "Git 저장소 URL 설치" 패널과 같은 형태의
입력창이 있습니다. `plugin_list.txt`에 등록돼 있지 않은 저장소라도 GitHub 주소만
입력하면 바로 설치할 수 있습니다. 내부적으로는 카드의 `신규설치` 버튼과 동일한
`apply({"action": "install_git", "git_url": ...})`를 호출할 뿐이라, 별도의 백엔드
로직이 추가된 것은 아닙니다. 설치가 끝나면 목록을 새로고침하며, `plugin_list.txt`에
없는 저장소이므로 §4에서 설명한 "미등록 설치 플러그인" 카드로 표시됩니다.

### 7. 활성화/비활성화 · 환경설정 · 삭제 — 코어 공통 API 그대로 사용

설치된 카드 하단에는 관리 행이 추가로 표시됩니다.

- **활성화/비활성화 스위치** — 코어 서비스 `services.plugin_service.PluginService
  .toggle_plugin_enabled(...)`를 그대로 호출합니다. plugin_board가 직접 구현하지
  않고 코어에 위임하므로, 다른 화면(예: 환경설정 > 플러그인 설정)에서 본 상태와
  항상 일치합니다.
- **환경설정(⚙) 버튼** — 설치된 플러그인에 `config_schema` 또는 `settings.html`이
  있을 때 표시됩니다. 클릭하면 모든 플러그인이 공통으로 쓰는 코어 API를 호출해
  설정 화면을 엽니다.
  - 조회: `GET /api/media/metadata/plugins/manage`
  - 저장: `POST /api/media/metadata/plugins/save-config`
  - **`settings.html`이 있으면 그 커스텀 UI를 최우선으로 사용합니다.** 코어가
    렌더링해 내려주는 `settings_ui.html`/`.css`/`.js`를 그대로 모달에 삽입·실행합니다
    (madnite1/plugin_manager의 환경설정 모달과 동일한 방식). `settings.html`이 없으면
    `config_schema` 기반 자동 생성 폼(text / password / number / checkbox / select,
    가이드 §4와 동일)으로 대체합니다.
  - 저장은 두 경우 모두 동일하게 폼 안의 `name` 속성이 있는 input/select 값을
    모아 `save-config`로 전송합니다 — `settings.html` 작성 시 입력 요소의 `name`을
    저장하려는 설정 키와 맞추면 됩니다.
- **삭제(🗑) 버튼** — 확인 대화상자 후 `plugins/metadata/{id}/` 폴더를 삭제합니다.
  경로 검증은 설치 엔진과 동일한 함수(`_validate_plugin_id`, `_safe_join`)를
  재사용합니다. `plugin_board` 자기 자신은 비활성화·삭제 모두 차단됩니다.

이 세 기능 모두 **plugin_manager가 만든 전용 API가 아니라 BookOasis 코어가 모든
플러그인에 공통으로 제공하는 API**를 사용하므로, plugin_manager 설치 여부와
무관하게 동작합니다.

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
3. 환경설정 > 플러그인 설정에서 `플러그인게시판`을 활성화합니다.
4. (선택) `GitHub Personal Access Token`을 입력하면 API 호출 한도가 늘어납니다.
5. 좌측 사이드바의 `플러그인게시판` 카테고리에서 카드별로 설치·업데이트·활성화·설정·삭제를
   사용합니다.

## 설정

| 키             | UI 유형     | 필수 | 설명                                             |
| ------------- | --------- | -- | ------------------------------------------------ |
| `GITHUB_TOKEN` | password | 선택 | GitHub Personal Access Token. 설명/토픽 조회(`api.github.com`)의 무인증 한도(60/시간)를 늘리는 용도. 목록 조회(`raw.githubusercontent.com`)와 설치용 zip 다운로드(`codeload.github.com`)는 공개 저장소라면 토큰 없이도 동작 |

## plugin_list.txt에 새 저장소 추가하기

`plugin_board.py`를 건드릴 필요 없이,
[yume-script/plugin_board](https://github.com/yume-script/plugin_board)의
`plugin_list.txt`에 GitHub 주소를 한 줄 추가하면 됩니다.

```
https://github.com/javara999/naverkakaoridi
https://github.com/yume-script/pixiv_ranking
https://github.com/owner/new_plugin   ← 이렇게 한 줄 추가
```

다음 캐시 만료(최대 1시간) 또는 서버 재시작 후 자동으로 카드가 나타납니다.
`plugin_board.py`/`index.html`/`script.js`는 수정할 필요가 없습니다. 새로 추가한
저장소는 미설치 상태로 인식되어 카드에 `신규설치` 버튼이 표시됩니다.

**전제 조건**: 대상 저장소의 메인 모듈 파일명이 저장소 이름과 같아야 합니다
(예: `pixiv_ranking` 저장소 → `pixiv_ranking.py`). 이 가이드가 예시로 제시하는 폴더형
플러그인 구조(`my_plugin/my_plugin.py`)를 따르는 저장소라면 대부분 해당됩니다.

### 다른 목록 파일을 쓰고 싶다면

`plugin_board.py` 상단의 `REMOTE_PLUGIN_LIST_URL` 상수만 원하는 raw 텍스트 파일
주소로 바꾸면 됩니다.

### 분류(검색형 메타데이터 / 카테고리 탭 UI) 지정 — 선택 사항

GitHub API·README만으로는 저장소가 "검색형 메타데이터"인지 "카테고리 탭 UI"인지 자동으로
구분할 수 없습니다. 상단 필터 버튼에서 구분해서 보고 싶다면 `plugin_board.py`의
`TYPE_OVERRIDES`에 `"owner/repo": "search"` 또는 `"tab"`을 추가하세요. 지정하지 않으면
화면에 "기타"로 표시되며, 필터 버튼도 실제 데이터에 존재하는 분류만 자동으로 생성됩니다.
(이미 설치된 저장소는 소스에서 자동으로 재추정되므로 `TYPE_OVERRIDES`보다 우선합니다.)

```python
TYPE_OVERRIDES = {
    "javara999/naverkakaoridi": "search",
    "owner/new_plugin": "tab",   # 추가 (생략 가능)
}
```

## 자동 업데이트 (plugin_board 자기 자신)

`update_manifest`에 GitHub raw 기반 업데이트 계약이 선언되어 있습니다.

```python
update_manifest = {
    "enabled": True,
    "provider": "github-raw",
    "raw_base_url": "https://raw.githubusercontent.com/yume-script/plugin_board/refs/heads/main",
    "files": [
        "plugin_board.py", "__init__.py", "VERSION",
        "index.html", "style.css", "script.js", "README.md",
    ],
    "version_file": "VERSION",
    "version_key": "plugin version",
    "show_sample_update_button": True,
}
```

`raw_base_url`은 `yume-script/plugin_board` 저장소 루트를 직접 가리키며(그 저장소의
파일이 `plugins/metadata/plugin_board/` 하위가 아니라 저장소 루트에 바로 있는 구조),
`files`에는 이 폴더의 7개 파일을 전부 등록해 전체가 업데이트 대상에 포함됩니다.
GitHub의 `VERSION`이 로컬보다 높을 때만 환경설정 화면의 샘플 업데이트 버튼으로
갱신됩니다. (이 계약은 plugin_board 자신을 업데이트하는 용도이며, §5의 전체
재다운로드 설치 엔진과는 별개의 코어 표준 메커니즘입니다.)

## 보안 관련 설계 메모

- **경로 이탈 방지**: 설치 대상 경로(`_safe_join`)와 zip 압축 해제(`_extract_zip_safe`)
  모두 결과 경로가 `plugins/metadata/` 하위인지 매번 검증합니다.
- **플러그인 ID 검증**: 저장소 이름은 영문·숫자·`_`·`-`만 허용합니다.
- **최소 신원 확인 후 교체**: `{repo}.py`(메인 모듈) 존재를 먼저 확인하고, 그 확인을
  통과한 뒤에야 기존 설치 폴더를 삭제하고 새 소스로 교체합니다. 확인에 실패하면
  기존 설치를 전혀 건드리지 않습니다. 다운로드한 소스는 이 확인 과정에서 import/exec
  되지 않고 파일 존재 여부만 확인합니다 — 단, 설치 자체를 진행하면 그 플러그인의 코드는
  BookOasis가 정상적으로 로드해 실행합니다(플러그인 설치는 본질적으로 해당 저장소의
  코드 실행을 신뢰하는 행위이므로, 신뢰할 수 있는 저장소만 설치해야 합니다).
- **비-플러그인 폴더 제외**: `plugins/metadata/` 스캔 시 `__pycache__`, `-`, 숨김 폴더 등은
  제외하고, `{폴더명}.py` 또는 `VERSION` 파일이 실제로 있는 폴더만 플러그인으로 인정합니다.
- **목록 출처 신뢰**: `plugin_list.txt`는 `yume-script/plugin_board` 저장소 하나에서만
  읽어옵니다. 다른 출처를 신뢰하려면 `REMOTE_PLUGIN_LIST_URL`을 직접 바꿔야 합니다.
- **커스텀 설정 UI 실행**: `settings.html`/`settings.js`는 신뢰된 관리자 화면(환경설정)에서만
  삽입·실행되며, plugin_manager와 동일하게 `new Function(...)`으로 실행됩니다. 이미 설치를
  허용한 플러그인의 코드이므로 별도로 샌드박싱하지 않습니다.

## 제한 사항

- 검색/메타데이터 적용은 지원하지 않는 안내·설치·관리용 플러그인입니다(`is_searchable = False`).
- GitHub API 무인증 한도(60회/시간)를 서버 전체가 공유합니다. `GITHUB_TOKEN` 설정을 권장합니다.
- 기능 목록(`features`)은 GitHub API로 자동 추출하지 않으므로 기본적으로 비어 있습니다.
- Git URL 설치 패널·`신규설치`/`업데이트` 버튼 모두 저장소에 `{repo}.py` 메인 모듈이
  있어야 동작합니다(가이드의 폴더형 플러그인 구조 관례).
- 설치/업데이트는 대상 폴더를 **완전히 교체**합니다. 설치 폴더 안에 수동으로 넣어둔
  파일이 있다면 다음 업데이트 때 사라집니다.
