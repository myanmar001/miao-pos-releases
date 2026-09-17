"""Publish only the user-authorized, already-tested original-signature APK."""
import base64,datetime,hashlib,json,os,pathlib,re,subprocess,urllib.parse,urllib.request
REPO='myanmar001/miao-pos-releases'
assert os.environ['GITHUB_REPOSITORY']==REPO
proof=json.loads(pathlib.Path('release-input.json').read_text())
assert proof['package']=='com.yuepos.app' and proof['version_code']==174
assert proof['build_commit']=='2674f5a4795fabb30a07ba9626c995e3ad5e5c6c'
assert proof['targeted_tests']>=18 and proof['full_tests']>=309
assert proof['native_tests']=={'tests':10,'failures':0,'errors':0}
assert proof['certificate_sha256']=='01f72838bf9ed809aa8e641a1c8b0fedb8ccad590fba1b80333e3ce143e22d3b'
url=urllib.parse.urlsplit(proof['transfer_url'])
assert url.scheme=='https' and url.hostname == 'github.com' and url.path == '/myanmar001/miao-pos-releases/releases/download/v1.0.1%2B174/MIAO_POS_1.0.1%2B174_OWNER_CLEANUP_R1.apk' and not url.username
name='MIAO_POS_1.0.1+174_OWNER_CLEANUP_R1.apk'
assert proof['asset_name']==name
# The file-only CDN request carries no repository token.
with urllib.request.urlopen(proof['transfer_url'],timeout=120) as response:data=response.read(proof['bytes']+1)
assert len(data)==proof['bytes'] and hashlib.sha256(data).hexdigest()==proof['sha256']
apk=pathlib.Path(name);apk.write_bytes(data)
certificate=subprocess.check_output(['keytool','-printcert','-jarfile',str(apk)],text=True)
certs=[s.replace(':','').lower() for s in re.findall(r'^\s*SHA256:\s*([0-9A-Fa-f:]+)\s*$',certificate,re.M)]
assert certs and set(certs)=={proof['certificate_sha256']}
def gh(*args):
 return subprocess.check_output(['gh',*args],text=True)
def api(path):return json.loads(gh('api','repos/'+REPO+'/'+path))
metadata=api('contents/metadata/android-stable.json?ref=main')
current=json.loads(base64.b64decode(metadata['content']))
assert current['latest_build']<=174,'A newer release already exists; do not downgrade'
if current['latest_build']==174:assert current['sha256']==proof['sha256'],'Do not replace a different 174 build'
notes='''旧 MIAO POS Android 1.0.1+174

新增老板专用入口：设置 → 数据同步状态 → 异常待同步清理。

支持核对并逐条清理无商品明细、尚未上传且符合保护条件的异常订单及关联挂单状态。显示单号、金额、时间和实际唯一编号，填写原因并确认；须联网完成云端权限校验和审计留档后才清理本机。

同店其他已升级设备同步时会识别清理记录，防止局域网重新带回已清理的异常记录。正常订单不在此入口的清理范围内；退款、钱包付款和云端已存在订单等保护条件保持生效。

保留 +173 的同步确认和既有功能。原包名 com.yuepos.app、原签名覆盖升级，无需卸载或清除 App 数据。后台价内税设置已由独立的 R12 网页更新提供。

验证：18 项清理专项测试、309 项 Flutter 测试、10 项原生测试通过；APK 包名、版本和原签名已校验。设备现场验收尚未进行。

SHA-256: DIGEST
'''.replace('DIGEST',proof['sha256'])
pathlib.Path('release-notes.md').write_text(notes)
tag='v1.0.1+174'
def find_release():
 matches=[r for r in api('releases?per_page=100') if r['tag_name']==tag]
 assert len(matches)<=1,'Ambiguous release'
 return matches[0] if matches else None
release=find_release()
if release is None:
 raise RuntimeError('Expected user-published 174 release')
 subprocess.run(['gh','release','create',tag,str(apk),'--repo',REPO,'--target','main','--draft','--title','MIAO POS Android 1.0.1+174','--notes-file','release-notes.md'],check=True)
 release=find_release()
assert release and release['tag_name']==tag
release_id=release['id']
assert release_id==390370152
release=api('releases/'+str(release_id))
asset=next(a for a in release['assets'] if a['name']==name)
assert asset['size']==proof['bytes'] and asset['digest']=='sha256:'+proof['sha256']
assert not release['draft']
if release['draft']:
 subprocess.run(['gh','release','edit',tag,'--repo',REPO,'--draft=false','--latest','--notes-file','release-notes.md'],check=True)
subprocess.run(['gh','release','edit',tag,'--repo',REPO,'--notes-file','release-notes.md'],check=True)
release=api('releases/'+str(release_id))
assert release['id']==release_id and release['tag_name']==tag
assert not release['draft'] and not release['prerelease']
asset=next(a for a in release['assets'] if a['name']==name)
# Verify the public file before advertising it in the Android stable feed.
with urllib.request.urlopen(asset['browser_download_url'],timeout=120) as response:public=response.read(proof['bytes']+1)
assert len(public)==proof['bytes'] and hashlib.sha256(public).hexdigest()==proof['sha256']
current.update(latest_build=174,latest_version='1.0.1',download_url=asset['browser_download_url'],sha256=proof['sha256'],file_size=proof['bytes'],published_at=release['published_at'],release_notes=[
 '新增老板专用「异常待同步清理」入口，核对后逐条清理符合条件的无明细未上传订单',
 '清理前必须联网校验权限并保留审计记录；同店已升级设备同步识别清理结果，防止局域网回流',
 '保留 +173 功能，原签名覆盖升级，不清数据；后台价内税设置由独立 R12 网页更新提供'])
body={'message':'release(old-pos): publish verified Android 1.0.1+174 owner cleanup','branch':'main','sha':metadata['sha'],'content':base64.b64encode((json.dumps(current,ensure_ascii=False,indent=2)+'\n').encode()).decode()}
pathlib.Path('metadata-update.json').write_text(json.dumps(body))
gh('api','--method','PUT','repos/'+REPO+'/contents/metadata/android-stable.json','--input','metadata-update.json')
actual=json.loads(base64.b64decode(api('contents/metadata/android-stable.json?ref=main')['content']))
assert actual==current
# Keep the download page usable when the releases API is unavailable.
index_meta=api('contents/index.html?ref=main')
index=base64.b64decode(index_meta['content']).decode()
updated=index.replace('v1.0.1%2B173/MIAO_POS_1.0.1%2B173_PENDING_CONFIRM_R1.apk','v1.0.1%2B174/MIAO_POS_1.0.1%2B174_OWNER_CLEANUP_R1.apk').replace('Android 1.0.1+173','Android 1.0.1+174').replace('Android +173','Android +174')
assert 'v1.0.1%2B174/MIAO_POS_1.0.1%2B174_OWNER_CLEANUP_R1.apk' in updated
if updated!=index:
 index_body={'message':'release(old-pos): align Android fallback download with verified 174 stable release','branch':'main','sha':index_meta['sha'],'content':base64.b64encode(updated.encode()).decode()}
 pathlib.Path('index-update.json').write_text(json.dumps(index_body))
 gh('api','--method','PUT','repos/'+REPO+'/contents/index.html','--input','index-update.json')
assert base64.b64decode(api('contents/index.html?ref=main')['content']).decode()==updated
print('PUBLIC_ANDROID_174='+json.dumps({'release':release['html_url'],'asset':asset['browser_download_url'],'sha256':proof['sha256'],'bytes':proof['bytes'],'stable_build':actual['latest_build'],'source_commit':proof['build_commit']}))
