/** @odoo-module **/

import { Component, useRef, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

function uid() { return `${Date.now()}-${Math.random().toString(36).slice(2,8)}`; }
function fmtTime(d) {
  try { const hh = String(d.getHours()).padStart(2,"0"), mm = String(d.getMinutes()).padStart(2,"0"); return `${hh}:${mm}`; }
  catch { return ""; }
}

/**
 * CameraAI – chụp ảnh, gửi AI, gom kết quả theo {received_map, serials_map}
 * Props:
 *  - prompt?: string
 *  - expectedItems: Array<{ma_part, ten, so_yeu_cau}>
 *  - onResult?: (payload, score, cancelled) => void
 *  - simulate?: boolean   // tùy chọn: true = giả lập dữ liệu từ expectedItems
 *
 * Template: "my_camera.CameraAI" (giữ nguyên template cũ của bạn)
 */
export class CameraAI extends Component {
  static template = "my_camera.CameraAI";
  static props = {
    prompt: { type: String, optional: true },
    expectedItems: { type: Array },      // [{ma_part, ten, so_yeu_cau}]
    onResult: { type: Function, optional: true },
    simulate: { type: Boolean, optional: true }, // mặc định false
  };

  setup() {
    this.videoRef     = useRef("video");
    this.rpc          = useService("rpc");
    this.notification = useService("notification");

    this.state = useState({
      busy: false,
      expected: (this.props.expectedItems || []).map(x => ({
        ma_part: x.ma_part ?? "",
        ten: x.ten ?? "",
        so_yeu_cau: Number(x.so_yeu_cau) || 0,
      })),
      detected_map: {},     // {code: total_received}
      captures: [],         // [{id, ts, items:[{_id, ma_part, ten, so_luong, serials[]}], manual?}]
      rawAnswer: "",
      editor: { open:false, ma_part:null, tempLines:[] },
    });

    this.imageCapture = null;
    this.stream = null;

    onMounted(() => this._startCamera());
    onWillUnmount(() => this._stopCamera());
  }

  /* ===== Camera ===== */
  async _startCamera() {
    await this._stopCamera();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 2592 }, height: { ideal: 1944 } },
        audio: false,
      });
      const track = this.stream.getVideoTracks()[0];
      if (window.ImageCapture) this.imageCapture = new window.ImageCapture(track);
      this.videoRef.el.srcObject = this.stream;
      await this.videoRef.el.play();
    } catch (err) {
      this.notification.add("Cannot open camera: " + (err?.message || err), { type: "danger" });
      this.close();
    }
  }
  _stopCamera() {
    if (this.stream) {
      this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
      this.imageCapture = null;
    }
  }

  /* ===== Capture & send (KHÔNG đóng dialog) ===== */
  async takePhoto() {
    let dataURL;

    if (this.imageCapture?.takePhoto) {
      try {
        const blob = await this.imageCapture.takePhoto();
        dataURL = await new Promise((resolve) => {
          const r = new FileReader(); r.onload = () => resolve(r.result); r.readAsDataURL(blob);
        });
      } catch (e) { console.warn("takePhoto error:", e); }
    }
    if (!dataURL) {
      const vid = this.videoRef.el;
      if (!vid.videoWidth || !vid.videoHeight) {
        this.notification.add("Camera is not ready. Please wait.", { type: "warning" });
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.width = vid.videoWidth; canvas.height = vid.videoHeight;
      canvas.getContext("2d").drawImage(vid, 0, 0, canvas.width, canvas.height);
      dataURL = canvas.toDataURL("image/jpeg", 0.9);
    }
    await this._sendImage(dataURL, this.state.expected);
  }

  async _sendImage(dataURL, expectedList) {
    this.state.busy = true;
    this.state.rawAnswer = "";
    const base64 = (dataURL || "").split(",", 2)[1] || "";

    try {
      let res;
      if (this.props.simulate) {
        res = await this._fakeApiCall(expectedList);
      } else {
        res = await this.rpc("/camera/upload", {
          image: base64,
          expected: expectedList,
          prompt: this.props.prompt,
        });
      }

      if (res.status === "ok") {
        // Cập nhật log + thêm 1 capture mới từ kết quả AI
        this.state.rawAnswer = res.answer;
        let parsed = {};
        try { parsed = JSON.parse(res.answer || "{}"); } catch { parsed = {}; }

        const now = new Date();
        const cap = { id: uid(), ts: now, items: [] };
        const items = Array.isArray(parsed.items) ? parsed.items : [];
        for (const it of items) {
          const ma  = String(it.ma_part || "").trim();
          const ten = String(it.ten || "");
          const qty = Number(it.so_luong || 0) || 0;
          const serials = Array.isArray(it.serials)
            ? it.serials
                .filter((s) => typeof s === "string" && s.trim())
                .map((s) => s.trim())
            : [];
          if (!ma && !ten) continue;
          cap.items.push({ _id: uid(), ma_part: ma, ten, so_luong: Math.max(0, qty), serials });
        }
        this.state.captures.push(cap);
        this._recomputeDetectedMap();

        // KHÔNG gọi onResult tại đây → người dùng bấm Confirm mới gửi
      } else {
        this.notification.add(res.message || "Unknown error.", { type: "danger" });
      }
    } catch (e) {
      this.notification.add("Cannot connect to AI server: " + (e?.message || e), { type: "danger" });
    } finally {
      this.state.busy = false;
    }
  }

  // (Tùy chọn) Fake API – sinh dữ liệu từ expectedList
  async _fakeApiCall(expectedList = []) {
    await new Promise((r) => setTimeout(r, 300));
    const items = [];

    for (const e of expectedList) {
      if (Math.random() < 0.85) {
        const need  = Number(e.so_yeu_cau) || 0;
        const base  = need || (1 + Math.floor(Math.random() * 5));
        const delta = [-2,-1,0,1,2][Math.floor(Math.random() * 5)];
        const qty   = Math.max(0, base + delta);

        // giả định mã có hậu tố "-SER" là hàng serial → sinh serials
        const isSerial = String(e.ma_part || "").includes("-SER");
        const serials = isSerial
          ? Array.from({ length: Math.min(qty, 30) }, (_, i) => `${e.ma_part}-SN${String(i+1).padStart(3,"0")}`)
          : [];

        items.push({
          ma_part: String(e.ma_part || "").trim(),
          ten: String(e.ten || ""),
          so_luong: qty,
          serials,
        });
      }
    }

    // Thêm 0–2 sản phẩm ngoài danh sách
    const extras = Math.floor(Math.random() * 3);
    for (let i = 0; i < extras; i++) {
      const suffix = Math.random().toString(36).slice(2, 6).toUpperCase();
      items.push({ ma_part: `UNK-${suffix}`, ten: `Sản phẩm lạ ${i + 1}`, so_luong: 1 + Math.floor(Math.random() * 3), serials: [] });
    }

    return { status: "ok", answer: JSON.stringify({ items }) };
  }

  _recomputeDetectedMap() {
    const sum = {};
    for (const cap of this.state.captures) {
      for (const it of cap.items || []) {
        if (!it.ma_part) continue;
        sum[it.ma_part] = (sum[it.ma_part] || 0) + (Number(it.so_luong) || 0);
      }
    }
    this.state.detected_map = sum;
  }

  /* ===== Editor (nếu bạn dùng) ===== */
  openEditor(ma_part) {
    const temp = [];
    let idx = 0;
    for (const cap of this.state.captures) {
      idx += 1;
      const label = `#${idx} • ${fmtTime(cap.ts)}`;
      for (const it of cap.items) {
        if (it.ma_part === ma_part) {
          temp.push({
            _id: it._id,
            capture_id: cap.id,
            capture_label: label,
            ma_part: it.ma_part,
            ten: it.ten,
            so_luong: Number(it.so_luong) || 0,
            serials: Array.isArray(it.serials) ? it.serials.slice() : [],
          });
        }
      }
    }
    this.state.editor = { open: true, ma_part, tempLines: temp };
  }
  addEditorLine = () => {
    this.state.editor.tempLines.push({
      _id: uid(),
      capture_id: "manual",
      capture_label: "Manual",
      ma_part: this.state.editor.ma_part,
      ten: "",
      so_luong: 0,
      serials: [],
    });
  };
  removeEditorLine = (id) => {
    this.state.editor.tempLines = this.state.editor.tempLines.filter(r => r._id !== id);
  };
  editorTotal() { return this.state.editor.tempLines.reduce((a, r) => a + (Number(r.so_luong) || 0), 0); }
  saveEditor = () => {
    const part = this.state.editor.ma_part;
    const byId = new Map(this.state.editor.tempLines.map(r => [r._id, r]));
    // cập nhật các dòng thuộc captures
    for (const cap of this.state.captures) {
      for (const it of (cap.items || [])) {
        if (it.ma_part === part && byId.has(it._id)) {
          const row = byId.get(it._id);
          it.ten = row.ten || it.ten;
          it.so_luong = Math.max(0, Number(row.so_luong) || 0);
          it.serials = Array.isArray(row.serials)
            ? row.serials.filter((s)=>typeof s==="string" && s.trim()).map((s)=>s.trim())
            : [];
        }
      }
    }
    // gom dòng manual
    const manualRows = this.state.editor.tempLines.filter(r => r.capture_id === "manual");
    if (manualRows.length) {
      let manualCap = this.state.captures.find(c => c.manual === true);
      if (!manualCap) { manualCap = { id: uid(), ts: new Date(), items: [], manual: true }; this.state.captures.push(manualCap); }
      for (const r of manualRows) {
        const existed = manualCap.items.find(x => x._id === r._id);
        const payload = {
          _id: r._id,
          ma_part: part,
          ten: r.ten || "",
          so_luong: Math.max(0, Number(r.so_luong) || 0),
          serials: Array.isArray(r.serials)
            ? r.serials.filter((s)=>typeof s==="string" && s.trim()).map((s)=>s.trim())
            : [],
        };
        if (existed) Object.assign(existed, payload);
        else manualCap.items.push(payload);
      }
    }
    this._recomputeDetectedMap();
    this.cancelEditor();
  };
  cancelEditor = () => { this.state.editor = { open:false, ma_part:null, tempLines:[] }; };

  /* ===== Confirm / Cancel ===== */
  buildSubmission() {
    // summary theo expected + detected_map hiện tại
    const summary = (this.state.expected || []).map(e => {
      const got = Number(this.state.detected_map[e.ma_part] || 0);
      const need = Number(e.so_yeu_cau || 0);
      return {
        ma_part: e.ma_part,
        ten: e.ten,
        required: need,
        received: got,
        missing: Math.max(0, need - got),
      };
    });

    // xuất toàn bộ captures (audit)
    const captures = (this.state.captures || []).map(c => ({
      id: c.id,
      ts_iso: (c.ts && c.ts.toISOString) ? c.ts.toISOString() : null,
      items: (c.items || []).map(it => ({
        _id: it._id,
        ma_part: it.ma_part,
        ten: it.ten,
        qty: Number(it.so_luong) || 0,
        serials: Array.isArray(it.serials) ? it.serials : [],
      })),
      manual: !!c.manual,
    }));

    // map nhanh mã → tổng nhận
    const received_map = { ...this.state.detected_map };

    // gom toàn bộ serial theo mã (unique, giữ thứ tự)
    const serials_map = {};
    for (const cap of (this.state.captures || [])) {
      for (const it of (cap.items || [])) {
        if (!it?.ma_part) continue;
        const list = Array.isArray(it.serials) ? it.serials : [];
        if (!list.length) continue;
        if (!serials_map[it.ma_part]) serials_map[it.ma_part] = [];
        for (const s of list) {
          const v = (typeof s === "string" ? s.trim() : "");
          if (v && !serials_map[it.ma_part].includes(v)) serials_map[it.ma_part].push(v);
        }
      }
    }

    return { received_map, serials_map, summary, captures };
  }

  confirmAndSend = () => {
    const payload = this.buildSubmission();
    this.props.onResult?.(payload, null, false);
    this.close();
  };

  cancelAll = () => {
    this.close(); // không trả dữ liệu
  };

  /* ===== Close ===== */
  close() {
    this._stopCamera();
    this.props.onResult?.(null, null, true); // báo cancelled
  }
}
