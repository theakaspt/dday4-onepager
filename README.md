# d.day one-pager · 모바일 웹

부스 키오스크(55인치 세로 1080×1920 고정 화면)의 "Claude 채팅창 컨셉 대화형 원페이저"를 폰(360~480px)에서 읽기 좋게 다시 만든 정적 웹입니다. 원고·디자인 토큰·대화 흐름은 키오스크와 같고, 레이아웃과 키오스크 전용 기능만 바꿨습니다.

## 폴더 구조
```
dday-mobile/
├─ kiosk-src/            키오스크 원본 (읽기 전용, 수정 금지). 로고·사진·폰트·워드마크는 여기서 읽음
├─ data/data.json        모바일 원고 (kiosk-src/data.json 사본 + 아래 "원고 변경" 반영). 빌드·테스트가 읽는 원고
├─ mobile/template.html  모바일 화면 전체 (CSS + JS, 플레이스홀더 __DATA__ 등)
├─ mobile/linebreak_rules.json  줄바꿈 보조 규칙(B2·B3 구절 목록). 아래 "줄바꿈 보조" 참고
├─ mobile/og.html        공유 미리보기 이미지 원본(1200x630). 빌드가 스크린샷해 assets/og.<hash>.png 생성
├─ build_mobile.py       빌드: template + data/data.json (+ kiosk-src 자산) -> dist/
├─ tests/check_mobile.py 회귀 검사 (playwright)
├─ dist/                 배포 산출물 (Vercel 정적 호스팅에 이 폴더를 올림)
│  ├─ index.html         CSS·JS·DATA 인라인
│  ├─ assets/            suit.<hash>.woff2, mono.<hash>.woff2, w_*.<hash>.webp(로고), m0~m7.<hash>.webp(멘토), og.<hash>.png(공유 미리보기)
│  └─ vercel.json        캐시 헤더(assets immutable, index.html revalidate), cleanUrls
└─ shots/                테스트가 저장하는 폰 화면 스크린샷
```

## 빌드·테스트
```bash
python3 -I build_mobile.py        # dist/ 삭제 후 재생성. 파일 크기·첫 로드 합계, 줄바꿈 원문 대조, og 이미지 출력. 금지 문자열/예산/원문 대조/og 실패 시 exit 1
python3 -I tests/check_mobile.py  # 약 15분. 뷰포트 4종 모두 "screens 42 no-next []", errors [] 이고 마지막 줄 RESULT PASS
```
- 필요: python3, pillow, fonttools(+brotli), pyftsubset, playwright(chromium) (빌드도 og 이미지 때문에 playwright 사용)
- 수정은 `mobile/template.html`(화면)과 `data/data.json`(원고)에서만. dist는 직접 고치지 않습니다. `kiosk-src/data.json`은 키오스크 원본이라 빌드가 읽지 않으며, 원고를 고칠 때는 키오스크 쪽에도 같은 변경이 필요한지 따로 확인합니다.
- 빌드 금지 문자열: `타겟`, `orbit-04`, `—`(em dash), `디캠프`, `D.CAMP`, `PIONEER`, `전담 멘토`
- 테스트는 `offline=True` 컨텍스트에서 `file://`로 엽니다(로컬 http 서버는 offline 모드에서 차단됨). file:// 이외 요청은 전부 막고 기록합니다.
- 딥링크: `#home`, `#c0`~`#c6`(c0 = Q-01), `#c3a5`(퍼스트랩을 열고 0~5번 섹션 답변을 연출 없이 채운 뒤 5번 질문 말풍선을 상단 바 아래로). 딥링크로 들어와도 뒤로가기는 목록으로 갑니다.
- 주소 갱신: 상세 진입 `#c{기업}`, 질문할 때마다(키워드 탭·다음 질문) `#c{기업}a{섹션}`으로 `history.replaceState`(기록이 쌓이지 않아 뒤로가기는 그대로 목록). 그 주소로 새로 열면 같은 섹션까지 복원.

