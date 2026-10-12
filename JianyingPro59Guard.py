#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JianyingPro Version Guard v2.0
剪映专业版 - 主程序版本锁定守护

目标:
  1. 禁止剪映自身 / 第三方工具(如 360 软件助手) 升级或降级主程序版本
  2. 主程序目录 Apps 设为只读可执行, 任何进程都改不动(含 SYSTEM)
  3. User Data 保持完全可写 -> 素材下载 / 草稿 / 预设 / 缓存 全部照旧
  4. 不限制主程序联网 -> 字幕识别 / 素材下载 等在线功能全部照旧

只依赖 Python 标准库, 可直接用 PyInstaller 打包成 exe.
用法:
  以管理员身份双击 启动守护.bat
  或命令行: python JianyingPro59Guard.py [--install|--check|--watch|--repair|--unlock|--lock|--uninstall] [--root 路径]
"""

import os
import sys
import json
import time
import stat
import shutil
import hashlib
import argparse
import subprocess
import datetime

IS_WIN = os.name == 'nt'
if IS_WIN:
    try:
        import winreg
    except Exception:
        winreg = None
    import ctypes

VERSION = '2.1'

USAGE = """剪映专业版 版本锁定守护 v%s

用法:
  JianyingPro59Guard.exe                 交互式菜单(推荐, 以管理员运行)
  JianyingPro59Guard.exe --help          显示本帮助
  JianyingPro59Guard.exe --install       非交互安装守护
  JianyingPro59Guard.exe --check         快速体检(大小/数量)
  JianyingPro59Guard.exe --deep-check    深度体检(全量 SHA256)
  JianyingPro59Guard.exe --repair        深度体检并自动修复
  JianyingPro59Guard.exe --unlock        临时解锁本体(供你自行升级)
  JianyingPro59Guard.exe --lock          恢复锁定
  JianyingPro59Guard.exe --uninstall     完全卸载守护
  JianyingPro59Guard.exe --watch         值守巡检(计划任务专用, 无需管理员)

通用选项:
  --root <路径>   指定 JianyingPro 根目录(含 Apps 和 User Data 的那一层)
  --quiet         非交互
""" % VERSION

# ---------------------------------------------------------------- 基础工具
PROG_DATA = os.environ.get('ProgramData', r'C:\ProgramData')
GUARD_DIR = os.path.join(PROG_DATA, 'JianyingPro59Guard')
CFG_FILE = os.path.join(GUARD_DIR, 'config.json')
BASE_DIR = os.path.join(GUARD_DIR, 'baseline')
PTR_DIR = os.path.join(BASE_DIR, 'ptr')
QUAR_DIR = os.path.join(GUARD_DIR, 'quarantine')
ORIG_DIR = os.path.join(GUARD_DIR, 'original')
BACKUP_DIR = os.path.join(GUARD_DIR, 'backup', 'Apps')
STATE_DIR = os.path.join(GUARD_DIR, 'state')
LOG_FILE = os.path.join(GUARD_DIR, 'guard.log')
GUARD_SCRIPT = os.path.join(GUARD_DIR, 'guard.py')

TASK_LOOP = 'JianyingProVersionGuard'
TASK_BOOT = 'JianyingProVersionGuardBoot'

NO_WINDOW = 0x08000000 if IS_WIN else 0
UPDATER_KEYWORDS = ('update', 'updater', 'upgrade', 'installer', 'setup', 'patch',
                    'selfupdate', 'bootstrapper')
POINTER_NAMES = ('Configure.ini', 'JianyingProPacket.xml')
TOTAL_PARTS = 5          # hash 轮转采样份数


# ---------------------------------------------------------------- 基础工具
def log(msg):
    line = '[%s] %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    try:
        os.makedirs(GUARD_DIR, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def echo(msg=''):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def run_cmd(cmd, check=False):
    """执行外部命令, 返回 (returncode, stdout, stderr)"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors='ignore', creationflags=NO_WINDOW, timeout=900)
        code, out, err = p.returncode, p.stdout or '', p.stderr or ''
    except FileNotFoundError:
        return 127, '', 'command not found: %s' % cmd
    except Exception as e:
        return 1, '', str(e)
    return code, out, err


def is_admin():
    if not IS_WIN:
        return os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """申请管理员权限并重启自己"""
    if not IS_WIN:
        return False
    exe = sys.executable
    if exe.lower().endswith('pythonw.exe'):
        alt = exe.lower().replace('pythonw.exe', 'python.exe')
        if os.path.exists(alt):
            exe = alt
    if getattr(sys, 'frozen', False):
        params = ' '.join(sys.argv[1:])
        target = exe
    else:
        params = '"%s" %s' % (os.path.abspath(__file__), ' '.join('"%s"' % a for a in sys.argv[1:]))
        target = exe
    rc = ctypes.windll.shell32.ShellExecuteW(None, 'runas', target, params, None, 1)
    return rc > 32


def require_admin(auto=True):
    if is_admin():
        return True
    echo('  * 本操作需要管理员权限')
    if auto:
        echo('    正在申请管理员权限, 请在 UAC 提示中点击 [是] ...')
        if elevate():
            sys.exit(0)
    echo('    未获得管理员权限。请右键点击本程序 -> 以管理员身份运行。')
    return False


