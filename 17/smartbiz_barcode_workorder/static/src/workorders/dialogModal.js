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
    static template = "DialogModal";
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
    getInputValue(field){
        const val = this.state.form[field.name];
        if (field.type === 'datetime-local' && val){
            return utcToLocalInput(val, this.tz);                   // UTC ➜ local
        }
        if (field.type === "select") {
            return (val === null || val === undefined) ? "" : String(val);
        }
        return val ?? "";
    }

    /* ------ ghi vào form khi người dùng nhập ------ */
    _onInput(name, ev){
        let val = ev.target.value;
        if (ev.target.type === 'datetime-local' && val){
            val = localInputToUtc(val, this.tz);                    // local ➜ UTC
        }
            /* ép kiểu number nếu input là số */
        else if (ev.target.type === "number" && val !== "") {
            val = Number(val);                 // parseFloat/parseInt đều OK
        }

        /* cũng ép kiểu nếu <select> trả về id dạng chuỗi '12' */
        else if (ev.target.tagName === "SELECT" && /^\d+$/.test(val)) {
            val = Number(val);
        }
        this.state.form[name] = val;
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