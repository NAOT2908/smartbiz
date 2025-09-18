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


/*-----------------------------------------------------------
  Component EditPackageForm
------------------------------------------------------------*/
export class EditPackage extends Component {
  static template = "EditPackage";
  // props:
  //  - packageInfo
  //  - finishMoves
  //  - closeModal (callback để cha đóng form)
  static props = ["packageInfo","unpacked_move_lines","closeModal"]
  setup() {
    this.rpc = useService("rpc");
    this.notification = useService("notification");

    this.state = useState({
      editedQuantities: {}
    });
  }

  onQuantityChange(productId, ev) {
    this.state.editedQuantities[productId] = parseFloat(ev.target.value) || 0;
  }

  async confirmEdit() {
    const updateData = [];
    for (const line of this.props.unpacked_move_lines) {
      console.log({line})
      if(line.modified_quantity > 0 && line.current_quantity != line.modified_quantity && line.package_name != '' ){
        updateData.push({ id: line.id, quantity: line.modified_quantity,result_package_id:this.props.packageInfo.id });
      }else if(line.modified_quantity > 0 && line.package_name == '' ){
        updateData.push({ id: line.id, quantity: line.modified_quantity,result_package_id:this.props.packageInfo.id });
      }
      else if(line.modified_quantity <= 0 && line.package_name != ''){
        updateData.push({ id: line.id, quantity: 0,result_package_id:false });
      }
      
    }
  
    this.props.closeModal('editPackage',updateData); // gọi callback của cha để ẩn form
   
  }

  cancel() {
    this.props.closeModal('editPackage',false);
  }
}

/*-----------------------------------------------------------
  Component CreatePackageForm
------------------------------------------------------------*/
export class CreatePackages extends Component {
  static template = "CreatePackages";
  static props = ["orderInfo","unpacked_products","closeModal"]
  // props:
  // - products
  // - closeForm (callback)
  setup() {
    this.rpc = useService("rpc");
    this.orm = useService("orm");
    this.notification = useService("notification");

    this.state = useState({
      lot_name: '',    // Số lô chung dùng cho tất cả sản phẩm có tracking
      createPackageQty: false,   // Checkbox "Tạo Package mới?"
      packageQty: 0,             // Số pack cần tạo nếu chọn tạo mới
      resultPackages: [],        // Danh sách package đích (nếu có)
      productData: {}            // Dữ liệu riêng của từng sản phẩm (chỉ số lượng trên một pack)


      
    });
    this.state.lot_name = this.props.orderInfo[0].lot_name
    //console.log({productData:this.state.productData,lot_name:this.props})
    if (this.props.unpacked_products) {
      this.props.unpacked_products.forEach(prod => {
         
          this.state.productData[prod.move_id] = {
             lot_name: '',
             qtyPerPackage: 0,
          };
          
      });
    }
  }
  
   // Hàm làm tròn số đến 2 chữ số thập phân
   roundToTwo(num) {
    return Math.round(num * 100) / 100;
  }
  async createMoveLines(move, qtyPerPackage, packageQty, lotName) {
    const lines = [];
    // Lấy số lượng cần cấp phát từ move (available_quantity)
    let remainingQty = move.available_quantity;
  
    // Kiểm tra điều kiện hợp lệ: số lượng trên một pack và số thùng cần đóng phải > 0
    if (qtyPerPackage <= 0 || packageQty <= 0 || remainingQty <= 0) {
      console.warn("Số lượng trên một pack, số thùng cần đóng hoặc số lượng cần cấp phát không hợp lệ!");
      return [];
    }
  
    // Tạo hoặc lấy danh sách các package chung (global packages) được dùng chung cho tất cả các sản phẩm
    this.state.globalPackages = this.state.globalPackages || [];
  
    // Đảm bảo danh sách globalPackages có đủ số lượng theo packageQty
    for (let i = 0; i < packageQty; i++) {
      if (!this.state.globalPackages[i]) {
        let packageName = this.state.scannedPackageName || "Package_Mặc_Định";
        if (this.state.createPackageQty) {
          // Tạo package mới nếu chọn tạo mới
          let data = await this.orm.call("mrp.production", "create_package", [null, ''], {});
          if (!data || !data.id) {
            console.error("Lỗi khi tạo package!");
            return [];
          }
          this.state.globalPackages[i] = { id: data.id, name: data.name };
        } else {
          // Nếu không tạo mới, cố gắng lấy từ resultPackages
          if (this.state.resultPackages && this.state.resultPackages[i]) {
            this.state.globalPackages[i] = this.state.resultPackages[i];
          } else {
            // Nếu chưa có, tạo mới với tên quét được hoặc mặc định
            let data = await this.orm.call("mrp.production", "create_package", [null, packageName], {});
            if (!data || !data.id) {
              console.error("Lỗi khi tạo package!");
              return [];
            }
            this.state.globalPackages[i] = { id: data.id, name: data.name };
            this.state.resultPackages = this.state.resultPackages || [];
            this.state.resultPackages.push({ id: data.id, name: data.name });
          }
        }
      }
    }
  
    // Tạo move line cho move cho mỗi package trong globalPackages
    for (let i = 0; i < packageQty && remainingQty > 0; i++) {
      // Nếu remainingQty chưa đủ cho qtyPerPackage thì dùng remainingQty
      let quantityToAssign = this.roundToTwo(Math.min(qtyPerPackage, remainingQty));
      if (quantityToAssign <= 0) {
        console.warn("Không có số lượng hợp lệ để cấp phát!");
        break;
      }
  
      let globalPackage = this.state.globalPackages[i];
  
      let line = {
        id: 0,
        move_id: move.move_id, // Chú ý: dùng đúng key của move (có thể là move.id)
        product_id: move.product_id,
        product_name: move.product_name,
        location_id: move.location_id,
        location_name: move.location_name,
        location_dest_id: move.location_dest_id,
        location_dest_name: move.location_dest_name,
        lot_name: lotName, // Số lô chung áp dụng cho tất cả các move line
        lot_id: null,
        product_uom_id: move.product_uom_id,
        package_id: null,
        package_name: null,
        result_package_id: globalPackage.id,
        result_package_name: globalPackage.name,
        product_uom_qty: move.product_uom_qty,
        quantity: quantityToAssign,
        quantity_done: quantityToAssign,
        quantity_need: this.roundToTwo(move.product_uom_qty - move.quantity - quantityToAssign),
        product_uom: move.product_uom,
        product_tracking: move.product_tracking,
        picking_type_code: move.picking_type_code,
        state: "draft",
        package: true,
        picking_id: move.picking_id,
      };
  
      lines.push(line);
      remainingQty -= quantityToAssign;
    }
  
    console.log({ move });
    console.log("Danh sách move lines sau khi tạo:", lines);
    return lines;
  }
  

