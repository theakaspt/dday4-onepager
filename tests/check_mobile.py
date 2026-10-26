"""모바일 웹 회귀 검사 (playwright, chromium)

  python3 -I tests/check_mobile.py            # dist/ 를 먼저 빌드해 둘 것 (build_mobile.py)

- 오프라인 컨텍스트(offline=True) + file:// 로 dist/index.html 을 연다. file:// 이 아닌 요청은 전부 차단·기록.
- 뷰포트 4종 x 7개사: 목록 > 행 터치 > 진입 연출 종료 대기 > 다음 질문(인라인 카드 또는 고정 바)으로 MENTOR까지 > 다른 기업 이야기 보기 > 목록
  답변마다 (a) 가로 스크롤 없음 (b) 다음 질문 어포던스 보임 (c) 보이는 글자 12px 이상, 본문 p 16px 이상 (d) 콘솔 에러·요청 실패 0
- 키워드 탭(MARKET), 뒤로가기(go_back), 링크 href, 키워드 탭바 한 줄 수용, 스크린샷(shots/)
통과 기준: 모든 뷰포트에서 "screens N no-next []" 와 errors [] 출력
"""
import asyncio, json, os, sys
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
URL = 'file://' + os.path.join(ROOT, 'dist', 'index.html')
SHOTS = os.path.join(ROOT, 'shots')
DATA = json.load(open(os.path.join(ROOT, 'kiosk-src', 'data.json'), encoding='utf-8'))
VIEWPORTS = [('360x780', 360, 780), ('393x852', 393, 852), ('412x915', 412, 915), ('440x956', 440, 956)]
EXPECT_HOME = {i: c['home'] for i, c in enumerate(DATA)}

JS_STATE = """() => {
  const bar = document.querySelector('#dHead').getBoundingClientRect();
  const chips = document.querySelector('#chips').getBoundingClientRect();
  const g = document.querySelector('#next .ghost button');
  let card = false, home = false, label = '';
  if (g) { const r = g.getBoundingClientRect(); card = r.height > 0 && r.top >= bar.bottom - 1 && r.bottom <= chips.top + 1; home = !!g.dataset.home; label = g.textContent; }
  const nb = document.querySelector('#nbar');
  return { card, nbar: nb.classList.contains('on'), home, label,
           sw: document.documentElement.scrollWidth, iw: innerWidth,
           turns: [...document.querySelectorAll('#thread .turn')].map(t => t.id) };
}"""

JS_FONTS = """() => {
  const scr = document.querySelector('.screen.on');
  let min = 1e9, minEl = '', pmin = 1e9, pEl = '';
  const walker = document.createTreeWalker(scr, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.textContent.trim()) continue;
    const el = n.parentElement; if (seen.has(el)) continue; seen.add(el);
    const cs = getComputedStyle(el);
    if (cs.visibility !== 'visible' || el.getClientRects().length === 0) continue;
    let a = el, hidden = false; while (a && a !== document.body) { const s = getComputedStyle(a); if (s.opacity === '0' || s.display === 'none' || s.visibility === 'hidden') { hidden = true; break; } a = a.parentElement; }
    if (hidden) continue;
    const r = el.getBoundingClientRect(); if (r.bottom < 0 || r.top > innerHeight) continue;
    const fs = parseFloat(cs.fontSize);
    if (fs < min) { min = fs; minEl = el.className + ':' + n.textContent.trim().slice(0, 16); }
    const p = el.closest('p'); if (p) { const pf = parseFloat(getComputedStyle(p).fontSize); if (pf < pmin) { pmin = pf; pEl = p.className; } }
  }
  return { min, minEl, pmin: pmin === 1e9 ? null : pmin, pEl };
}"""


async def wait_reveal_done(pg):
    if os.environ.get('DEBUG'):
        print('  state', await pg.evaluate("[location.hash, document.querySelector('.screen.on').id, document.querySelector('#next').className]"))
    await pg.wait_for_function("document.querySelector('#next').classList.contains('on') || !document.querySelector('#next').classList.contains('rv')", timeout=15000)
    await pg.wait_for_timeout(800)   # 카드 등장 후 연출 종료(busy 해제)까지 약 0.5초


async def wait_answer(pg, n_before):
    await pg.wait_for_function(f"(()=>{{const t=document.querySelectorAll('#thread .turn');return t.length>0 && t[t.length-1].querySelector('.ans') && document.querySelector('#next .ghost button')}})()", timeout=10000)
    await pg.wait_for_timeout(1300)


