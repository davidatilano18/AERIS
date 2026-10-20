"""Read-only browser QA against a local Flask server. No ingestion or task calls."""
import base64
import json
import subprocess
import time
import uuid
from pathlib import Path
from urllib.request import urlopen
import websocket

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'reports/dashboard_v21_preview';output.mkdir(exist_ok=True)
    profile=ROOT/'data/sync_runtime/dashboard_browser'/uuid.uuid4().hex
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    process=subprocess.Popen([str(browser),'--headless=new','--disable-gpu','--no-first-run',
        '--no-default-browser-check','--disable-background-networking','--disable-component-update',
        '--disable-extensions','--remote-debugging-port=9229',
        '--remote-allow-origins=http://127.0.0.1:9229','--user-data-dir='+str(profile),'about:blank'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    connection=None;checks=[];errors=[];command_id=0;viewport_width=1440
    try:
        deadline=time.monotonic()+15
        while True:
            try:
                with urlopen('http://127.0.0.1:9229/json/list',timeout=2) as response:targets=json.load(response)
                target=next(t for t in targets if t['type']=='page');break
            except Exception:
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        connection=websocket.create_connection(target['webSocketDebuggerUrl'],origin='http://127.0.0.1:9229',timeout=15)
        def command(method,params=None):
            nonlocal command_id
            command_id+=1;expected=command_id
            connection.send(json.dumps({'id':expected,'method':method,'params':params or {}}))
            while True:
                message=json.loads(connection.recv())
                if message.get('method')=='Runtime.exceptionThrown':errors.append(message['params'])
                if message.get('id')==expected:
                    if 'error' in message:raise RuntimeError(str(message['error']))
                    return message.get('result',{})
        def evaluate(expression):
            result=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in result:raise RuntimeError(str(result['exceptionDetails']))
            return result['result'].get('value')
        def wait_state(expected='ready'):
            until=time.monotonic()+15
            while time.monotonic()<until:
                try:
                    if evaluate('document.documentElement.dataset.loadState')==expected:return
                except RuntimeError:pass
                time.sleep(.15)
            raise RuntimeError('Browser state did not become '+expected)
        def navigate(query='',width=1440,mobile=False,path='/v2'):
            nonlocal viewport_width
            viewport_width=width
            command('Emulation.setDeviceMetricsOverride',{'width':width,'height':1100,'deviceScaleFactor':1,'mobile':mobile})
            command('Page.navigate',{'url':'http://127.0.0.1:5056'+path+query});wait_state()
        def capture(name):
            state=evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,state:document.documentElement.dataset.loadState,value:document.getElementById("latestValue").textContent,station:document.getElementById("station").value,source:document.getElementById("source").value,readingState:document.getElementById("readingState").textContent,chart:!!Chart.getChart("pmChart"),external:performance.getEntriesByType("resource").filter(r=>r.name.startsWith("https:")).length})')
            assert state['scrollWidth']<=state['width'],str(state)
            assert state['width']==viewport_width, 'Mobile layout widened the viewport: '+str(state)
            assert state['external']==0
            dimensions=command('Page.getLayoutMetrics')['cssContentSize']
            image=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,
                'clip':{'x':0,'y':0,'width':dimensions['width'],'height':dimensions['height'],'scale':1}})['data']
            (output/(name+'-full.png')).write_bytes(base64.b64decode(image))
            if name=='mobile':evaluate('document.documentElement.style.scrollBehavior="auto";window.scrollTo(0,document.getElementById("tu-estacion").getBoundingClientRect().top+window.scrollY-18);new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            viewport=command('Page.captureScreenshot',{'format':'png'})['data']
            (output/(name+'.png')).write_bytes(base64.b64decode(viewport))
            evaluate('document.documentElement.style.scrollBehavior="auto";window.scrollTo(0,0)')
            (output/(name+'.html')).write_text(evaluate('document.documentElement.outerHTML'),encoding='utf-8')
            checks.append({'view':name,**state})
        command('Page.enable');command('Runtime.enable');command('Network.enable')
        command('Network.setBlockedURLs',{'urls':['https://*']})
        navigate();capture('landing-desktop')
        assert evaluate('document.getElementById("latestValue").textContent')=='—'
        assert not evaluate('!!Chart.getChart("pmChart")')
        navigate('?station=1352676');capture('desktop')
        assert evaluate('!!Chart.getChart("pmChart")')
        assert evaluate('Chart.getChart("pmChart").options.scales.x.title.text.includes("Querétaro")')
        navigate('?station=1352676',390,True);capture('mobile')
        # Municipality is a catalogue filter, never a concentration aggregation.
        evaluate('document.getElementById("municipality").value="El Marqués";document.getElementById("municipality").dispatchEvent(new Event("change"))')
        wait_state()
        assert evaluate('document.getElementById("station").options.length')==2
        assert evaluate('document.getElementById("station").value')=='all'
        evaluate('document.getElementById("openMarques").click()');wait_state();capture('marques-history-mobile')
        assert evaluate('document.getElementById("period").value')=='all'
        assert evaluate('document.getElementById("source").value')=='OpenAQ'
        assert evaluate('document.getElementById("measuredAt").textContent.includes("2021")')
        assert evaluate('document.getElementById("measuredAt").textContent.includes("05:00")')
        assert evaluate('!document.getElementById("historicalNotice").hidden')
        assert evaluate('Chart.getChart("pmChart").data.datasets[0].data.filter(p=>p.observation.gap).length')>0
        assert evaluate('Chart.getChart("pmChart").data.datasets[0].spanGaps') is False
        assert evaluate('document.getElementById("observedHours").textContent')=='333 de 375'
        # Keyboard can focus the native historical entry point.
        evaluate('document.getElementById("openMarques").focus()')
        assert evaluate('document.activeElement.id')=='openMarques'
        navigate('?station=1352686',390,True);capture('marques-no-recent')
        assert not evaluate('!!Chart.getChart("pmChart")')
        assert evaluate('document.getElementById("latestValue").textContent')=='9.37'
        navigate('?station=1352686&source=OpenAQ-Archive&period=all',390,True);capture('marques-archive-empty')
        assert evaluate('document.getElementById("latestValue").textContent')=='—'
        navigate('?station=1352676&source=OpenAQ-Archive&period=all',1440);capture('archive-desktop')
        assert evaluate('Chart.getChart("pmChart").data.datasets[0].data.every(p=>p.observation.gap||p.observation.source==="OpenAQ-Archive")')
        navigate('?station=1352719',390,True);capture('no-observations-mobile')
        assert evaluate('document.getElementById("readingState").textContent')=='Sin observaciones'
        navigate('?station=1352676',320,True);capture('narrow-mobile')
        command('Network.setBlockedURLs',{'urls':['https://*','*api/v2/public*']})
        evaluate('document.getElementById("refresh").click()');wait_state('error');capture('error-mobile')
        assert evaluate('document.getElementById("latestValue").textContent')=='—'
        assert not evaluate('!!Chart.getChart("pmChart")')
        assert not evaluate('document.getElementById("error").hidden')
        command('Network.setBlockedURLs',{'urls':['https://*']})
        navigate('?station=1352676',1440,path='/v2/datos')
        assert evaluate('!!Chart.getChart("pmChart")')
        assert evaluate('document.getElementById("source").tagName')=='SELECT'
        assert not errors,str(errors)
        report={'successful':True,'checks':checks,'javascript_errors':errors,'external_https_blocked':True,
                'manual_sync_calls':0,'scope':'read-only public UI, source filters, local dates, empty/error, explorer; not WCAG certification'}
        (output/'browser_checks.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(report,indent=2,ensure_ascii=False))
    finally:
        if connection:connection.close()
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
