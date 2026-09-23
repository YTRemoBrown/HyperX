# -*- coding: utf-8 -*-
"""
HyperX v5.0 Resource Guard - حماية الذاكرة والموارد
Developed by: ريمو براون
© 2026 All Rights Reserved
"""
import os
import gc
import shutil
import resource
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor


LIMITS = {
    "max_apk_mb": 400,
    "max_zip_files": 50000,
    "max_unpacked_mb": 1200,
    "max_python_mem_mb": 800,
    "max_tmpdir_mb": 1500,
    "unzip_workers": 8,
}


class ResourceError(Exception):
    pass


def check_apk_size(path):
    try:
        size_mb = os.path.getsize(path) / (1024 * 1024)
    except Exception as e:
        raise ResourceError(f"فشل قراءة حجم الملف: {e}")

    if size_mb > LIMITS["max_apk_mb"]:
        raise ResourceError(
            f"⚠️ الملف كبير جداً ({size_mb:.0f} MB). "
            f"الحد الأقصى {LIMITS['max_apk_mb']} MB لحماية ذاكرة الهاتف."
        )
    return size_mb


def check_zip_contents(zip_path):
    import zipfile
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            infos = z.infolist()
            n = len(infos)
            if n > LIMITS["max_zip_files"]:
                raise ResourceError(
                    f"⚠️ ZIP يحتوي على {n} ملف. الحد الأقصى {LIMITS['max_zip_files']}."
                )
            total = sum(i.file_size for i in infos)
            total_mb = total / (1024 * 1024)
            if total_mb > LIMITS["max_unpacked_mb"]:
                raise ResourceError(
                    f"⚠️ الحجم المفكوك {total_mb:.0f} MB يتجاوز الحد "
                    f"{LIMITS['max_unpacked_mb']} MB."
                )
            compressed = sum(max(i.compress_size, 1) for i in infos)
            ratio = total / compressed if compressed > 0 else 0
            if ratio > 100:
                raise ResourceError(
                    f"⚠️ نسبة ضغط مشبوهة ({ratio:.0f}x) — احتمال zip bomb."
                )
            return {"files": n, "unpacked_mb": total_mb, "ratio": ratio}
    except zipfile.BadZipFile:
        raise ResourceError("⚠️ الملف ليس ZIP صالح.")
    except ResourceError:
        raise
    except Exception as e:
        raise ResourceError(f"فشل فحص ZIP: {e}")


def check_memory():
    try:
        usage_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        usage_mb = usage_bytes / 1024
    except Exception:
        usage_mb = 0
    if usage_mb > LIMITS["max_python_mem_mb"]:
        gc.collect()
        try:
            usage_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            usage_mb = usage_bytes / 1024
        except Exception:
            pass
        if usage_mb > LIMITS["max_python_mem_mb"]:
            raise ResourceError(
                f"⚠️ ذاكرة Python مرتفعة ({usage_mb:.0f} MB) — "
                f"أغلق التطبيقات الأخرى."
            )
    return usage_mb


def cleanup_orphans():
    tmp = tempfile.gettempdir()
    cleaned = 0
    try:
        for entry in os.listdir(tmp):
            if entry.startswith("hyperx_"):
                full = os.path.join(tmp, entry)
                if os.path.isdir(full):
                    try:
                        age = time.time() - os.path.getmtime(full)
                        if age > 3600:
                            shutil.rmtree(full, ignore_errors=True)
                            cleaned += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return cleaned


def get_disk_usage(path):
    total = 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
    except Exception:
        pass
    return total / (1024 * 1024)


def fast_extract(zip_path, dest_dir, workers=None):
    """
    فك ZIP بسرعة عبر ThreadPoolExecutor.
    يرجع dict {extracted, failed, files}
    """
    import zipfile
    workers = workers or LIMITS["unzip_workers"]
    extracted = 0
    failed = 0
    files_list = []

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            # حماية ضد path traversal
            safe_infos = []
            dest_abs = os.path.abspath(dest_dir)
            for i in infos:
                target = os.path.abspath(os.path.join(dest_dir, i.filename))
                if not target.startswith(dest_abs):
                    continue
                safe_infos.append(i)

            def _extract_one(info):
                try:
                    # قراءة بالدفعات لتقليل الذاكرة
                    with z.open(info, "r") as src:
                        target = os.path.join(dest_dir, info.filename)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with open(target, "wb") as dst:
                            while True:
                                chunk = src.read(1024 * 256)
                                if not chunk:
                                    break
                                dst.write(chunk)
                    return (info.filename, True)
                except Exception:
                    return (info.filename, False)

            with ThreadPoolExecutor(max_workers=workers) as ex:
                for name, ok in ex.map(_extract_one, safe_infos):
                    if ok:
                        extracted += 1
                        files_list.append(name)
                    else:
                        failed += 1
    except Exception as e:
        raise ResourceError(f"فشل الفك: {e}")

    return {"extracted": extracted, "failed": failed, "files": files_list}


def guard_against_size(path, limit_mb, label="ملف"):
    mb = get_disk_usage(path) if os.path.isdir(path) else os.path.getsize(path) / (1024 * 1024)
    if mb > limit_mb:
        raise ResourceError(f"⚠️ {label} كبير جداً ({mb:.0f} MB > {limit_mb} MB).")
    return mb