# ---------------------------------------------------------------- 配置
class Config(dict):
    DEFAULTS = {
        'root': '',
        'verdir': '',
        'mode': 'STRICT',     # STRICT | LOOSE
        'fw': 1,              # 拦截更新程序联网
        'ifeo': 0,            # 拦截更新程序被启动
        'auto_quarantine': 1,
        'hash_sample': 1,     # 值守时按比例轮转校验 hash
        'updaters': [],
    }

    def __init__(self):
        super().__init__(self.DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(CFG_FILE):
            try:
                self.update(json.load(open(CFG_FILE, encoding='utf-8')))
            except Exception:
                pass

    def save(self):
        os.makedirs(GUARD_DIR, exist_ok=True)
        json.dump(dict(self), open(CFG_FILE, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)

    # 派生路径
    @property
    def root(self):
        return self['root']

    @property
    def apps(self):
        return os.path.join(self['root'], 'Apps')

    @property
    def udata(self):
        return os.path.join(self['root'], 'User Data')

    @property
    def verpath(self):
        d = self['verdir']
        return os.path.join(self.apps, d) if d else self.apps


# ---------------------------------------------------------------- 路径探测
def detect_root(cfg, explicit=None):
    cands = []
    if explicit:
        cands.append(explicit)
    cands.append(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'JianyingPro'))
    cands.append(os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'JianyingPro'))
    for c in cands:
        if c and os.path.isdir(os.path.join(c, 'Apps')):
            return os.path.abspath(c)
    return None


def detect_version(cfg):
    """找到包含 JianyingPro.exe 的版本子目录"""
    apps = cfg.apps
    if not os.path.isdir(apps):
        return ''
    for name in sorted(os.listdir(apps)):
        d = os.path.join(apps, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, 'JianyingPro.exe')):
            return name
    return ''


def ensure_paths(cfg, interactive=True):
    if not cfg['root'] or not os.path.isdir(cfg.apps):
        found = detect_root(cfg)
        if found:
            cfg['root'] = found
        elif interactive:
            echo('  未能自动发现剪映目录。')
            p = input('  请输入 JianyingPro 根目录(含 Apps 和 User Data 的那一层): ').strip().strip('"')
            if p and os.path.isdir(os.path.join(p, 'Apps')):
                cfg['root'] = os.path.abspath(p)
            elif p:
                echo('  路径无效: %s' % p)
        if not cfg['root']:
            return False
    cfg['verdir'] = detect_version(cfg)
    return True


# ---------------------------------------------------------------- ACL 防护
def _icacls(*args):
    return run_cmd(['icacls'] + [str(a) for a in args])


def lock_acl(cfg):
    _icacls(cfg.apps, '/deny', '*S-1-1-0:(OI)(CI)(DE,DC,WD,AD,WA,WEA)', '/T', '/C', '/Q')
    _icacls(cfg['root'], '/deny', '*S-1-1-0:(DC)', '/Q')


def unlock_acl(cfg):
    _icacls(cfg.apps, '/remove:d', '*S-1-1-0', '/T', '/C', '/Q')
    _icacls(cfg['root'], '/remove:d', '*S-1-1-0', '/Q')


def is_locked(cfg):
    code, out, _ = run_cmd(['icacls', cfg.apps])
    if code != 0:
        return False
    up = out.upper()
    return '(DENY)' in up and 'EVERYONE' in up


def guard_self_protect():
    """
    保护守护自身的基线: 禁止删除/重命名。
    注意只 deny DE,DC 而不动写入权限 —— 否则连守护自己都没法更新基线了。
    """
    os.makedirs(BASE_DIR, exist_ok=True)
    _icacls(BASE_DIR, '/deny', '*S-1-1-0:(OI)(CI)(DE,DC)', '/T', '/C', '/Q')


def ensure_udata_writable(cfg):
    if os.path.isdir(cfg.udata):
        _icacls(cfg.udata, '/remove:d', '*S-1-1-0', '/T', '/C', '/Q')


# ----------------------------------------------------------------  firewall / IFEO
def netsh(*args):
    return run_cmd(['netsh', 'advfirewall', 'firewall'] + [str(a) for a in args])


def fw_add(cfg):
    if not cfg['fw']:
        return 0
    n = 0
    for p in cfg['updaters']:
        if not os.path.exists(p):
            continue
        netsh('add', 'rule', 'name=JY59Guard-out', 'dir=out', 'action=block',
              'program=' + p, 'enable=yes')
        netsh('add', 'rule', 'name=JY59Guard-in', 'dir=in', 'action=block',
              'program=' + p, 'enable=yes')
        n += 1
    return n


def fw_remove(cfg):
    n = 0
    for p in cfg['updaters']:
        netsh('delete', 'rule', 'name=all', 'program=' + p)
        n += 1
    return n


IFEOK = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'


