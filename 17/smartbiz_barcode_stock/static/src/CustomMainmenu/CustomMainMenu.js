/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
  useEnv,
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";

import { MainMenu } from "@smartbiz_barcode/main_menu";

export default class CustomMainMenu extends MainMenu {
  static template = "CustomMainMenu";
  
  setup() {
    this.actionService = useService("action");
    this.dialogService = useService("dialog");
    this.home = useService("home_menu");
    this.notificationService = useService("notification");
    this.rpc = useService("rpc");
    console.log('oke');
  }

}
