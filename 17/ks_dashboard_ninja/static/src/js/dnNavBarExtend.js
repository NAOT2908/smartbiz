/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { MenuDropdown } from '@web/webclient/navbar/navbar';
import { onWillStart, onWillUnmount, onWillRender, useEffect, onMounted, useRef, onPatched } from "@odoo/owl";
import { NavBar } from "@web/webclient/navbar/navbar";
import { ActionContainer } from "@web/webclient/actions/action_container";


export function dnNavBarAddClasses(){
    $('body').addClass('ks_body_class');
}



export function dnNavBarRemoveClasses(){
    $('body').removeClass('ks_body_class');
}



patch(NavBar.prototype,{
    async adapt(){
        if(this.currentApp?.xmlid === "ks_dashboard_ninja.board_menu_root" || this.actionService?.currentController?.action.tag === 'ks_dashboard_ninja'){
            if(!$('body').hasClass('ks_body_class'))
                dnNavBarAddClasses();
        }
        else{
            if($('body').hasClass('ks_body_class'))
                dnNavBarRemoveClasses();
        }
        return super.adapt();
    },

});

patch(ActionContainer.prototype,{
    setup(){
        super.setup();
        onPatched( () => {
            if(this?.env.services.menu.getCurrentApp?.()?.xmlid === "ks_dashboard_ninja.board_menu_root" || this.info?.componentProps?.action?.tag === 'ks_dashboard_ninja'){
                if(!$('body').hasClass('ks_body_class'))
                    dnNavBarAddClasses();
            }
            else if(this?.env.services.menu.getCurrentApp?.()?.xmlid !== "ks_dashboard_ninja.board_menu_root" || this.info?.componentProps?.action?.tag !== 'ks_dashboard_ninja'){
                if($('body').hasClass('ks_body_class'))
                    dnNavBarRemoveClasses();
            }
        });
    },

});