def ifeo_add(cfg):
    if not cfg['ifeo'] or not IS_WIN or winreg is None:
        return 0
    n = 0
    for p in cfg['updaters']:
        name = os.path.basename(p)
        try:
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, IFEOK + '\\' + name,
                                    0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, 'Debugger', 0, winreg.REG_SZ,
                                  r'%SystemRoot%\system32\systray.exe')
            n += 1
        except Exception:
            pass
    return n


def ifeo_remove(cfg):
    if not IS_WIN or winreg is None:
        return
    for p in cfg['updaters']:
        try:
            winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, IFEOK + '\\' + os.path.basename(p))
        except Exception:
            pass


# ---------------------------------------------------------------- 计划任务
def task_cmd(cfg, arg):
    if getattr(sys, 'frozen', False):
        runner = os.path.join(GUARD_DIR, 'guard.exe')
        if os.path.exists(runner):
            return '"%s" %s' % (runner, arg)
        return '"%s" %s' % (sys.executable, arg)
    script = GUARD_SCRIPT if os.path.exists(GUARD_SCRIPT) else os.path.abspath(__file__)
    exe = sys.executable
    if exe.lower().endswith('pythonw.exe'):
        alt = exe.lower().replace('pythonw.exe', 'python.exe')
        if os.path.exists(alt):
            exe = alt
    return '"%s" "%s" %s' % (exe, script, arg)


def tasks_create(cfg):
    cmd = task_cmd(cfg, '--watch')
    ok = False
    for principal in (['/ru', 'SYSTEM', '/rl', 'HIGHEST'], ['/rl', 'HIGHEST']):
        c, _, _ = run_cmd(['schtasks', '/create', '/tn', TASK_LOOP, '/tr', cmd,
                           '/sc', 'minute', '/mo', '15', '/f'] + principal)
        if c == 0:
            ok = True
            break
    run_cmd(['schtasks', '/create', '/tn', TASK_BOOT, '/tr', cmd, '/sc', 'onstart',
             '/ru', 'SYSTEM', '/rl', 'HIGHEST', '/f'])
    return ok


def tasks_set(enable=True):
    verbs = ['/enable'] if enable else ['/disable']
    for t in (TASK_LOOP, TASK_BOOT):
        run_cmd(['schtasks', '/change', '/tn', t] + verbs)


def tasks_remove():
    for t in (TASK_LOOP, TASK_BOOT):
        run_cmd(['schtasks', '/delete', '/tn', t, '/f'])


def tasks_installed():
    c, _, _ = run_cmd(['schtasks', '/query', '/tn', TASK_LOOP])
    return c == 0


# ---------------------------------------------------------------- 文件指纹
HM_HEAD = 262144
FULL_HASH_LIMIT = 1 << 20      # 1MB 以下整算 hash


def file_digest(path):
    """大文件取头尾各 256KB, 小文件整算"""
    h = hashlib.sha256()
    try:
        st = os.stat(path)
        size = st.st_size
        if size <= FULL_HASH_LIMIT:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
        else:
            with open(path, 'rb') as f:
                h.update(f.read(HM_HEAD))
                f.seek(max(0, size - HM_HEAD))
                h.update(f.read(HM_HEAD))
        return h.hexdigest()
    except Exception as e:
        return 'ERR:%s' % e


def find_updaters(cfg):
    found = []
    for dp, dns, fns in os.walk(cfg.apps):
        for fn in fns:
            if not fn.lower().endswith('.exe'):
                continue
            low = fn.lower()
            if any(k in low for k in UPDATER_KEYWORDS):
                found.append(os.path.join(dp, fn))
    return sorted(set(found))


def walk_apps(cfg, with_hash=True, idx_filter=None):
    """返回 {rel: {'s':size,'m':mtime_ns,'h':hash or ''}}"""
    apps = cfg.apps
    out = {}
    i = 0
    for dp, dns, fns in os.walk(apps):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, cfg['root'])
            try:
                st = os.stat(full)
            except Exception:
                continue
            rec = {'s': st.st_size, 'm': st.st_mtime_ns}
            if with_hash and (idx_filter is None or idx_filter(i)):
                rec['h'] = file_digest(full)
            else:
                rec['h'] = ''
            out[rel] = rec
            i += 1
    return out


# ---------------------------------------------------------------- 基线
def save_baseline(cfg):
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(PTR_DIR, exist_ok=True)
    echo('    正在记录主程序指纹(SHA256), 文件较多时请稍候 ...')
    files = walk_apps(cfg, with_hash=True)
    apps_top = sorted(os.listdir(cfg.apps)) if os.path.isdir(cfg.apps) else []
    root_top = sorted(os.listdir(cfg['root'])) if os.path.isdir(cfg['root']) else []
    data = {
        'version': VERSION,
        'created': time.time(),
        'root': cfg['root'],
        'verdir': cfg['verdir'],
        'apps_top': apps_top,
        'root_top': root_top,
        'files': files,
    }
    json.dump(data, open(os.path.join(BASE_DIR, 'manifest.json'), 'w',
                         encoding='utf-8'), ensure_ascii=False)
    # 版本指针留副本
    for name in POINTER_NAMES:
        src = os.path.join(cfg.apps, name)
        if os.path.exists(src):
            try:
                shutil.copy2(src, os.path.join(PTR_DIR, name))
            except Exception:
                pass
    cfg['updaters'] = find_updaters(cfg)
    cfg.save()
    return data


