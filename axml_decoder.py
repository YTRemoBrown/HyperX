# -*- coding: utf-8 -*-
"""
HyperX AXML Decoder - فك Android Binary XML
Developed by: ريمو براون
© 2026 All Rights Reserved

يدعم:
- AndroidManifest.xml الثنائي
- res/*.xml المشفرة
- ARSC resources.arsc (جزئياً)
"""
import struct


# ═══════════════════════════════════════════════════════════
# AXML Constants
# ═══════════════════════════════════════════════════════════
RES_STRING_POOL_TYPE = 0x0001
RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_TABLE_TYPE = 0x0002
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202

UTF8_FLAG = 0x00000100

# Chunk header size (type + headerSize + size)
CHUNK_HEADER_SIZE = 8


def _read_u8(data, off):
    return data[off]


def _read_u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def _read_u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def _read_i32(data, off):
    return struct.unpack_from("<i", data, off)[0]


# ═══════════════════════════════════════════════════════════
# String Pool Decoder
# ═══════════════════════════════════════════════════════════
def _parse_string_pool(data, off):
    """يرجع (list_strings, end_offset)."""
    type_ = _read_u16(data, off)
    header_size = _read_u16(data, off + 2)
    size = _read_u32(data, off + 4)
    string_count = _read_u32(data, off + 8)
    style_count = _read_u32(data, off + 12)
    flags = _read_u32(data, off + 16)
    strings_start = _read_u32(data, off + 20)
    styles_start = _read_u32(data, off + 24)

    is_utf8 = (flags & UTF8_FLAG) != 0
    offsets_base = off + header_size
    strings_base = off + strings_start

    result = []
    for i in range(string_count):
        try:
            str_off = _read_u32(data, offsets_base + i * 4)
            pos = strings_base + str_off
            if is_utf8:
                # UTF-8: len via 1 or 2 bytes
                n = data[pos]
                if n & 0x80:
                    n = ((n & 0x7F) << 8) | data[pos + 1]
                    pos += 2
                else:
                    pos += 1
                # skip second length (byte length)
                b = data[pos]
                if b & 0x80:
                    pos += 2
                else:
                    pos += 1
                s = data[pos:pos + n].decode("utf-8", "replace")
            else:
                # UTF-16
                n = _read_u16(data, pos)
                if n & 0x8000:
                    n = ((n & 0x7FFF) << 16) | _read_u16(data, pos + 2)
                    pos += 4
                else:
                    pos += 2
                s = data[pos:pos + n * 2].decode("utf-16-le", "replace")
            result.append(s)
        except Exception:
            result.append("")
    return result, off + size


# ═══════════════════════════════════════════════════════════
# AXML Parser
# ═══════════════════════════════════════════════════════════
def decode_axml(data):
    """فك AXML وإرجاع string XML."""
    if len(data) < 8:
        return None
    type_ = _read_u16(data, 0)
    if type_ != RES_XML_TYPE:
        return None

    header_size = _read_u16(data, 2)
    total_size = _read_u32(data, 4)
    data = data[:total_size] if total_size <= len(data) else data

    # Chunks after XML header
    pos = header_size
    strings = []
    res_map = []

    # First chunk should be string pool
    if pos + 8 > len(data):
        return None
    ct = _read_u16(data, pos)
    if ct == RES_STRING_POOL_TYPE:
        strings, pos = _parse_string_pool(data, pos)

    # resource map
    if pos + 8 <= len(data):
        ct = _read_u16(data, pos)
        if ct == RES_XML_RESOURCE_MAP_TYPE:
            hs = _read_u16(data, pos + 2)
            sz = _read_u32(data, pos + 4)
            n = (sz - hs) // 4
            for i in range(n):
                res_map.append(_read_u32(data, pos + hs + i * 4))
            pos += sz

    # Iterate element chunks
    out = []
    depth = 0
    while pos + 8 <= len(data):
        ct = _read_u16(data, pos)
        hs = _read_u16(data, pos + 2)
        sz = _read_u32(data, pos + 4)
        if sz < 8 or pos + sz > len(data):
            break

        if ct == RES_XML_START_ELEMENT_TYPE:
            line = _read_u32(data, pos + 8)
            # comment, ns, name
            ns_idx = _read_i32(data, pos + 16)
            name_idx = _read_i32(data, pos + 20)
            attr_start = _read_u16(data, pos + 24)
            attr_size = _read_u16(data, pos + 26)
            attr_count = _read_u16(data, pos + 28)

            name = strings[name_idx] if 0 <= name_idx < len(strings) else "?"
            indent = "  " * depth
            attrs = []
            attr_base = pos + 16 + attr_start
            for i in range(attr_count):
                apos = attr_base + i * attr_size
                if apos + 20 > len(data):
                    break
                a_ns = _read_i32(data, apos)
                a_name = _read_i32(data, apos + 4)
                a_raw = _read_i32(data, apos + 8)
                a_type = data[apos + 15]
                a_data = _read_u32(data, apos + 16)

                attr_name = strings[a_name] if 0 <= a_name < len(strings) else f"?{a_name}"
                # try raw value
                if 0 <= a_raw < len(strings):
                    attr_val = strings[a_raw]
                elif a_type == 0x03:
                    attr_val = strings[a_data] if 0 <= a_data < len(strings) else f"@{a_data:08x}"
                elif a_type == 0x12:
                    attr_val = "true" if a_data != 0 else "false"
                elif a_type == 0x10:
                    attr_val = str(_read_i32(data, apos + 16))
                elif a_type == 0x11:
                    attr_val = f"0x{a_data:x}"
                else:
                    attr_val = f"0x{a_data:x}"
                attrs.append(f'{attr_name}="{_escape(attr_val)}"')
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            out.append(f'{indent}<{name}{attr_str}>')
            depth += 1

        elif ct == RES_XML_END_ELEMENT_TYPE:
            depth = max(0, depth - 1)
            ns_idx = _read_i32(data, pos + 16)
            name_idx = _read_i32(data, pos + 20)
            name = strings[name_idx] if 0 <= name_idx < len(strings) else "?"
            indent = "  " * depth
            out.append(f'{indent}</{name}>')

        elif ct == RES_XML_CDATA_TYPE:
            idx = _read_i32(data, pos + 16)
            txt = strings[idx] if 0 <= idx < len(strings) else ""
            out.append(_escape(txt))

        pos += sz

    return '<?xml version="1.0" encoding="utf-8"?>\n' + "\n".join(out)


