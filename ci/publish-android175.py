"""Publish the verified Android175 binary, then remove only authorized old APKs."""
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
TAG = 'v1.0.1+175'
NAME = 'MIAO_POS_1.0.1+175_LOCAL_STORAGE_R1.apk'
CERT = '01f72838bf9ed809aa8e641a1c8b0fedb8ccad590fba1b80333e3ce143e22d3b'
CONFIG = json.loads(Path('ci/android175-publication.json').read_text())


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


def release_notes():
    return '''旧 MIAO POS Android 1.0.1+175

修复连续营业后暂存/挂单保存越来越慢的问题：订单、挂单及 Pending 改为逐条持久化，避免每次重写全部历史记录。相关业务数据和 Pending 在同一事务内保存，并增加保存耗时日志。

保留离线营业、历史订单、收据、挂单、备份恢复、LAN 同步、云端同步及 174 的 Pending 恢复机制。首次启动自动迁移旧本地数据并保留原始迁移副本。不修改服务器营业数据。

沿用包名 com.yuepos.app 和原签名，覆盖安装；请勿卸载或清除数据。升级前请先导出完整备份。首次迁移耗时取决于原数据量。

175 开始产生营业数据后，请勿直接降级到 174：174 无法读取新的 SQLite 订单数据。

384 项 Flutter 自动测试及 10 项原生测试通过。包名、版本、原签名与 APK 校验值已核验；真实营业设备的覆盖安装和现场验收尚未完成。
''' + '\nSHA256: ' + CONFIG['sha256'] + '\n'


def verify_apk(path):
    sdk = Path(os.environ.get('ANDROID_HOME') or os.environ['ANDROID_SDK_ROOT'])
    bt = next(p for p in sorted((sdk / 'build-tools').iterdir(), reverse=True)
              if (p / 'aapt').is_file() and (p / 'apksigner').is_file())
    badging = subprocess.check_output([str(bt / 'aapt'), 'dump', 'badging', str(path)], text=True)
    match = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging)
    assert match and match.groups() == ('com.yuepos.app', '175', '1.0.1')
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
    subprocess.run(['git', 'fetch', '--depth=1', 'origin', 'refs/heads/transfer/android175-apk-20260919'], check=True)
    data = bytearray()
    for index in range(CONFIG['transfer_parts']):
        encoded = subprocess.check_output(['git', 'show', 'FETCH_HEAD:_transfer175/part-%03d.b64' % index])
        data.extend(base64.b64decode(encoded, validate=True))
        assert len(data) <= CONFIG['bytes'], 'Oversized APK transfer'
    assert len(data) == CONFIG['bytes'] and hashlib.sha256(data).hexdigest() == CONFIG['sha256']
    target = Path(NAME)
    target.write_bytes(data)
    verify_apk(target)
    Path('RELEASE_NOTES.md').write_text(release_notes())
    Path('SHA256SUMS.txt').write_text(CONFIG['sha256'] + '  ' + NAME + '\n')
    Path('ANDROID_175_RESULT.json').write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2) + '\n')
    release = next((r for r in api('releases?per_page=100') if r['tag_name'] == TAG), None)
    if release is None:
        subprocess.run(['gh', 'release', 'create', TAG, '--repo', REPO, '--target', os.environ['GITHUB_SHA'],
                        '--draft', '--title', 'MIAO POS Android 1.0.1+175',
                        '--notes-file', 'RELEASE_NOTES.md', NAME, 'SHA256SUMS.txt', 'ANDROID_175_RESULT.json'], check=True)
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
    assert metadata['latest_build'] in (174, 175), 'Concurrent newer release detected'
    metadata.update(latest_version='1.0.1', latest_build=175,
                    download_url=asset['browser_download_url'], sha256=CONFIG['sha256'],
                    file_size=CONFIG['bytes'], published_at=release['published_at'],
                    release_notes=[
                        '优化长期营业后的暂存/挂单保存：逐条写入本地 SQLite，避免重写全部历史订单。',
                        '订单与 Pending 原子保存，保留离线、备份、LAN/云端同步及旧数据自动迁移。',
                        '原签名覆盖安装，不卸载、不清数据；升级前导出备份，175 营业后不要直接降级。',
                        '自动测试和签名已核验，真实营业设备现场验收待完成。'])
    body = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode()
    api('contents/metadata/android-stable.json', {'message': 'release: enable verified Android 175 online update',
        'sha': current['sha'], 'content': base64.b64encode(body).decode(), 'branch': 'main'}, 'PUT')
    current = api('contents/index.html')
    html = base64.b64decode(current['content']).decode()
    old_url = 'https://github.com/myanmar001/miao-pos-releases/releases/download/v1.0.1%2B174/MIAO_POS_1.0.1%2B174_OWNER_CLEANUP_R1.apk'
    assert old_url in html or asset['browser_download_url'] in html
    updated = html.replace(old_url, asset['browser_download_url']).replace('Android 1.0.1+174', 'Android 1.0.1+175').replace('Android +174', 'Android +175')
    if updated != html:
        api('contents/index.html', {'message': 'release: point Android download fallback to verified 175',
            'sha': current['sha'], 'content': base64.b64encode(updated.encode()).decode(), 'branch': 'main'}, 'PUT')
    actual = json.loads(base64.b64decode(api('contents/metadata/android-stable.json')['content']))
    assert actual['latest_build'] == 175 and actual['sha256'] == CONFIG['sha256']
    print('ANDROID175_PUBLISHED=' + json.dumps({'url': release['html_url'], 'download_url': asset['browser_download_url'],
        'sha256': CONFIG['sha256'], 'bytes': CONFIG['bytes'], 'metadata_build': actual['latest_build']}))


def cleanup():
    metadata = json.loads(base64.b64decode(api('contents/metadata/android-stable.json')['content']))
    assert metadata['latest_build'] == 175 and metadata['sha256'] == CONFIG['sha256']
    read_public(metadata['download_url'])
    release174 = api('releases/tags/v1.0.1%2B174')
    assert any(a['name'] == 'MIAO_POS_1.0.1+174_OWNER_CLEANUP_R1.apk' and
               a['digest'] == 'sha256:2312fb69a359038d5681fe1ccccde5cb03ccb7ecf80bb8cc8ee155418f5eb436'
               for a in release174['assets'])
    deleted = []
    for expected in CONFIG['delete_old_apks']:
        try:
            asset = api('releases/assets/' + str(expected['id']))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        assert asset['name'] == expected['name'] and asset['size'] == expected['size']
        match = re.fullmatch(r'MIAO_POS_1\.0\.1\+(\d+)(?:_[A-Za-z0-9_]+)?\.apk', asset['name'])
        assert match and int(match.group(1)) < 174, 'Refusing to delete a retained version or non-APK'
        api('releases/assets/' + str(asset['id']), method='DELETE')
        deleted.append({'id': asset['id'], 'name': asset['name']})
    releases = api('releases?per_page=100')
    assert len(releases) < 100, 'Need to verify next page'
    remaining = [a['name'] for r in releases for a in r['assets'] if a['name'].lower().endswith('.apk')]
    assert sorted(remaining) == sorted(['MIAO_POS_1.0.1+174_OWNER_CLEANUP_R1.apk', NAME])
    print('OLD_APK_CLEANUP=' + json.dumps({'deleted': deleted, 'remaining_apks': remaining}, ensure_ascii=False))


if __name__ == '__main__':
    publish()
    cleanup()
