/** @odoo-module **/
import { registry } from "@web/core/registry";
import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/webclient/barcode/barcode_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { View } from "@web/views/view";
// import { ManualBarcodeScanner } from "@smartbiz_barcode/Components/manual_barcode";
import { url } from "@web/core/utils/urls";
import { utils as uiUtils } from "@web/core/ui/ui_service";


export class DialogModal extends Component {
  static template = "DialogModal";

  static props = ["title","records","closeModal"]
  setup() {
    this.rpc = useService("rpc");
    this.notification = useService("notification");

    this.state = useState({
      selectedRecord: false
    });
  }

  selectRecord(id){
    this.state.selectedRecord = id
  }

  async confirmEdit() {
    
    let data = this.props.records.find(x=>x.id == this.state.selectedRecord)
    console.log({data,records:this.props.records})
    this.props.closeModal('selectWorkcenter',data); // gọi callback của cha để ẩn form
   
  }

  cancel() {
    this.props.closeModal('selectWorkcenter',false);
  }
}
