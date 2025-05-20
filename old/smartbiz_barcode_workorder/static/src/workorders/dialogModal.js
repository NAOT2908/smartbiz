/** @odoo-module **/
import { Component, useState, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class DialogModal extends Component {
    static template = "DialogModal";
    static props    = ["title","action", "records", "fields", "closeModal"];

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            selectedRecord: null,
            form: {},
        });
    }
    // selector (workcenter)
    selectRecord(id){this.state.selectedRecord = id;}

    // form input
    _onInput(name, ev){this.state.form[name] = ev.target.value;}

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