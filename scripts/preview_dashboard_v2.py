"""Capture local headless previews with an existing Chrome. No ingestion calls."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    browser=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not browser.is_file(): raise FileNotFoundError('Chrome not installed; no browser installation attempted')
    output=ROOT/'reports/dashboard_v2_preview';output.mkdir(exist_ok=True)
    results=[]
    for name,size,query in [('desktop','1440,1100',''),('mobile','390,1080',''),
                             ('archive','1440,1100','?source=OpenAQ-Archive&period=all'),
                             ('empty','390,1080','?station=1352719')]:
        profile=ROOT/'data/sync_runtime/dashboard_preview'/name
        command=[str(browser),'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
                 '--disable-background-networking','--disable-extensions','--disable-component-update',
                 '--user-data-dir='+str(profile),'--window-size='+size,'--virtual-time-budget=6000',
                 '--screenshot='+str(output/(name+'.png')),'--dump-dom','http://127.0.0.1:5055/v2'+query]
        completed=subprocess.run(command,capture_output=True,timeout=60)
        dom=completed.stdout.decode('utf8',errors='replace')
        (output/(name+'.html')).write_text(dom,encoding='utf8')
        state='ready' if 'data-load-state="ready"' in dom else 'error'
        results.append({'view':name,'size':size,'state':state,'exit_code':completed.returncode,
                        'screenshot':str(output/(name+'.png')),
                        'leaflet_initialized':'leaflet-pane' in dom,
                        'chart_rendered':'box-sizing: border-box; height:' in dom})
    (output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    print(json.dumps(results,indent=2))
    if any(r['state']!='ready' for r in results): raise RuntimeError('Browser view did not load successfully')


if __name__=='__main__': main()
