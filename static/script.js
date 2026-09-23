/* HyperX v5.0 Frontend — Upload progress + SSE
   Developed by: ريمو براون
   © 2026 All Rights Reserved */

const $ = (id) => document.getElementById(id);
const fileInput = $("fileInput");
const drop = $("drop");
const fileName = $("fileName");
const fileInfo = $("fileInfo");
const analyzeBtn = $("analyzeBtn");
const progressBlock = $("progressBlock");
const bar = $("bar");
const progressPct = $("progressPct");
const progressLabel = $("progressLabel");
const progressStage = $("progressStage");
const progressSpeed = $("progressSpeed");
const statusEl = $("status");
const results = $("results");
const uploadCard = $("uploadCard");
const newBtn = $("newBtn");
const exportJsonBtn = $("exportJson");
const exportTxtBtn = $("exportTxt");
const resultMeta = $("resultMeta");

let currentFile = null;
let currentId = null;

// ═══════════════════════════════════════════════════════════
// Auto restore آخر تحليل
// ═══════════════════════════════════════════════════════════
(async function restoreLast() {
  try {
    const r = await fetch("/api/history/latest");
    const j = await r.json();
    if (j.ok && j.item) {
      currentId = j.item.id;
      render(j.item.data);
      resultMeta.textContent = "🕐 من السجل: " + j.item.created_at + " (#" + j.item.id + ")";
      uploadCard.classList.add("collapsed");
      results.classList.remove("hidden");
    }
  } catch (e) {}
})();

// ═══════════════════════════════════════════════════════════
// حدود الحماية
// ═══════════════════════════════════════════════════════════
(async function showLimits() {
  try {
    const r = await fetch("/api/limits");
    const j = await r.json();
    if (j.ok) {
      const el = $("status");
      if (el && !el.textContent) {
        el.innerHTML = '🛡️ الحد الأقصى: <b>' + j.limits.max_apk_mb + ' MB</b> '
          + '| ذاكرة: <b>' + j.current_mem_mb + ' MB</b>';
      }
    }
  } catch (e) {}
})();

newBtn.addEventListener("click", () => {
  results.classList.add("hidden");
  uploadCard.classList.remove("collapsed");
  fileName.textContent = "";
  fileInfo.textContent = "";
  currentFile = null;
  currentId = null;
  analyzeBtn.disabled = true;
  progressBlock.classList.remove("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
});

drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(2) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function handleFile(f) {
  const n = f.name.toLowerCase();
  const ok = [".apk", ".apks", ".xapk", ".zip", ".tgz", ".tar.gz"].some(e => n.endsWith(e));
  if (!ok) {
    alert("⚠️ الملف يجب أن يكون APK أو ZIP");
    return;
  }
  currentFile = f;
  fileName.textContent = "📎 " + f.name;
  fileInfo.textContent = "💾 " + fmtSize(f.size) + "  •  🕐 " + new Date().toLocaleTimeString();
  analyzeBtn.disabled = false;
  progressBlock.classList.remove("active");
  statusEl.textContent = "";
}

// ═══════════════════════════════════════════════════════════
// Upload مع XHR للتقدم
// ═══════════════════════════════════════════════════════════
analyzeBtn.addEventListener("click", () => {
  if (!currentFile) return;
  analyzeBtn.disabled = true;
  results.classList.add("hidden");
  progressBlock.classList.add("active");

  setProgress(0, "⬆️ جاري رفع الملف", "");
  bar.style.width = "0%";

  const fd = new FormData();
  fd.append("file", currentFile);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/start");

  let uploadStart = Date.now();
  let lastLoaded = 0;
  let lastTime = uploadStart;

  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const now = Date.now();
    const pct = Math.round((e.loaded / e.total) * 100);
    // الرفع يحتل أول 40% من الشريط
    const displayPct = Math.round(pct * 0.4);
    const dt = (now - lastTime) / 1000;
    const dBytes = e.loaded - lastLoaded;
    const speed = dt > 0 ? dBytes / dt : 0;
    const remain = speed > 0 ? (e.total - e.loaded) / speed : 0;

    bar.style.width = displayPct + "%";
    progressPct.textContent = displayPct + "%";
    progressLabel.textContent = "⬆️ رفع الملف";
    progressStage.textContent =
      fmtSize(e.loaded) + " / " + fmtSize(e.total) +
      (remain > 0 ? "  •  باقي " + Math.ceil(remain) + "ث" : "");
    progressSpeed.textContent = speed > 0 ? "⚡ " + fmtSize(speed) + "/s" : "";

    lastLoaded = e.loaded;
    lastTime = now;
  };

  xhr.onload = () => {
    if (xhr.status !== 200) {
      let msg = "خطأ في الرفع";
      try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) {}
      progressLabel.textContent = "❌ فشل";
      progressStage.textContent = msg;
      analyzeBtn.disabled = false;
      return;
    }
    let j;
    try {
      j = JSON.parse(xhr.responseText);
    } catch (e) {
      progressLabel.textContent = "❌ استجابة غير صالحة";
      analyzeBtn.disabled = false;
      return;
    }
    if (!j.ok) {
      progressLabel.textContent = "❌ " + (j.error || "خطأ");
      progressStage.textContent = j.error || "";
      analyzeBtn.disabled = false;
      return;
    }
    // ابدأ متابعة SSE
    trackAnalysis(j.job_id);
  };

  xhr.onerror = () => {
    progressLabel.textContent = "❌ فشل الاتصال";
    analyzeBtn.disabled = false;
  };

  xhr.send(fd);
});

