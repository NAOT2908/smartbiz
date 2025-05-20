/** @odoo-module **/

import { LoadingIndicator } from "@web/webclient/loading_indicator/loading_indicator";
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";
import { BlockUI } from "@web/core/ui/block_ui";
import { useEffect, useRef, xml } from "@odoo/owl";


patch(LoadingIndicator.prototype, {
  setup() {
    super.setup();
  },
      requestCall({ detail }) {
        if (detail.settings.silent) {
            return;
        }
        if (this.state.count === 0) {
            browser.clearTimeout(this.startShowTimer);
            this.startShowTimer = browser.setTimeout(() => {
                if (this.state.count) {
                    this.state.show = true;
                    let ks_active_el = $(this.env.services.ui.activeElement).find('.chat-ai-box').length
                    if((!ks_active_el) &&( this.env.services.action.currentController?.action?.tag === 'dashboard_ninja'
                                        || this.env.services.action.currentController?.action?.tag === 'ks_dashboard_ninja'
                                        || this.env.services.action.currentController?.action?.xml_id === 'ks_dashboard_ninja.layout_tree_action_window'
                                        || this.env.services.action.currentController?.action?.xml_id === 'ks_dashboard_ninja.board_form_tree_action_window')){
                        this.blockUITimer = browser.setTimeout(() => {
                                this.shouldUnblock = true;
                                this.uiService.block();
                            }, 3000);
                    }
                }
            }, 250);
        }
        this.rpcIds.add(detail.data.id);
        this.state.count++;
    },

});

patch(BlockUI.prototype, {
    setup(){
        super.setup();
        this.menuService = useService('menu');

        useEffect( () => {
            let spinnerImg = document.querySelector('.o_blockUI .o_spinner img');
            if(spinnerImg && spinnerImg.src){
                spinnerImg.src = "/web/static/img/spin.svg"
            }
            let currentApp = this.menuService?.getCurrentApp();
            if (currentApp && currentApp.xmlid === "ks_dashboard_ninja.board_menu_root"){
                if(spinnerImg && spinnerImg.src){
                    spinnerImg.src = "/ks_dashboard_ninja/static/images/loader.gif"
                }
            }
        });
    }
});

