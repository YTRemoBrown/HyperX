/* HyperX v3.0 History Page
   Developed by: ريمو براون
   © 2026 All Rights Reserved */

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function gradeColor(score) {
  return score >= 85 ? "good" : score >= 65 ? "warn" : "bad";
}

async function loadStats() {
  try {
    const r = await fetch("/api/history?limit=1");
    const j = await r.json();
    const s = j.stats || {};
    const sg = $("globalStats");
    sg.innerHTML = "";
    const map = [
      ["📚 إجمالي التحليلات", s.total ?? 0],
      ["📊 متوسط التقييم", s.avg_score ?? 0],
      ["🏆 أفضل تقييم", s.best ?? 0],
      ["💀 أسوأ تقييم", s.worst ?? 0],
    ];
    map.forEach(([k, v]) => {
      const d = document.createElement("div");
      d.className = "kv";
      d.innerHTML = '<div class="k">' + esc(k) + '</div><div class="v">' + esc(v) + '</div>';
      sg.appendChild(d);
    });
  } catch (e) {}
}

async function loadList(q = "") {
  try {
    const r = await fetch("/api/history?q=" + encodeURIComponent(q) + "&limit=200");
    const j = await r.json();
    const list = $("historyList");
    list.innerHTML = "";
    if (!j.items || !j.items.length) {
      list.innerHTML = '<div class="empty">لا يوجد سجل بعد</div>';
      return;
    }
    j.items.forEach(it => {
      const div = document.createElement("div");
      div.className = "item history-item";
      const val = document.createElement("div");
      val.className = "val";
      val.innerHTML =
        '<div style="display:flex;flex-direction:column;gap:4px">' +
          '<b style="color:var(--text)">📦 ' + esc(it.app_name || it.filename) + '</b>' +
          '<span style="color:var(--muted);font-size:0.78rem">' + esc(it.package) + ' — v' + esc(it.version) + '</span>' +
          '<span style="color:var(--muted);font-size:0.72rem">🕐 ' + esc(it.created_at) + ' • #' + it.id + '</span>' +
        '</div>';
      div.appendChild(val);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML =
        '<span class="badge ' + gradeColor(it.score) + '">🎯 ' + (it.score ?? 0) + '</span>' +
        '<span class="badge">📊 ' + (it.findings_count ?? 0) + '</span>';
      div.appendChild(meta);

      // أزرار
      const btns = document.createElement("div");
      btns.style.display = "flex";
      btns.style.gap = "4px";

      const openBtn = document.createElement("button");
      openBtn.className = "copy-btn";
      openBtn.textContent = "📂";
      openBtn.title = "استعراض";
      openBtn.onclick = () => {
        // احفظ id في localStorage وأذهب للرئيسية
        localStorage.setItem("hyperx_load_id", it.id);
        window.location = "/";
      };
      btns.appendChild(openBtn);

      const dlBtn = document.createElement("button");
      dlBtn.className = "copy-btn";
      dlBtn.textContent = "⬇️";
      dlBtn.title = "تنزيل JSON";
      dlBtn.onclick = () => window.location = "/api/export/" + it.id + ".json";
      btns.appendChild(dlBtn);

      const delBtn = document.createElement("button");
      delBtn.className = "copy-btn";
      delBtn.textContent = "🗑️";
      delBtn.title = "حذف";
      delBtn.onclick = async () => {
        if (!confirm("حذف التحليل #" + it.id + "؟")) return;
        await fetch("/api/history/" + it.id, { method: "DELETE" });
        loadList($("searchInput").value);
        loadStats();
      };
      btns.appendChild(delBtn);

      div.appendChild(btns);
      list.appendChild(div);
    });
  } catch (e) {
    console.error(e);
  }
}

$("searchInput").addEventListener("input", (e) => {
  loadList(e.target.value);
});

$("clearAllBtn").onclick = async () => {
  if (!confirm("⚠️ حذف كل السجل؟ لا يمكن التراجع!")) return;
  await fetch("/api/history/clear", { method: "POST" });
  loadStats();
  loadList();
};

loadStats();
loadList();