## v1.2 바뀐 점 (10/28)
| 항목 | 내용 |
|---|---|
| A1 연출 중 터치 | 답변 생각 모션(0.5초)·등장 애니메이션·숫자 카운트업(1초) 중에 키워드 탭·다음 질문 카드·고정 바를 누르면 진행 중 답변을 즉시 완성(블록 전부, 숫자 최종값, 애니메이션 생략)하고 새 요청을 바로 처리. 진입 연출 중 터치는 기존처럼 연출을 끝내고 처리. 진행 중 답변은 `pend` 하나로 관리(타이머 취소 후 완성)해 늦게 붙는 답변·중복 없음. 진입 연출 중 아직 안 보이는 다음 질문 카드는 터치 대상에서 제외(그 자리를 누르면 연출만 끝남) |
| A2 공유 미리보기 | og:image(절대 URL `https://dday-onepager.vercel.app/assets/og.<hash>.png`, 1200x630, 200KB 이하), og:image:width/height, og:url, twitter:card=summary_large_image. 문구는 CONFIG.event(kicker·lead·footL·footR) + "one-pager" |
| A3 상단 아이콘 | 사이드 아이콘 삭제. 상세 화면 메뉴 아이콘 = "목록으로 돌아가기" 버튼(44x44, aria-label). 첫 화면 메뉴 아이콘은 장식(동작 없음). 좁은 화면 숨김 규칙 해제, 바 제목은 핸들부터 말줄임(기업명 우선 보존) |
| A4 좁은 화면 탭바 | 폭 320px 미만에서 탭 글자 11px·간격 축소, 넘치면 탭바 가로 스크롤(스크롤바 숨김). 읽는 섹션이 바뀌면 활성 탭이 보이도록 탭바만 가로 이동 |
| A5 주소 갱신 | 위 "주소 갱신" 참고 |
| A6 홈페이지 링크 | 아래 "원고 변경" 참고 |
| A7 본 기업 표시 | 상세를 연 기업은 목록 행 화살표가 라임 체크로, 질문 글자 opacity .72. localStorage `dday4.seen`(기업 id 배열), 읽기·쓰기 모두 try/catch(사생활 모드 등에서는 이번 방문 동안만 표시) |
| B 줄바꿈 | 아래 "줄바꿈 보조" 참고. 회사 소개 core_field는 `text-wrap: balance` |

## 줄바꿈 보조 (B1~B3)
- 원고(`data/data.json`)는 그대로 두고, 빌드가 화면용 DATA에만 보이지 않는 보조 문자를 넣습니다. 보이는 글자는 바뀌지 않습니다.
  - U+2060(단어결합자): 그 자리에서 줄이 나뉘지 않음
  - U+2011(비분리 하이픈): '-'와 같은 모양(빌드가 SUIT 서브셋에서 U+2011을 '-' 글리프에 연결), 뒤에서 줄이 안 나뉨
  - U+E000 / U+E001: 묶음 시작·끝 표시. 템플릿 `nw()`가 `<span class="nw">`(white-space:nowrap)로 바꿈. HTML 이스케이프 뒤에 바꾸므로 원고의 `<b>` 등과 충돌하지 않음