def load_baseline():
    p = os.path.join(BASE_DIR, 'manifest.json')
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return None


# ---------------------------------------------------------------- 体检
def check(cfg, hash_mode='full', slot=None):
    """
    hash_mode: none | sample | full
    slot: 0..TOTAL_PARTS-1, 轮转采样用
    返回 dict 结果
    """
    base = load_baseline()
    res = {'ok': True, 'missing': [], 'changed': [], 'stray': [],
           'count_base': 0, 'count_now': 0, 'pointer_bad': [], 'verified': 0}
    if base is None:
        res['ok'] = False
        res['error'] = '尚未建立基线, 请先执行安装'
        return res

    # 1. 顶层结构
    try:
        now_root_top = sorted(os.listdir(cfg['root']))
        now_apps_top = sorted(os.listdir(cfg.apps))
    except Exception as e:
        res['ok'] = False
        res['error'] = '无法读取主程序目录: %s' % e
        return res
    allowed_root = set(base.get('root_top', []))
    for n in now_root_top:
        if n in allowed_root or n in ('Apps', 'User Data'):
            continue
        res['stray'].append(os.path.join(cfg['root'], n))
    allowed_apps = set(base.get('apps_top', []))
    for n in now_apps_top:
        if n in allowed_apps:
            continue
        res['stray'].append(os.path.join(cfg.apps, n))

    # 2. 文件指纹
    if hash_mode == 'sample':
        f = (lambda i: (i % TOTAL_PARTS) == (slot or 0))
    elif hash_mode == 'full':
        f = None
    else:
        f = lambda i: False
    now = walk_apps(cfg, with_hash=hash_mode != 'none', idx_filter=f)
    old = base.get('files', {})
    res['count_base'] = len(old)
    res['count_now'] = len(now)

    for rel, rec in old.items():
        cur = now.get(rel)
        if cur is None:
            res['missing'].append(rel)
            continue
        # 判定是否被改动:
        #   1) 大小不等 -> 一定变了
        #   2) 新旧都有 hash 且不等 -> 被掉包了(即使大小/时间都一样)
        #   3) 无 hash 可依时(sample 未命中) -> 退化为比对修改时间
        bad = False
        if cur['s'] != rec['s']:
            bad = True
        elif cur.get('h') and rec.get('h'):
            bad = (cur['h'] != rec['h'])
        elif hash_mode == 'none':
            bad = (cur['m'] != rec['m'])
        if bad:
            res['changed'].append((rel, rec.get('s'), cur['s']))
        elif cur.get('h'):
            res['verified'] += 1
    res['added'] = [r for r in now if r not in old]

    # 3. 版本指针
    for name in POINTER_NAMES:
        got = os.path.join(PTR_DIR, name)
        cur = os.path.join(cfg.apps, name)
        if not os.path.exists(got) or not os.path.exists(cur):
            if os.path.exists(got):
                res['pointer_bad'].append(name)
            continue
        try:
            a = open(got, 'rb').read()
            b = open(cur, 'rb').read()
            if a != b:
                res['pointer_bad'].append(name)
        except Exception:
            pass

    if res['missing'] or res['changed'] or res['stray'] or res['added'] or res['pointer_bad']:
        res['ok'] = False
    return res


def show_result(cfg, res):
    echo('')
    echo('    ------------------------------------------------------------------')
    echo('    体检结果: %s' % ('正常' if res['ok'] else '发现异常'))
    echo('    ------------------------------------------------------------------')
    echo('    主程序文件 : 基线 %d 个, 当前 %d 个' % (res['count_base'], res['count_now']))
    echo('    锁定版本   : %s' % (cfg['verdir'] or '未知'))
    echo('    hash 校验  : %s 个文件' % res.get('verified', 0))
    if res['ok']:
        echo('    版本指针   : 与基线一致')
        return
    if res['stray']:
        echo('')
        echo('    [非法新增条目 - 需隔离]')
        for s in res['stray'][:40]:
            echo('      ' + s)
    if res['added']:
        echo('')
        echo('    [新增文件] %d 个' % len(res['added']))
        for s in res['added'][:40]:
            echo('      ' + s)
    if res['missing']:
        echo('')
        echo('    [缺失文件] %d 个' % len(res['missing']))
        for s in res['missing'][:40]:
            echo('      ' + s)
    if res['changed']:
        echo('')
        echo('    [内容被篡改] %d 个' % len(res['changed']))
        for rel, old_s, new_s in res['changed'][:40]:
            echo('      %s  (基线 %s 字节 -> 现在 %s 字节)' % (rel, old_s, new_s))
    if res['pointer_bad']:
        echo('')
        echo('    [版本指针被改写] %s' % ', '.join(res['pointer_bad']))
    echo('')