async def check_screen(pg, vp, tag, bad, issues):
    s = await pg.evaluate(JS_STATE)
    if not (s['card'] or s['nbar']):
        bad.append((vp, tag))
    if s['sw'] > s['iw']:
        issues.append(f'{vp} {tag}: horizontal scroll {s["sw"]}>{s["iw"]}')
    f = await pg.evaluate(JS_FONTS)
    if f['min'] < 12:
        issues.append(f'{vp} {tag}: font {f["min"]}px at {f["minEl"]}')
    if f['pmin'] is not None and f['pmin'] < 16:
        issues.append(f'{vp} {tag}: p font {f["pmin"]}px at {f["pEl"]}')
    return s


async def tap_next(pg):
    s = await pg.evaluate(JS_STATE)
    if s['card']:
        await pg.locator('#next .ghost button').tap()
        return 'card'
    await pg.locator('#nbar').tap()
    return 'nbar'


async def run_viewport(b, vp, w, h):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, is_mobile=True, has_touch=True, device_scale_factor=3, offline=True)
    external, errors = [], []

    async def router(route):
        if route.request.url.startswith(('file://', 'data:')):
            await route.continue_()
        else:
            external.append(route.request.url); await route.abort()
    await ctx.route('**/*', router)
    pg = await ctx.new_page()
    pg.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    pg.on('requestfailed', lambda r: errors.append(f'requestfailed: {r.url} {r.failure}'))
    await pg.goto(URL)
    await pg.wait_for_timeout(600)
    shot = lambda name: pg.screenshot(path=os.path.join(SHOTS, f'{vp}_{name}.png'))

    bad, issues, screens, via = [], [], 0, {'card': 0, 'nbar': 0}
    # 첫 화면
    if await pg.evaluate("document.documentElement.scrollWidth > innerWidth"):
        issues.append(f'{vp} home: horizontal scroll')
    f = await pg.evaluate(JS_FONTS)
    if f['min'] < 12: issues.append(f'{vp} home: font {f["min"]}px at {f["minEl"]}')
    if vp in ('393x852', '360x780'):
        await shot('01_home')
        await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_01_home_full.png'), full_page=True)
    # 키워드 탭바 한 줄 수용
    chip_fit = None

    for i, c in enumerate(DATA):
        await pg.locator(f'.row[data-i="{i}"]').tap()
        await wait_reveal_done(pg)
        if chip_fit is None:
            chip_fit = await pg.evaluate("""(()=>{const C=document.querySelector('#chips');const r=C.getBoundingClientRect();
              const over=[...C.children].filter(x=>x.scrollWidth>x.clientWidth+0.5||x.getBoundingClientRect().right>r.right+0.5).map(x=>x.textContent);
              const tops=new Set([...C.children].map(x=>Math.round(x.getBoundingClientRect().top)));
              return {fs:getComputedStyle(C.children[0]).fontSize, w:C.clientWidth, sw:C.scrollWidth, rows:tops.size, over}})()""")
            if vp == '360x780':
                await pg.locator('#dock').screenshot(path=os.path.join(SHOTS, f'{vp}_02_keyword_tabbar.png'))
        if vp == '393x852' and i == 1:
            await shot('02_ideaocean_after_reveal')
        # 링크
        href = await pg.evaluate("[document.querySelector('#bWeb').getAttribute('href'), document.querySelector('#bMail').getAttribute('href'), document.querySelector('#bWeb').target]")
        from urllib.parse import quote
        exp_mail = 'mailto:' + c['email'] + '?subject=' + quote('[d.day founders summit] 부스 문의드립니다', safe="-_.!~*'()")
        if href[0] != c['home'] or href[1] != exp_mail or href[2] != '_blank':
            issues.append(f'{vp} {c["ko"]}: link mismatch {href} vs {c["home"]} {exp_mail}')
        # 진입 직후에도 다음 질문이 보여야 함
        await check_screen(pg, vp, f'{c["ko"]}/intro', bad, issues)
        steps = 0
        while True:
            s = await pg.evaluate(JS_STATE)
            if s['home']:
                break
            n0 = len(s['turns'])
            via[await tap_next(pg)] += 1
            await wait_answer(pg, n0)
            steps += 1; screens += 1
            s = await check_screen(pg, vp, f'{c["ko"]}/{s["turns"][-1] if s["turns"] else ""}+{steps}', bad, issues)
            key = DATA[i]['sections'][steps - 1]['key']
            if vp == '393x852' and i == 1:
                if key == 'problem': await shot('03_ideaocean_problem')
                if key == 'market': await shot('04_ideaocean_market')
                if key == 'mentor':
                    await shot('05_ideaocean_mentor')
            if steps > 10:
                issues.append(f'{vp} {c["ko"]}: did not reach end'); break
        if steps != len(c['sections']):
            issues.append(f'{vp} {c["ko"]}: steps {steps} != sections {len(c["sections"])}')
        # 마지막 카드
        s = await pg.evaluate(JS_STATE)
        if not (s['card'] or s['nbar']): bad.append((vp, f'{c["ko"]}/end'))
        if vp == '393x852' and i == 1:
            await pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await pg.wait_for_timeout(700)
            await shot('06_ideaocean_last_card')
        await tap_next(pg)
        await pg.wait_for_function("document.querySelector('#home').classList.contains('on')", timeout=5000)
        await pg.wait_for_timeout(350)
        if '#c' in pg.url:
            issues.append(f'{vp} {c["ko"]}: url still {pg.url} after home')

    # 키워드 탭: 코스모비에서 2개 답변 후 MARKET 탭 -> 스레드가 MARKET 하나로 새로 시작
    await pg.locator('.row[data-i="0"]').tap(); await wait_reveal_done(pg)
    for _ in range(2):
        await tap_next(pg); await wait_answer(pg, 0)
    before = (await pg.evaluate(JS_STATE))['turns']
    await pg.locator('.chip', has_text='MARKET').tap(); await wait_answer(pg, 0)
    after = await pg.evaluate(JS_STATE)
    on = await pg.evaluate("[...document.querySelectorAll('.chip.on')].map(x=>x.textContent)")
    kw = f'before={before} after={after["turns"]} on={on}'
    if after['turns'] != ['turn-3'] or on != ['MARKET']:
        issues.append(f'{vp} keyword tab: {kw}')
    # 진입 연출 중 키워드 탭
    await pg.locator('#bAll').tap(); await pg.wait_for_function("document.querySelector('#home').classList.contains('on')")
    await pg.locator('.row[data-i="2"]').tap(); await pg.wait_for_timeout(500)
    await pg.locator('.chip', has_text='MARKET').tap(); await wait_answer(pg, 0)
    rv = await pg.evaluate("[[...document.querySelectorAll('#thread .turn')].map(t=>t.id).join(), document.querySelector('#dQ').textContent, document.querySelectorAll('#panel .rv:not(.on)').length]")
    if rv[0] != 'turn-3' or rv[1] != DATA[2]['intro'] or rv[2] != 0:
        issues.append(f'{vp} chip during reveal: {rv}')
    # 뒤로가기
    await pg.go_back(); await pg.wait_for_timeout(500)
    back_ok = await pg.evaluate("document.querySelector('#home').classList.contains('on') && !document.querySelector('#detail').classList.contains('on')")
    if not back_ok: issues.append(f'{vp} go_back did not return to list')
    # 딥링크
    await pg.goto('about:blank'); await pg.goto(URL + '#c4'); await pg.wait_for_timeout(600)
    dl = await pg.evaluate("[document.querySelector('#detail').classList.contains('on'), document.querySelector('#dBar').textContent]")
    await pg.go_back(); await pg.wait_for_timeout(500)
    dl_back = await pg.evaluate("document.querySelector('#home').classList.contains('on')")
    if not dl[0] or DATA[4]['ko'] not in dl[1] or not dl_back:
        issues.append(f'{vp} deeplink #c4: {dl} back_to_home={dl_back}')
    await ctx.close()
    return screens, bad, issues, errors, external, via, chip_fit, kw


async def main():
    os.makedirs(SHOTS, exist_ok=True)
    allok = True
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for vp, w, h in VIEWPORTS:
            screens, bad, issues, errors, external, via, chip_fit, kw = await run_viewport(b, vp, w, h)
            print(f'[{vp}] screens {screens} no-next {bad}')
            print(f'[{vp}] advance via {via}; keyword-tab {kw}')
            print(f'[{vp}] tabbar {chip_fit}')
            print(f'[{vp}] issues {issues}')
            print(f'[{vp}] external {external}')
            print(f'[{vp}] errors {errors}')
            if bad or issues or errors or external or (chip_fit and (chip_fit['rows'] != 1 or chip_fit['over'] or chip_fit['sw'] > chip_fit['w'])):
                allok = False
        await b.close()
    print('RESULT', 'PASS' if allok else 'FAIL')
    sys.exit(0 if allok else 1)


asyncio.run(main())
