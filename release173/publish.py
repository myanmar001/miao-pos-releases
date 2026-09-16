"""Publish only the user-authorized, already-tested original-signature APK."""
import base64,datetime,hashlib,json,os,pathlib,re,subprocess,urllib.parse,urllib.request
REPO='myanmar001/miao-pos-releases'
assert os.environ['GITHUB_REPOSITORY']==REPO
proof=json.loads(pathlib.Path('release-input.json').read_text())
assert proof['package']=='com.yuepos.app' and proof['version_code']==173
assert proof['build_commit']=='ad16e881f4eca905fb351949d8a4538e697dacc6'
assert proof['targeted_tests']>=37 and proof['full_tests']>=264
assert proof['native_tests']=={'tests':10,'failures':0,'errors':0}
assert proof['certificate_sha256']=='01f72838bf9ed809aa8e641a1c8b0fedb8ccad590fba1b80333e3ce143e22d3b'
url=urllib.parse.urlsplit(proof['transfer_url'])
assert url.scheme=='https' and url.hostname in ('release-assets.githubusercontent.com','objects.githubusercontent.com') and not url.username
name='MIAO_POS_1.0.1+173_PENDING_CONFIRM_R1.apk'
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
assert current['latest_build']<=173,'A newer release already exists; do not downgrade'
if current['latest_build']==173:assert current['sha256']==proof['sha256'],'Do not replace a different 173 build'
notes='''旧 MIAO POS Android 1.0.1+173

修复云端已有数据、本机仍显示未同步：订单、挂单、商品与分类先核对云端，确认后仅清除对应本机 Pending，避免重复写入。未上传、核对失败或内容/关联冲突的记录继续保留并重试。

手动同步显示未完成的领域和原因。保护核对期间的新编辑、切换门店及本地保存失败。

基于原 1.0.1+172，原包名 com.yuepos.app、原签名覆盖升级。无需卸载或清除 App 数据。网关、税务、打印、后台和小程序未修改。

验证：TARGETED 项专项测试、FULL 项 Flutter 测试、10 项原生测试通过；APK 包名、版本和原签名已校验。设备现场验收由升级后的实际结果确认。

SHA-256: DIGEST
'''.replace('TARGETED',str(proof['targeted_tests'])).replace('FULL',str(proof['full_tests'])).replace('DIGEST',proof['sha256'])
pathlib.Path('release-notes.md').write_text(notes)
tag='v1.0.1+173'
r=subprocess.run(['gh','release','view',tag,'--repo',REPO,'--json','isDraft,assets'],capture_output=True,text=True)
if r.returncode!=0:
 subprocess.run(['gh','release','create',tag,str(apk),'--repo',REPO,'--target','main','--draft','--title','MIAO POS Android 1.0.1+173','--notes-file','release-notes.md'],check=True)
release=api('releases/389670599')
assert release['id']==389670599 and release['tag_name']==tag
asset=next(a for a in release['assets'] if a['name']==name)
assert asset['size']==proof['bytes'] and asset['digest']=='sha256:'+proof['sha256']
if release['draft']:
 subprocess.run(['gh','release','edit',tag,'--repo',REPO,'--draft=false','--latest','--notes-file','release-notes.md'],check=True)
release=api('releases/389670599')
assert release['id']==389670599 and release['tag_name']==tag
assert not release['draft'] and not release['prerelease']
asset=next(a for a in release['assets'] if a['name']==name)
# Verify the public file before advertising it in the Android stable feed.
with urllib.request.urlopen(asset['browser_download_url'],timeout=120) as response:public=response.read(proof['bytes']+1)
assert len(public)==proof['bytes'] and hashlib.sha256(public).hexdigest()==proof['sha256']
current.update(latest_build=173,latest_version='1.0.1',download_url=asset['browser_download_url'],sha256=proof['sha256'],file_size=proof['bytes'],published_at=release['published_at'],release_notes=[
 '云端确认已成功的订单、挂单、商品与分类后，自动恢复清除本机 Pending',
 '未上传或无法确认的记录继续保留；手动同步明确显示未完成领域与原因',
 '保护并发编辑和切店；保留 +172 功能，原签名覆盖升级，不清数据'])
body={'message':'release(old-pos): publish verified Android 1.0.1+173 pending confirmation','branch':'main','sha':metadata['sha'],'content':base64.b64encode((json.dumps(current,ensure_ascii=False,indent=2)+'\n').encode()).decode()}
pathlib.Path('metadata-update.json').write_text(json.dumps(body))
gh('api','--method','PUT','repos/'+REPO+'/contents/metadata/android-stable.json','--input','metadata-update.json')
actual=json.loads(base64.b64decode(api('contents/metadata/android-stable.json?ref=main')['content']))
assert actual==current
print('PUBLIC_ANDROID_173='+json.dumps({'release':release['html_url'],'asset':asset['browser_download_url'],'sha256':proof['sha256'],'bytes':proof['bytes'],'stable_build':actual['latest_build'],'source_commit':proof['build_commit']}))
