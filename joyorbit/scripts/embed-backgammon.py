"""Package the separate GNU executable; stamp the bytes after Android stripping."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[1]
binary=ROOT/'build/backgammon/android/libjoyorbit_backgammon.so'
stamp_path=ROOT/'build/backgammon/android/source.json'
if not binary.is_file() or not stamp_path.is_file():
    raise SystemExit('Run prepare-backgammon.py first.')
stamp=json.loads(stamp_path.read_text())
if stamp.get('facade_source')!='eb538998513c4171f4f6392c7c15a0bdb7ef83e5' or stamp.get('weights_sha256')!='d03c629d8b916236ce6eee05d891986830ec943fce6febd4e5b6725b284c66ee':
    raise SystemExit('GNU engine source does not match the approved pin.')
module=ROOT/'build/backgammon-engine'
target=module/'jniLibs/arm64-v8a'
target.mkdir(parents=True,exist_ok=True)
shutil.copy2(binary,target/binary.name)
assets=module/'assets/joyorbit/backgammon'
assets.mkdir(parents=True,exist_ok=True)
(assets/'engine.json').write_text(json.dumps(stamp))
template=ROOT/'build/android-apk'
shutil.copytree(template/'gradle',module/'gradle',dirs_exist_ok=True)
shutil.copy2(template/'gradlew',module/'gradlew')
(module/'settings.gradle').write_text("pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositories { google(); mavenCentral() } }\nrootProject.name='backgammon-engine'\n")
(module/'local.properties').write_text('sdk.dir='+os.environ['ANDROID_SDK_ROOT']+'\n')
(module/'AndroidManifest.xml').write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android"/>\n')
(module/'build.gradle').write_text("""plugins { id 'com.android.library' version '9.1.0' }
android {
 namespace 'io.precisiondata.joyorbit.backgammon.engine'
 compileSdk 36
 ndkVersion '29.0.14206865'
 defaultConfig { minSdk 24 }
 sourceSets { main { manifest.srcFile 'AndroidManifest.xml'; jniLibs.srcDirs=['jniLibs']; assets.srcDirs=['assets'] } }
}
""")
subprocess.run(['sh',str(module/'gradlew'),'-p',str(module),'assembleDebug','--no-daemon'],check=True)
output=ROOT/'build/android-apk/libs/joyorbit-backgammon-engine.aar'
with zipfile.ZipFile(module/'build/outputs/aar/backgammon-engine-debug.aar') as source,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    compiled=source.read('jni/arm64-v8a/libjoyorbit_backgammon.so')
    stamp['binary_sha256']=hashlib.sha256(compiled).hexdigest()
    for entry in source.infolist():
        archive.writestr(entry,json.dumps(stamp).encode() if entry.filename=='assets/joyorbit/backgammon/engine.json' else source.read(entry.filename))
print('Separate GNU program packaged; verify app execution and private saves separately.')
