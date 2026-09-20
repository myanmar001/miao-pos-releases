"""Publish only the verified Android 176 APK and its online update metadata."""
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
TAG = 'v1.0.1+176'
NAME = 'MIAO_POS_1.0.1+176_PENDING_RECOVERY_R1.apk'
CERT = '01f72838bf9ed809aa8e641a1c8b0fedb8ccad590fba1b80333e3ce143e22d3b'
CONFIG = json.loads(Path('ci/android176/publication.json').read_text())


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
    return data


def publication_preflight():
    current = api('contents/metadata/android-stable.json')
    metadata = json.loads(base64.b64decode(current['content']))
    assert metadata['platform'] == 'android' and metadata['channel'] == 'stable'
    assert metadata['latest_version'] == '1.0.1'
    assert metadata['latest_build'] in (175, 176), 'Concurrent newer release detected'
    latest = api('releases/latest')
    tag = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)\+(\d+)', latest['tag_name'])
    assert tag, 'Unrecognized latest release tag; refusing to change latest'
    assert tuple(map(int, tag.groups())) <= (1, 0, 1, 176), 'Public latest is newer'


def release_notes():
    return '''旧 MIAO POS Android 1.0.1+176

修复商品已删除、本机缺少商品内容时待同步标记无法核对清除的问题。只有云端授权删除状态明确确认、且本机记录和门店未变化时，才清理对应残留标记；无删除证据、网络失败或有新修改时保留重试。单条异常不阻塞其他商品上传。

修复异常待同步订单清理页的窄屏布局，完整显示单号、金额、核对信息和操作按钮。

保留 175 的 SQLite 本地存储、离线营业、订单历史、备份、LAN 和云同步。沿用 com.yuepos.app 及原签名，覆盖安装，不卸载、不清数据。

自动检查通过：Flutter ''' + str(CONFIG['flutter_tests']) + ' 项、原生 ' + str(CONFIG['native_tests']) + ''' 项；APK 包名、版本、原签名及下载文件 SHA256 已核验。现场覆盖安装验证待用户完成。

SHA256: ''' + CONFIG['sha256'] + '\n'


def verify_apk(path):
    sdk = Path(os.environ.get('ANDROID_HOME') or os.environ['ANDROID_SDK_ROOT'])
    bt = next(p for p in sorted((sdk / 'build-tools').iterdir(), reverse=True)
              if (p / 'aapt').is_file() and (p / 'apksigner').is_file())
    badging = subprocess.check_output([str(bt / 'aapt'), 'dump', 'badging', str(path)], text=True)
    match = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging)
    assert match and match.groups() == ('com.yuepos.app', '176', '1.0.1')
    signer = subprocess.check_output([str(bt / 'apksigner'), 'verify', '--verbose', '--print-certs', str(path)], text=True)
    assert re.search(r'^Number of signers:\s*1\s*$', signer, re.M)
    certs = []
    for line in signer.splitlines():
        if 'certificate SHA-256 digest:' not in line or not re.search(r'\bSigner\b', line):
            continue
        match = re.fullmatch(r'.*\bSigner\b.*?certificate SHA-256 digest:\s*([0-9a-fA-F]{64})\s*', line)
        assert match, 'Malformed signer certificate line'
        certs.append(match[1].lower())
    assert certs and set(certs) == {CERT}, 'Wrong APK signer'
    independent = subprocess.check_output(['keytool', '-printcert', '-jarfile', str(path)], text=True)
    digests = [x.replace(':', '').lower() for x in re.findall(r'^\s*SHA256:\s*([0-9A-Fa-f:]+)\s*$', independent, re.M)]
    assert digests and set(digests) == {CERT}, 'Independent signer mismatch'


