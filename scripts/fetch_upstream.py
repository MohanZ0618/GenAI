"""Fetch a fixed public FinRCA source revision; never overwrite local changes."""
from pathlib import Path
import io, urllib.request, zipfile

SHA = '76c93ec32536e29826e2ab9e68b58e0351410bc7'
target = Path(__file__).resolve().parents[1] / 'packages/data/upstream'
if target.exists():
    raise SystemExit('Upstream folder already exists; refusing to overwrite it.')
url = f'https://codeload.github.com/PratikGhawate/FinRCA-AI-Bench/zip/{SHA}'
with urllib.request.urlopen(url, timeout=60) as response:
    archive = zipfile.ZipFile(io.BytesIO(response.read()))
for item in archive.infolist():
    relative = Path(*Path(item.filename).parts[1:])
    if not relative.parts or '..' in relative.parts:
        continue
    if relative.parts[0] not in {'src','tests','docs'} and str(relative) not in {'LICENSE','README.md','requirements.txt','config.yaml','generate_finrca_bench.py'}:
        continue
    destination = target / relative
    if item.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(item))
(target / 'UPSTREAM_COMMIT').write_text(SHA + '\n', encoding='utf-8')
print(f'Fetched pinned FinRCA source: {SHA}')
