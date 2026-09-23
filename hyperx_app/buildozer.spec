[app]
title = HyperX
package.name = hyperx
package.domain = com.rimo.hyperx
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,json,txt
source.include_patterns = assets/*,templates/*,static/*,*.py,*.json,*.db
version = 1.0.0

requirements = python3,kivy==2.3.0,flask==3.0.3,pyjnius,android,werkzeug==3.0.3,jinja2==3.1.4,itsdangerous==2.2.0,click==8.1.7,markupsafe==2.1.5,blinker==1.8.2

orientation = portrait
fullscreen = 0
presplash.filename = %(source.dir)s/data/presplash.png
icon.filename = %(source.dir)s/data/icon.png

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.allow_backup = True
android.accept_sdk_license = True
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