def publish():
    assert CONFIG['package'] == 'com.yuepos.app'
    assert CONFIG['version_code'] == 176 and CONFIG['version_name'] == '1.0.1'
    assert CONFIG['certificate_sha256'] == CERT
    assert CONFIG['flutter_tests'] >= 384 and CONFIG['native_tests'] == 10
    assert re.fullmatch(r'transfer/android176-apk-\d+', CONFIG['transfer_branch'])
    assert re.fullmatch(r'[0-9a-f]{40}', CONFIG['public_transfer_commit'])
    assert re.fullmatch(r'[0-9a-f]{64}', CONFIG['sha256'])
    subprocess.run(['git', 'fetch', '--depth=1', 'origin',
                    'refs/heads/' + CONFIG['transfer_branch']], check=True)
    actual_commit = subprocess.check_output(['git', 'rev-parse', 'FETCH_HEAD'], text=True).strip()
    assert actual_commit == CONFIG['public_transfer_commit'], 'Transfer branch changed'
    data = bytearray()
    for index in range(CONFIG['transfer_parts']):
        encoded = subprocess.check_output(['git', 'show', 'FETCH_HEAD:_transfer176/part-%03d.b64' % index])
        data.extend(base64.b64decode(encoded, validate=True))
        assert len(data) <= CONFIG['bytes'], 'Oversized APK transfer'
    assert len(data) == CONFIG['bytes'] and hashlib.sha256(data).hexdigest() == CONFIG['sha256']
    target = Path(NAME)
    target.write_bytes(data)
    verify_apk(target)
    Path('RELEASE_NOTES.md').write_text(release_notes())
    Path('SHA256SUMS.txt').write_text(CONFIG['sha256'] + '  ' + NAME + '\n')
    Path('ANDROID_176_RESULT.json').write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2) + '\n')
    publication_preflight()
    release = next((r for r in api('releases?per_page=100') if r['tag_name'] == TAG), None)
    if release is None:
        subprocess.run(['gh', 'release', 'create', TAG, '--repo', REPO, '--target', os.environ['GITHUB_SHA'],
                        '--draft', '--title', 'MIAO POS Android 1.0.1+176',
                        '--notes-file', 'RELEASE_NOTES.md', NAME, 'SHA256SUMS.txt', 'ANDROID_176_RESULT.json'], check=True)
        release = next(r for r in api('releases?per_page=100') if r['tag_name'] == TAG)
    asset = next(a for a in release['assets'] if a['name'] == NAME)
    assert asset['size'] == CONFIG['bytes'] and asset['digest'] == 'sha256:' + CONFIG['sha256']
    if release['draft']:
        release = api('releases/' + str(release['id']), {'draft': False, 'prerelease': False, 'make_latest': 'true'}, 'PATCH')
    # Publishing replaces the draft's untagged download URLs with tag URLs.
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
    assert metadata['platform'] == 'android' and metadata['channel'] == 'stable'
    assert metadata['latest_build'] in (175, 176), 'Concurrent newer release detected'
    metadata.update(latest_version='1.0.1', latest_build=176,
                    download_url=asset['browser_download_url'], sha256=CONFIG['sha256'],
                    file_size=CONFIG['bytes'], published_at=release['published_at'],
                    release_notes=[
                        '修复已删除商品的本机待同步残留，经云端授权核对后自动清理。',
                        '保留未确认和新修改数据，单条异常不阻塞其他商品上传。',
                        '修复异常订单清理页面宽度和按钮布局。',
                        '保留 175 的订单和 SQLite 数据；沿用原签名覆盖安装。'])
    body = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode()
    api('contents/metadata/android-stable.json', {'message': 'release: enable verified Android 176 online update',
        'sha': current['sha'], 'content': base64.b64encode(body).decode(), 'branch': 'main'}, 'PUT')
    current = api('contents/index.html')
    html = base64.b64decode(current['content']).decode()
    old_url = 'https://github.com/myanmar001/miao-pos-releases/releases/download/v1.0.1%2B175/MIAO_POS_1.0.1%2B175_LOCAL_STORAGE_R1.apk'
    assert old_url in html or asset['browser_download_url'] in html
    updated = html.replace(old_url, asset['browser_download_url']).replace('Android 1.0.1+175', 'Android 1.0.1+176').replace('Android +175', 'Android +176')
    if updated != html:
        api('contents/index.html', {'message': 'release: point Android download fallback to verified 176',
            'sha': current['sha'], 'content': base64.b64encode(updated.encode()).decode(), 'branch': 'main'}, 'PUT')
    actual = json.loads(base64.b64decode(api('contents/metadata/android-stable.json')['content']))
    assert actual['latest_build'] == 176 and actual['sha256'] == CONFIG['sha256']
    print('ANDROID176_PUBLISHED=' + json.dumps({'url': release['html_url'], 'download_url': asset['browser_download_url'],
        'sha256': CONFIG['sha256'], 'bytes': CONFIG['bytes'], 'metadata_build': actual['latest_build']}))



if __name__ == '__main__':
    publish()
