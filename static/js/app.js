/* CloudPrint — logică UI */
(function () {
  "use strict";

  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = window.PDF_WORKER_SRC;
  }

  var $ = function (id) { return document.getElementById(id); };

  var els = {
    dropzone: $("dropzone"),
    fileInput: $("fileInput"),
    uploadProgress: $("uploadProgress"),
    dropzoneInner: document.querySelector(".dropzone-inner"),
    preview: $("preview"),
    pages: $("pages"),
    pagesScroll: $("pagesScroll"),
    fileName: $("fileName"),
    fileMeta: $("fileMeta"),
    fileBadge: $("fileBadge"),
    removeFile: $("removeFile"),
    zoomIn: $("zoomIn"),
    zoomOut: $("zoomOut"),
    zoomLevel: $("zoomLevel"),
    zoomGroup: $("zoomGroup"),
    printerSelect: $("printerSelect"),
    printerChipName: $("printerChipName"),
    printerDot: $("printerDot"),
    copies: $("copies"),
    copiesMinus: $("copiesMinus"),
    copiesPlus: $("copiesPlus"),
    colorSeg: $("colorSeg"),
    duplexSeg: $("duplexSeg"),
    orientSeg: $("orientSeg"),
    edgeSeg: $("edgeSeg"),
    mediaSelect: $("mediaSelect"),
    qualitySelect: $("qualitySelect"),
    pageRange: $("pageRange"),
    pageRangeError: $("pageRangeError"),
    fitToPage: $("fitToPage"),
    advanced: $("advanced"),
    printBtn: $("printBtn"),
    printBtnLabel: $("printBtnLabel"),
    jobsSection: $("jobsSection"),
    jobsList: $("jobsList"),
    toasts: $("toasts"),
    tabs: $("tabs"),
    filesBadge: $("filesBadge"),
    fileGrid: $("fileGrid"),
    filesCount: $("filesCount"),
    filesEmpty: $("filesEmpty"),
    historyList: $("historyList"),
    historyEmpty: $("historyEmpty"),
    clearHistory: $("clearHistory"),
  };

  var views = {
    print: $("view-print"),
    files: $("view-files"),
    history: $("view-history"),
  };

  var state = {
    file: null,        // {id, name, type, url, size}
    pdfDoc: null,
    pageCount: 0,
    zoom: 1,
    printing: false,
    printers: [],
  };

  var PAGE_RANGE_RE = /^\d+(-\d+)?(,\d+(-\d+)?)*$/;

  /* ---------- utilitare ---------- */

  function toast(message, kind) {
    var el = document.createElement("div");
    el.className = "toast " + (kind || "");
    el.textContent = message;
    els.toasts.appendChild(el);
    setTimeout(function () {
      el.classList.add("leaving");
      setTimeout(function () { el.remove(); }, 300);
    }, 4000);
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }

  function formatDate(unixSeconds) {
    if (!unixSeconds) return "";
    var d = new Date(unixSeconds * 1000);
    var now = new Date();
    var opts = { hour: "2-digit", minute: "2-digit" };
    if (d.toDateString() === now.toDateString()) return "azi " + d.toLocaleTimeString("ro-RO", opts);
    var yest = new Date(now); yest.setDate(now.getDate() - 1);
    if (d.toDateString() === yest.toDateString()) return "ieri " + d.toLocaleTimeString("ro-RO", opts);
    return d.toLocaleDateString("ro-RO", { day: "numeric", month: "short" }) +
      " " + d.toLocaleTimeString("ro-RO", opts);
  }

  var TYPE_ICON = { pdf: "📕", jpg: "🖼️", png: "🖼️", gif: "🖼️", txt: "📄" };

  function typeIcon(type) { return TYPE_ICON[type] || "📄"; }

  function optionsSummary(o) {
    var bits = [];
    if (o.copies && o.copies > 1) bits.push(o.copies + " copii");
    bits.push(o.grayscale ? "alb-negru" : "color");
    bits.push(o.duplex ? "față-verso" : "o față");
    if (o.media) bits.push(o.media);
    if (o.page_range) bits.push("pag. " + o.page_range);
    return bits;
  }

  function segValue(seg) {
    var active = seg.querySelector("button.active");
    return active ? active.dataset.value : null;
  }

  function setSegValue(seg, value) {
    seg.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.value === value);
    });
  }

  function initSegmented(seg, onChange) {
    seg.addEventListener("click", function (e) {
      var btn = e.target.closest("button");
      if (!btn) return;
      setSegValue(seg, btn.dataset.value);
      if (onChange) onChange(btn.dataset.value);
    });
  }

  /* ---------- imprimante ---------- */

  function loadPrinters() {
    fetch("/api/printers")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.printers = data.printers;
        els.printerSelect.innerHTML = "";
        if (!data.printers.length) {
          var opt = document.createElement("option");
          opt.textContent = "Nicio imprimantă găsită";
          opt.value = "";
          els.printerSelect.appendChild(opt);
          els.printerChipName.textContent = "Fără imprimantă";
          els.printerDot.className = "status-dot error";
          if (data.error) toast(data.error, "error");
          return;
        }
        data.printers.forEach(function (p) {
          var opt = document.createElement("option");
          opt.value = p.name;
          opt.textContent = p.name.replace(/_/g, " ");
          if (p.name === data.default) opt.selected = true;
          els.printerSelect.appendChild(opt);
        });
        updatePrinterChip();
      })
      .catch(function () {
        els.printerChipName.textContent = "Server indisponibil";
        els.printerDot.className = "status-dot error";
      });
  }

  function updatePrinterChip() {
    var name = els.printerSelect.value;
    var printer = state.printers.find(function (p) { return p.name === name; });
    if (!printer) return;
    els.printerChipName.textContent = printer.name.replace(/_/g, " ");
    els.printerDot.className = "status-dot " + printer.state;
    els.printerChipName.textContent +=
      printer.state === "printing" ? " · printează" :
      printer.state === "disabled" ? " · oprită" : "";
  }

  els.printerSelect.addEventListener("change", updatePrinterChip);

  /* ---------- încărcare fișier ---------- */

  function pickFile() { els.fileInput.click(); }

  els.dropzone.addEventListener("click", pickFile);
  els.dropzone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickFile(); }
  });

  ["dragover", "dragenter"].forEach(function (evt) {
    els.dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      els.dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (evt) {
    els.dropzone.addEventListener(evt, function (e) {
      e.preventDefault();
      els.dropzone.classList.remove("dragover");
    });
  });
  els.dropzone.addEventListener("drop", function (e) {
    var file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  // permite drop oriunde pe pagină când e deja un fișier încărcat
  document.addEventListener("dragover", function (e) { e.preventDefault(); });
  document.addEventListener("drop", function (e) {
    e.preventDefault();
    if (els.preview.hidden) return;
    var file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  els.fileInput.addEventListener("change", function () {
    if (els.fileInput.files[0]) uploadFile(els.fileInput.files[0]);
    els.fileInput.value = "";
  });

  function uploadFile(file) {
    els.dropzone.hidden = false;
    els.preview.hidden = true;
    els.dropzoneInner.hidden = true;
    els.uploadProgress.hidden = false;

    var form = new FormData();
    form.append("file", file);

    fetch("/api/upload", { method: "POST", body: form })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error || "Încărcarea a eșuat.");
          return data;
        });
      })
      .then(function (data) {
        state.file = data;
        showPreview();
        loadFiles();  // apare imediat în „Fișiere”
      })
      .catch(function (err) {
        toast(err.message, "error");
        resetToDropzone();
      });
  }

  function resetToDropzone() {
    state.file = null;
    state.pdfDoc = null;
    state.pageCount = 0;
    state.zoom = 1;
    els.pages.innerHTML = "";
    els.dropzone.hidden = false;
    els.preview.hidden = true;
    els.dropzoneInner.hidden = false;
    els.uploadProgress.hidden = true;
    updatePrintButton();
  }

  els.removeFile.addEventListener("click", resetToDropzone);

  /* ---------- previzualizare ---------- */

  function showPreview() {
    var f = state.file;
    els.dropzone.hidden = true;
    els.dropzoneInner.hidden = false;
    els.uploadProgress.hidden = true;
    els.preview.hidden = false;

    els.fileName.textContent = f.name;
    els.fileBadge.textContent = f.type.toUpperCase();
    els.fileMeta.textContent = formatSize(f.size);
    els.pages.innerHTML = "";
    state.zoom = 1;
    els.zoomLevel.textContent = "100%";
    els.zoomGroup.style.visibility = f.type === "pdf" ? "visible" : "hidden";

    if (f.type === "pdf") {
      renderPdf();
    } else if (f.type === "txt") {
      renderText();
    } else {
      renderImage();
    }
    applyGrayscalePreview();
    updatePrintButton();
  }

  function renderPdf() {
    if (!window.pdfjsLib) {
      toast("PDF.js nu s-a încărcat — previzualizarea nu este disponibilă.", "error");
      return;
    }
    pdfjsLib.getDocument(state.file.url).promise
      .then(function (doc) {
        state.pdfDoc = doc;
        state.pageCount = doc.numPages;
        els.fileMeta.textContent =
          formatSize(state.file.size) + " · " + doc.numPages +
          (doc.numPages === 1 ? " pagină" : " pagini");
        renderAllPages();
      })
      .catch(function () {
        toast("PDF-ul nu a putut fi citit.", "error");
        resetToDropzone();
      });
  }

  function renderAllPages() {
    els.pages.innerHTML = "";
    var containerWidth = Math.min(els.pagesScroll.clientWidth - 48, 820);
    var dpr = Math.min(window.devicePixelRatio || 1, 2);

    var renderPage = function (num) {
      state.pdfDoc.getPage(num).then(function (page) {
        var base = page.getViewport({ scale: 1 });
        var scale = (containerWidth / base.width) * state.zoom;
        var viewport = page.getViewport({ scale: scale });

        var wrap = document.createElement("div");
        wrap.className = "page-wrap";
        wrap.dataset.page = num;

        var canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = Math.floor(viewport.width) + "px";
        canvas.style.height = Math.floor(viewport.height) + "px";
        wrap.appendChild(canvas);

        var label = document.createElement("span");
        label.className = "page-num";
        label.textContent = num + " / " + state.pageCount;
        wrap.appendChild(label);

        els.pages.appendChild(wrap);

        page.render({
          canvasContext: canvas.getContext("2d"),
          viewport: viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
        }).promise.then(function () {
          if (num < state.pageCount) renderPage(num + 1);
          else applyPageRangePreview();
        });
      });
    };
    renderPage(1);
  }

  function renderImage() {
    var wrap = document.createElement("div");
    wrap.className = "page-wrap";
    var img = document.createElement("img");
    img.src = state.file.url;
    img.alt = state.file.name;
    wrap.appendChild(img);
    els.pages.appendChild(wrap);
  }

  function renderText() {
    fetch(state.file.url)
      .then(function (r) { return r.text(); })
      .then(function (text) {
        var pre = document.createElement("pre");
        pre.className = "text-preview";
        pre.textContent = text.slice(0, 20000);
        els.pages.appendChild(pre);
      });
  }

  /* ---------- zoom ---------- */

  function setZoom(delta) {
    if (!state.pdfDoc) return;
    state.zoom = Math.max(0.5, Math.min(2.5, state.zoom + delta));
    els.zoomLevel.textContent = Math.round(state.zoom * 100) + "%";
    renderAllPages();
  }

  els.zoomIn.addEventListener("click", function () { setZoom(0.25); });
  els.zoomOut.addEventListener("click", function () { setZoom(-0.25); });

  /* ---------- opțiuni & previzualizare live ---------- */

  function applyGrayscalePreview() {
    els.pages.classList.toggle("grayscale", segValue(els.colorSeg) === "gray");
  }

  function parsePageRange(text, maxPage) {
    var pages = {};
    text.split(",").forEach(function (part) {
      var bits = part.split("-");
      var start = parseInt(bits[0], 10);
      var end = bits.length > 1 ? parseInt(bits[1], 10) : start;
      for (var i = start; i <= Math.min(end, maxPage); i++) pages[i] = true;
    });
    return pages;
  }

  function applyPageRangePreview() {
    var text = els.pageRange.value.replace(/\s/g, "");
    var valid = text === "" || PAGE_RANGE_RE.test(text);
    els.pageRange.classList.toggle("invalid", !valid);
    els.pageRangeError.hidden = valid;

    var wraps = els.pages.querySelectorAll(".page-wrap[data-page]");
    if (!valid || text === "") {
      wraps.forEach(function (w) { w.classList.remove("excluded"); });
      return;
    }
    var included = parsePageRange(text, state.pageCount);
    wraps.forEach(function (w) {
      w.classList.toggle("excluded", !included[w.dataset.page]);
    });
  }

  initSegmented(els.colorSeg, function () { applyGrayscalePreview(); clearPreset(); });
  initSegmented(els.duplexSeg, clearPreset);
  initSegmented(els.orientSeg, clearPreset);
  initSegmented(els.edgeSeg, clearPreset);
  els.pageRange.addEventListener("input", applyPageRangePreview);
  els.mediaSelect.addEventListener("change", clearPreset);
  els.qualitySelect.addEventListener("change", clearPreset);
  els.fitToPage.addEventListener("change", clearPreset);

  /* ---------- copii ---------- */

  function clampCopies() {
    var v = parseInt(els.copies.value, 10);
    if (isNaN(v)) v = 1;
    els.copies.value = Math.max(1, Math.min(99, v));
    updatePrintButton();
  }

  els.copiesMinus.addEventListener("click", function () {
    els.copies.value = parseInt(els.copies.value, 10) - 1 || 1;
    clampCopies();
  });
  els.copiesPlus.addEventListener("click", function () {
    els.copies.value = (parseInt(els.copies.value, 10) || 0) + 1;
    clampCopies();
  });
  els.copies.addEventListener("change", clampCopies);

  /* ---------- presetări ---------- */

  var PRESETS = {
    document: { color: "gray", duplex: "duplex", media: "A4", quality: "normal", fit: false },
    photo:    { color: "color", duplex: "simplex", media: "A4", quality: "high", fit: true },
    draft:    { color: "gray", duplex: "duplex", media: "A4", quality: "draft", fit: false },
  };

  function clearPreset() {
    document.querySelectorAll(".preset").forEach(function (b) {
      b.classList.remove("active");
    });
  }

  document.querySelectorAll(".preset").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var p = PRESETS[btn.dataset.preset];
      if (!p) return;
      setSegValue(els.colorSeg, p.color);
      setSegValue(els.duplexSeg, p.duplex);
      els.mediaSelect.value = p.media;
      els.qualitySelect.value = p.quality;
      els.fitToPage.checked = p.fit;
      applyGrayscalePreview();
      clearPreset();
      btn.classList.add("active");
    });
  });

  /* ---------- printare ---------- */

  function updatePrintButton() {
    els.printBtn.disabled = !state.file || state.printing;
    var copies = parseInt(els.copies.value, 10) || 1;
    els.printBtnLabel.textContent = state.printing
      ? "Se trimite…"
      : copies > 1 ? "Printează " + copies + " copii" : "Printează";
  }

  els.printBtn.addEventListener("click", function () {
    if (!state.file || state.printing) return;

    var rangeText = els.pageRange.value.replace(/\s/g, "");
    if (rangeText && !PAGE_RANGE_RE.test(rangeText)) {
      toast("Intervalul de pagini este invalid.", "error");
      return;
    }

    state.printing = true;
    updatePrintButton();

    var payload = {
      file_id: state.file.id,
      printer: els.printerSelect.value || null,
      copies: parseInt(els.copies.value, 10) || 1,
      grayscale: segValue(els.colorSeg) === "gray",
      duplex: segValue(els.duplexSeg) === "duplex",
      duplex_edge: segValue(els.edgeSeg),
      landscape: segValue(els.orientSeg) === "landscape",
      media: els.mediaSelect.value,
      quality: els.qualitySelect.value,
      page_range: rangeText,
      fit_to_page: els.fitToPage.checked,
    };

    fetch("/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error || "Printarea a eșuat.");
          return data;
        });
      })
      .then(function (data) {
        toast("Trimis la imprimantă ✓", "success");
        rememberJobTitle(data.job_id, data.title);
        pollJobsSoon();
        loadFiles();  // reîmprospătează contorul de printări
      })
      .catch(function (err) {
        toast(err.message, "error");
      })
      .finally(function () {
        state.printing = false;
        updatePrintButton();
      });
  });

  /* ---------- coada de printare ---------- */

  var jobTitles = {};

  function rememberJobTitle(jobId, title) {
    if (jobId) jobTitles[jobId] = title;
  }

  var jobsTimer = null;

  function pollJobsSoon() {
    refreshJobs();
    loadPrinters(); // starea imprimantei se schimbă când printează
  }

  function refreshJobs() {
    fetch("/api/jobs")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderJobs(data.jobs || []);
        clearTimeout(jobsTimer);
        jobsTimer = setTimeout(refreshJobs, data.jobs && data.jobs.length ? 3000 : 12000);
      })
      .catch(function () {
        clearTimeout(jobsTimer);
        jobsTimer = setTimeout(refreshJobs, 15000);
      });
  }

  function renderJobs(jobs) {
    els.jobsSection.hidden = jobs.length === 0;
    els.jobsList.innerHTML = "";
    jobs.forEach(function (job) {
      var li = document.createElement("li");

      var dot = document.createElement("span");
      dot.className = "status-dot printing";
      li.appendChild(dot);

      var title = document.createElement("span");
      title.className = "job-title";
      title.textContent = job.title || jobTitles[job.id] ||
        job.printer.replace(/_/g, " ") + " · #" + job.number;
      li.appendChild(title);

      var cancel = document.createElement("button");
      cancel.className = "job-cancel";
      cancel.title = "Anulează";
      cancel.setAttribute("aria-label", "Anulează jobul");
      cancel.textContent = "✕";
      cancel.addEventListener("click", function () {
        cancel.disabled = true;
        fetch("/api/jobs/" + encodeURIComponent(job.id) + "/cancel", { method: "POST" })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.error) throw new Error(data.error);
            toast("Job anulat.", "success");
            pollJobsSoon();
          })
          .catch(function (err) { toast(err.message, "error"); });
      });
      li.appendChild(cancel);

      els.jobsList.appendChild(li);
    });
  }

  /* ---------- navigare între vizualizări ---------- */

  function switchView(name) {
    Object.keys(views).forEach(function (key) {
      views[key].hidden = key !== name;
    });
    els.tabs.querySelectorAll(".tab").forEach(function (t) {
      t.classList.toggle("active", t.dataset.view === name);
    });
    if (name === "files") loadFiles();
    if (name === "history") loadHistory();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  els.tabs.addEventListener("click", function (e) {
    var tab = e.target.closest(".tab");
    if (tab) switchView(tab.dataset.view);
  });

  document.addEventListener("click", function (e) {
    var goto = e.target.closest("[data-goto]");
    if (goto) switchView(goto.dataset.goto);
  });

  /* ---------- bibliotecă de fișiere ---------- */

  function loadFiles() {
    fetch("/api/files")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var files = data.files || [];
        els.filesBadge.hidden = files.length === 0;
        els.filesBadge.textContent = files.length;
        renderFiles(files);
      })
      .catch(function () {});
  }

  function renderFiles(files) {
    els.fileGrid.innerHTML = "";
    els.filesEmpty.hidden = files.length > 0;
    els.filesCount.textContent = files.length
      ? files.length + (files.length === 1 ? " fișier" : " fișiere")
      : "";

    files.forEach(function (f) {
      var li = document.createElement("li");
      li.className = "file-card";

      var top = document.createElement("div");
      top.className = "file-card-top";

      var thumb = document.createElement("div");
      thumb.className = "file-thumb";
      thumb.textContent = typeIcon(f.type);
      top.appendChild(thumb);

      var info = document.createElement("div");
      info.className = "file-card-info";
      var name = document.createElement("div");
      name.className = "file-card-name";
      name.textContent = f.name;
      info.appendChild(name);
      var meta = document.createElement("div");
      meta.className = "file-card-meta";
      meta.textContent = formatSize(f.size) + " · " + formatDate(f.created_at);
      info.appendChild(meta);
      if (f.print_count > 0) {
        var pc = document.createElement("div");
        pc.className = "print-count";
        pc.textContent = "✓ printat de " + f.print_count +
          (f.print_count === 1 ? " dată" : " ori");
        info.appendChild(pc);
      }
      top.appendChild(info);
      li.appendChild(top);

      var actions = document.createElement("div");
      actions.className = "file-card-actions";

      var open = document.createElement("button");
      open.className = "open-btn";
      open.innerHTML = "🖨️ Deschide";
      open.addEventListener("click", function () { openFromLibrary(f); });
      actions.appendChild(open);

      var del = document.createElement("button");
      del.className = "del-btn";
      del.title = "Șterge fișierul";
      del.setAttribute("aria-label", "Șterge fișierul");
      del.innerHTML = "🗑";
      del.addEventListener("click", function () { deleteFile(f, li); });
      actions.appendChild(del);

      li.appendChild(actions);
      els.fileGrid.appendChild(li);
    });
  }

  function openFromLibrary(f) {
    state.file = { id: f.id, name: f.name, type: f.type, url: f.url, size: f.size };
    switchView("print");
    showPreview();
    toast("„" + f.name + "” — alege opțiunile și printează.", "success");
  }

  function deleteFile(f, li) {
    if (!confirm("Ștergi „" + f.name + "”?")) return;
    fetch("/api/files/" + encodeURIComponent(f.id), { method: "DELETE" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        li.remove();
        loadFiles();
        if (state.file && state.file.id === f.id) resetToDropzone();
      })
      .catch(function (err) { toast(err.message, "error"); });
  }

  /* ---------- istoric ---------- */

  function loadHistory() {
    fetch("/api/history")
      .then(function (r) { return r.json(); })
      .then(function (data) { renderHistory(data.history || []); })
      .catch(function () {});
  }

  function renderHistory(items) {
    els.historyList.innerHTML = "";
    els.historyEmpty.hidden = items.length > 0;
    els.clearHistory.hidden = items.length === 0;

    items.forEach(function (h) {
      var li = document.createElement("li");
      li.className = "history-item";

      var badge = document.createElement("div");
      badge.className = "history-badge";
      badge.textContent = typeIcon(h.type);
      li.appendChild(badge);

      var body = document.createElement("div");
      body.className = "history-body";
      var name = document.createElement("div");
      name.className = "history-name";
      name.textContent = h.name;
      body.appendChild(name);

      var meta = document.createElement("div");
      meta.className = "history-meta";
      var when = document.createElement("span");
      when.className = "history-chip";
      when.textContent = "🕑 " + formatDate(h.created_at);
      meta.appendChild(when);
      optionsSummary(h.options).forEach(function (bit) {
        var chip = document.createElement("span");
        chip.className = "history-chip";
        chip.textContent = bit;
        meta.appendChild(chip);
      });
      body.appendChild(meta);
      li.appendChild(body);

      var btn = document.createElement("button");
      btn.className = "reprint-btn";
      btn.innerHTML = "🖨️ Reprintează";
      btn.disabled = !h.can_reprint;
      if (!h.can_reprint) btn.title = "Fișierul nu mai există";
      btn.addEventListener("click", function () { reprint(h, btn); });
      li.appendChild(btn);

      els.historyList.appendChild(li);
    });
  }

  function reprint(h, btn) {
    btn.disabled = true;
    var payload = Object.assign({}, h.options, { file_id: h.file_id });
    fetch("/api/print", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error || "Printarea a eșuat.");
          return data;
        });
      })
      .then(function (data) {
        toast("Retrimis la imprimantă ✓", "success");
        rememberJobTitle(data.job_id, data.title);
        pollJobsSoon();
      })
      .catch(function (err) { toast(err.message, "error"); })
      .finally(function () { btn.disabled = !h.can_reprint; });
  }

  els.clearHistory.addEventListener("click", function () {
    if (!confirm("Golești tot istoricul de printări?")) return;
    fetch("/api/history", { method: "DELETE" })
      .then(function (r) { return r.json(); })
      .then(function () { loadHistory(); toast("Istoric golit.", "success"); })
      .catch(function (err) { toast(err.message, "error"); });
  });

  /* ---------- pornire ---------- */

  loadPrinters();
  refreshJobs();
  loadFiles();
  updatePrintButton();
})();
