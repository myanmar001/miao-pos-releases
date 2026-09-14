"""Promote the original Windows171 binaries only after anonymous byte checks."""
import base64
import datetime
import hashlib
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = 'myanmar001/miao-pos-releases'
RELEASE = 388532800
TAG = 'v1.0.1+171'
API = 'https://api.github.com/repos/' + REPO
ROOT = pathlib.Path('ci/windows171-publication')
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
    for attempt in range(3):
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Creation and branch movement are not blindly repeated.
            if method != 'GET' or error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def content(path, ref):
    value = api('/contents/' + path + '?ref=' + urllib.parse.quote(ref, safe=''))
    assert value['encoding'] == 'base64'
    return base64.b64decode(value['content']).decode('utf-8')


def verify_public(asset, expected):
    assert asset['state'] == 'uploaded' and asset['size'] == expected['size']
    assert asset['digest'] == 'sha256:' + expected['sha256']
    url = ('https://github.com/' + REPO + '/releases/download/' +
           urllib.parse.quote(TAG, safe='') + '/' + urllib.parse.quote(expected['name'], safe=''))
    assert asset['browser_download_url'] == url
    # No authorization header is sent on this public download or its redirects.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                raw = response.read(expected['size'] + 1)
            assert len(raw) == expected['size'], 'Public download size mismatch'
            assert hashlib.sha256(raw).hexdigest() == expected['sha256'], 'Public download hash mismatch'
            return url
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2: raise
            time.sleep(3 * (attempt + 1))


def ensure_website_portable_alias(original):
    # The existing live website builds this stable filename from the version.
    name = 'MIAO_POS_Windows_1.0.1+171_Portable.zip'
    expected = dict(original, name=name)
    def find():
        matches = [a for a in api('/releases/' + str(RELEASE) + '/assets?per_page=100') if a['name'] == name]
        assert len(matches) <= 1
        return matches[0] if matches else None
    alias = find()
    if alias is None:
        with urllib.request.urlopen(original['download_url'], timeout=90) as response:
            raw = response.read(original['size'] + 1)
        assert len(raw) == original['size'] and hashlib.sha256(raw).hexdigest() == original['sha256']
        url = 'https://uploads.github.com/repos/' + REPO + '/releases/' + str(RELEASE) + '/assets?name=' + urllib.parse.quote(name, safe='')
        request = urllib.request.Request(url, method='POST', data=raw,
            headers=dict(HEADERS, **{'Content-Type': 'application/zip'}))
        for attempt in range(3):
            try:
                with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
                    alias = json.load(response)
                break
            except urllib.error.HTTPError as error:
                # Resolve a possibly completed upload before any retry.
                alias = find()
                if alias is not None: break
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2: raise
                time.sleep(3 * (attempt + 1))
    url = verify_public(alias, expected)
    return dict(expected, asset_id=alias['id'], download_url=url)


