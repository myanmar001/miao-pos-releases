"""Publish only the accepted original APK. Never compile or change stable feeds."""
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

REPO = 'myanmar001/miao-pos-releases'
TAG = 'v1.0.1+170'
NAME = 'MIAO_POS_1.0.1+170_HISTORY_ORDER_RECOVERY_R1.apk'
SIZE = 33576309
SHA = 'ba35c41e2c870fd398d1ba77106ee2229d0f65550e83d5664dc9f6ba729b11c0'
BASE = '00125ec2d579a0ab40d94b72db02795f79927a4c'
API = 'https://api.github.com/repos/' + REPO
assert os.environ['GITHUB_REPOSITORY'] == REPO
HEADERS = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
           'Accept': 'application/vnd.github+json',
           'X-GitHub-Api-Version': '2022-11-28'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(path, method='GET', data=None):
    request = urllib.request.Request(API + path, method=method, headers=HEADERS,
        data=None if data is None else json.dumps(data).encode())
    # Non-idempotent creation is retried only after resolving its result.
    for attempt in range(3):
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=40) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if method == 'POST' or error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def verify(raw):
    assert len(raw) == SIZE and hashlib.sha256(raw).hexdigest() == SHA, 'Original APK bytes mismatch'
    return raw


def download_asset(asset):
    assert asset['name'] == NAME and asset['state'] == 'uploaded'
    assert asset['size'] == SIZE and asset['digest'] == 'sha256:' + SHA
    request = urllib.request.Request(API + '/releases/assets/' + str(asset['id']),
        headers=dict(HEADERS, Accept='application/octet-stream'))
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            return verify(response.read(SIZE + 1))
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 307, 308):
            raise
        # Repository credential is not forwarded to the binary host.
        with urllib.request.urlopen(error.headers['Location'], timeout=90) as response:
            return verify(response.read(SIZE + 1))


def find_release():
    matches = [r for r in api('/releases?per_page=100') if r['tag_name'] == TAG]
    assert len(matches) <= 1, 'Duplicate release tags'
    return matches[0] if matches else None


def find_asset(release):
    matches = [a for a in api('/releases/' + str(release['id']) + '/assets?per_page=100')
               if a['name'] == NAME]
    assert len(matches) <= 1, 'Duplicate APK names'
    return matches[0] if matches else None


notes = pathlib.Path('ci/android170/RELEASE_NOTES.md').read_text()
release = find_release()
for attempt in range(3):
    if release:
        break
    try:
        release = api('/releases', 'POST', {'tag_name': TAG, 'target_commitish': BASE,
            'name': 'MIAO POS Android 1.0.1+170', 'body': notes,
            'draft': True, 'prerelease': False, 'make_latest': 'false'})
    except urllib.error.HTTPError as error:
        release = find_release()
        if not release and (error.code not in (429, 500, 502, 503, 504) or attempt == 2):
            raise
        time.sleep(2 * (attempt + 1))
assert release and release['tag_name'] == TAG

asset = find_asset(release)
if not asset:
    assert release['draft'], 'Published release has no original APK'
    result = {'status': 'awaiting_original_apk_attachment',
        'release_id': release['id'], 'release_url': release['html_url'],
        'expected_filename': NAME, 'sha256': SHA, 'size_bytes': SIZE,
        'apk_rebuilt': False, 'stable_metadata_changed': False}
    print('ANDROID_170_PUBLIC_RELEASE=' + json.dumps(result))
    raise SystemExit(0)

# Attachment must be byte-identical to the accepted private original.
download_asset(asset)
release = api('/releases/' + str(release['id']), 'PATCH',
    {'draft': False, 'prerelease': False, 'make_latest': 'true', 'body': notes})
assert not release['draft'] and not release['prerelease']
latest = api('/releases/latest')
assert latest['id'] == release['id'] and latest['tag_name'] == TAG
asset = find_asset(release)
# Validate the public URL with no Authorization header after publication.
with urllib.request.urlopen(asset['browser_download_url'], timeout=90) as response:
    verify(response.read(SIZE + 1))
result = {'status': 'stable_original_apk_published', 'release_id': release['id'],
    'release_url': release['html_url'], 'asset_id': asset['id'],
    'download_url': asset['browser_download_url'], 'sha256': SHA, 'size_bytes': SIZE,
    'public_download_verified': True, 'original_build': 34852370108,
    'apk_rebuilt': False, 'stable_metadata_changed': False}
print('ANDROID_170_PUBLIC_RELEASE=' + json.dumps(result))