- B1: `build_mobile.py`의 `B1_RE` 정규식. 원고 전체에서 닫는 괄호 `)`·닫는 따옴표 `’ ”` 바로 뒤에 조사(을/를/이/가/은/는/의/로/으로/와/과/에/도/만)가 오면 사이에 U+2060. HTML 태그 밖 글자에만 적용. 현재 20곳
- B1 묶음(v1.2.1): 괄호가 줄 첫머리로 떨어지던 6곳은 앞 단어까지 한 덩어리(.nw) — 서비스(CRO)를 / 위탁(CRO)으로 / 위탁생산(CDMO)으로 / ‘허니비’를(2곳) / 빈피킹(Bin‑picking)이라고(하이픈 U+2011, 기존 Bin-picking 규칙을 흡수) / 장비(DEBREX)를. 280px에서도 넘침 없음
- 적용 순서: 묶음 규칙(원문 구절로 찾음) -> B1 단어결합자(묶음 표시가 사이에 있어도 인식)
- B2·B3: `mobile/linebreak_rules.json`의 구절 목록. `qn` + `where`(intro | 섹션key.title | 섹션key.blocks)로 위치를 좁히고, `count`와 실제 찾은 개수가 다르면 빌드 실패(원고가 바뀌었다는 신호). `nbhyphen: true`면 구절 안 '-'를 U+2011로
- 빌드 검사: index.html에 실제로 들어간 DATA에서 보조 문자를 걷어내고 U+2011을 '-'로 되돌리면 data/data.json과 완전히 같은지, 묶음 표시 짝이 맞는지 확인
- 구절을 추가하려면 linebreak_rules.json에 한 줄 추가 후 빌드. 묶음이 너무 길면 좁은 화면에서 가로로 넘치므로 테스트(280px 포함)로 확인