def _escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# ═══════════════════════════════════════════════════════════
# ARSC Decoder (resources.arsc)
# ═══════════════════════════════════════════════════════════
def decode_arsc_strings(data):
    """
    يستخرج كل النصوص من resources.arsc كبديل عن aapt.
    يعمل بفك global string pool الأساسي + package strings.
    """
    if len(data) < 12:
        return []
    type_ = _read_u16(data, 0)
    if type_ != RES_TABLE_TYPE:
        return []

    header_size = _read_u16(data, 2)
    total_size = _read_u32(data, 4)
    data = data[:total_size] if total_size <= len(data) else data

    pos = header_size
    all_strings = []

    while pos + 8 <= len(data):
        ct = _read_u16(data, pos)
        hs = _read_u16(data, pos + 2)
        sz = _read_u32(data, pos + 4)
        if sz < 8 or pos + sz > len(data):
            break

        if ct == RES_STRING_POOL_TYPE:
            strings, _ = _parse_string_pool(data, pos)
            all_strings.extend(strings)
        elif ct == RES_TABLE_PACKAGE_TYPE:
            # recurse into package
            inner = data[pos:pos + sz]
            all_strings.extend(_parse_package_strings(inner, hs))

        pos += sz

    # dedupe + filter
    seen = set()
    out = []
    for s in all_strings:
        if not s or s in seen:
            continue
        if len(s) < 3 or len(s) > 300:
            continue
        seen.add(s)
        out.append(s)
    return out


def _parse_package_strings(pkg_data, pkg_header_size):
    """يدخل في حزمة ARSC ويستخرج كل string pools + entries."""
    out = []
    pos = pkg_header_size
    while pos + 8 <= len(pkg_data):
        ct = _read_u16(pkg_data, pos)
        hs = _read_u16(pkg_data, pos + 2)
        sz = _read_u32(pkg_data, pos + 4)
        if sz < 8 or pos + sz > len(pkg_data):
            break
        try:
            if ct == RES_STRING_POOL_TYPE:
                strings, _ = _parse_string_pool(pkg_data, pos)
                out.extend(strings)
            elif ct == RES_TABLE_TYPE_SPEC_TYPE:
                pass
            elif ct == RES_TABLE_TYPE_TYPE:
                # type chunk: read its own string pool
                # The type chunk has a strings pool reference (usually global)
                pass
        except Exception:
            pass
        pos += sz
    return out


def is_axml(data):
    """هل الملف AXML ثنائي؟"""
    if len(data) < 8:
        return False
    return _read_u16(data, 0) == RES_XML_TYPE


def is_arsc(data):
    if len(data) < 8:
        return False
    return _read_u16(data, 0) == RES_TABLE_TYPE