function setProgress(pct, label, stage, speed) {
  pct = Math.max(0, Math.min(100, pct));
  bar.style.width = pct + "%";
  progressPct.textContent = pct + "%";
  if (label) progressLabel.textContent = label;
  if (stage !== undefined) progressStage.textContent = stage;
  if (speed !== undefined) progressSpeed.textContent = speed;
}

// ═══════════════════════════════════════════════════════════
// متابعة SSE
// ═══════════════════════════════════════════════════════════
function trackAnalysis(jobId) {
  // التحليل يحتل 40%-100% من الشريط
  const es = new EventSource("/api/progress/" + jobId);

  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (d.error) {
      setProgress(100, "❌ خطأ", d.error);
      es.close();
      analyzeBtn.disabled = false;
      return;
    }
    // ازدهار النسبة: 40% → 100%
    const mapped = 40 + Math.round((d.pct || 0) * 0.6);
    setProgress(mapped, "🔬 تحليل", d.stage || "...", "");
    if (d.done) {
      es.close();
      fetchResult(jobId);
    }
  };

  es.onerror = () => {
    // إعادة محاولة عبر polling كـ fallback
    es.close();
    pollResult(jobId);
  };
}

async function fetchResult(jobId) {
  setProgress(99, "📥 استلام النتيجة", "...");
  try {
    const r = await fetch("/api/result/" + jobId);
    const j = await r.json();
    if (!j.ok) {
      setProgress(100, "❌ فشل", j.error || "خطأ");
      analyzeBtn.disabled = false;
      return;
    }
    setProgress(100, "✅ اكتمل التحليل", "تم الحفظ في السجل", "");
    currentId = j.history_id;
    render(j.data);
    resultMeta.textContent = "🆕 جديد — محفوظ #" + (currentId || "?");
    uploadCard.classList.add("collapsed");
    results.classList.remove("hidden");
    results.scrollIntoView({ behavior: "smooth" });
    setTimeout(() => progressBlock.classList.remove("active"), 1500);
  } catch (e) {
    setProgress(100, "❌ فشل الاتصال", e.message);
  }
  analyzeBtn.disabled = false;
}

async function pollResult(jobId) {
  for (let i = 0; i < 300; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const r = await fetch("/api/result/" + jobId);
      if (r.status === 202) continue;
      const j = await r.json();
      if (j.ok) {
        currentId = j.history_id;
        render(j.data);
        setProgress(100, "✅ اكتمل", "");
        resultMeta.textContent = "🆕 جديد — محفوظ #" + currentId;
        uploadCard.classList.add("collapsed");
        results.classList.remove("hidden");
        analyzeBtn.disabled = false;
        return;
      } else {
        setProgress(100, "❌ " + (j.error || "خطأ"), "");
        analyzeBtn.disabled = false;
        return;
      }
    } catch (e) {}
  }
}

// ═══════════════════════════════════════════════════════════
// Export buttons
// ═══════════════════════════════════════════════════════════
exportJsonBtn.onclick = () => {
  if (!currentId) return alert("لا يوجد تحليل محفوظ");
  window.location = "/api/export/" + currentId + ".json";
};
exportTxtBtn.onclick = () => {
  if (!currentId) return alert("لا يوجد تحليل محفوظ");
  window.location = "/api/export/" + currentId + ".txt";
};