def main():
    release = api('/releases/' + str(RELEASE))
    assert release['tag_name'] == TAG and not release['draft'] and not release['prerelease']
    assets = api('/releases/' + str(RELEASE) + '/assets?per_page=100')
    android = [a for a in assets if a['id'] == 563740567]
    assert len(android) == 1 and android[0]['digest'] == 'sha256:3cb08e804aaaf11a141984ce3f14d46a6110263d69e84053003681d9ac1c717c'
    specs = json.loads((ROOT/'ASSETS.json').read_text())
    by_name = {a['name']: a for a in assets}
    assert len(by_name) == len(assets), 'Duplicate release attachment names'
    missing = [a['name'] for a in specs if a['name'] not in by_name]
    if missing:
        result = {'status': 'awaiting_original_windows_attachments', 'release_id': RELEASE,
                  'edit_url': 'https://github.com/' + REPO + '/releases/edit/v1.0.1%2B171',
                  'missing': missing, 'rebuilt': False, 'stable_metadata_changed': False}
        print('WINDOWS_171_PUBLICATION=' + json.dumps(result))
        return
    verified = []
    for expected in specs:
        asset = by_name[expected['name']]
        url = verify_public(asset, expected)
        verified.append(dict(expected, asset_id=asset['id'], download_url=url))
    portable = next(a for a in verified if a['name'].endswith('_Portable.zip'))
    website_portable = ensure_website_portable_alias(portable)

    head = api('/git/ref/heads/main')['object']['sha']
    parent = api('/git/commits/' + head)
    old_windows = json.loads(content('metadata/windows-stable.json', head))
    android_text = content('metadata/android-stable.json', head)
    android_meta = json.loads(android_text)
    assert android_meta['latest_build'] == 171 and android_meta['sha256'] == android[0]['digest'][7:]
    assert old_windows['latest_build'] in (159, 171), 'Windows stable changed; review required'
    assert old_windows['platform'] == 'windows' and old_windows['channel'] == 'stable'
    assert old_windows['minimum_supported_build'] == 149 and old_windows['update_level'] == 'normal'
    setup = next(a for a in verified if a['name'].endswith('_Setup.exe'))
    template = json.loads((ROOT/'WINDOWS_STABLE_TEMPLATE.json').read_text())
    template['published_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
    assert template['download_url'] == setup['download_url'] and template['sha256'] == setup['sha256']
    old_index = content('index.html', head)
    old_url = 'https://github.com/' + REPO + '/releases/download/v1.0.1%2B159/MIAO_POS_Windows_1.0.1%2B159_Setup.exe'
    assert old_url in old_index or setup['download_url'] in old_index, 'Windows fallback changed; review required'
    new_index = old_index.replace(old_url, setup['download_url']).replace('Windows +159', 'Windows +171')
    new_index = new_index.replace('id="winText">下载最新版 Windows 安装程序', 'id="winText">Windows 1.0.1+171')
    result = {'status': 'stable_windows171_published', 'release_id': RELEASE,
              'release_url': release['html_url'], 'original_build': 34869701668,
              'original_commit': '4fa54fb804da7f3f74ed4d87f05802f41980bb70',
              'rebuilt': False, 'public_download_verified': True, 'assets': verified,
              'website_portable_alias': website_portable,
              'published_at': template['published_at'], 'workflow_run': os.environ['GITHUB_RUN_ID'],
              'stable_android_build': 171, 'stable_windows_build': 171}
    notes = (ROOT/'RELEASE_NOTES.md').read_text(encoding='utf-8')
    api('/releases/' + str(RELEASE), 'PATCH', {'name': 'MIAO POS Android / Windows 1.0.1+171', 'body': notes})
    if old_windows['latest_build'] == 171:
        assert old_windows['sha256'] == setup['sha256'] and old_windows['download_url'] == setup['download_url']
        assert old_windows['file_size'] == setup['size'] and old_index == new_index
        result.update(stable_metadata_changed=False, stable_commit=head, published_at=old_windows['published_at'])
    else:
        entries = [
            {'path': 'metadata/windows-stable.json', 'mode': '100644', 'type': 'blob', 'content': json.dumps(template, ensure_ascii=False, indent=2)+'\n'},
            {'path': 'index.html', 'mode': '100644', 'type': 'blob', 'content': new_index},
            {'path': 'metadata/windows171-publication.json', 'mode': '100644', 'type': 'blob', 'content': json.dumps(result, indent=2)+'\n'},
        ]
        tree = api('/git/trees', 'POST', {'base_tree': parent['tree']['sha'], 'tree': entries})
        commit = api('/git/commits', 'POST', {'message': 'release(windows171): promote verified original Setup and Portable', 'tree': tree['sha'], 'parents': [head]})
        # A concurrent main update must fail instead of being overwritten.
        api('/git/refs/heads/main', 'PATCH', {'sha': commit['sha'], 'force': False})
        result.update(stable_metadata_changed=True, stable_commit=commit['sha'])
    final = json.loads(content('metadata/windows-stable.json', 'main'))
    assert final['latest_build'] == 171 and final['sha256'] == setup['sha256']
    assert content('metadata/android-stable.json', 'main') == android_text
    assert content('index.html', 'main') == new_index
    print('WINDOWS_171_PUBLICATION=' + json.dumps(result))


if __name__ == '__main__':
    main()
