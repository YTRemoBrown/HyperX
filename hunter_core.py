# -*- coding: utf-8 -*-
"""
HyperX Core v5.0 - Fast APK/ZIP Analyzer + AXML + Threaded Unzip
Developed by: ريمو براون
© 2026 All Rights Reserved
"""
import os
import re
import zipfile
import subprocess
import tempfile
import shutil
import hashlib
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from axml_decoder import (
    decode_axml, decode_arsc_strings, is_axml, is_arsc
)
from resource_guard import (
    check_apk_size, check_zip_contents, check_memory,
    cleanup_orphans, get_disk_usage, ResourceError, LIMITS,
    fast_extract
)


SDK_DOMAINS = [
    "schemas.android.com", "w3.org", "apache.org", "googleapis.com",
    "gstatic.com", "crashlytics.com", "firebase.com", "firebaseio.com",
    "facebook.com/help", "example.com", "github.com/schemas",
    "xmlpull.org", "json.org", "slf4j.org", "squareup.com",
    "bouncycastle.org", "kotlinlang.org", "jetbrains.com",
    "mozilla.org", "creativecommons.org", "unity3d.com",
    "adobe.com", "oracle.com", "microsoft.com",
    "android.com", "gradle.org", "intellij.net", "eclipse.org",
    "openssl.org", "zlib.net", "libpng.org", "sqlite.org",
    "unicode.org", "ietf.org", "iana.org", "rfc-editor.org",
    "json-schema.org", "swagger.io", "openapis.org",
]

TRACKER_DOMAINS = {
    "Google Analytics": ["google-analytics.com", "googletagmanager.com", "analytics.google.com"],
    "Firebase": ["firebase.com", "firebaseio.com", "firebaseapp.com", "crashlytics.com"],
    "Facebook": ["facebook.com", "fbcdn.net", "graph.facebook.com"],
    "AdMob": ["admob.com", "pagead2.googlesyndication.com"],
    "Adjust": ["adjust.com"],
    "AppsFlyer": ["appsflyer.com"],
    "Mixpanel": ["mixpanel.com"],
    "Amplitude": ["amplitude.com"],
    "Sentry": ["sentry.io"],
    "Bugsnag": ["bugsnag.com"],
    "OneSignal": ["onesignal.com"],
    "Unity Ads": ["unityads.unity3d.com"],
    "AppLovin": ["applovin.com"],
    "Vungle": ["vungle.com"],
    "ironSource": ["ironsrc.com", "supersonicads.com"],
    "TikTok Ads": ["tiktok.com", "byteoversea.com"],
    "Huawei": ["huawei.com", "hicloud.com"],
    "Yandex": ["yandex.ru", "yandex.net"],
    "Branch": ["branch.io"],
    "Leanplum": ["leanplum.com"],
    "MoPub": ["mopub.com"],
    "Chartboost": ["chartboost.com"],
    "Flurry": ["flurry.com"],
    "Countly": ["count.ly"],
}

CODE_NOISE_PATTERNS = [
    r"^L[a-zA-Z0-9_/;$]+$",
    r"^\[L[a-zA-Z0-9_/;$]+;?$",
    r"^\([A-Za-z0-9_/;\[\]]+\)",
    r"^[VZBCSIJFD]$",
    r"^[0-9a-f]{8,}$",
    r"^[A-Z0-9_]{20,}$",
    r"^\s*[{}();]+\s*$",
    r"^[a-z]{1,2}$",
    r"^[A-Za-z0-9+/]{40,}={0,2}$",
    r"^.*\\u[0-9a-fA-F]{4}.*$",
    r"^.*\$\{.*\}.*$",
]

AUTHOR_PATTERNS = [
    re.compile(r"(?:developed|created|made|built|written|authored|maintained)\s+by\s+[:\-]?\s*([A-Za-z\u0600-\u06FF][A-Za-z0-9\u0600-\u06FF ._\-]{1,60})", re.I),
    re.compile(r"(?:copyright|\(c\))\s*(?:19|20)?\d{0,4}\s*[:\-]?\s*(?:by\s+)?([A-Za-z\u0600-\u06FF][A-Za-z0-9\u0600-\u06FF ._\-]{2,60})", re.I),
    re.compile(r"(?:author|developer|owner|maintainer|creator)\s*[:=]\s*([A-Za-z\u0600-\u06FF][A-Za-z0-9\u0600-\u06FF ._\-]{1,60})", re.I),
    re.compile(r"(?:all rights reserved)\s*(?:by|to)?\s*([A-Z][A-Za-z0-9 ._\-]{2,60})", re.I),
]

CODE_CONTEXT_BLACKLIST = [
    "class ", "public ", "private ", "protected ", "static ",
    "extends ", "implements ", "interface ", "package ",
    "import ", "return ", "throw ", "void ", "int ", "long ",
    "<init>", "<clinit>", "Ljava/", "Landroid/", "Lkotlin/",
    "0x", "0X", "\\u", "%s", "%d", "{}", "//", "/*", "*/",
]


