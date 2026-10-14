"""Build the pinned GNU engine facade as a separate program, never a Godot library."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PIN = 'eb538998513c4171f4f6392c7c15a0bdb7ef83e5'
WEIGHTS = 'd03c629d8b916236ce6eee05d891986830ec943fce6febd4e5b6725b284c66ee'
parser = argparse.ArgumentParser()
parser.add_argument('--target', choices=['macos', 'android'], default='android')
args = parser.parse_args()

def run(command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, **kwargs)

def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()

def archive(name, url, expected):
    path = ROOT/'build'/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as response, path.open('wb') as output:
            shutil.copyfileobj(response, output)
    if digest(path) != expected:
        raise SystemExit('Source archive checksum mismatch: '+name)
    destination = ROOT/'build/gnubg-deps'
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path) as source:
        directory = destination/source.getnames()[0].split('/')[0]
        if not directory.exists():
            source.extractall(destination, filter='data')
    return directory

source = ROOT/'.sources/gnubg-android'
if not source.exists():
    run(['git', 'clone', '--no-checkout', 'https://github.com/PrecisionDataHQ/gnubg-android.git', source])
    run(['git', '-C', source, 'fetch', 'origin', PIN])
    run(['git', '-C', source, 'checkout', '--detach', PIN])
head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True)
if head != PIN or dirty:
    raise SystemExit('Preserve modified source; use a clean pinned GNU facade checkout.')
weights = source/'gnubg-app/app/src/main/assets/gnubg.weights'
if digest(weights) != WEIGHTS:
    raise SystemExit('GNU neural-network weights do not match their pinned source.')

prefix = ROOT/'build/gnubg-deps-install'
if args.target == 'android':
    sdk = Path(os.environ['ANDROID_SDK_ROOT'])
    ndk = sdk/'ndk/29.0.14206865'
    host = 'darwin-x86_64' if os.uname().sysname == 'Darwin' else 'linux-x86_64'
    tools = ndk/'toolchains/llvm/prebuilt'/host/'bin'
    iconv = archive('libiconv-1.18.tar.gz', 'https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.18.tar.gz',
        '3b08f5f4f9b4eb82f151a7040bfd6fe6c6fb922efe4b1659c66ea933276965e8')
    glib = archive('glib-2.88.1.tar.xz', 'https://download.gnome.org/sources/glib/2.88/glib-2.88.1.tar.xz',
        '51ab804c56f6eab3e5045c774d1290ac5e4c923d4f9a3d8e33123bee45c1840e')
    iconv_build = ROOT/'build/gnubg-iconv'
    iconv_build.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, CC=str(tools/'aarch64-linux-android24-clang'),
        AR=str(tools/'llvm-ar'), RANLIB=str(tools/'llvm-ranlib'), CFLAGS='-O2 -fPIC',
        LDFLAGS='-Wl,-z,max-page-size=16384')
    if not (iconv_build/'Makefile').exists():
        run([iconv/'configure', '--host=aarch64-linux-android', '--disable-shared', '--enable-static',
            '--prefix='+str(prefix)], cwd=iconv_build, env=environment)
    run(['make', '-j6'], cwd=iconv_build)
    run(['make', 'install'], cwd=iconv_build)
    cross = ROOT/'build/gnubg-deps/android-arm64.cross'
    compile_flags = ['-DANDROID', '-fPIC', '-O2', '-I'+str(prefix/'include')]
    link_flags = ['-Wl,-z,max-page-size=16384', '-L'+str(prefix/'lib'), '-liconv']
    cross.write_text(f'''[binaries]
c = '{tools}/aarch64-linux-android24-clang'
cpp = '{tools}/aarch64-linux-android24-clang++'
ar = '{tools}/llvm-ar'
strip = '{tools}/llvm-strip'
pkg-config = 'false'
[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'
[built-in options]
c_args = {compile_flags!r}
cpp_args = {compile_flags!r}
c_link_args = {link_flags!r}
cpp_link_args = {link_flags!r}
[properties]
have_posix_threads = true
''')
    glib_build = ROOT/'build/gnubg-glib-iconv'
    if not (glib_build/'build.ninja').exists():
        run(['meson', 'setup', glib_build, glib, '--cross-file', cross, '--prefix', '/', '--libdir', 'lib',
            '--includedir', 'include', '--buildtype', 'release', '--default-library', 'static',
            '-Dglib_debug=disabled', '-Dtests=false', '-Dinstalled_tests=false', '-Ddocumentation=false',
            '-Dman-pages=disabled', '-Dintrospection=disabled', '-Dselinux=disabled', '-Dxattr=false',
            '-Dlibelf=disabled', '-Dlibmount=disabled', '-Ddtrace=disabled', '-Dsystemtap=disabled',
            '-Dsysprof=disabled', '-Dglib_assert=false', '-Dglib_checks=false', '-Dnls=disabled',
            '--wrap-mode=forcefallback'])
    libraries = ['glib/libglib-2.0.a', 'gobject/libgobject-2.0.a', 'subprojects/pcre2-10.46/libpcre2-8.a',
        'subprojects/libffi-3.5.2/src/libffi.a', 'subprojects/proxy-libintl-0.5/libintl.a']
    # Build only the required archives; fallback projects otherwise build thousands of test binaries.
    run(['ninja', '-C', glib_build, '-j6', *libraries])
    installed = json.loads(subprocess.check_output(['meson', 'introspect', '--installed', str(glib_build)], text=True))
    for src, destination in installed.items():
        if isinstance(destination, str) and (destination.startswith('/include/') or destination.endswith('/glibconfig.h')) and Path(src).is_file():
            target = prefix/destination.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    for library in libraries:
        shutil.copy2(glib_build/library, prefix/'lib'/Path(library).name)

module = ROOT/('build/backgammon-android' if args.target == 'android' else 'build/backgammon-host')
module.mkdir(parents=True, exist_ok=True)
stage = module/'source'
for directory in ['engine-core', 'jni-bridge']:
    shutil.copytree(source/directory, stage/directory, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('build*', 'external'))
if args.target == 'android':
    config = stage/'engine-core/config.h'
    config.write_text(re.sub(r'^#define HAVE_GETRANDOM .*$',
        '/* Android API24: use the GNU urandom fallback. */', config.read_text(), flags=re.M))
for filename in ['backgammon-cli.c', 'backgammon-log.c']:
    shutil.copy2(ROOT/'scripts'/filename, module/filename)
body = re.search(r'add_library\(gnubg-engine SHARED(.*?)\n\)',
    (source/'jni-bridge/CMakeLists.txt').read_text(), re.S).group(1)
sources = []
for line in body.strip().splitlines():
    filename = line.strip().replace('${ENGINE}', str(stage/'engine-core')).replace('${CMAKE_CURRENT_SOURCE_DIR}', str(stage/'jni-bridge'))
    if filename.startswith('src/'):
        filename = str(stage/'jni-bridge'/filename)
    if not filename.endswith('native-lib.c'):
        sources.append(filename)
includes = [stage/'jni-bridge', stage/'jni-bridge/include', stage/'engine-core', stage/'engine-core/lib']
output = ROOT/'build/backgammon'/args.target
output.mkdir(parents=True, exist_ok=True)
if args.target == 'macos':
    flags = subprocess.check_output(['pkg-config', '--cflags', 'glib-2.0', 'gobject-2.0'], text=True).split()
    libraries = subprocess.check_output(['pkg-config', '--libs', 'glib-2.0', 'gobject-2.0'], text=True).split()
    command = ['cc', '-O2', '-DHAVE_CONFIG_H', '-DAC_DATADIR="."', '-DAC_PKGDATADIR="."', '-DAC_DOCDIR="."']
    for include in [source/'tools/shim', *includes]:
        command += ['-I', str(include)]
    run(command + flags + ['-o', output/'backgammon', module/'backgammon-cli.c', module/'backgammon-log.c'] + sources + libraries + ['-lm', '-lpthread'])
else:
    includes += [prefix/'include', prefix/'include/glib-2.0', prefix/'lib/glib-2.0/include']
    cmake = 'cmake_minimum_required(VERSION 3.22)\nproject(joyorbit_backgammon C)\nadd_executable(joyorbit_backgammon backgammon-cli.c\n'
    cmake += '\n'.join(json.dumps(filename) for filename in sources)+'\n)\n'
    cmake += 'target_include_directories(joyorbit_backgammon PRIVATE '+' '.join(json.dumps(str(p)) for p in includes)+')\n'
    cmake += 'target_compile_definitions(joyorbit_backgammon PRIVATE HAVE_CONFIG_H G_INTL_STATIC_COMPILATION PCRE2_STATIC AC_DATADIR="." AC_PKGDATADIR="." AC_DOCDIR="." USE_SIMD_INSTRUCTIONS HAVE_NEON USE_NEON)\n'
    cmake += 'target_compile_options(joyorbit_backgammon PRIVATE -O2)\ntarget_link_options(joyorbit_backgammon PRIVATE -Wl,-z,max-page-size=16384)\n'
    cmake += 'target_link_libraries(joyorbit_backgammon PRIVATE -Wl,--start-group '+' '.join(json.dumps(str(prefix/'lib'/name)) for name in ['libgobject-2.0.a', 'libglib-2.0.a', 'libpcre2-8.a', 'libffi.a', 'libintl.a', 'libiconv.a'])+' -Wl,--end-group log m atomic)\n'
    (module/'CMakeLists.txt').write_text(cmake)
    cmake_program = sdk/'cmake/3.22.1/bin/cmake'
    run([cmake_program, '-S', module, '-B', module/'cmake', '-G', 'Ninja', '-DCMAKE_TOOLCHAIN_FILE='+str(ndk/'build/cmake/android.toolchain.cmake'),
        '-DANDROID_ABI=arm64-v8a', '-DANDROID_PLATFORM=android-24', '-DCMAKE_BUILD_TYPE=Release'])
    run([cmake_program, '--build', module/'cmake', '-j6'])
    shutil.copy2(module/'cmake/joyorbit_backgammon', output/'libjoyorbit_backgammon.so')

data = ROOT/'games/data/backgammon'
data.mkdir(parents=True, exist_ok=True)
shutil.copy2(weights, data/'gnubg.weights')
shutil.copytree(source/'gnubg-app/app/src/main/assets/met', data/'met', dirs_exist_ok=True)
(output/'source.json').write_text(json.dumps({'engine':'GNU Backgammon', 'version':'1.08.003', 'facade_source':PIN, 'weights_sha256':WEIGHTS}))
print('Separate GNU Backgammon program built; runtime and device checks remain separate.')
