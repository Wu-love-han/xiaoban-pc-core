#!/bin/bash
# 小伴手机端 APK 构建脚本（无需 Gradle/Android Studio）
set -e
export JAVA_HOME="/c/Program Files/Microsoft/jdk-21.0.13.21-hotspot"
export PATH="$JAVA_HOME/bin:$PATH"
BT="C:/AndroidSdk/build-tools/35.0.0"
PLATFORM="C:/AndroidSdk/platforms/android-35/android.jar"
PKG=com.xiaoban.app

rm -rf build && mkdir -p build/gen build/obj build/dex

echo "[0/6] 生成 Shizuku AIDL 接口"
python gen_aidl.py || true

echo "[1/6] 编译资源"
"$BT/aapt2.exe" compile --dir res -o build/res.zip

echo "[2/6] 链接资源 + manifest"
"$BT/aapt2.exe" link -o build/base.apk -I "$PLATFORM" \
  --manifest AndroidManifest.xml -R build/res.zip --java build/gen --auto-add-overlay

echo "[3/6] 编译 Java"
LIBS="libs/api.jar;libs/provider.jar"
javac -nowarn -source 8 -target 8 -bootclasspath "$PLATFORM" -cp "$LIBS" -d build/obj \
  build/gen/com/xiaoban/app/R.java src/com/xiaoban/app/*.java \
  aidl-gen/moe/shizuku/server/*.java aidl-gen/com/xiaoban/app/*.java 2>&1 | grep -vE "^ע|^����|warning" || true

echo "[4/6] 转 dex"
"$BT/d8.bat" --lib "$PLATFORM" --min-api 24 --output build/dex \
  build/obj/com/xiaoban/app/*.class build/obj/moe/shizuku/server/*.class \
  libs/api.jar libs/provider.jar

echo "[5/6] 打包"
python - << 'PY'
import zipfile, shutil, os
shutil.copyfile("build/base.apk", "build/unsigned.apk")
with zipfile.ZipFile("build/unsigned.apk", "a", zipfile.ZIP_DEFLATED) as z:
    z.write("build/dex/classes.dex", "classes.dex")
print("  dex 已注入")
PY
"$BT/zipalign.exe" -f 4 build/unsigned.apk build/aligned.apk

echo "[6/6] 签名"
"$BT/apksigner.bat" sign --ks xiaoban.keystore --ks-pass pass:xiaoban123 \
  --key-pass pass:xiaoban123 --out xiaoban.apk build/aligned.apk

echo "✅ 构建完成: xiaoban.apk ($(stat -c%s xiaoban.apk) 字节)"
