#!/usr/bin/env python3
import base64,json,os,subprocess,tempfile,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
SRC=HERE/'files'/'registry-server-app'
OWNER='mavisgroupiishki-alt';REPO='mavis-kp-generator';BRANCH='main';PREFIX='registry-server-app'
SERVICE='mavis-registry-github';ACCOUNT=f'{OWNER}/{REPO}'
def tok():
 r=subprocess.run(['security','find-generic-password','-s',SERVICE,'-a',ACCOUNT,'-w'],capture_output=True,text=True)
 return r.stdout.strip() if r.returncode==0 else None
def call(method,url,token,body=None):
 cmd=['curl','--silent','--show-error','--location','--connect-timeout','30','--max-time','180','--retry','3','--retry-delay','2','--retry-all-errors','-X',method,'-H','Accept: application/vnd.github+json','-H',f'Authorization: Bearer {token}','-H','X-GitHub-Api-Version: 2022-11-28','-H','User-Agent: MAVIS-Registry-ServerV10-Publisher']
 tmp=None
 try:
  if body is not None:
   tmp=tempfile.NamedTemporaryFile(prefix='mavis-srv10-',suffix='.json',delete=False)
   tmp.write(json.dumps(body,ensure_ascii=False).encode());tmp.close()
   cmd+=['-H','Content-Type: application/json','--data-binary','@'+tmp.name]
  cmd+=['--write-out','\n%{http_code}',url]
  r=subprocess.run(cmd,capture_output=True,text=True)
  if r.returncode!=0: raise RuntimeError(r.stderr.strip())
  text,cs=r.stdout.rsplit('\n',1);code=int(cs);data=json.loads(text) if text.strip() else {}
  if not 200<=code<300: raise RuntimeError(f'GitHub HTTP {code}: {data.get("message",text[:500]) if isinstance(data,dict) else text[:500]}')
  return data
 finally:
  if tmp:
   try: os.unlink(tmp.name)
   except OSError: pass
def api(p): return f'https://api.github.com/repos/{OWNER}/{REPO}{p}'
def main():
 token=os.environ.get('GITHUB_TOKEN') or tok()
 if not token: sys.exit('Не найден GitHub-токен в Keychain.')
 ref=call('GET',api(f'/git/ref/heads/{BRANCH}'),token);head=ref['object']['sha']
 commit=call('GET',api(f'/git/commits/{head}'),token);base_tree=commit['tree']['sha']
 files=[p for p in SRC.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 tree=[];print(f'Публикую сервер v10: {len(files)} изменённых файла')
 for i,p in enumerate(files,1):
  rel=p.relative_to(SRC).as_posix();print(f'[{i}/{len(files)}] {rel}')
  blob=call('POST',api('/git/blobs'),token,{'content':base64.b64encode(p.read_bytes()).decode(),'encoding':'base64'})
  tree.append({'path':f'{PREFIX}/{rel}','mode':'100644','type':'blob','sha':blob['sha']})
 nt=call('POST',api('/git/trees'),token,{'base_tree':base_tree,'tree':tree})
 nc=call('POST',api('/git/commits'),token,{'message':'Registry server v10 enable all deal funnels','tree':nt['sha'],'parents':[head]})
 call('PATCH',api(f'/git/refs/heads/{BRANCH}'),token,{'sha':nc['sha'],'force':False})
 print('\nГОТОВО: ограничение по воронке снято.')
 print('Render автоматически начнёт deploy. После Live /health покажет version 10.0-all-funnels.')
if __name__=='__main__': main()
