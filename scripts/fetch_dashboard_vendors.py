"""Fetch pinned frontend packages, verify registry SHA512, copy only named assets."""
import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
PACKAGES={'leaflet':'1.9.4','chart.js':'4.4.7'}


def main():
    manifest=[]
    for name,version in PACKAGES.items():
        with urlopen('https://registry.npmjs.org/'+name+'/'+version,timeout=45) as response:
            metadata=json.load(response)
        url=metadata['dist']['tarball']
        if not url.startswith('https://registry.npmjs.org/'):
            raise ValueError('Unexpected package host')
        with urlopen(url,timeout=60) as response: archive=response.read()
        integrity='sha512-'+base64.b64encode(hashlib.sha512(archive).digest()).decode()
        if integrity!=metadata['dist']['integrity']: raise ValueError('Package integrity mismatch')
        base=ROOT/'static/v2/vendor'/('leaflet' if name=='leaflet' else 'chartjs')
        files=['dist/leaflet.js','dist/leaflet.css','LICENSE'] if name=='leaflet' else ['dist/chart.umd.js','LICENSE.md']
        with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as package:
            if name=='leaflet':
                files += [m.name.removeprefix('package/') for m in package.getmembers()
                          if m.isfile() and m.name.startswith('package/dist/images/')]
            entries=[]
            for relative in files:
                content=package.extractfile('package/'+relative).read()
                target=base/relative.removeprefix('dist/')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(content)
                entries.append({'path':str(target.relative_to(ROOT)),'sha256':hashlib.sha256(content).hexdigest()})
        manifest.append({'package':name,'version':version,'url':url,'registry_integrity':integrity,'files':entries})
    (ROOT/'static/v2/vendor/manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print('Pinned local Leaflet and Chart.js packages verified and copied')


if __name__=='__main__':main()