// ═══════════════════════════════════════════════════════════
// Render helpers
// ═══════════════════════════════════════════════════════════
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function copyBtn(text) {
  const b = document.createElement("button");
  b.className = "copy-btn";
  b.textContent = "📋";
  b.onclick = () => {
    navigator.clipboard.writeText(text).then(() => {
      b.textContent = "✅";
      b.classList.add("copied");
      setTimeout(() => { b.textContent = "📋"; b.classList.remove("copied"); }, 1200);
    });
  };
  return b;
}

function renderItem(value, file, count, badgeText, badgeClass, context) {
  const div = document.createElement("div");
  div.className = "item";
  const val = document.createElement("div");
  val.className = "val";
  val.textContent = value;
  div.appendChild(val);

  const meta = document.createElement("div");
  meta.className = "meta";
  if (file) {
    const f = document.createElement("div");
    f.className = "file";
    f.textContent = "📍 " + file;
    meta.appendChild(f);
  }
  if (context && context.length) {
    context.forEach(c => {
      const cx = document.createElement("div");
      cx.className = "file ctx";
      cx.textContent = "🔗 " + c;
      meta.appendChild(cx);
    });
  }
  if (count) {
    const b = document.createElement("span");
    b.className = "badge " + (badgeClass || "");
    b.textContent = (badgeText || "×") + " " + count;
    meta.appendChild(b);
  }
  div.appendChild(meta);
  div.appendChild(copyBtn(value));
  return div;
}

function renderList(id, items, getVal, getFile, getCount, badgeText, badgeClass) {
  const el = $(id);
  el.innerHTML = "";
  if (!items || !items.length) {
    el.innerHTML = '<div class="empty">لا توجد نتائج</div>';
    return;
  }
  items.forEach(it => {
    el.appendChild(renderItem(
      getVal(it),
      getFile ? getFile(it) : null,
      getCount ? getCount(it) : null,
      badgeText, badgeClass,
      it.context
    ));
  });
}

