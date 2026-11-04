"""生成 Shizuku AIDL 的 Java 接口（aidl.exe 对路径敏感，用 Python 调更稳）。"""
import subprocess, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BT = r"C:\AndroidSdk\build-tools\35.0.0\aidl.exe"
FW = r"C:\AndroidSdk\platforms\android-35\framework.aidl"
IMPL = os.path.join(ROOT, "libs", "aidl")
OUT = os.path.join(ROOT, "aidl-gen")
os.makedirs(OUT, exist_ok=True)

env = dict(os.environ)
env["MSYS_NO_PATHCONV"] = "1"

names = ["IRemoteProcess", "IShizukuApplication", "IShizukuService", "IShizukuServiceConnection"]
ok = True
for name in names:
    src = os.path.join(IMPL, "moe", "shizuku", "server", name + ".aidl")
    r = subprocess.run([BT, "-p" + FW, "-I" + IMPL, "-o" + OUT, src],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 or r.stderr.strip():
        print(f"  [aidl] {name} 失败: {r.stderr.strip()[:120]}", file=sys.stderr)
        ok = False
print(f"[0/6] AIDL 生成{'完成' if ok else '有失败'}")
sys.exit(0 if ok else 1)
