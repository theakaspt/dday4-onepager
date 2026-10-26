# d.day one-pager · 모바일 웹

부스 키오스크(55인치 세로 1080×1920 고정 화면)의 "Claude 채팅창 컨셉 대화형 원페이저"를 폰(360~480px)에서 읽기 좋게 다시 만든 정적 웹입니다. 원고·디자인 토큰·대화 흐름은 키오스크와 같고, 레이아웃과 키오스크 전용 기능만 바꿨습니다.

## 폴더 구조
```
dday-mobile/
├─ kiosk-src/            키오스크 원본 (읽기 전용, 수정 금지). 로고·사진·폰트·워드마크는 여기서 읽음
├─ data/data.json        모바일 원고 (kiosk-src/data.json 사본 + 아래 "원고 변경" 반영). 빌드·테스트가 읽는 원고
├─ mobile/template.html  모바일 화면 전체 (CSS + JS, 플레이스홀더 __DATA__ 등)
├─ build_mobile.py       빌드: template + data/data.json (+ kiosk-src 자산) -> dist/
├─ tests/check_mobile.py 회귀 검사 (playwright)
├─ dist/                 배포 산출물 (Vercel 정적 호스팅에 이 폴더를 올림)
│  ├─ index.html         CSS·JS·DATA 인라인
│  ├─ assets/            suit.<hash>.woff2, mono.<hash>.woff2, w_*.<hash>.webp(로고), m0~m7.<hash>.webp(멘토)
│  └─ vercel.json        캐시 헤더(assets immutable, index.html revalidate), cleanUrls
└─ shots/                테스트가 저장하는 폰 화면 스크린샷
```

## 빌드·테스트
```bash
python3 -I build_mobile.py        # dist/ 삭제 후 재생성. 파일 크기·첫 로드 합계 출력, 금지 문자열/예산 실패 시 exit 1
python3 -I tests/check_mobile.py  # 약 11분. 뷰포트 4종 모두 "screens 42 no-next []", errors [] 이고 마지막 줄 RESULT PASS
```
- 필요: python3, pillow, fonttools(+brotli), pyftsubset, playwright(chromium)
- 수정은 `mobile/template.html`(화면)과 `data/data.json`(원고)에서만. dist는 직접 고치지 않습니다. `kiosk-src/data.json`은 키오스크 원본이라 빌드가 읽지 않으며, 원고를 고칠 때는 키오스크 쪽에도 같은 변경이 필요한지 따로 확인합니다.
- 빌드 금지 문자열: `타겟`, `orbit-04`, `—`(em dash), `디캠프`, `D.CAMP`, `PIONEER`, `전담 멘토`
- 테스트는 `offline=True` 컨텍스트에서 `file://`로 엽니다(로컬 http 서버는 offline 모드에서 차단됨). file:// 이외 요청은 전부 막고 기록합니다.
- 딥링크: `#home`, `#c0`~`#c6`(c0 = Q-01), `#c3a5`(퍼스트랩을 열고 5번 섹션 질문). 딥링크로 들어와도 뒤로가기는 목록으로 갑니다.

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
| 상단 바 | 아이콘 ≡ ◫ 항상 | 상세 화면은 폭 440px 미만에서 아이콘 숨김(기업명·핸들이 잘리지 않게) |
| 폰트 | 데이터 URI 인라인, font-display block, KS X 1001 2350자 포함 | 별도 woff2 파일, font-display swap, 실제 쓰는 글자만(약 600자) |
| 로고 | 높이 124px WebP data URI | 원본 높이 그대로(105~227px, 248px 상한) 무손실 WebP 파일 |

## 원고 변경 (kiosk-src/data.json 대비)
| 위치 | 원문 | 현재 | 상태 |
|---|---|---|---|
| 7개사 MENTOR 섹션 label (7곳) + 멘토 role (8곳) | 전담 멘토 | 담당 멘토 | 반영 (10/26, 키오스크 v2와 동일) |

## 추가한 UI 문구
화면에 보이는 새 문구는 없습니다. 메타 정보만 추가했습니다.
- `<title>`, og:title: `d.day : founders summit · one-pager`
- meta description, og:description: `궤도에 오르기까지, 일곱 개의 기록 / dcamp batch 4 7개사 원페이저`
- 이미지 alt: 로고는 기업 한글명(data.json `ko`), 멘토 사진은 멘토 이름(data.json `name`)

## 알려진 한계
- `text-wrap: balance/pretty` 미지원 브라우저(iOS 17.4 미만 등)는 일반 줄바꿈으로 보입니다.
- SUIT 서브셋에 없는 기호 `–`(바의 "Q-01 – Q-07"은 Chivo Mono로 표시되어 영향 없음), `•`, `₆`, `％`는 시스템 폰트로 대체됩니다(현재 원고에서 SUIT로 쓰이는 곳 없음).
- 원고나 UI 문구에 새 글자가 들어가면 반드시 다시 빌드해야 폰트에 포함됩니다(빌드가 자동 수집).
- 전체화면: 헤드리스 크로미움에서는 `document.fullscreenElement`만 설정되고 화면 높이는 바뀌지 않아, 높이 변화는 `set_viewport_size`로 모사해 검사합니다. Android 크롬 실기에서 첫 터치 전환, 주소창·내비게이션 바 숨김, 전체화면 상태에서 뒤로가기(전체화면 해제와 목록 복귀가 어떤 순서로 일어나는지) 확인이 필요합니다.
- 테스트는 데스크톱 크로미움의 모바일 에뮬레이션입니다. iOS Safari 실기(주소창 높이 변화, safe-area, 뒤로가기 스와이프) 확인은 별도로 필요합니다.
- 키워드 탭은 360px에서 13px 기준 한 줄에 맞지만 여백이 좁습니다(라벨 내부 띄어쓰기를 -0.3em 줄여 구분).
