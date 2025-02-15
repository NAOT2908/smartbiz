/** @odoo-module **/

import { FormController } from '@web/views/form/form_controller';
import { patch } from '@web/core/utils/patch';
import { onMounted, onRendered, onPatched} from "@odoo/owl";

patch(FormController.prototype,  {  
    setup() {
        super.setup(...arguments);  
        this._updateButtonsVisibility = this._updateButtonsVisibility.bind(this);
        onMounted(() => {         
            this._updateButtonsVisibility();           
        });
        onPatched(() => {            
            this._updateButtonsVisibility(); 
        });
    },

    _updateButtonsVisibility(buttonsInfo) {
        if (!buttonsInfo) {
            const record = this.model.root.data;
            if (record && record.button_permissions) {
                buttonsInfo = JSON.parse(record.button_permissions);
            }
        }
        if (buttonsInfo) {
            for (const [functionName, visible] of Object.entries(buttonsInfo)) {
                const button = this.rootRef.el.querySelector(`button[name="${functionName}"]`);
                if (button) {
                    button.style.display = visible ? '' : 'none';
                }
            }
        }
    },
});