# ---------------------------------------------------------------- 修复
def repair(cfg, res=None):
    if res is None:
        res = check(cfg, hash_mode='full')
    if 'error' in res:
        echo('    ' + res['error'])
        return False
    if res['ok']:
        return True

    echo('    正在修复 ...')
    unlock_acl(cfg)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    qdir = os.path.join(QUAR_DIR, stamp)

    # 1. 隔离非法条目
    if cfg['auto_quarantine'] and (res['stray'] or res['added']):
        os.makedirs(qdir, exist_ok=True)
        targets = list(res['stray'])
        for rel in res['added']:
            full = os.path.join(cfg['root'], rel)
            # 上面已经把顶层新增记进 stray, 这里补深层新增文件
            if full not in targets:
                targets.append(full)
        for t in targets:
            if not os.path.exists(t):
                continue
            try:
                dst = os.path.join(qdir, os.path.basename(t))
                shutil.move(t, dst)
                echo('    已隔离: %s' % t)
                log('隔离非法条目: %s -> %s' % (t, dst))
            except Exception as e:
                echo('    隔离失败(可能被占用): %s (%s)' % (t, e))
                log('隔离失败: %s (%s)' % (t, e))

    # 2. 还原版本指针
    for name in res['pointer_bad']:
        src = os.path.join(PTR_DIR, name)
        dst = os.path.join(cfg.apps, name)
        try:
            shutil.copy2(src, dst)
            echo('    已还原版本指针: %s' % name)
            log('还原版本指针: %s' % name)
        except Exception as e:
            echo('    还原失败: %s (%s)' % (name, e))

    # 3. 缺失/被篡改文件 -> 用完整备份还原
    if (res['missing'] or res['changed']) and os.path.isdir(BACKUP_DIR):
        echo('    正在用完整备份覆盖还原受损文件 ...')
        c, _, _ = run_cmd(['robocopy', BACKUP_DIR, cfg.apps, '/E', '/COPY:DAT',
                           '/R:1', '/W:1', '/NJH', '/NJS', '/NFL', '/NDL', '/NP'])
        log('已从备份还原主程序, robocopy=%s' % c)
    elif res['missing'] or res['changed']:
        echo('    注意: 有文件缺失或被篡改, 但未创建完整备份, 无法自动回滚。')
        echo('          请先在菜单执行 [7] 创建完整备份。')
        log('发现受损文件但无备份: 缺失%d 篡改%d' % (len(res['missing']), len(res['changed'])))

    # 4. 干掉从非基线目录跑起来的进程
    kill_stray_procs(cfg)

    # 5. 重新上锁
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
    fw_add(cfg)
    if cfg['ifeo']:
        ifeo_add(cfg)
    echo('    修复流程结束。')
    log('修复流程结束')
    return True


def kill_stray_procs(cfg):
    if not IS_WIN:
        return
    try:
        ps = (
            "$p='%s'; $v='%s'; $ok='%s'; "
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -and $_.Path.StartsWith($p,[StringComparison]::OrdinalIgnoreCase) "
            "-and -not $_.Path.StartsWith($v,[StringComparison]::OrdinalIgnoreCase) "
            "-and $_.Path -ne $ok } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            % (cfg.apps, cfg.verpath, os.path.join(cfg.apps, 'JianyingPro.exe'))
        )
        run_cmd(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps])
    except Exception:
        pass


# ---------------------------------------------------------------- 备份
def backup_create(cfg):
    if not os.path.isdir(cfg.apps):
        echo('    主程序目录不存在')
        return
    echo('    源  : %s' % cfg.apps)
    echo('    目标: %s' % BACKUP_DIR)
    echo('    正在备份, 数据量大时请耐心等待 ...')
    unlock_acl(cfg)
    c, out, _ = run_cmd(['robocopy', cfg.apps, BACKUP_DIR, '/E', '/COPY:DAT',
                         '/R:1', '/W:1', '/NP'])
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
    if c >= 8:
        echo('    备份失败, robocopy 返回码 %s' % c)
        log('备份失败 rc=%s' % c)
    else:
        echo('    备份完成。')
        log('完整备份已更新')


def backup_restore(cfg):
    if not os.path.isdir(BACKUP_DIR):
        echo('    尚未创建备份, 请先执行 [7]')
        return
    echo('    警告: 将用备份覆盖当前主程序本体(目标中多余文件会被删除)。')
    echo('    源  : %s' % BACKUP_DIR)
    echo('    目标: %s' % cfg.apps)
    y = input('    确认继续? [Y/N]: ').strip().upper()
    if y != 'Y':
        return
    unlock_acl(cfg)
    c, _, _ = run_cmd(['robocopy', BACKUP_DIR, cfg.apps, '/MIR', '/R:1', '/W:1', '/NP'])
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
    log('从备份还原主程序 rc=%s' % c)
    echo('    还原完成, robocopy 返回码 %s' % c)


# ---------------------------------------------------------------- 阉割更新程序
def neuter_state(cfg):
    st = []
    for p in cfg['updaters']:
        if not os.path.exists(p):
            st.append('已删除')
        elif os.path.getsize(p) == 0:
            st.append('已阉割')
        else:
            st.append('原始')
    if not st:
        return '未处理'
    if all(x == '原始' for x in st):
        return '原始'
    return '/'.join(sorted(set(st)))