function render(data) {
  // Score
  const sb = $("scoreBox");
  sb.innerHTML = "";
  const sc = data.security_score || { score: 0, grade: "N/A", issues: [] };
  const scoreBox = document.createElement("div");
  scoreBox.className = "score-box";
  const circ = document.createElement("div");
  circ.className = "score-circle";
  circ.style.background = `conic-gradient(${sc.score >= 85 ? '#22c55e' : sc.score >= 65 ? '#f59e0b' : '#ef4444'} ${sc.score * 3.6}deg, #223052 0deg)`;
  const val = document.createElement("div");
  val.className = "score-value";
  val.textContent = sc.score;
  circ.appendChild(val);
  const info = document.createElement("div");
  info.className = "score-info";
  info.innerHTML = '<div class="score-grade">' + esc(sc.grade) + '</div>';
  if (sc.issues && sc.issues.length) {
    const ul = document.createElement("ul");
    ul.className = "score-issues";
    sc.issues.slice(0, 8).forEach(i => {
      const li = document.createElement("li");
      li.textContent = i;
      ul.appendChild(li);
    });
    info.appendChild(ul);
  } else {
    info.innerHTML += '<div style="color:var(--good)">✅ لا مشاكل كبيرة</div>';
  }
  scoreBox.appendChild(circ);
  scoreBox.appendChild(info);
  sb.appendChild(scoreBox);

  // Basic
  const bg = $("basicGrid");
  bg.innerHTML = "";
  const b = data.basic || {};
  const kindMap = {
    apk: "📦 APK عادي",
    zip_unpacked: "🗂️ ZIP مفكوك",
    zip_with_apk: "📦 ZIP يحتوي APK",
    dir: "📁 مجلد",
    unknown: "❓ غير معروف",
  };
  const basicMap = [
    ["📛 اسم الملف", b.name],
    ["🗂️ نوع المدخل", kindMap[b.input_kind] || b.input_kind],
    ["🏷️ اسم التطبيق", b.app_name],
    ["📦 الحزمة", b.package],
    ["🔢 الإصدار", b.version],
    ["🆔 كود الإصدار", b.version_code],
    ["⬇️ minSdk", b.min_sdk],
    ["⬆️ targetSdk", b.target_sdk],
    ["💾 الحجم", b.size_mb + " MB"],
    ["📂 الحجم (مفكوك)", b.size_unpacked_mb + " MB"],
    ["🗂️ عدد DEX", b.dex_count],
    ["⚙️ عدد .so", b.so_count],
    ["🚀 النشاط الرئيسي", b.launchable],
  ];
  basicMap.forEach(([k, v]) => {
    const d = document.createElement("div");
    d.className = "kv";
    d.innerHTML = '<div class="k">' + esc(k) + '</div><div class="v">' + esc(v ?? "-") + '</div>';
    bg.appendChild(d);
  });
  if (b.sha256) {
    const d = document.createElement("div");
    d.className = "kv";
    d.style.gridColumn = "1 / -1";
    d.innerHTML = '<div class="k">🔐 SHA-256</div><div class="v mono">' + esc(b.sha256) + '</div>';
    bg.appendChild(d);
  }
  if (b.permissions && b.permissions.length) {
    const d = document.createElement("div");
    d.className = "kv";
    d.style.gridColumn = "1 / -1";
    d.innerHTML = '<div class="k">🔐 الصلاحيات (' + b.permissions.length + ')</div>' +
      '<div class="v mono" style="font-size:0.75rem;font-weight:400;line-height:1.6">' +
      b.permissions.map(esc).join("<br>") + '</div>';
    bg.appendChild(d);
  }

  // Manifest
  const mg = $("manifestGrid");
  mg.innerHTML = "";
  const mf = data.manifest_info || {};
  const mfMap = [
    ["🚀 Activities", mf.activities ?? "-"],
    ["⚙️ Services", mf.services ?? "-"],
    ["📡 Receivers", mf.receivers ?? "-"],
    ["🗄️ Providers", mf.providers ?? "-"],
    ["🔓 Exported", mf.exported_count ?? "-"],
    ["🐛 Debuggable", mf.debuggable ? "⚠️ نعم" : "✅ لا"],
    ["💾 Allow Backup", mf.allow_backup ? "⚠️ نعم" : "✅ لا"],
    ["🌐 Cleartext HTTP", mf.cleartext ? "⚠️ نعم" : "✅ لا"],
  ];
  mfMap.forEach(([k, v]) => {
    const d = document.createElement("div");
    d.className = "kv";
    d.innerHTML = '<div class="k">' + esc(k) + '</div><div class="v">' + esc(v) + '</div>';
    mg.appendChild(d);
  });

  renderList("appNames", (data.app_names || []).map(n => ({value: n, file: "aapt", count: 1})),
    x => x.value, x => x.file, x => x.count, "🏷️", "info");

  renderList("developers", data.developers,
    x => x.value, x => x.file, x => x.count, "🔁", "warn");

  renderList("emails", data.emails,
    x => x.value, x => x.file, x => x.count, "🔁", "good");

  const scEl = $("social");
  scEl.innerHTML = "";
  const social = data.social || {};
  let anySocial = false;
  Object.keys(social).forEach(k => {
    if (!social[k] || !social[k].length) return;
    anySocial = true;
    const g = document.createElement("div");
    g.className = "social-group";
    g.innerHTML = "<h3>" + esc(k) + " (" + social[k].length + ")</h3>";
    social[k].forEach(it => {
      g.appendChild(renderItem(it.value, it.file, it.count, "🔁", "good", it.context));
    });
    scEl.appendChild(g);
  });
  if (!anySocial) scEl.innerHTML = '<div class="empty">لا توجد روابط تواصل</div>';

  renderList("websites", data.websites,
    x => x.value, x => x.file, x => x.count, "🔁", "");

  const trEl = $("trackers");
  trEl.innerHTML = "";
  if (!data.trackers || !data.trackers.length) {
    trEl.innerHTML = '<div class="empty">لا توجد أدوات تتبع</div>';
  } else {
    data.trackers.forEach(t => {
      const div = document.createElement("div");
      div.className = "item";
      const val = document.createElement("div");
      val.className = "val";
      val.innerHTML = '<span class="badge warn">🕵️</span> <b>' + esc(t.name) + '</b> — <span style="color:var(--muted)">' + esc(t.domain) + '</span>';
      div.appendChild(val);
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = '<span class="badge">× ' + t.count + '</span>';
      div.appendChild(meta);
      trEl.appendChild(div);
    });
  }

  const secEl = $("secrets");
  secEl.innerHTML = "";
  if (!data.secrets || !data.secrets.length) {
    secEl.innerHTML = '<div class="empty">لا توجد أسرار</div>';
  } else {
    data.secrets.forEach(it => {
      const div = document.createElement("div");
      div.className = "item";
      const val = document.createElement("div");
      val.className = "val";
      val.innerHTML = '<span class="badge bad">' + esc(it.type) + '</span> ' + esc(it.value);
      div.appendChild(val);
      const meta = document.createElement("div");
      meta.className = "meta";
      if (it.file) meta.innerHTML = '<div class="file">📍 ' + esc(it.file) + '</div>';
      if (it.context) {
        it.context.forEach(c => {
          const cx = document.createElement("div");
          cx.className = "file ctx";
          cx.textContent = "🔗 " + c;
          meta.appendChild(cx);
        });
      }
      div.appendChild(meta);
      div.appendChild(copyBtn(it.value));
      secEl.appendChild(div);
    });
  }

  const crEl = $("crypto");
  crEl.innerHTML = "";
  if (!data.crypto || !data.crypto.length) {
    crEl.innerHTML = '<div class="empty">لا توجد محافظ</div>';
  } else {
    data.crypto.forEach(it => {
      const div = document.createElement("div");
      div.className = "item";
      const val = document.createElement("div");
      val.className = "val";
      val.innerHTML = '<span class="badge info">💰 ' + esc(it.type) + '</span> ' + esc(it.value);
      div.appendChild(val);
      const meta = document.createElement("div");
      meta.className = "meta";
      if (it.file) meta.innerHTML = '<div class="file">📍 ' + esc(it.file) + '</div>';
      div.appendChild(meta);
      div.appendChild(copyBtn(it.value));
      crEl.appendChild(div);
    });
  }

  renderList("ips", data.ips,
    x => x.value, x => x.file, x => x.count, "🌍", "info");

  renderList("soLibs", data.so_libs,
    x => x.lib, null, x => x.size_kb, "💾", "info");

  const soEl = $("soSymbols");
  soEl.innerHTML = "";
  if (!data.so_symbols || !data.so_symbols.length) {
    soEl.innerHTML = '<div class="empty">لا توجد رموز</div>';
  } else {
    data.so_symbols.forEach(it => {
      const div = document.createElement("div");
      div.className = "item";
      const val = document.createElement("div");
      val.className = "val";
      val.textContent = it.symbol;
      div.appendChild(val);
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = '<div class="file">📚 ' + esc(it.lib) + '</div><span class="badge">× ' + it.count + '</span>';
      div.appendChild(meta);
      div.appendChild(copyBtn(it.symbol));
      soEl.appendChild(div);
    });
  }

  const rsEl = $("resources");
  rsEl.innerHTML = "";
  if (!data.resources || !data.resources.length) {
    rsEl.innerHTML = '<div class="empty">لا توجد نصوص موارد</div>';
  } else {
    data.resources.forEach(it => {
      const div = document.createElement("div");
      div.className = "item";
      const val = document.createElement("div");
      val.className = "val";
      val.innerHTML = '<span class="badge info">' + esc(it.key) + '</span> ' + esc(it.value);
      div.appendChild(val);
      const meta = document.createElement("div");
      meta.className = "meta";
      if (it.file) meta.innerHTML = '<div class="file">📍 ' + esc(it.file) + '</div>';
      div.appendChild(meta);
      div.appendChild(copyBtn(it.value));
      rsEl.appendChild(div);
    });
  }

  const sg = $("statsGrid");
  sg.innerHTML = "";
  const st = data.stats || {};
  const statsMap = [
    ["🗂️ DEX", st.dex],
    ["⚙️ .so", st.so],
    ["📂 ملفات مفحوصة", st.files_scanned],
    ["🔤 Strings", st.strings_extracted],
    ["🎯 نتائج", st.total_findings],
  ];
  statsMap.forEach(([k, v]) => {
    const d = document.createElement("div");
    d.className = "kv";
    d.innerHTML = '<div class="k">' + esc(k) + '</div><div class="v">' + esc(v ?? 0) + '</div>';
    sg.appendChild(d);
  });

  renderList("files", data.files,
    x => x.file, null, x => x.count, "🎯", "warn");

  bindFilters();
}

function bindFilters() {
  document.querySelectorAll(".filter").forEach(inp => {
    inp.oninput = () => {
      const target = inp.dataset.target;
      const q = inp.value.trim().toLowerCase();
      const el = $(target);
      if (!el) return;
      el.querySelectorAll(".item").forEach(it => {
        it.style.display = it.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    };
  });
}
