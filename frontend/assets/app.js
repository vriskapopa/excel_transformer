const DOC_TYPE_RU = {
  INVOICE: "Инвойс",
  PACKING_LIST: "Упаковочный лист",
  SPECIFICATION: "Спецификация",
  CATALOG: "Справочник",
  PERMIT: "РД",
};

const STATUS_RU = {
  DRAFT: "черновик",
  UPLOADING: "загрузка",
  PARSING: "разбор",
  RECONCILING: "сверка",
  NEEDS_REVIEW: "нужна проверка",
  READY_TO_EXPORT: "готово к выгрузке",
  EXPORTING: "выгрузка",
  EXPORTED: "выгружено",
  FAILED: "ошибка",
};

const state = { shipmentId: null, workspace: null, selectedItemId: null, pendingFiles: [] };

const $ = (sel) => document.querySelector(sel);

function classifyUploadName(filename) {
  const name = String(filename || "").toUpperCase();
  if (name.endsWith(".PDF")) return "pdf";
  if (/\.(PNG|JPE?G|TIF{1,2}|BMP|WEBP)$/.test(name)) return "scan";
  if (name.includes("INVOICE") || name.includes("ИНВОЙС")) return "invoice";
  if (name.includes("-PL") || name.includes("PACKING") || name.endsWith("PL.XLSX") || name.includes("ПАКИНГ")) {
    return "packing";
  }
  if (name.includes("SPEC") || name.includes("СПЕЦИФ")) return "specification";
  return null;
}

function syncFileInput() {
  const input = $("#files");
  const list = $("#file-list");
  const dt = new DataTransfer();
  state.pendingFiles.forEach((f) => dt.items.add(f));
  input.files = dt.files;
  list.innerHTML = "";
  const roleRu = {
    invoice: "инвойс",
    packing: "упаковочный",
    specification: "спецификация",
    pdf: "PDF",
    scan: "скан",
  };
  const found = new Set();
  state.pendingFiles.forEach((f) => {
    const role = classifyUploadName(f.name);
    if (role) found.add(role);
    const li = document.createElement("li");
    li.textContent = role ? `${f.name} → ${roleRu[role]}` : `${f.name} → ?`;
    list.appendChild(li);
  });
  const missing = ["invoice", "packing", "specification"].filter((r) => !found.has(r));
  const hint = $("#kit-check");
  if (!hint) return;
  if (!state.pendingFiles.length) {
    hint.textContent = "";
    return;
  }
  if (missing.length) {
    hint.textContent =
      `Можно добавить ещё: ${missing.map((m) => roleRu[m]).join(", ")}. Если есть только инвойс 626-x — сервис сам подставит PL и Specification из материалов.`;
    hint.className = "status kit-warn";
  } else {
    hint.textContent = "Комплект полный: инвойс + упаковочный + спецификация.";
    hint.className = "status kit-ok";
  }
}

function addPendingFiles(fileList) {
  const byName = new Map(state.pendingFiles.map((f) => [f.name, f]));
  [...fileList].forEach((f) => byName.set(f.name, f));
  state.pendingFiles = [...byName.values()];
  syncFileInput();
}

$("#files").addEventListener("change", (e) => {
  addPendingFiles(e.target.files);
});

const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  });
});
dropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) addPendingFiles(e.dataTransfer.files);
});

$("#create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  if (!state.pendingFiles.length) {
    $("#upload-status").textContent = "Выберите файлы комплекта.";
    return;
  }
  const fd = new FormData();
  fd.append("title", form.title.value);
  fd.append("profile_type", form.profile_type.value);
  state.pendingFiles.forEach((f) => fd.append("files", f));
  $("#upload-status").textContent = "Обработка…";
  try {
    const created = await api("/api/v1/shipments/", { method: "POST", body: fd });
    state.shipmentId = created.id;
    $("#upload-status").textContent =
      `Готово: ${created.item_count} позиций, предупреждений: ${created.warning_count}`;
    await loadWorkspace(created.id);
  } catch (err) {
    $("#upload-status").textContent = `Ошибка: ${err.message}`;
  }
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function severityClass(errors) {
  // Full-row tint only for hard mismatches — yellow wash made the table look "all white"
  if (!errors?.length) return "";
  if (errors.some((e) => e.severity === "RED" && !e.resolved)) return "sev-RED";
  return "";
}

