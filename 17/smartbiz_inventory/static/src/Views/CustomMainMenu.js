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

import { patch } from "@web/core/utils/patch";
import { MainMenu } from "@smartbiz_barcode/main_menu";

patch(MainMenu.prototype, {
  setup() {
    super.setup?.();
    this.actionService = useService("action");
  },

  async openInventory() {
    await this.actionService.doAction(
      "smartbiz_inventory.adjustment_inventory_action"
    );
  },
});

export default class CustomInventory extends MainMenu {
  static template = "CustomInventory";

  setup() {
    super.setup();
    this.actionService = useService("action");
    this.dialogService = useService("dialog");
    this.home = useService("home_menu");
    this.notificationService = useService("notification");
    this.rpc = useService("rpc");
    this.env = useEnv();
    this.state = useState({
      showBarcodeStock: false,
      showBarcodeProduction: false,
      showBarcodeWorkorder: false,
    });
  }
}