## 키오스크 대비 바뀐 점
| 구분 | 키오스크 | 모바일 |
|---|---|---|
| 레이아웃 | 1080×1920 스테이지를 통째로 축소(fit) | 유동 레이아웃, 최대 480px 컬럼 가운데 정렬(560px 이상도 동일), 배경 전체 다크 |
| 스크롤 | 내부 패널(#panel) 스크롤 | 페이지(window) 스크롤, 상단 바 sticky, 하단 영역(고정 바 + 키워드 탭) sticky |
| 글자 | 본문 27px(폰에서 9~11px로 보임) | 본문 16px/행간 1.7, 회사 소개 20~22px, 섹션 제목 22~24px, 첫 화면 헤드라인 34~38px, mono 라벨 12~13px, 키워드 탭 13px |
| 줄바꿈 | introLines·titleBr·fixBreaks(쉼표 24자 규칙) 강제 줄바꿈 | 전부 해제. intro/title 원문 자동 줄바꿈, 제목 balance·본문 pretty, keep-all + overflow-wrap:anywhere. 추가로 가운뎃점(·)이 줄 첫머리에 오지 않게 앞 글자와 묶음(글자는 그대로) |
| 진입 연출 | 타자 효과가 글자를 하나씩 추가(줄 위치가 바뀜) | 남은 글자를 투명 처리해 줄 위치를 고정한 채 타자 효과 |
| 답변 위치 | 답변 시작을 눈높이(위 216px)에 맞춤 | 직전 질문 말풍선이 상단 바 바로 아래에 오도록 scrollTo(smooth) |
| 다음 질문 | 카드 + 고정 바 + "위로 밀어" 제스처 + fitNext(반쯤 걸림 방지) | 카드 + 고정 바(IntersectionObserver). 제스처·fitNext·"↑ 위로 밀어 더 보기"·"눌러서 묻거나, 위로 밀어 이어서 보기" 안내 삭제. 고정 바가 뜬 동안 화면 아래 걸린 인라인 카드는 숨김(중복 방지) |
| 연락처 | 누르면 QR 창 | `<a>` 링크: 홈페이지 새 탭, 메일은 mailto(제목 CONFIG.mailSubject) |
| 연락처 위치 | 키워드 탭 아래 고정 줄 | 본문 끝(다음 질문 카드 > 연락처 > 목록으로 돌아가기 > 서명) |
| 뒤로가기 | 버튼만 | 상세 진입 시 pushState, 브라우저·제스처 뒤로가기로 목록 복귀, 목록 스크롤 위치 복원 |
| TARGET·MARKET | 2열 그리드 | 1열(폰 폭에서 큰 숫자·키워드가 2열에 안 들어감) |
| 배경 애니메이션 | 1080×1920 캔버스, 점 간격 9px | 화면 크기×min(dpr,1.5) 캔버스에 같은 궤도를 cover로 매핑, 점 간격 6 CSS px, 밝기 DIM 0.62 동일. 상세·탭 숨김 시 정지, 모션 줄이기면 정지 프레임 1장 |
| 전체화면 | 관리자 메뉴에서 전환 | 접속 후 첫 터치/클릭(어디든) 때 `requestFullscreen({navigationUI:'hide'})` 1회 시도(webkit 접두사 대체 포함). 지원 브라우저(Android 크롬 등)만, 거부·예외는 무시, 해제돼도 재시도 없음. 아이폰 사파리는 API가 없어 아무 일도 하지 않음. 그 터치의 원래 동작(질문 행 열기 등)은 그대로. 진입·해제로 높이가 바뀌면 하단 여백(#pad)을 다시 맞춰 보던 위치 유지 |
| 삭제 | | QR 전부(휴대폰으로 보기, QR 창, 연락처 QR, qrcode 라이브러리), 관리자 메뉴, 통계 localStorage, 높이 가이드, 90초 자동 복귀, 커서 숨김, 줌·롱프레스·우클릭·선택·링크·단축키 잠금, 첫 화면 아이콘 줄, contact 턴("휴대폰으로 스캔해…") |
| 유지한 잠금 | | 이미지 드래그 방지, 더블탭 확대 방지(touch-action: manipulation, 핀치 줌은 가능) |
| 상단 바 | 아이콘 ≡ ◫ 항상(장식) | ◫ 삭제. 상세 화면 ≡는 "목록으로 돌아가기" 버튼(항상 표시), 첫 화면 ≡는 장식. 바 제목은 핸들부터 말줄임 |
| 폰트 | 데이터 URI 인라인, font-display block, KS X 1001 2350자 포함 | 별도 woff2 파일, font-display swap, 실제 쓰는 글자만(약 600자) |
| 로고 | 높이 124px WebP data URI | 원본 높이 그대로(105~227px, 248px 상한) 무손실 WebP 파일 |

## 원고 변경 (kiosk-src/data.json 대비)
| 위치 | 원문 | 현재 | 상태 |
|---|---|---|---|
| 7개사 MENTOR 섹션 label (7곳) + 멘토 role (8곳) | 전담 멘토 | 담당 멘토 | 반영 (10/26, 키오스크 v2와 동일) |
| 스페이스린텍 home / homeLabel | http://www.spaceliintech.com / www.spaceliintech.com | https://spaceliintech-en.com/?redirect=no / spaceliintech-en.com | 반영 (10/28, 국문 사이트. `?redirect=no`는 영문 자동 전환 방지용, 지우지 말 것) |
| 코스모비·아이디어오션·테파로보틱스·퍼스트랩·피트인 home | http:// | https:// (호스트 그대로) | 반영 (10/28) |
| 갭텍 home | http://www.gap-t.com | 그대로 | https 미지원 |

## 추가한 UI 문구
화면에 보이는 새 문구는 없습니다. 메타 정보·보조 기술용 라벨만 추가했습니다.
- `<title>`, og:title: `d.day : founders summit · one-pager`
- og:image 이미지 안 문구: CONFIG.event의 kicker·lead·footL·footR + "one-pager"
- 상세 화면 메뉴 버튼 aria-label: `목록으로 돌아가기`(화면의 "목록으로 돌아가기" 버튼과 같은 문구)
- meta description, og:description: `궤도에 오르기까지, 일곱 개의 기록 / dcamp batch 4 7개사 원페이저`
- 이미지 alt: 로고는 기업 한글명(data.json `ko`), 멘토 사진은 멘토 이름(data.json `name`)

## 알려진 한계
- `text-wrap: balance/pretty` 미지원 브라우저(iOS 17.4 미만 등)는 일반 줄바꿈으로 보입니다.
- SUIT 서브셋에 없는 기호 `–`(바의 "Q-01 – Q-07"은 Chivo Mono로 표시되어 영향 없음), `•`, `₆`, `％`는 시스템 폰트로 대체됩니다(현재 원고에서 SUIT로 쓰이는 곳 없음).
- 원고나 UI 문구에 새 글자가 들어가면 반드시 다시 빌드해야 폰트에 포함됩니다(빌드가 자동 수집).
- 전체화면: 헤드리스 크로미움에서는 `document.fullscreenElement`만 설정되고 화면 높이는 바뀌지 않아, 높이 변화는 `set_viewport_size`로 모사해 검사합니다. Android 크롬 실기에서 첫 터치 전환, 주소창·내비게이션 바 숨김, 전체화면 상태에서 뒤로가기(전체화면 해제와 목록 복귀가 어떤 순서로 일어나는지) 확인이 필요합니다.
- 테스트는 데스크톱 크로미움의 모바일 에뮬레이션입니다. iOS Safari 실기(주소창 높이 변화, safe-area, 뒤로가기 스와이프) 확인은 별도로 필요합니다.
- 키워드 탭은 360px에서 13px 기준 한 줄에 맞지만 여백이 좁습니다(라벨 내부 띄어쓰기를 -0.3em 줄여 구분). 320px 미만은 가로 스크롤(스크롤된다는 시각 힌트는 없음).
- U+2060(단어결합자)은 SUIT에 글리프가 없지만 브라우저가 기본 무시 문자로 처리해 보이지 않습니다(크로미움 확인). iOS Safari 실기 확인 필요.
- 키워드 탭은 기존대로 스레드를 비우고 그 섹션부터 다시 시작하므로, 연출 중 탭을 누르면 직전 답변은 완성 후 바로 비워집니다(같은 탭 연타는 그 자리에서 완성).

## 테스트 항목 (tests/check_mobile.py)
- 뷰포트 4종 360x780(Galaxy S24), 375x667(iPhone SE), 393x852(iPhone 16), 430x932(iPhone Pro Max), is_mobile·has_touch·dpr 3, + 280x700
- 기존: 7개사 전체 흐름(가로 스크롤·다음 질문 어포던스·글자 크기·에러·외부 요청), 키워드 탭 리셋, 진입 연출 중 탭, 뒤로가기, 딥링크 #c4, 링크 href, 탭바 한 줄, 전체화면 4종
- A1: 답변 카운트업 300ms 시점 카드 클릭(직전 답변 완성·숫자 최종값·애니메이션 없음·블록 수, 새 질문 즉시), 생각 모션 중 다른 탭(즉시 시작·늦게 붙는 답변 없음), 같은 탭 연타, 카드·고정 바 연타 5회(순서·중복 없음)
- A3: 메뉴 버튼 44x44·aria-label·눌러서 목록, 사이드 아이콘 없음, 7개사 바에서 기업명이 잘리지 않음
- A4: 280x700 탭 11px·가로 스크롤, MENTOR 탭 터치(활성 탭이 탭바 안에 보임), 다시 WHY NOW
- A5: 진행마다 hash `#c{i}a{k}`, 그 hash로 새로 열어 같은 섹션까지 복원, 딥링크 #c2a3(0~3번, 말풍선 위치, 활성 탭, 뒤로가기)
- A7: 2개사 열람 후 체크 표시·흐림, 새로고침 유지, localStorage 예외 환경에서 에러 0
- B1~B3: 구절 19개가 한 줄 안(B1은 앞 단어 묶음 + 단어결합자, 제목 끝 (CDMO)으로는 단어결합자만), 화면의 모든 .nw가 한 줄(Range.getClientRects 같은 줄) + B1은 단어결합자, B2·B3는 .nw 안. 5개 폭 모두. `.nw`가 화면 밖으로 안 나가는지, 가로 스크롤 없음, 묶음 표시가 화면에 새지 않음
- B4: Q-01·Q-03·Q-04 core_field 마지막 줄 4자 이상(또는 한 줄)
- 스크린샷(shots/): 393x852 첫 화면(읽음 2개)·Q-05 VISION(_08, _11_q05_vision_v2)·Q-03 PROBLEM·Q-01 진입 연출, 280x700 탭바, og.png