function formatNum(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return escapeHtml(value);
  return n.toLocaleString("ru-RU", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : Math.min(digits, 2),
    maximumFractionDigits: digits,
  });
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return escapeHtml(value);
  return n.toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const SEVERITY_RU = {
  RED: "Расхождение",
  YELLOW: "Пропуск",
  ORANGE: "OCR",
  BLUE: "РД",
};

const FIELD_RU = {
  article: "артикул",
  rolls: "рулоны",
  meters: "метры",
  width: "ширина",
  area: "площадь",
  net_weight: "нетто",
  gross_weight: "брутто",
  price: "цена",
  amount: "сумма",
  qty: "кол-во",
  hs_code: "HS",
  tnved_code: "ТН ВЭД",
  description: "описание",
  design_family: "группа",
  ocr: "OCR",
};

function renderFlags(errors) {
  const active = (errors || []).filter((e) => !e.resolved);
  if (!active.length) {
    return '<span class="flag-pill flag-pill-ok" title="Расхождений нет">✓ Без замечаний</span>';
  }
  return `<div class="flags-wrap">${active
    .map((e) => {
      const label = SEVERITY_RU[e.severity] || e.severity;
      const field = FIELD_RU[e.field_name] || e.field_name || "";
      const msg = e.message || e.error_type || "";
      const title = escapeHtml([field, msg].filter(Boolean).join(" — "));
      const text = field ? `${label}: ${field}` : label;
      return `<span class="flag-pill flag-pill-${e.severity}" title="${title}">${escapeHtml(text)}</span>`;
    })
    .join("")}</div>`;
}

