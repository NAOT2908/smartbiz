/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onRendered, useRef } from "@odoo/owl";
import { FormLabel } from "@web/views/form/form_label";




patch(FormController.prototype,{
    setup(){
        super.setup();
        onMounted(()=>{
            let cpSaveButton = this.rootRef.el.querySelector('.o_form_button_save')
            let cpDiscardButton = this.rootRef.el.querySelector('.o_form_button_cancel')

            if(this.rootRef.el && this.props.resModel.startsWith('ks_dashboard_ninja.')){
                if(cpSaveButton)    cpSaveButton.innerHTML = "Save"
                if(cpDiscardButton) cpDiscardButton.innerHTML = "Discard"

                let cpCogMenu = this.rootRef.el.querySelector('.o_cp_action_menus')
                if(this.props.resModel === 'ks_dashboard_ninja.item' && cpCogMenu)  cpCogMenu.remove()
            }
        });

        onRendered(() => {
            if(this.props.resModel === 'ks_dashboard_ninja.item'){
                this.env.config.setDisplayName(this.displayName() === 'New' ? 'Create New Chart' : this.displayName());
            }
        });
    }
});


patch(FormLabel.prototype,{
    setup(){
        this.ksRootRef = useRef("ksRootRef");
        onMounted(()=>{
            let tooltip = this.ksRootRef.el?.querySelector('.text-info')
            if(tooltip && (this.env.model?.config?.resModel.startsWith('ks_dashboard_ninja.' ||
                                    this.env.services.action?.currentController?.action?.tag === 'ks_dashboard_ninja')))
                    tooltip.innerHTML = '<i class="fa fa-exclamation-circle" aria-hidden="true"></i>'
        });
    }

});



