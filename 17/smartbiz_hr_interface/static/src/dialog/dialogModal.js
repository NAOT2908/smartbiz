/** @odoo-module **/
import { Component, useState, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const { DateTime } = luxon; // Thư viện Luxon để xử lý thời gian

/* ───────── helpers ───────── */
function utcToLocalInput(utcString, tz) {
    // utcString: "YYYY-MM-DD HH:mm:ss" (từ Odoo) hoặc ISO
    return DateTime
        .fromISO(utcString.replace(" ", "T"), { zone: "utc" })   // coi là UTC
        .setZone(tz)                                             // đổi sang TZ người dùng
        .toFormat("yyyy-LL-dd'T'HH:mm");                         // cho <input>
}

function localInputToUtc(localString, tz) {
    // localString: "YYYY-MM-DDTHH:mm" (người dùng nhập)
    return DateTime
        .fromFormat(localString, "yyyy-LL-dd'T'HH:mm", { zone: tz })
        .toUTC()
        .toFormat("yyyy-LL-dd HH:mm:ss");                        // trả về cho Odoo
}

export class DialogModal extends Component {
    static template = "DialogModals";
    static props    = ["title","action", "records", "fields", "closeModal", "defaultValues"];

    setup() {
        this.notification = useService("notification");
        this.userSrv      = useService("user");                      // lấy tz
        this.tz           = this.userSrv.context.tz || DateTime.local().zoneName;
        
        
        /* ==== LỌC CHỈ CÁC TRƯỜNG ĐANG CÓ TRONG props.fields ==== */
        const defaults = this.props.defaultValues || {};
        const formInit = (this.props.fields || []).reduce((acc, f) => {
            acc[f.name] = defaults[f.name] ?? "";      // điền "" nếu không có
            return acc;
        }, {});

        // bảo đảm luôn có id nếu defaultValues cung cấp
        if ("id" in defaults) {
            formInit.id = defaults.id;
        }
        this.state = useState({
            selectedRecord: null,
            form: formInit,  
        });
        console.log("DialogModal", this.state.form);
        
    }
    // selector (workcenter)
    selectRecord(id){this.state.selectedRecord = id;}

    /* ------ giá trị hiển thị lên input ------ */
    getInputValue(field) {
    const val = this.state.form[field.name];
    
    if ((field.type === 'datetime-local' || field.type === 'date') && val) {
        const dt = DateTime.fromISO(val.replace(" ", "T"), { zone: "utc" }).setZone(this.tz);
        return field.type === 'date'
            ? dt.toFormat("yyyy-LL-dd")            // chỉ ngày
            : dt.toFormat("yyyy-LL-dd'T'HH:mm");   // datetime-local
    }

    if (field.type === "select") {
        return (val === null || val === undefined) ? "" : String(val);
    }
    return val ?? "";
}


    /* ------ ghi vào form khi người dùng nhập ------ */
    _onInput(name, ev) {
    let val = ev.target.value;

    if ((ev.target.type === 'datetime-local' || ev.target.type === 'date') && val) {
        const fmt = ev.target.type === 'date'
            ? "yyyy-LL-dd"
            : "yyyy-LL-dd'T'HH:mm";

        val = DateTime.fromFormat(val, fmt, { zone: this.tz })
                      .toUTC()
                      .toFormat("yyyy-LL-dd HH:mm:ss");
    } else if (ev.target.type === "number" && val !== "") {
        val = Number(val);
    } else if (ev.target.tagName === "SELECT" && /^\d+$/.test(val)) {
        val = Number(val);
    }

    this.state.form[name] = val;
    this._onAfterInput(name);
}

    _onAfterInput(changedField) {
    const form = this.state.form;

    // Tính duration (chỉ khi đang ở màn overtime)
    if ('start_date' in form && 'end_date' in form && form.start_date && form.end_date) {
        const start = DateTime.fromFormat(form.start_date, "yyyy-LL-dd HH:mm:ss", { zone: "utc" });
        const end   = DateTime.fromFormat(form.end_date, "yyyy-LL-dd HH:mm:ss", { zone: "utc" });
        const duration = end.diff(start, "hours").hours;

        // chỉ update nếu hợp lệ
        if (!isNaN(duration) && duration >= 0) {
            form.duration = Math.round(duration * 100) / 100;
        } else {
            form.duration = 0;
        }
    }

    // Tính number_of_days (chỉ khi ở leave_data)
    if ('date_from' in form && 'date_to' in form && form.date_from && form.date_to) {
        const from = DateTime.fromFormat(form.date_from, "yyyy-LL-dd HH:mm:ss", { zone: "utc" });
        const to   = DateTime.fromFormat(form.date_to, "yyyy-LL-dd HH:mm:ss", { zone: "utc" });

        const days = to.diff(from, "days").days;
        if (!isNaN(days) && days >= 0) {
            form.number_of_days = Math.round((days + 1) * 100) / 100;  // +1 nếu tính cả 2 ngày
        } else {
            form.number_of_days = 0;
        }
    }
}


    confirmEdit(){
        // form mode
        if(this.props.fields){
            const invalid = this.props.fields.find(f => f.required && !this.state.form[f.name]);
            if (invalid) {
                this.notification.add(`Trường "${invalid.label}" là bắt buộc`, { type: 'danger' });
                return;
            }
            this.props.closeModal(this.props.title, this.state.form,this.props.action);
            return;
        }
        // selector mode
        const rec = this.props.records.find(r=>r.id===this.state.selectedRecord);
        this.props.closeModal(this.props.title, rec || false);
    }
    cancel(){this.props.closeModal(this.props.title,false);}  
}