  /**
   * Hàm xử lý barcode cho chức năng đóng gói hàng loạt.
   * Khi quét barcode, nếu không tìm thấy thông tin phù hợp, sẽ tạo mới package với barcode đó.
   * Nếu barcode hợp lệ và thuộc loại packages, sẽ thêm package vào danh sách resultPackages (nếu chưa tồn tại).
   * @param {string} barcode - Giá trị barcode quét được
   */
  async processBarcode(barcode) {
    // Giả sử this.env.model.parseBarcodeMrp đã được thiết lập sẵn trong môi trường Owl
    let barcodeData = await this.env.model.parseBarcodeMrp(barcode, false, false, false);
    console.log(barcodeData);
    if (!barcodeData.match) {
      let data = await this.orm.call("mrp.production", "create_package", [null, barcode], {});
      if (!data || !data.id) {
        console.error("Lỗi khi tạo package!");
        return;
      }
      let newPackage = { id: data.id, name: data.name };
      if (this.props.title === "Đóng Packages hàng loạt") {
        if (!this.state.createPackageQty) {
          this.state.resultPackages.push(newPackage);
        }
      }
      console.log("Package mới đã tạo:", newPackage);
      return;
    }

    if (barcodeData.barcodeType !== "packages") {
      const message = _t(`Barcode: ${barcode} không phải là Packages!`);
      this.notification.add(message, { type: "warning" });
      return;
    }

    let packageInfo = {
      id: barcodeData.record.id,
      name: barcodeData.barcode
    };

   
    if (!this.state.createPackageQty) {
      let findpack = this.state.resultPackages.find((x) => x.id === packageInfo.id);
      if (!findpack) {
        this.state.resultPackages.push(packageInfo);
      } else {
        const message = _t(`Pack ${packageInfo.name} đã được quét`);
        this.notification.add(message, { type: "warning" });
      }
    }
    
  }

  /**
   * Hàm được gọi khi bấm nút "Xác nhận".
   * Lặp qua từng sản phẩm trong unpacked_products, tạo ra move lines và gửi về component cha thông qua closeModal.
   */
  async confirmCreate() {
    let allLines = [];
    for (const prod of this.props.unpacked_products) {
      let qtyPerPackage = parseFloat(this.state.productData[prod.move_id].qtyPerPackage) || 0;
      let packageQty = parseFloat(this.state.packageQty) || 0;
      let lot_name = this.state.productData[prod.move_id].lot_name || this.state.lot_name
      let moveLines = await this.createMoveLines(prod, qtyPerPackage, packageQty, lot_name);
      allLines = allLines.concat(moveLines);
    }
    this.props.closeModal('createPackages', allLines);
  }

  cancel() {
    this.props.closeModal('createPackages', false);
  }

}


/*-----------------------------------------------------------
  Component Package: Hiển thị danh sách package và thao tác (sửa, in, xóa, tạo mới)
------------------------------------------------------------*/
export class Packages extends Component {
  static template = "Package";
  static props = ["updateData","data","showModal"];
  

  setup() {
    this.state = useState({
      selectedItem: 0,
      showEditPackageForm: false,   // Biến kiểm soát hiển thị form sửa gói
      showCreatePackageForm: false, // Biến kiểm soát hiển thị form tạo gói
      packageInfo: {},
      finishMoves: [],
      products: [],  // Dữ liệu sản phẩm chưa đóng gói cho CreatePackageForm
    });
    this.rpc = useService("rpc");
    this.notification = useService("notification");
    this.orm = useService("orm");
    this.dialog = useService("dialog");
    this.action = useService("action");
  }

  select(id) {
    this.state.selectedItem = id;
  }
  footerClass() {
    return "s_footer";
  }

  editPackage(data) {
    this.props.showModal('editPackage',data)
  }

  createPackage() {
    this.props.showModal('createPackages',false)
  }

  async printPackage(data) {
    let values =  await this.orm.call(
      "mrp.production",
      "print_package",
      [, this.production_id,data.id],
      {}
    );
    // this.updateData(values)
  }

  async deletePackage(data) {
    let values =  await this.orm.call(
      "mrp.production",
      "delete_package",
      [, this.production_id,data.id],
      {}
    );
    this.updateData(values)
  }

  lineClass(line) {
    let cl = "s_move-line";
    if (line.id === this.state.selectedItem) {
      cl += " s_selectedItem";
    }
    if (line.picked) {
      cl += " s_move_line_done";
    }
    return cl;
  }

  
}