function fieldSeverity(errors, field) {
  const hit = (errors || []).find((e) => e.field_name === field && !e.resolved);
  return hit ? `sev-${hit.severity}` : "";
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const text = await res.text();
    let detail = text || res.statusText;
    try {
      const parsed = JSON.parse(text);
      if (parsed?.detail) {
        detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch {
      /* keep raw text */
    }
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res;
}

async function downloadExportFile(url, filename) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Не удалось скачать ${filename}: ${res.status}`);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}

async function loadWorkspace(id) {
  state.shipmentId = id;
  sessionStorage.setItem("shipmentId", id);
  const ws = await api(`/api/v1/shipments/${id}/workspace`);
  state.workspace = ws;
  $("#workspace").classList.remove("hidden");
  $("#ws-title").textContent = ws.title;
  $("#ws-meta").textContent =
    `${ws.profile_type} · ${STATUS_RU[ws.status] || ws.status} · ${ws.items.length} позиций`;

  const badges = $("#files-badges");
  badges.innerHTML = "";
  ws.files.forEach((f) => {
    const span = document.createElement("span");
    span.className = `badge ${f.doc_type ? "" : "unknown"}`;
    const typeRu = DOC_TYPE_RU[f.doc_type] || (f.filename?.toLowerCase().endsWith(".pdf") ? "PDF" : "не определён");
    const ocrHint =
      f.ocr_confidence != null ? ` · OCR ${Math.round(Number(f.ocr_confidence) * 100)}%` : "";
    span.textContent = `${f.filename} → ${typeRu}${ocrHint}`;
    badges.appendChild(span);
  });

  const hf = ws.header_fields || {};
  const headerForm = $("#header-form");
  [
    "buyer",
    "seller",
    "contract_no",
    "contract_date",
    "invoice_no",
    "invoice_date",
    "delivery_terms",
    "payment_terms",
    "manufacturer",
    "delivery_date",
    "warehouse_address",
  ].forEach((k) => {
    if (headerForm[k]) headerForm[k].value = hf[k] || "";
  });

  const tbody = $("#items-table tbody");
  tbody.innerHTML = "";
  ws.items.forEach((item, idx) => {
    const tr = document.createElement("tr");
    const c = item.commercial_data || {};
    const p = item.packing_data || {};
    const u = item.customs_data || {};
    const errs = item.validation_errors || [];
    tr.className = `item-row ${severityClass(errs)}`.trim();
    tr.dataset.id = item.id;
    tr.title = "Нажмите для правки позиции";
    const desc = u.description || u.description_ru || u.description_en || "—";
    const descSafe = escapeHtml(desc);
    tr.innerHTML = `
      <td class="row-no">${idx + 1}</td>
      <td class="article">${escapeHtml(item.article || "—")}</td>
      <td class="num ${fieldSeverity(errs, "rolls")}">${formatNum(p.rolls, 0)}</td>
      <td class="num ${fieldSeverity(errs, "meters")}">${formatNum(p.meters)}</td>
      <td class="num ${fieldSeverity(errs, "width")}">${formatNum(p.width, 3)}</td>
      <td class="num ${fieldSeverity(errs, "area")}">${formatNum(p.area, 3)}</td>
      <td class="num ${fieldSeverity(errs, "net_weight")}">${formatNum(p.net_weight)}</td>
      <td class="num ${fieldSeverity(errs, "gross_weight")}">${formatNum(p.gross_weight)}</td>
      <td class="money ${fieldSeverity(errs, "price")}">${formatMoney(c.price)}</td>
      <td class="money ${fieldSeverity(errs, "amount")}">${formatMoney(c.amount)}</td>
      <td class="${fieldSeverity(errs, "hs_code")}">${escapeHtml(u.hs_code || "—")}</td>
      <td class="${fieldSeverity(errs, "tnved_code")}">${escapeHtml(u.tnved_code || "—")}</td>
      <td class="desc" title="${descSafe}">${descSafe.slice(0, 60)}${descSafe.length > 60 ? "…" : ""}</td>
      <td class="flags-cell">${renderFlags(errs)}</td>
    `;
    tbody.appendChild(tr);
  });
}

$("#items-table").addEventListener("click", (e) => {
  const row = e.target.closest("tbody tr.item-row");
  if (!row?.dataset.id) return;
  openEdit(row.dataset.id);
});

function editField(id) {
  return document.getElementById(id);
}

function openEdit(itemId) {
  if (!state.workspace?.items) {
    alert("Сначала обработайте комплект файлов.");
    return;
  }
  const item = state.workspace.items.find((i) => String(i.id) === String(itemId));
  if (!item) {
    alert("Позиция не найдена. Обновите страницу и попробуйте снова.");
    return;
  }
  state.selectedItemId = itemId;
  editField("edit-item-id").value = itemId;
  editField("edit-article").value = item.article || "";
  editField("edit-qty").value = item.packing_data?.meters ?? item.commercial_data?.qty ?? "";
  editField("edit-price").value = item.commercial_data?.price ?? "";
  editField("edit-amount").value = item.commercial_data?.amount ?? "";
  editField("edit-net-weight").value = item.packing_data?.net_weight ?? "";
  editField("edit-gross-weight").value = item.packing_data?.gross_weight ?? "";
  editField("edit-tnved").value = item.customs_data?.tnved_code ?? "";
  editField("edit-desc-en").value =
    item.customs_data?.description ?? item.customs_data?.description_en ?? "";
  editField("edit-desc-ru").value = item.customs_data?.description_ru ?? "";
  $("#edit-status").textContent = "";
  $("#edit-dialog").showModal();
}

async function saveEditedItem() {
  if (!state.shipmentId) {
    alert("Сессия поставки потеряна. Загрузите комплект заново.");
    return;
  }
  const itemId = editField("edit-item-id").value;
  if (!itemId) return;

  const saveBtn = $("#edit-save");
  const status = $("#edit-status");
  saveBtn.disabled = true;
  status.textContent = "Сохранение…";

  const payload = {
    article: editField("edit-article").value || null,
    commercial_data: {
      qty: numOrNull(editField("edit-qty").value),
      price: numOrNull(editField("edit-price").value),
      amount: numOrNull(editField("edit-amount").value),
    },
    packing_data: {
      meters: numOrNull(editField("edit-qty").value),
      net_weight: numOrNull(editField("edit-net-weight").value),
      gross_weight: numOrNull(editField("edit-gross-weight").value),
    },
    customs_data: {
      tnved_code: editField("edit-tnved").value || null,
      description: editField("edit-desc-en").value || null,
      description_en: editField("edit-desc-en").value || null,
      description_ru: editField("edit-desc-ru").value || null,
    },
  };

  try {
    await api(`/api/v1/shipments/${state.shipmentId}/items/${itemId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("#edit-dialog").close();
    await loadWorkspace(state.shipmentId);
    $("#upload-status").textContent = "Позиция сохранена.";
  } catch (err) {
    status.textContent = `Ошибка: ${err.message}`;
    alert(`Не удалось сохранить позицию: ${err.message}`);
  } finally {
    saveBtn.disabled = false;
  }
}

$("#edit-form").addEventListener("submit", (e) => {
  e.preventDefault();
  saveEditedItem();
});

$("#edit-cancel").addEventListener("click", () => {
  $("#edit-dialog").close();
});

function numOrNull(v) {
  if (v === "" || v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

$("#header-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.shipmentId) return;
  const form = e.target;
  const payload = {
    buyer: form.buyer.value,
    seller: form.seller.value,
    contract_no: form.contract_no.value,
    contract_date: form.contract_date.value,
    invoice_no: form.invoice_no.value,
    invoice_date: form.invoice_date.value,
    delivery_terms: form.delivery_terms.value,
    payment_terms: form.payment_terms.value,
    manufacturer: form.manufacturer.value,
    delivery_date: form.delivery_date.value,
    warehouse_address: form.warehouse_address.value,
  };
  try {
    await api(`/api/v1/shipments/${state.shipmentId}/header`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await loadWorkspace(state.shipmentId);
  } catch (err) {
    alert(`Не удалось сохранить шапку: ${err.message}`);
  }
});

$("#btn-export").addEventListener("click", async () => {
  const btn = $("#btn-export");
  const box = $("#export-result");
  if (!state.shipmentId) {
    box.textContent = "Сначала обработайте комплект файлов.";
    return;
  }
  btn.disabled = true;
  const prevLabel = btn.textContent;
  btn.textContent = "Формирование…";
  box.textContent = "Формирую Excel…";
  try {
    const result = await api(`/api/v1/shipments/${state.shipmentId}/export`, { method: "POST" });
    const files = result.files || [];
    if (!files.length) {
      throw new Error("Сервер не вернул файлы.");
    }
    const zipName = files.find((f) => String(f).toLowerCase().endsWith(".zip")) || files[0];
    box.textContent = `Скачиваю ${zipName}…`;
    await downloadExportFile(`${result.download_base}/${encodeURIComponent(zipName)}`, zipName);
    const links = files
      .map(
        (f) =>
          `<a href="${result.download_base}/${encodeURIComponent(f)}" download="${escapeHtml(f)}">${escapeHtml(f)}</a>`
      )
      .join("<br>");
    box.innerHTML = `Готово — скачан архив. Отдельные файлы:<br>${links}`;
    try {
      await loadWorkspace(state.shipmentId);
    } catch {
      /* keep export status even if refresh fails */
    }
  } catch (err) {
    box.textContent = `Ошибка экспорта: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = prevLabel;
  }
});

$("#btn-permits").addEventListener("click", async () => {
  if (!state.shipmentId) {
    alert("Сначала обработайте комплект файлов.");
    return;
  }
  try {
    const itemId = state.selectedItemId || state.workspace?.items?.[0]?.id;
    const q = itemId ? `?item_id=${itemId}` : "";
    const data = await api(`/api/v1/shipments/${state.shipmentId}/permits${q}`);
    $("#permit-body").textContent = JSON.stringify(data.by_database, null, 2);
    $("#permit-dialog").showModal();
  } catch (err) {
    alert(`Не удалось загрузить РД: ${err.message}`);
  }
});

$("#permit-close").addEventListener("click", () => $("#permit-dialog").close());

const savedShipmentId = sessionStorage.getItem("shipmentId");
if (savedShipmentId) {
  loadWorkspace(savedShipmentId).catch(() => sessionStorage.removeItem("shipmentId"));
}
