"""Start the integrated Photo / Paint / Lab and phone reception services."""
from pathlib import Path
import argparse, importlib.util, os, socket, subprocess, sys, time, urllib.request, webbrowser

ROOT=Path(__file__).resolve().parent
VENDORS=[ROOT/'photo/experiment/vendor',ROOT/'photo/intake/vendor']
if sys.platform=='win32' and sys.version_info[:2]==(3,12):
    sys.path[:0]=[str(p) for p in VENDORS]

def available(port):
    try:
        with socket.socket() as s:s.bind(('0.0.0.0',port))
        return True
    except OSError:return False

def main():
    parser=argparse.ArgumentParser(description='Sonify 最终整合版：Photo / Paint / Lab / 社区')
    parser.add_argument('--port',type=int,default=8781)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--paint-only',action='store_true')
    parser.add_argument('--lan',action='store_true',
                        help='允许局域网内其它设备访问主控台（默认仅监听 127.0.0.1）。')
    args=parser.parse_args()
    if not 1024<=args.port<=65530:parser.error('端口应为1024—65530')
    required={'numpy':'numpy','PIL':'Pillow','cv2':'opencv-contrib-python-headless','tinysoundfont':'tinysoundfont','mido':'mido','soundfile':'soundfile','qrcode':'qrcode[pil]'}
    missing=[package for name,package in required.items() if importlib.util.find_spec(name) is None]
    if args.check:
        print('Python:',sys.version.split()[0]);print('Dependencies:', 'OK' if not missing else ', '.join(missing))
        print('Photo:',(ROOT/'photo/intake/server.py').is_file(),'Paint:',(ROOT/'paint/modules/fourier/Sonify-Fourier.html').is_file(),'Lab:',(ROOT/'photo/intake/web/museum/museum-extensions.json').is_file())
        return bool(missing)
    if missing and not args.paint_only:
        print('请先安装依赖：');print(f'"{sys.executable}" -m pip install -r "{ROOT / "photo/requirements-share.txt"}"')
        return 1
    port=args.port
    while not all(available(port+n) for n in (0,1,3)):
        port+=4
        if port>65530:raise RuntimeError('没有找到空闲端口')
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env['SONIFY_DISCOVER_PORT']=str(port+3)
    if sys.platform=='win32' and sys.version_info[:2]==(3,12):env['PYTHONPATH']=os.pathsep.join(str(p) for p in VENDORS)
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    processes=[]
    try:
        if args.paint_only:
            command=[sys.executable,'-m','http.server',str(port),'--bind','127.0.0.1','--directory',str(ROOT/'paint')]
        else:
            discover=subprocess.Popen([sys.executable,str(ROOT/'photo/intake/discover_service.py')],cwd=ROOT,env=env,creationflags=creationflags);processes.append(discover)
            # H1 (security): the host console used to listen on 0.0.0.0 with
            # no authentication at all, so any device on the LAN could list
            # every job, download every original photo and burn the paid
            # Seedream API quota.  Default to loopback only; `--lan` is now
            # an explicit opt-in.
            host_bind='0.0.0.0' if args.lan else '127.0.0.1'
            command=[sys.executable,str(ROOT/'photo/intake/server.py'),'--port',str(port),'--share','--guest-port',str(port+1),'--host-bind',host_bind]
        server=subprocess.Popen(command,cwd=ROOT,env=env,creationflags=creationflags);processes.append(server)
        url=f'http://127.0.0.1:{port}/'
        for _ in range(150):
            if server.poll() is not None:raise RuntimeError('主服务未启动，请查看错误')
            try:
                with urllib.request.urlopen(url,timeout=.5) as response:
                    if response.status==200:break
            except OSError:time.sleep(.2)
        else:raise RuntimeError('启动超时')
        print('SONIFY 最终整合版!!!',flush=True)
        print('主页:',url,'\n扫码接待:',url+'host','\nPhoto:',url+'experience','\nLab:',url+'musiclab',flush=True)
        if args.lan:
            print('已启用局域网访问（--lan）：同网设备可直接访问主控台，请仅在受信任网络使用。',flush=True)
        else:
            print('主控台仅监听 127.0.0.1；如需让手机扫码访问，请使用 --lan 启动。',flush=True)
        if port!=args.port:print('旧版本占用了原端口，当前整合版使用上面的新地址。',flush=True)
        if not args.no_browser:webbrowser.open(url)
        return server.wait()
    except KeyboardInterrupt:return 0
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:p.kill()

if __name__=='__main__':raise SystemExit(main())
