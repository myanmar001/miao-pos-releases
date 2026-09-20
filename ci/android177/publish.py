"""Publish verified Android 177, preserve 176, and remove only older APK assets."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = 'myanmar001/miao-pos-releases'
TAG = 'v1.0.1+177'
NAME = 'MIAO_POS_1.0.1+177_SYNC_THROTTLE_R1.apk'
CERT = '01f72838bf9ed809aa8e641a1c8b0fedb8ccad590fba1b80333e3ce143e22d3b'
CONFIG = json.loads(Path('ci/android177/publication.json').read_text())


def api(path, data=None, method='GET'):
    request = urllib.request.Request(
        'https://api.github.com/repos/' + REPO + '/' + path,
        data=None if data is None else json.dumps(data).encode(), method=method,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def read_public(url):
    assert urllib.parse.urlparse(url).scheme == 'https'
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read(CONFIG['bytes'] + 1)
    assert len(data) == CONFIG['bytes'], 'APK byte count mismatch'
    assert hashlib.sha256(data).hexdigest() == CONFIG['sha256'], 'APK SHA256 mismatch'


def verify_apk(path):
    sdk = Path(os.environ.get('ANDROID_HOME') or os.environ['ANDROID_SDK_ROOT'])
    bt = next(p for p in sorted((sdk / 'build-tools').iterdir(), reverse=True)
              if (p / 'aapt').is_file() and (p / 'apksigner').is_file())
    badging = subprocess.check_output([str(bt / 'aapt'), 'dump', 'badging', str(path)], text=True)
    match = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging)
    assert match and match.groups() == ('com.yuepos.app', '177', '1.0.1')
    signer = subprocess.check_output(
        [str(bt / 'apksigner'), 'verify', '--verbose', '--print-certs', str(path)], text=True)
    assert re.search(r'^Number of signers:\s*1\s*$', signer, re.M)
    certs = []
    for line in signer.splitlines():
        if 'certificate SHA-256 digest:' not in line or not re.search(r'\bSigner\b', line):
            continue
        digest = re.fullmatch(
            r'.*\bSigner\b.*?certificate SHA-256 digest:\s*([0-9a-fA-F]{64})\s*', line)
        assert digest, 'Malformed signer certificate line'
        certs.append(digest[1].lower())
    assert certs and set(certs) == {CERT}, 'Wrong APK signer'
    independent = subprocess.check_output(['keytool', '-printcert', '-jarfile', str(path)], text=True)
    digests = [x.replace(':', '').lower()
               for x in re.findall(r'^\s*SHA256:\s*([0-9A-Fa-f:]+)\s*$', independent, re.M)]
    assert digests and set(digests) == {CERT}, 'Independent signer mismatch'


def release_notes():
    return '''旧 MIAO POS Android 1.0.1+177

降低 Cloudflare 请求量，修复挂单业务 400 后高频重试和空闲状态后台轮询过密。确定性业务错误进入等待核对状态；网络错误逐步退避；相同同步触发合并，空闲游标检查逐级延长。

不改变销售、打印、UI、税务、商品业务逻辑。保留 176 的本地数据、离线营业、订单历史、备份、LAN 和云同步。沿用 com.yuepos.app 及原签名，覆盖安装，不卸载、不清数据。

自动检查通过：Flutter/SQLite ''' + str(CONFIG['flutter_tests']) + ' 项、原生 ' + str(CONFIG['native_tests']) + ''' 项；APK 包名、版本、原签名及下载文件 SHA256 已核验。Cloudflare 24 小时实际降幅需安装 177 后观察。

SHA256: ''' + CONFIG['sha256'] + '\n'


def publication_preflight():
    current = api('contents/metadata/android-stable.json')
    metadata = json.loads(base64.b64decode(current['content']))
    assert metadata['platform'] == 'android' and metadata['channel'] == 'stable'
    assert metadata['latest_version'] == '1.0.1' and metadata['latest_build'] in (176, 177)
    latest = api('releases/latest')
    tag = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)\+(\d+)', latest['tag_name'])
    assert tag and tuple(map(int, tag.groups())) <= (1, 0, 1, 177), 'Concurrent newer release detected'


def delete_older_android_packages(releases):
    removed = []
    for release in releases:
        match = re.fullmatch(r'v1\.0\.1\+(\d+)', release['tag_name'])
        if not match or int(match[1]) >= 176:
            continue
        for asset in release['assets']:
            if asset['name'].lower().endswith('.apk'):
                api('releases/assets/' + str(asset['id']), method='DELETE')
                removed.append(release['tag_name'] + '/' + asset['name'])
    assert all(not item.startswith('v1.0.1+176/') for item in removed)
    return removed


def publish():
    assert CONFIG['package'] == 'com.yuepos.app'
    assert CONFIG['version_code'] == 177 and CONFIG['version_name'] == '1.0.1'
    assert CONFIG['certificate_sha256'] == CERT
    assert CONFIG['flutter_tests'] == 484 and CONFIG['native_tests'] == 10
    assert re.fullmatch(r'transfer/android177-apk-\d+', CONFIG['transfer_branch'])
    assert re.fullmatch(r'[0-9a-f]{40}', CONFIG['public_transfer_commit'])
    assert re.fullmatch(r'[0-9a-f]{64}', CONFIG['sha256'])
    Path('RELEASE_NOTES.md').write_text(release_notes())
    Path('SHA256SUMS.txt').write_text(CONFIG['sha256'] + '  ' + NAME + '\n')
    Path('ANDROID_177_RESULT.json').write_text(
        json.dumps(CONFIG, ensure_ascii=False, indent=2) + '\n')
    publication_preflight()

    releases = api('releases?per_page=100')
    release = next((r for r in releases if r['tag_name'] == TAG), None)
    assert release is not None and release['draft'], 'Expected the user-uploaded 177 draft release'
    asset = next(a for a in release['assets'] if a['name'] == NAME)
    assert asset['size'] == CONFIG['bytes'] and asset['digest'] == 'sha256:' + CONFIG['sha256']
    if release['draft']:
        release = api('releases/' + str(release['id']),
                      {'draft': False, 'prerelease': False, 'make_latest': 'true'}, 'PATCH')
    asset = next(a for a in release['assets'] if a['name'] == NAME)
    assert asset['size'] == CONFIG['bytes'] and asset['digest'] == 'sha256:' + CONFIG['sha256']
    for attempt in range(6):
        try:
            read_public(asset['browser_download_url'])
            break
        except urllib.error.HTTPError as error:
            if error.code != 404 or attempt == 5:
                raise
            time.sleep(3)
    assert api('releases/latest')['tag_name'] == TAG

    current = api('contents/metadata/android-stable.json')
    metadata = json.loads(base64.b64decode(current['content']))
    assert metadata['latest_build'] in (176, 177), 'Concurrent newer metadata detected'
    metadata.update(
        latest_version='1.0.1', latest_build=177,
        download_url=asset['browser_download_url'], sha256=CONFIG['sha256'],
        file_size=CONFIG['bytes'], published_at=release['published_at'],
        release_notes=[
            '降低 Cloudflare 请求量，合并重复同步触发并延长空闲轮询。',
            '修复挂单业务 400 后高频重试；网络失败采用逐步退避。',
            '保留销售、打印、UI、税务和商品业务逻辑不变。',
            '保留 176 数据并沿用原签名，可直接覆盖安装。'])
    body = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode()
    api('contents/metadata/android-stable.json', {
        'message': 'release: enable verified Android 177 online update',
        'sha': current['sha'], 'content': base64.b64encode(body).decode(), 'branch': 'main'}, 'PUT')

    current = api('contents/index.html')
    html = base64.b64decode(current['content']).decode()
    old_url = 'https://github.com/myanmar001/miao-pos-releases/releases/download/v1.0.1%2B176/MIAO_POS_1.0.1%2B176_PENDING_RECOVERY_R1.apk'
    assert old_url in html or asset['browser_download_url'] in html
    updated = (html.replace(old_url, asset['browser_download_url'])
               .replace('Android 1.0.1+176', 'Android 1.0.1+177')
               .replace('Android +176', 'Android +177'))
    if updated != html:
        api('contents/index.html', {
            'message': 'release: point Android download fallback to verified 177',
            'sha': current['sha'], 'content': base64.b64encode(updated.encode()).decode(),
            'branch': 'main'}, 'PUT')

    removed = delete_older_android_packages(api('releases?per_page=100'))
    assert api('releases/tags/v1.0.1%2B176')['tag_name'] == 'v1.0.1+176'
    actual = json.loads(base64.b64decode(api('contents/metadata/android-stable.json')['content']))
    assert actual['latest_build'] == 177 and actual['sha256'] == CONFIG['sha256']
    print('ANDROID177_PUBLISHED=' + json.dumps({
        'url': release['html_url'], 'download_url': asset['browser_download_url'],
        'sha256': CONFIG['sha256'], 'bytes': CONFIG['bytes'],
        'metadata_build': actual['latest_build'], 'removed_apks': removed}))


if __name__ == '__main__':
    publish()
