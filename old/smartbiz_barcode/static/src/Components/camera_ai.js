/** @odoo-module **/

import { Component, useRef, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/* ------------------------------------------------------------------
   CropperDialog – cho phép người dùng crop ảnh sau khi chụp
------------------------------------------------------------------ */
export class CropperDialog extends Component {
    static template = "my_camera.CropperDialog";
    static props = {
        src: { type: String },           // dataURL ảnh vừa chụp
        onCancel: { type: Function },    // đóng dialog
        onOK: { type: Function },        // trả về dataURL đã crop
    };

    setup() {
        this.imgRef       = useRef("img");
        this.cropper      = null;
        this.notification = useService("notification");

        onMounted(() => {
            const img = this.imgRef.el;
            const init = () => {
                this.cropper = new window.Cropper(img, {
                    viewMode: 1,
                    dragMode: "move",
                    movable: true,
                    zoomable: true,
                    autoCropArea: 1,
                    responsive: true,
                    background: false,
                });
            };
            img.complete ? init() : img.addEventListener("load", init, { once: true });
        });

        onWillUnmount(() => this.cropper?.destroy?.());
    }

    confirm() {
        if (!this.cropper) {
            this.notification.add("Vùng crop chưa sẵn sàng, hãy thử lại.", { type: "warning" });
            return;
        }
        // Xuất canvas ở độ phân giải gốc của ảnh
        const imgData = this.cropper.getImageData();
        const canvas = this.cropper.getCroppedCanvas({
            width: imgData.naturalWidth,
            height: imgData.naturalHeight,
        });
        if (!canvas) {
            this.notification.add("Không thể lấy vùng crop.", { type: "warning" });
            return;
        }
        // Xuất ra JPEG chất lượng 0.9 để vừa nét vừa không quá nặng
        const dataURL = canvas.toDataURL("image/jpeg", 0.9);
        this.props.onOK(dataURL);
    }
}

/* ------------------------------------------------------------------
   CameraAI – bật camera, chụp, crop và gửi backend
------------------------------------------------------------------ */
export class CameraAI extends Component {
    static template = "my_camera.CameraAI";
    static components = { CropperDialog };

    static props = {
        prompt:   { type: String },
        onResult: { type: Function, optional: true },
    };

    setup() {
        this.videoRef     = useRef("video");
        this.rpc          = useService("rpc");
        this.notification = useService("notification");

        this.state = useState({
            busy: false,
            showCropper: false,
            capturedURL: null,
            previewURL:  null,
            result: "",
        });
        this._sendCropped = this._sendCropped.bind(this);
        this.imageCapture = null;  // giữ instance ImageCapture

        onMounted(() => this._startCamera());
        onWillUnmount(() => this._stopCamera());
    }

    /* -------------------- Camera -------------------- */
    async _startCamera() {
        await this._stopCamera();
        try {
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: "environment" },
                    width:  { ideal: 1920 },
                    height: { ideal: 1080 },
                },
                audio: false,
            });
            // tạo ImageCapture để chụp ảnh chất lượng cao
            const track = this.stream.getVideoTracks()[0];
            if (window.ImageCapture) {
                this.imageCapture = new window.ImageCapture(track);
            }
            this.videoRef.el.srcObject = this.stream;
            await this.videoRef.el.play();
        } catch (err) {
            this.notification.add("Không thể mở camera: " + err.message, { type: "danger" });
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

    /* -------------------- Chụp ảnh -------------------- */
    async takePhoto() {
        let dataURL;
        // ưu tiên ImageCapture nếu trình duyệt hỗ trợ
        if (this.imageCapture?.takePhoto) {
            try {
                const blob = await this.imageCapture.takePhoto();
                dataURL = await new Promise(resolve => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                });
            } catch (err) {
                console.warn("ImageCapture.takePhoto lỗi:", err);
            }
        }
        // fallback về canvas snapshot
        if (!dataURL) {
            const vid = this.videoRef.el;
            if (!vid.videoWidth || !vid.videoHeight) {
                this.notification.add("Camera chưa sẵn sàng, vui lòng đợi chút.", { type: "warning" });
                return;
            }
            const canvas = document.createElement("canvas");
            canvas.width  = vid.videoWidth;
            canvas.height = vid.videoHeight;
            canvas.getContext("2d").drawImage(vid, 0, 0, canvas.width, canvas.height);
            // xuất PNG gốc, sau crop sẽ chuyển sang JPEG
            dataURL = canvas.toDataURL("image/png");
        }

        this.state.capturedURL = dataURL;
        this.state.showCropper = true;
        this.videoRef.el.pause();
    }

    /* Nhận ảnh crop, gửi backend */
    async _sendCropped(dataURL) {
        this.state.showCropper = false;
        this.state.busy        = true;
        this.state.previewURL  = dataURL;
        this.state.result      = "";

        // tách phần base64
        const base64 = dataURL.split(",", 2)[1] || "";
        try {
            const res = await this.rpc("/camera/upload", {
                image:  base64,
                prompt: this.props.prompt,
            });
            if (res.status === "ok") {
                this.state.result = res.answer;
            } else {
                this.notification.add(res.message || "Lỗi không xác định.", { type: "danger" });
                this.state.result = "Lỗi: " + (res.message || "unknown");
            }
        } catch (e) {
            this.notification.add("Không kết nối được AI-server: " + e.message, { type: "danger" });
            this.state.result = "RPC error: " + e.message;
        } finally {
            this.state.busy = false;
            this.videoRef.el.play();
        }
    }

    close() {
        this._stopCamera();
        this.props.onResult?.(null, null, true);
    }
}
