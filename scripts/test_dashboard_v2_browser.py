"""Real browser checks against local Flask, blocking external HTTPS resources."""
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
    directory=ROOT/'reports/dashboard_v2_preview'; directory.mkdir(exist_ok=True)
    profile=ROOT/'data/sync_runtime/dashboard_browser'/uuid.uuid4().hex
    process=subprocess.Popen(['C:/Program Files/Google/Chrome/Application/chrome.exe',
        '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--disable-background-networking','--disable-component-update','--disable-extensions',
        '--remote-debugging-port=9227','--remote-allow-origins=http://127.0.0.1:9227',
        '--user-data-dir='+str(profile),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    connection=None; results=[]; command_id=0
    try:
        deadline=time.monotonic()+15
        while True:
            try:
                with urlopen('http://127.0.0.1:9227/json/list',timeout=2) as response: targets=json.load(response)
                target=next(t for t in targets if t['type']=='page'); break
            except Exception:
                if time.monotonic()>deadline: raise
                time.sleep(.2)
        connection=websocket.create_connection(target['webSocketDebuggerUrl'],origin='http://127.0.0.1:9227',timeout=15)
        def command(method,params=None):
            nonlocal command_id
            command_id+=1; expected=command_id
            connection.send(json.dumps({'id':expected,'method':method,'params':params or {}}))
            while True:
                message=json.loads(connection.recv())
                if message.get('id')==expected:
                    if 'error' in message: raise RuntimeError(str(message['error']))
                    return message.get('result',{})
        def evaluate(expression):
            result=command('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in result: raise RuntimeError(str(result['exceptionDetails']))
            return result['result'].get('value')
        def wait_state(expected):
            until=time.monotonic()+15
            while time.monotonic()<until:
                try:
                    if evaluate('document.documentElement.dataset.loadState')==expected: return
                except RuntimeError: pass
                time.sleep(.15)
            raise RuntimeError('Browser state did not become '+expected)
        def capture(name):
            metrics=evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,state:document.documentElement.dataset.loadState,mean:document.getElementById("meanValue").textContent,station:document.getElementById("station").value,source:document.getElementById("source").value,chart:!!Chart.getChart("pmChart"),map:!!document.querySelector(".leaflet-pane"),disabled:document.querySelector(".disabled-badge").textContent,external:performance.getEntriesByType("resource").filter(r=>r.name.startsWith("https:")).length})')
            assert metrics['scrollWidth']<=metrics['width'], 'Horizontal viewport overflow: '+str(metrics)
            assert metrics['map'] and metrics['disabled']=='DESHABILITADO' and metrics['external']==0
            image=command('Page.captureScreenshot',{'format':'png'})['data']
            (directory/(name+'.png')).write_bytes(base64.b64decode(image))
            (directory/(name+'.html')).write_text(evaluate('document.documentElement.outerHTML'),encoding='utf8')
            results.append({'view':name,**metrics})
        command('Page.enable'); command('Runtime.enable'); command('Network.enable')
        command('Network.setBlockedURLs',{'urls':['https://*']})
        for name,width,mobile in [('desktop',1440,False),('mobile',390,True)]:
            command('Emulation.setDeviceMetricsOverride',{'width':width,'height':1100,'deviceScaleFactor':1,'mobile':mobile})
            command('Page.navigate',{'url':'http://127.0.0.1:5055/v2/datos'})
            wait_state('ready'); capture(name)
        evaluate('document.getElementById("source").value="OpenAQ-Archive";document.getElementById("source").dispatchEvent(new Event("change"))')
        wait_state('ready'); capture('archive-mobile')
        assert evaluate('document.getElementById("period").value')=='all'
        assert evaluate('Chart.getChart("pmChart").data.datasets.every(s=>s.data.every(p=>p.observation.gap || p.observation.source==="OpenAQ-Archive"))')
        evaluate('document.getElementById("station").value="1352719";document.getElementById("station").dispatchEvent(new Event("change"))')
        wait_state('ready'); capture('empty')
        assert evaluate('document.getElementById("meanValue").textContent')=='—'
        assert not evaluate('!!Chart.getChart("pmChart")')
        command('Network.setBlockedURLs',{'urls':['https://*','*api/v2/observations*']})
        evaluate('document.getElementById("refresh").click()')
        wait_state('error'); capture('error')
        assert not evaluate('document.getElementById("error").hidden')
        report={'successful':True,'checks':results,'external_https_blocked':True,'manual_sync_calls':0}
        (directory/'browser_checks.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report,indent=2))
    finally:
        if connection: connection.close()
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__=='__main__':main()