def do_neuter(cfg):
    unlock_acl(cfg)
    os.makedirs(ORIG_DIR, exist_ok=True)
    for p in cfg['updaters']:
        if not os.path.exists(p):
            continue
        if os.path.getsize(p) > 0:
            shutil.copy2(p, os.path.join(ORIG_DIR, os.path.basename(p)))
        open(p, 'wb').truncate(0)
        echo('    已阉割: %s' % p)
        log('更新程序已阉割为空壳: %s' % p)
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
    save_baseline(cfg)
    echo('    完成。原始文件保存在 %s, 可随时还原。' % ORIG_DIR)


def do_unneuter(cfg):
    unlock_acl(cfg)
    for p in cfg['updaters']:
        src = os.path.join(ORIG_DIR, os.path.basename(p))
        if os.path.exists(src):
            shutil.copy2(src, p)
            echo('    已还原: %s' % p)
            log('更新程序已还原: %s' % p)
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
    save_baseline(cfg)


def do_delete_updaters(cfg):
    unlock_acl(cfg)
    os.makedirs(ORIG_DIR, exist_ok=True)
    for p in cfg['updaters']:
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(ORIG_DIR, os.path.basename(p)))
            try:
                os.remove(p)
                echo('    已删除: %s' % p)
                log('更新程序已删除: %s' % p)
            except Exception as e:
                echo('    删除失败: %s (%s)' % (p, e))
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
    save_baseline(cfg)