class InputInfo:
    def __init__(self, path):
        self.path = path
        self.kind = "unknown"
        self.original_apk = None
        self._detect()

    def _detect(self):
        if os.path.isdir(self.path):
            self.kind = "dir"
            return
        low = self.path.lower()
        if low.endswith((".apk", ".apks", ".xapk")):
            self.kind = "apk"
            return
        try:
            if zipfile.is_zipfile(self.path):
                with zipfile.ZipFile(self.path, "r") as z:
                    names = z.namelist()
                    sig_files = ["classes.dex", "AndroidManifest.xml", "resources.arsc"]
                    if any(any(n == s or n.endswith("/" + s) for n in names) for s in sig_files):
                        self.kind = "zip_unpacked"
                        return
                    for n in names:
                        if n.lower().endswith(".apk"):
                            self.kind = "zip_with_apk"
                            self.original_apk = n
                            return
        except Exception:
            pass
        self.kind = "unknown"


class HyperX:
    def __init__(self, input_path, timeout=120, progress_cb=None):
        self.input_path = input_path
        self.timeout = timeout
        self.progress_cb = progress_cb
        self.tmpdir = None
        self.apk_path = None
        self.input_info = InputInfo(input_path)
        self.results = {
            "basic": {},
            "app_names": [],
            "developers": [],
            "emails": [],
            "social": {},
            "websites": [],
            "trackers": [],
            "secrets": [],
            "crypto": [],
            "ips": [],
            "so_symbols": [],
            "so_libs": [],
            "resources": [],
            "manifest_info": {},
            "security_score": {},
            "stats": {},
            "files": [],
            "input_kind": "",
        }
        self.file_hits = defaultdict(int)
        self._seen_strings = set()
        self._string_paths = defaultdict(set)

    def _report(self, pct, stage=""):
        if self.progress_cb:
            try:
                self.progress_cb(pct, stage)
            except Exception:
                pass

    def _run(self, cmd, timeout=30):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout, text=False)
            return r.stdout or b""
        except Exception:
            return b""

    def _prepare(self):
        self._report(2, "تهيئة")
        try:
            cleanup_orphans()
        except Exception:
            pass
        check_apk_size(self.input_path)
        try:
            check_memory()
        except ResourceError:
            pass

        self.tmpdir = tempfile.mkdtemp(prefix="hyperx_")
        self.results["input_kind"] = self.input_info.kind

        if self.input_info.kind == "apk":
            self._report(5, "فحص ZIP")
            check_zip_contents(self.input_path)
            self.apk_path = self.input_path
            self._report(8, "فك APK متوازي")
            fast_extract(self.input_path, self.tmpdir)

        elif self.input_info.kind in ("zip_unpacked", "zip_with_apk"):
            self._report(5, "فحص ZIP")
            check_zip_contents(self.input_path)
            self._report(8, "فك ZIP متوازي")
            fast_extract(self.input_path, self.tmpdir)

            mb = get_disk_usage(self.tmpdir)
            if mb > LIMITS["max_unpacked_mb"]:
                raise ResourceError(f"⚠️ الحجم المفكوك {mb:.0f} MB يتجاوز الحد.")

            if self.input_info.kind == "zip_with_apk":
                for root, dirs, files in os.walk(self.tmpdir):
                    for f in files:
                        if f.lower().endswith(".apk"):
                            self.apk_path = os.path.join(root, f)
                            try:
                                check_apk_size(self.apk_path)
                                check_zip_contents(self.apk_path)
                            except ResourceError:
                                raise
                            subdir = os.path.join(self.tmpdir, "_apk_inner")
                            os.makedirs(subdir, exist_ok=True)
                            self._report(10, "فك APK الداخلي")
                            fast_extract(self.apk_path, subdir)
                            shutil.rmtree(self.tmpdir, ignore_errors=True)
                            self.tmpdir = subdir
                            break

        elif self.input_info.kind == "dir":
            self.apk_path = None
            mb = get_disk_usage(self.input_path)
            if mb > LIMITS["max_unpacked_mb"]:
                raise ResourceError(f"⚠️ المجلد كبير ({mb:.0f} MB).")
            shutil.copytree(self.input_path, self.tmpdir, dirs_exist_ok=True)
        else:
            raise ValueError(f"نوع غير مدعوم: {self.input_info.kind}")

        self._report(15, "تم الفك")

    def _cleanup(self):
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        import gc
        gc.collect()

    def _is_code_noise(self, s):
        if not s or len(s) < 4:
            return True
        for pat in CODE_NOISE_PATTERNS:
            try:
                if re.match(pat, s):
                    return True
            except Exception:
                pass
        printable = sum(1 for c in s if c.isprintable() and (c.isalnum() or c in " .,:;_-@/()[]{}"))
        if len(s) > 0 and printable / len(s) < 0.7:
            return True
        return False

    def _track(self, rel_path, text):
        self._string_paths[text].add(rel_path)

    def _strings_from_binary(self, path, min_len=6):
        result = []
        out = self._run(["strings", "-n", str(min_len), path], 15)
        if out:
            for line in out.decode("utf-8", "ignore").splitlines():
                line = line.strip()
                if line and not self._is_code_noise(line):
                    result.append(line)
            return result
        try:
            data = open(path, "rb").read()
            if len(data) > 15 * 1024 * 1024:
                data = data[:15 * 1024 * 1024]
            pat = re.compile(rb"[\x20-\x7E]{%d,}" % min_len)
            for m in pat.finditer(data):
                s = m.group().decode("utf-8", "ignore")
                if not self._is_code_noise(s):
                    result.append(s)
        except Exception:
            pass
        return result

    def _strings_from_text(self, path):
        try:
            data = open(path, "rb").read()
            if len(data) > 5 * 1024 * 1024:
                data = data[:5 * 1024 * 1024]
            text = data.decode("utf-8", "ignore")
            return [l.strip() for l in text.splitlines() if l.strip() and not self._is_code_noise(l.strip())]
        except Exception:
            return []

    def _list_target_files(self):
        targets = []
        seen = set()
        for root, dirs, files in os.walk(self.tmpdir):
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, self.tmpdir)
                if rel in seen:
                    continue
                seen.add(rel)
                low = f.lower()
                try:
                    with open(fp, "rb") as pf:
                        head = pf.read(8)
                except Exception:
                    continue
                if len(head) >= 2:
                    import struct as _st
                    t = _st.unpack_from("<H", head, 0)[0]
                    if t == 0x0003:
                        targets.append((fp, rel, "axml"))
                        continue
                    if t == 0x0002:
                        targets.append((fp, rel, "arsc"))
                        continue

                if low.endswith((".xml", ".json", ".txt", ".properties", ".html",
                                 ".js", ".css", ".md", ".yml", ".yaml",
                                 ".smali", ".java", ".kt", ".gradle", ".pro")):
                    targets.append((fp, rel, "text"))
                elif low.endswith((".dex", ".so", ".odex", ".vdex", ".oat", ".jar", ".bin")):
                    targets.append((fp, rel, "binary"))
                elif rel.startswith(("assets/", "res/raw/")):
                    kind = "text" if low.endswith((".xml", ".json", ".txt", ".properties", ".html", ".js")) else "binary"
                    targets.append((fp, rel, kind))
        return targets

    def _analyze_basic(self):
        self._report(18, "قراءة المعلومات")
        size = os.path.getsize(self.input_path) if os.path.isfile(self.input_path) else 0
        name = os.path.basename(self.input_path)

        try:
            h = hashlib.sha256()
            if os.path.isfile(self.input_path):
                with open(self.input_path, "rb") as fp:
                    for chunk in iter(lambda: fp.read(65536), b""):
                        h.update(chunk)
                sha256 = h.hexdigest()
            else:
                sha256 = "N/A"
        except Exception:
            sha256 = "N/A"

        text = ""
        if self.apk_path and os.path.isfile(self.apk_path):
            out = self._run(["aapt", "dump", "badging", self.apk_path], 25)
            text = out.decode("utf-8", "ignore")

        pkg = re.search(r"package: name='([^']+)'", text)
        ver = re.search(r"versionName='([^']+)'", text)
        vcode = re.search(r"versionCode='([^']+)'", text)
        perms = re.findall(r"uses-permission: name='([^']+)'", text)

        app_label_matches = re.findall(r"application-label(?:-\w+)?:'([^']+)'", text)
        app_names = list(dict.fromkeys([n for n in app_label_matches if n.strip()]))
        self.results["app_names"] = app_names[:10]

        min_sdk = re.search(r"sdkVersion:'([^']+)'", text)
        target_sdk = re.search(r"targetSdkVersion:'([^']+)'", text)
        launchable = re.findall(r"launchable-activity: name='([^']+)'", text)

        manifest_path = None
        for root, dirs, files in os.walk(self.tmpdir):
            if "AndroidManifest.xml" in files:
                manifest_path = os.path.join(root, "AndroidManifest.xml")
                break

        manifest_xml = None
        if manifest_path:
            try:
                data = open(manifest_path, "rb").read()
                if is_axml(data):
                    manifest_xml = decode_axml(data)
                else:
                    manifest_xml = data.decode("utf-8", "ignore")
            except Exception:
                pass

        if manifest_xml and not pkg:
            m = re.search(r'package="([^"]+)"', manifest_xml)
            pkg_str = m.group(1) if m else "غير معروف"
            m = re.search(r'android:versionName="([^"]+)"', manifest_xml)
            ver_str = m.group(1) if m else "غير معروف"
            m = re.search(r'android:versionCode="([^"]+)"', manifest_xml)
            vcode_str = m.group(1) if m else "غير معروف"
            perms = re.findall(r'android:name="(android\.permission\.[A-Z_]+)"', manifest_xml)
            m = re.search(r'android:minSdkVersion="([^"]+)"', manifest_xml)
            min_sdk_str = m.group(1) if m else "غير معروف"
            m = re.search(r'android:targetSdkVersion="([^"]+)"', manifest_xml)
            target_sdk_str = m.group(1) if m else "غير معروف"
        else:
            pkg_str = pkg.group(1) if pkg else "غير معروف"
            ver_str = ver.group(1) if ver else "غير معروف"
            vcode_str = vcode.group(1) if vcode else "غير معروف"
            min_sdk_str = min_sdk.group(1) if min_sdk else "غير معروف"
            target_sdk_str = target_sdk.group(1) if target_sdk else "غير معروف"

        dex_count = 0
        so_count = 0
        total_size = 0
        for root, dirs, files in os.walk(self.tmpdir):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total_size += os.path.getsize(fp)
                except Exception:
                    pass
                if f.endswith(".dex"):
                    dex_count += 1
                if f.endswith(".so"):
                    so_count += 1

        self.results["basic"] = {
            "name": name,
            "app_name": app_names[0] if app_names else "غير معروف",
            "package": pkg_str,
            "version": ver_str,
            "version_code": vcode_str,
            "min_sdk": min_sdk_str,
            "target_sdk": target_sdk_str,
            "size_mb": round(size / (1024 * 1024), 2),
            "size_unpacked_mb": round(total_size / (1024 * 1024), 2),
            "size_bytes": size,
            "sha256": sha256,
            "dex_count": dex_count,
            "so_count": so_count,
            "launchable": launchable[0] if launchable else "غير معروف",
            "permissions": list(dict.fromkeys(perms))[:60],
            "input_kind": self.input_info.kind,
        }

        if manifest_xml:
            info = {}
            info["activities"] = len(re.findall(r"<activity[\s>]", manifest_xml))
            info["services"] = len(re.findall(r"<service[\s>]", manifest_xml))
            info["receivers"] = len(re.findall(r"<receiver[\s>]", manifest_xml))
            info["providers"] = len(re.findall(r"<provider[\s>]", manifest_xml))
            info["exported_count"] = len(re.findall(r'android:exported="true"', manifest_xml))
            info["debuggable"] = 'android:debuggable="true"' in manifest_xml
            info["allow_backup"] = 'android:allowBackup="true"' in manifest_xml
            info["cleartext"] = 'android:usesCleartextTraffic="true"' in manifest_xml
            self.results["manifest_info"] = info
            self.results["manifest_xml_preview"] = manifest_xml[:3000]

    def _collect_all_strings(self, targets):
        self._report(25, f"جمع النصوص من {len(targets)} ملف")
        all_strings = []
        total = len(targets)
        done = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {}
            for fp, rel, kind in targets:
                if kind == "axml":
                    futs[ex.submit(self._extract_axml_strings, fp, rel)] = rel
                elif kind == "arsc":
                    futs[ex.submit(self._extract_arsc_strings, fp, rel)] = rel
                elif kind == "binary":
                    futs[ex.submit(self._strings_from_binary, fp)] = rel
                else:
                    futs[ex.submit(self._strings_from_text, fp)] = rel
            for fut in as_completed(futs):
                rel = futs[fut]
                done += 1
                if done % 20 == 0 and total > 0:
                    pct = 25 + int((done / total) * 30)
                    self._report(pct, f"نصوص {done}/{total}")
                try:
                    strs = fut.result()
                except Exception:
                    strs = []
                for s in strs:
                    all_strings.append((rel, s))
                    self._track(rel, s)
        return all_strings

    def _extract_axml_strings(self, fp, rel):
        try:
            data = open(fp, "rb").read()
            xml_text = decode_axml(data)
            if not xml_text:
                return []
            lines = []
            for line in xml_text.splitlines():
                line = line.strip()
                if line and not self._is_code_noise(line):
                    lines.append(line)
            try:
                cache_dir = os.path.join(self.tmpdir, "_decoded_xml")
                os.makedirs(cache_dir, exist_ok=True)
                safe = rel.replace("/", "__")
                with open(os.path.join(cache_dir, safe + ".xml"), "w", encoding="utf-8") as wf:
                    wf.write(xml_text)
            except Exception:
                pass
            return lines
        except Exception:
            return []

    def _extract_arsc_strings(self, fp, rel):
        try:
            data = open(fp, "rb").read()
            strings = decode_arsc_strings(data)
            if len(strings) < 20:
                strings = self._strings_from_binary(fp, min_len=4)
            return strings
        except Exception:
            return []

    def _extract_developers(self, all_strings):
        self._report(58, "المطورون")
        counter = Counter()
        seen = set()
        for rel, s in all_strings:
            if len(s) > 300:
                continue
            if any(bl in s for bl in CODE_CONTEXT_BLACKLIST):
                continue
            for pat in AUTHOR_PATTERNS:
                m = pat.search(s)
                if m:
                    nm = m.group(1).strip()
                    nm = re.sub(r"\s+", " ", nm).strip(" .,:;-")
                    if len(nm) < 3 or len(nm) > 80:
                        continue
                    if re.match(r"^[\d\s\-.]+$", nm):
                        continue
                    if any(c in nm for c in "{}<>;()[]\\"):
                        continue
                    ctx = s.strip()[:150]
                    key = (ctx, rel)
                    if key in seen:
                        continue
                    seen.add(key)
                    counter[key] += 1
                    self.file_hits[rel] += 1
        ranked = sorted(counter.items(), key=lambda x: (-x[1], len(x[0][0])))
        self.results["developers"] = [
            {"value": k[0], "file": k[1], "count": v} for k, v in ranked[:10]
        ]

    def _extract_emails(self, all_strings):
        email_re = re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9][a-zA-Z0-9.\-]{2,}\.[a-zA-Z]{2,10}\b")
        counter = Counter()
        for rel, s in all_strings:
            for m in email_re.findall(s):
                if m.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")):
                    continue
                if "@2x" in m or "@3x" in m:
                    continue
                counter[(m, rel)] += 1
                self.file_hits[rel] += 1
        ranked = sorted(counter.items(), key=lambda x: -x[1])
        self.results["emails"] = [
            {"value": k[0], "file": k[1], "count": v} for k, v in ranked[:10]
        ]

    def _extract_social(self, all_strings):
        self._report(62, "روابط التواصل")
        patterns = {
            "GitHub": r"\bgithub\.com/([A-Za-z0-9_\-]{1,40})(?:/|$|\s|[\"'])",
            "YouTube": r"\b(?:youtube\.com/(?:@|c/|channel/|user/)([A-Za-z0-9_.\-]{2,50})|youtu\.be/([A-Za-z0-9_\-]{8,15}))",
            "Telegram": r"\bt\.me/([A-Za-z0-9_]{3,40})\b",
            "Twitter": r"\b(?:twitter\.com|x\.com)/([A-Za-z0-9_]{2,30})\b",
            "Facebook": r"\bfacebook\.com/([A-Za-z0-9_.\-]{2,60})\b",
            "Instagram": r"\binstagram\.com/([A-Za-z0-9_.\-]{2,60})\b",
            "Discord": r"\b(?:discord\.gg/([A-Za-z0-9]{4,20})|discord\.com/invite/([A-Za-z0-9]{4,20}))",
            "TikTok": r"\btiktok\.com/@([A-Za-z0-9_.\-]{2,40})\b",
            "LinkedIn": r"\blinkedin\.com/(?:in|company)/([A-Za-z0-9_\-]{2,60})\b",
            "WhatsApp": r"\b(?:wa\.me/(\d{6,20})|api\.whatsapp\.com/send\?phone=(\d{6,20}))",
            "Reddit": r"\breddit\.com/(?:u|user|r)/([A-Za-z0-9_\-]{2,40})\b",
            "Pinterest": r"\bpinterest\.com/([A-Za-z0-9_\-]{2,40})\b",
        }
        compiled = {k: re.compile(v, re.IGNORECASE) for k, v in patterns.items()}
        ignore_users = {
            "facebook": ["sharer", "dialog", "plugins", "tr", "connect", "profile.php", "policy.php", "help", "legal", "policies"],
            "twitter": ["intent", "share", "home", "i", "widgets", "oauth"],
            "youtube": ["watch", "results", "playlist", "embed", "channel"],
            "instagram": ["p", "reel", "explore", "developer"],
            "github": ["google", "facebook", "apache", "square", "jetbrains", "kotlin", "flutter", "react", "vue", "angular"],
            "linkedin": ["shareArticle", "sharing", "share"],
        }
        out = {}
        for name, rgx in compiled.items():
            counter = Counter()
            for rel, s in all_strings:
                for m in rgx.findall(s):
                    handle = next((g for g in (m if isinstance(m, tuple) else (m,)) if g), None)
                    if not handle:
                        continue
                    handle = handle.strip().strip("/.")
                    low = handle.lower()
                    if name.lower() in ignore_users:
                        if any(bad.lower() in low for bad in ignore_users[name.lower()]):
                            continue
                    full = self._rebuild_url(name, s, handle)
                    if not full:
                        continue
                    counter[(full, rel)] += 1
                    self.file_hits[rel] += 1
            ranked = sorted(counter.items(), key=lambda x: -x[1])
            out[name] = [
                {"value": k[0], "file": k[1], "count": v} for k, v in ranked[:10]
            ]
        self.results["social"] = out

    def _rebuild_url(self, platform, text, handle):
        patterns = {
            "GitHub": rf"github\.com/{re.escape(handle)}",
            "YouTube": rf"(?:youtube\.com/(?:@|c/|channel/|user/){re.escape(handle)}|youtu\.be/{re.escape(handle)})",
            "Telegram": rf"t\.me/{re.escape(handle)}",
            "Twitter": rf"(?:twitter\.com|x\.com)/{re.escape(handle)}",
            "Facebook": rf"facebook\.com/{re.escape(handle)}",
            "Instagram": rf"instagram\.com/{re.escape(handle)}",
            "Discord": rf"(?:discord\.gg|discord\.com/invite)/{re.escape(handle)}",
            "TikTok": rf"tiktok\.com/@{re.escape(handle)}",
            "LinkedIn": rf"linkedin\.com/(?:in|company)/{re.escape(handle)}",
            "WhatsApp": rf"(?:wa\.me|api\.whatsapp\.com/send\?phone=)/{re.escape(handle)}",
            "Reddit": rf"reddit\.com/(?:u|user|r)/{re.escape(handle)}",
            "Pinterest": rf"pinterest\.com/{re.escape(handle)}",
        }
        m = re.search(patterns.get(platform, ""), text, re.I)
        return m.group(0) if m else None

    def _extract_websites(self, all_strings):
        self._report(66, "المواقع")
        url_re = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9._\-]{0,60}\.[A-Za-z]{2,15}(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]{0,150})?")
        counter = Counter()
        for rel, s in all_strings:
            for m in url_re.findall(s):
                u = m.strip().rstrip(".,);\"'")
                low = u.lower()
                if any(sdk in low for sdk in SDK_DOMAINS):
                    continue
                if len(u) > 150:
                    continue
                if any(x in low for x in ["/maven2/", "/pom.xml", "/gradle/", "//schema", "//schemas"]):
                    continue
                counter[(u, rel)] += 1
                self.file_hits[rel] += 1
        ranked = sorted(counter.items(), key=lambda x: -x[1])
        self.results["websites"] = [
            {"value": k[0], "file": k[1], "count": v} for k, v in ranked[:10]
        ]

    def _detect_trackers(self, all_strings):
        self._report(70, "المتتبعات")
        found = {}
        for rel, s in all_strings:
            low = s.lower()
            for tracker, domains in TRACKER_DOMAINS.items():
                for d in domains:
                    if d in low or tracker.lower() in low:
                        if tracker not in found:
                            found[tracker] = {"count": 0, "files": set(), "domain": d}
                        found[tracker]["count"] += 1
                        found[tracker]["files"].add(rel)
                        break
        self.results["trackers"] = [
            {
                "name": name,
                "domain": info["domain"],
                "count": info["count"],
                "files": sorted(info["files"])[:3],
            }
            for name, info in sorted(found.items(), key=lambda x: -x[1]["count"])
        ]

    def _extract_secrets(self, all_strings):
        self._report(74, "الأسرار")
        patterns = {
            "Google API Key": (r"\bAIza[0-9A-Za-z_\-]{35}\b", None),
            "AWS Access Key": (r"\bAKIA[0-9A-Z]{16}\b", None),
            "AWS Secret Key": (r"(?i)aws[_\-]?secret[_\-]?(?:access[_\-]?)?key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?", 1),
            "Firebase DB": (r"https://[a-z0-9\-]{3,50}\.firebaseio\.com", None),
            "Firebase App": (r"https://[a-z0-9\-]{3,50}\.firebaseapp\.com", None),
            "JWT Token": (r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b", None),
            "Stripe Live": (r"\bsk_live_[0-9a-zA-Z]{24,}\b", None),
            "Stripe Test": (r"\bsk_test_[0-9a-zA-Z]{24,}\b", None),
            "Stripe Publishable": (r"\bpk_(?:live|test)_[0-9a-zA-Z]{24,}\b", None),
            "Slack Token": (r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b", None),
            "Slack Webhook": (r"https://hooks\.slack\.com/services/[A-Z0-9/]{20,}", None),
            "Private Key": (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----", None),
            "Google OAuth": (r"\b[0-9]{10,14}-[a-z0-9]{20,40}\.apps\.googleusercontent\.com\b", None),
            "GitHub Token": (r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", None),
            "SendGrid Key": (r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b", None),
            "Twilio SID": (r"\bAC[0-9a-fA-F]{32}\b", None),
            "Discord Webhook": (r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+", None),
            "Mailgun": (r"\bkey-[0-9a-zA-Z]{32}\b", None),
            "Mapbox": (r"\bpk\.[A-Za-z0-9]{60,}\b", None),
        }
        compiled = {k: (re.compile(v[0]), v[1]) for k, v in patterns.items()}
        counter = Counter()
        for rel, s in all_strings:
            if len(s) > 500:
                continue
            for name, (rgx, grp) in compiled.items():
                for m in rgx.finditer(s):
                    val = m.group(grp) if grp else m.group(0)
                    if not val or len(val) < 8:
                        continue
                    counter[(name, val, rel)] += 1
                    self.file_hits[rel] += 1
        ranked = sorted(counter.items(), key=lambda x: -x[1])
        self.results["secrets"] = [
            {"type": k[0], "value": k[1], "file": k[2], "count": v}
            for k, v in ranked[:15]
        ]

    def _extract_crypto(self, all_strings):
        patterns = {
            "Bitcoin": r"\b(?:bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b",
            "Ethereum": r"\b0x[a-fA-F0-9]{40}\b",
            "Tron": r"\bT[A-Za-z1-9]{33}\b",
            "Litecoin": r"\b(?:ltc1[a-z0-9]{25,62}|[LM3][a-km-zA-HJ-NP-Z1-9]{25,34})\b",
            "Monero": r"\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b",
            "Ripple": r"\br[1-9A-HJ-NP-Za-km-z]{24,34}\b",
        }
        compiled = {k: re.compile(v) for k, v in patterns.items()}
        counter = Counter()
        for rel, s in all_strings:
            if len(s) > 500:
                continue
            for name, rgx in compiled.items():
                for m in rgx.findall(s):
                    counter[(name, m, rel)] += 1
                    self.file_hits[rel] += 1
        ranked = sorted(counter.items(), key=lambda x: -x[1])
        self.results["crypto"] = [
            {"type": k[0], "value": k[1], "file": k[2], "count": v}
            for k, v in ranked[:10]
        ]

    def _extract_ips(self, all_strings):
        ip_re = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
        private_re = re.compile(r"^(?:10\.|127\.|0\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|224\.|255\.)")
        counter = Counter()
        for rel, s in all_strings:
            if len(s) > 500:
                continue
            for m in ip_re.findall(s):
                if private_re.match(m):
                    continue
                if m in ("0.0.0.0", "255.255.255.255", "1.1.1.1", "8.8.8.8"):
                    continue
                counter[(m, rel)] += 1
                self.file_hits[rel] += 1
        ranked = sorted(counter.items(), key=lambda x: -x[1])
        self.results["ips"] = [
            {"value": k[0], "file": k[1], "count": v} for k, v in ranked[:10]
        ]

    def _extract_so(self):
        self._report(80, "مكتبات .so")
        symbols = []
        libs = []
        for root, dirs, files in os.walk(self.tmpdir):
            for f in files:
                if not f.endswith(".so"):
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, self.tmpdir)
                try:
                    size = os.path.getsize(fp)
                except Exception:
                    size = 0
                libs.append({"lib": rel, "size_kb": round(size / 1024, 1)})

                out = self._run(["nm", "-D", "--defined-only", fp], 15)
                found = False
                if out:
                    for line in out.decode("utf-8", "ignore").splitlines():
                        parts = line.split()
                        if len(parts) >= 3 and parts[1] in "TtWw":
                            nm = parts[2]
                            if len(nm) >= 4 and not nm.startswith("__"):
                                symbols.append({"lib": rel, "symbol": nm})
                                found = True
                if not found:
                    strs = self._strings_from_binary(fp, min_len=6)
                    for s in strs[:3000]:
                        if re.match(r"^[A-Za-z_][A-Za-z0-9_]{4,80}$", s) and not s.startswith(("http", "www", "com.", "org.")):
                            symbols.append({"lib": rel, "symbol": s})

        counter = Counter((s["lib"], s["symbol"]) for s in symbols)
        ranked = sorted(counter.items(), key=lambda x: -x[1])
        self.results["so_symbols"] = [
            {"lib": k[0], "symbol": k[1], "count": v} for k, v in ranked[:30]
        ]
        self.results["so_libs"] = sorted(libs, key=lambda x: -x["size_kb"])[:30]

    def _extract_resources(self):
        self._report(85, "الموارد")
        resources = []
        seen = set()

        for root, dirs, files in os.walk(self.tmpdir):
            for f in files:
                if f.endswith(".arsc"):
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, self.tmpdir)
                    try:
                        data = open(fp, "rb").read()
                        strings = decode_arsc_strings(data)
                        for s in strings[:200]:
                            if s in seen or len(s) < 3 or len(s) > 200:
                                continue
                            seen.add(s)
                            resources.append({"key": "arsc", "value": s, "file": rel})
                    except Exception:
                        pass

        if self.apk_path and os.path.isfile(self.apk_path):
            out = self._run(["aapt", "dump", "resources", self.apk_path], 30)
            if out:
                text = out.decode("utf-8", "ignore")
                for m in re.finditer(r"resource 0x[0-9a-f]+ string/(\w+): t=\(string8\) \"([^\"]{1,200})\"", text):
                    key, val = m.group(1), m.group(2)
                    if not val.strip() or val in seen:
                        continue
                    seen.add(val)
                    resources.append({"key": key, "value": val, "file": "resources.arsc"})

        for root, dirs, files in os.walk(os.path.join(self.tmpdir, "res")):
            for f in files:
                if not f.endswith(".xml"):
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, self.tmpdir)
                try:
                    data = open(fp, "rb").read()
                    if is_axml(data):
                        continue
                    text = data.decode("utf-8", "ignore")
                except Exception:
                    continue
                for m in re.finditer(r'<string\s+name="([^"]+)"[^>]*>([^<]{1,200})</string>', text):
                    key, val = m.group(1), m.group(2).strip()
                    if not val or val in seen:
                        continue
                    seen.add(val)
                    resources.append({"key": key, "value": val, "file": rel})
                if "<resources" in text:
                    for m in re.finditer(r'>([^<>]{4,120})<', text):
                        v = m.group(1).strip()
                        if v and v not in seen and not v.startswith(("res/", "@", "http")):
                            seen.add(v)
                            resources.append({"key": f, "value": v, "file": rel})

        cleaned = []
        for r in resources:
            v = r["value"]
            if len(v) < 3 or len(v) > 150:
                continue
            if self._is_code_noise(v):
                continue
            cleaned.append(r)

        self.results["resources"] = cleaned[:60]

    def _extract_class_context(self):
        self._report(90, "سياق الكلاسات")
        value_classes = defaultdict(set)

        for root, dirs, files in os.walk(self.tmpdir):
            for f in files:
                if not f.endswith(".dex"):
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, self.tmpdir)
                try:
                    data = open(fp, "rb").read()
                except Exception:
                    continue
                try:
                    text = data.decode("utf-8", "ignore")
                except Exception:
                    continue

                for m in re.finditer(r"[a-zA-Z0-9._%+\-]{2,64}@[a-zA-Z0-9.\-]{2,60}\.[a-zA-Z]{2,10}", text):
                    val = m.group()
                    pos = m.start()
                    ctx = self._nearest_class_before(text, pos)
                    if ctx:
                        value_classes[val].add(f"{rel} → {ctx}")

                for m in re.finditer(r"https?://[A-Za-z0-9][A-Za-z0-9._\-]{0,60}\.[A-Za-z]{2,15}(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%\-]{0,150})?", text):
                    val = m.group()
                    pos = m.start()
                    ctx = self._nearest_class_before(text, pos)
                    if ctx:
                        value_classes[val].add(f"{rel} → {ctx}")

        def enrich(items, key_getter):
            for it in items:
                v = key_getter(it)
                if v and v in value_classes:
                    it["context"] = sorted(value_classes[v])[:3]

        enrich(self.results["emails"], lambda x: x.get("value"))
        enrich(self.results["websites"], lambda x: x.get("value"))
        enrich(self.results["secrets"], lambda x: x.get("value"))
        enrich(self.results["ips"], lambda x: x.get("value"))

    @staticmethod
    def _nearest_class_before(text, pos, window=800):
        start = max(0, pos - window)
        chunk = text[start:pos]
        matches = list(re.finditer(r"L[a-zA-Z][a-zA-Z0-9_/$]{5,150};", chunk))
        if not matches:
            return None
        return matches[-1].group()

    def _security_score(self):
        self._report(93, "التقييم")
        score = 100
        issues = []
        b = self.results["basic"]
        mf = self.results.get("manifest_info", {})

        dangerous = {
            "android.permission.READ_SMS": 15,
            "android.permission.RECEIVE_SMS": 10,
            "android.permission.SEND_SMS": 10,
            "android.permission.READ_CONTACTS": 8,
            "android.permission.WRITE_CONTACTS": 8,
            "android.permission.RECORD_AUDIO": 8,
            "android.permission.CAMERA": 5,
            "android.permission.ACCESS_FINE_LOCATION": 8,
            "android.permission.ACCESS_BACKGROUND_LOCATION": 12,
            "android.permission.READ_CALL_LOG": 12,
            "android.permission.WRITE_EXTERNAL_STORAGE": 5,
            "android.permission.REQUEST_INSTALL_PACKAGES": 15,
            "android.permission.SYSTEM_ALERT_WINDOW": 10,
            "android.permission.READ_PHONE_STATE": 5,
        }
        perms = set(b.get("permissions", []))
        for p, penalty in dangerous.items():
            if p in perms:
                score -= penalty
                issues.append(f"⚠️ صلاحية حساسة: {p.split('.')[-1]}")

        if self.results["secrets"]:
            score -= min(30, len(self.results["secrets"]) * 3)
            issues.append(f"🔑 {len(self.results['secrets'])} سرّ مكشوف")

        try:
            ts = int(b.get("target_sdk", "0"))
            if ts and ts < 30:
                score -= 10
                issues.append(f"📉 targetSdk قديم: {ts}")
        except Exception:
            pass

        if len(self.results["trackers"]) > 3:
            score -= 5
            issues.append(f"🕵️ {len(self.results['trackers'])} متتبع")

        if mf.get("debuggable"):
            score -= 15
            issues.append("🐛 التطبيق قابل للتصحيح (debuggable)")

        if mf.get("cleartext"):
            score -= 8
            issues.append("🔓 يسمح بـ cleartext HTTP")

        score = max(0, score)
        grade = "🟢 ممتاز" if score >= 85 else "🟡 جيد" if score >= 65 else "🟠 ضعيف" if score >= 40 else "🔴 خطير"

        self.results["security_score"] = {
            "score": score,
            "grade": grade,
            "issues": issues[:20],
        }

    def _build_stats(self, targets, all_strings):
        total = sum(self.file_hits.values())
        self.results["stats"] = {
            "dex": self.results["basic"].get("dex_count", 0),
            "so": self.results["basic"].get("so_count", 0),
            "files_scanned": len(targets),
            "strings_extracted": len(all_strings),
            "total_findings": total,
            "input_kind": self.input_info.kind,
        }
        self.results["files"] = sorted(
            [{"file": k, "count": v} for k, v in self.file_hits.items()],
            key=lambda x: -x["count"],
        )[:50]

    def run(self):
        try:
            self._prepare()
            try:
                check_memory()
            except ResourceError:
                pass
            self._analyze_basic()
            targets = self._list_target_files()
            all_strings = self._collect_all_strings(targets)

            self._extract_developers(all_strings)
            self._extract_emails(all_strings)
            self._extract_social(all_strings)
            self._extract_websites(all_strings)
            self._detect_trackers(all_strings)
            self._extract_secrets(all_strings)
            self._extract_crypto(all_strings)
            self._extract_ips(all_strings)
            self._extract_so()
            self._extract_resources()
            self._extract_class_context()
            self._security_score()
            self._build_stats(targets, all_strings)
            self._report(100, "اكتمل")
            return {"ok": True, "data": self.results}
        except ResourceError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            import traceback
            return {"ok": False, "error": str(e) + "\n" + traceback.format_exc()}
        finally:
            self._cleanup()


def analyze_apk(path, progress_cb=None):
    return HyperX(path, progress_cb=progress_cb).run()
