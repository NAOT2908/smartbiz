/** @odoo-module **/

import { WebClient } from "@web/webclient/webclient";
import { useService } from "@web/core/utils/hooks";
import { SmartBizNavBar } from "./navbar/navbar";

export class WebClientSmartBiz extends WebClient {
    setup() {
        super.setup();
        this.hm = useService("home_menu");
    }
    _loadDefaultApp() {
        return this.hm.toggle(true);
    }
}
WebClientSmartBiz.components = { ...WebClient.components, NavBar: SmartBizNavBar };