# ---------------------------------------------------------------- 安装 / 卸载
def install(cfg, interactive=True):
    echo('')
    echo('======================= 安装 / 重新部署守护 =========================')
    if not cfg['verdir']:
        cfg['verdir'] = detect_version(cfg)
    echo('   守护目标 : %s' % cfg['root'])
    echo('   锁定版本 : %s' % (cfg['verdir'] or '未知'))
    echo('')
    if interactive:
        echo('   选择保护模式:')
        echo('     [S] 严格模式(推荐): 主程序本体禁止一切写入, 任何进程都改不动')
        echo('     [L] 宽松模式      : 本体可写, 只靠值守任务发现变化时隔离还原')
        m = input('   请输入 S 或 L, 直接回车默认 S: ').strip().upper()
        cfg['mode'] = 'LOOSE' if m == 'L' else 'STRICT'
    echo('')

    os.makedirs(GUARD_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        if getattr(sys, 'frozen', False):
            shutil.copy2(sys.executable, os.path.join(GUARD_DIR, 'guard.exe'))
        else:
            shutil.copy2(os.path.abspath(__file__), GUARD_SCRIPT)
    except Exception:
        pass

    echo('   [1/6] 建立基线')
    data = save_baseline(cfg)
    echo('         主程序文件 %d 个已记录' % len(data['files']))
    echo('         更新程序候选:')
    for u in cfg['updaters']:
        echo('           ' + u)
    echo('')

    echo('   [2/6] 锁定主程序写入权限')
    unlock_acl(cfg)
    if cfg['mode'] == 'STRICT':
        lock_acl(cfg)
        echo('         严格模式已生效')
    else:
        echo('         宽松模式: 本次不锁定 ACL')
    echo('')

    echo('   [3/6] 拦截更新程序联网')
    n = fw_add(cfg)
    echo('         已处理 %d 个更新程序' % n)
    echo('')

    echo('   [4/6] 保护守护自身目录')
    guard_self_protect()
    echo('         已处理')
    echo('')

    echo('   [5/6] 确保 User Data 完全可写(素材/草稿/预设/缓存)')
    ensure_udata_writable(cfg)
    echo('         已处理')
    echo('')

    echo('   [6/6] 注册值守任务')
    if tasks_create(cfg):
        echo('         值守任务已注册: 每 15 分钟巡检 + 开机巡检')
        echo('         cmd = %s' % task_cmd(cfg, '--watch'))
    else:
        echo('         计划任务注册失败, 请以管理员身份重试')
    cfg.save()
    log('守护安装完成: root=%s ver=%s mode=%s' % (cfg['root'], cfg['verdir'], cfg['mode']))
    echo('')
    echo('    ------------------------------------------------------------------')
    echo('    安装完成。')
    echo('    * 主程序本体设为只读可执行, 剪映自己和第三方都改不动它')
    echo('    * User Data 不受影响: 素材下载 / 草稿 / 预设 / 缓存 全部照常')
    echo('    * 主程序没有被加入任何网络黑名单: 字幕识别 / 素材下载 照常')
    echo('    * 每 15 分钟自动巡检, 发现非法版本目录会自动隔离并还原版本指针')
    echo('    * 建议再执行一次 [7] 创建完整备份, 这是被破坏后唯一能回滚的手段')
    echo('    ------------------------------------------------------------------')


def uninstall(cfg):
    echo('   正在移除保护措施 ...')
    unlock_acl(cfg)
    fw_remove(cfg)
    ifeo_remove(cfg)
    tasks_remove()
    log('守护已卸载')
    echo('   守护已卸载, 主程序写入权限已恢复。')
    echo('   基线数据与备份仍保留在 %s, 可自行删除。' % GUARD_DIR)


# ---------------------------------------------------------------- 值守入口
def watch(cfg):
    slot = None
    if cfg['hash_sample']:
        slot = int(time.strftime('%H')) % TOTAL_PARTS
    res = check(cfg, hash_mode='sample' if cfg['hash_sample'] else 'none', slot=slot)
    if res.get('error'):
        log('值守中止: %s' % res['error'])
        return
    if res['ok']:
        if cfg['mode'] == 'STRICT' and not is_locked(cfg):
            lock_acl(cfg)
            log('检测到权限锁定丢失, 已自动补锁')
        log('值守通过: 版本 %s 完整无损 (%d 个文件)' % (cfg['verdir'], res['count_now']))
        return
    log('值守发现异常: 新增%d 缺失%d 篡改%d 指针%d -> 自动修复'
        % (len(res['stray']) + len(res['added']), len(res['missing']),
           len(res['changed']), len(res['pointer_bad'])))
    repair(cfg, res)
    after = check(cfg, hash_mode='none')
    log('修复后复检: %s' % ('正常' if after['ok'] else '仍有异常'))


# ---------------------------------------------------------------- 菜单
def draw_menu(cfg):
    os.system('cls' if IS_WIN else 'clear')
    installed = tasks_installed()
    locked = is_locked(cfg) if cfg['root'] else False
    state = ('运行中' if installed else '未安装') + ('' if locked else ' (本体未锁)')
    if cfg['mode'] == 'LOOSE':
        state += ' 宽松模式'
    print('==========================================================================')
    print('   剪映专业版 - 主程序版本锁定守护     JianyingPro Version Guard v%s' % VERSION)
    print('==========================================================================')
    print('   守护目标 : %s' % cfg['root'])
    print('   锁定版本 : %s' % (cfg['verdir'] or '未识别'))
    print('   保护模式 : %s        更新程序联网拦截: %s        更新进程拦截: %s'
          % (cfg['mode'], '开' if cfg['fw'] else '关', '开' if cfg['ifeo'] else '关'))
    print('   守护状态 : %s' % state)
    print('   更新程序 : %s' % (neuter_state(cfg)))
    print('--------------------------------------------------------------------------')
    print('     [1] 安装 / 重新部署守护        推荐先执行一次')
    print('     [2] 立即体检                   只报告, 不做任何修改')
    print('     [3] 深度体检                   全量 SHA256 校验, 较慢但最准')
    print('     [4] 巡检并修复                 隔离非法版本目录, 还原被篡改文件')
    print('     [5] 临时解锁主程序写入         需要手动升级/修复时用')
    print('     [6] 恢复锁定')
    print('     [7] 重建基线                   换版本或重装后执行')
    print('     [8] 创建 / 更新主程序完整备份  唯一可回滚手段, 建议做')
    print('     [9] 从备份还原主程序           被强行升降级后的急救')
    print('    [10] 切换 更新程序联网拦截      当前: %s' % ('开' if cfg['fw'] else '关'))
    print('    [11] 切换 更新进程执行拦截      当前: %s' % ('开' if cfg['ifeo'] else '关'))
    print('    [12] 阉割 / 还原 更新程序       当前: %s' % neuter_state(cfg))
    print('    [13] 查看运行日志')
    print('    [14] 完全卸载守护')
    print('     [0] 退出')
    print('--------------------------------------------------------------------------')


def menu_loop(cfg):
    while True:
        draw_menu(cfg)
        try:
            ch = input('请输入选项并回车: ').strip()
        except EOFError:
            return
        try:
            if ch == '1':
                install(cfg)
            elif ch == '2':
                echo('   正在体检(快速, 不校验 hash) ...')
                show_result(cfg, check(cfg, hash_mode='none'))
            elif ch == '3':
                echo('   正在深度体检(全量 SHA256) ...')
                show_result(cfg, check(cfg, hash_mode='full'))
            elif ch == '4':
                res = check(cfg, hash_mode='full')
                show_result(cfg, res)
                if res['ok']:
                    echo('   未发现异常, 无需修复。')
                else:
                    repair(cfg, res)
            elif ch == '5':
                unlock_acl(cfg)
                fw_remove(cfg)
                ifeo_remove(cfg)
                tasks_set(False)
                log('用户手动解锁本体写入')
                echo('   已解锁。现在可以对剪映本体做改动 / 手动升级。')
                echo('   完成后请回到菜单执行 [6] 恢复锁定; 值守任务已暂停。')
            elif ch == '6':
                if cfg['mode'] == 'STRICT':
                    lock_acl(cfg)
                fw_add(cfg)
                if cfg['ifeo']:
                    ifeo_add(cfg)
                tasks_set(True)
                log('用户恢复锁定')
                echo('   已重新锁定。')
            elif ch == '7':
                y = input('   确认把当前状态作为新的受保护版本? [Y/N]: ').strip().upper()
                if y == 'Y':
                    save_baseline(cfg)
                    log('基线已重建')
                    echo('   基线已重建。')
            elif ch == '8':
                backup_create(cfg)
            elif ch == '9':
                backup_restore(cfg)
            elif ch == '10':
                if cfg['fw']:
                    cfg['fw'] = 0
                    fw_remove(cfg)
                    echo('   已关闭 更新程序联网拦截。')
                else:
                    cfg['fw'] = 1
                    n = fw_add(cfg)
                    echo('   已开启 更新程序联网拦截 (%d 个程序)。' % n)
                cfg.save()
            elif ch == '11':
                if cfg['ifeo']:
                    cfg['ifeo'] = 0
                    ifeo_remove(cfg)
                    echo('   已关闭 进程执行拦截。')
                else:
                    if not cfg['updaters']:
                        cfg['updaters'] = find_updaters(cfg)
                    if not cfg['updaters']:
                        echo('   未发现明确的更新程序进程名, 无需开启。')
                    else:
                        echo('   即将按进程名屏蔽: %s'
                             % ', '.join(os.path.basename(u) for u in cfg['updaters']))
                        echo('   注意: 按镜像名屏蔽是全局的, 其它软件同名的 updater 也可能被屏蔽。')
                        y = input('   确认开启? [Y/N]: ').strip().upper()
                        if y == 'Y':
                            cfg['ifeo'] = 1
                            ifeo_add(cfg)
                            echo('   已开启 进程执行拦截。')
                cfg.save()
            elif ch == '12':
                sub_neuter_menu(cfg)
            elif ch == '13':
                try:
                    lines = open(LOG_FILE, encoding='utf-8').read().splitlines()[-60:]
                    print('\n'.join(lines) if lines else '(暂无日志)')
                except FileNotFoundError:
                    print('(暂无日志)')
            elif ch == '14':
                y = input('   确认移除所有保护措施? [Y/N]: ').strip().upper()
                if y == 'Y':
                    uninstall(cfg)
            elif ch == '0':
                return
        except Exception as e:
            echo('   执行出错: %s' % e)
        if ch not in ('0',):
            input('\n按回车键继续 ...')


def sub_neuter_menu(cfg):
    if not cfg['updaters']:
        cfg['updaters'] = find_updaters(cfg)
        cfg.save()
    print('--------------------------------------------------------------------------')
    print('   已识别到以下更新 / 安装类程序:')
    for u in cfg['updaters']:
        print('     ' + u)
    print('')
    print('   说明: VECreator.dll 中硬编码调用了 update.exe, 直接删除可能导致调用失败,')
    print('         因此推荐做法 1: 保留文件名, 内容换成 0 字节。')
    print('')
    print('     [1] 阉割: 保留文件名, 内容替换为 0 字节   推荐, 可还原')
    print('     [2] 还原: 恢复原始文件')
    print('     [3] 删除: 彻底删掉')
    print('     [0] 返回')
    c = input('   请选择: ').strip()
    if c == '1':
        do_neuter(cfg)
    elif c == '2':
        do_unneuter(cfg)
    elif c == '3':
        do_delete_updaters(cfg)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--root', default=None)
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--deep-check', action='store_true')
    ap.add_argument('--repair', action='store_true')
    ap.add_argument('--watch', action='store_true')
    ap.add_argument('--unlock', action='store_true')
    ap.add_argument('--lock', action='store_true')
    ap.add_argument('--uninstall', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--help', '-h', action='store_true')
    args, _ = ap.parse_known_args()

    if args.help:
        echo(USAGE)
        return 0

    cfg = Config()
    if args.root:
        cfg['root'] = os.path.abspath(args.root)

    # 静默的值守模式: 不需要交互, 也不需要额外申请权限(计划任务本身就是高权限)
    if args.watch:
        if not ensure_paths(cfg, interactive=False):
            log('值守失败: 未找到守护目标')
            return 1
        if not cfg['verdir']:
            cfg['verdir'] = detect_version(cfg)
        watch(cfg)
        return 0

    # 其它模式都需要管理员
    if not require_admin():
        return 1

    if not ensure_paths(cfg, interactive=not args.quiet):
        echo('未能确定剪映安装目录。')
        return 1
    if not cfg['verdir']:
        cfg['verdir'] = detect_version(cfg)

    if args.install:
        install(cfg, interactive=False)
    elif args.check:
        echo('   正在体检 ...')
        show_result(cfg, check(cfg, hash_mode='none'))
    elif args.deep_check:
        echo('   正在深度体检(全量 SHA256) ...')
        show_result(cfg, check(cfg, hash_mode='full'))
    elif args.repair:
        res = check(cfg, hash_mode='full')
        show_result(cfg, res)
        repair(cfg, res)
    elif args.unlock:
        unlock_acl(cfg)
        fw_remove(cfg)
        ifeo_remove(cfg)
        tasks_set(False)
        log('命令行: 已临时解锁')
        echo('已临时解锁。')
    elif args.lock:
        if cfg['mode'] == 'STRICT':
            lock_acl(cfg)
        fw_add(cfg)
        if cfg['ifeo']:
            ifeo_add(cfg)
        tasks_set(True)
        log('命令行: 已重新锁定')
        echo('已重新锁定。')
    elif args.uninstall:
        uninstall(cfg)
    else:
        menu_loop(cfg)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
