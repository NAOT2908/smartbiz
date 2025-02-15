/** @odoo-module **/
import { Component, useState } from '@odoo/owl';

export class Selector extends Component {
    setup() {
        this.state = useState({
            searchQuery: "",
            selectedRecords: [],
            quantity:false,
            records:this.props.records,
            selectedRecord: 0,
            
        });
        for (var r of this.state.records){
            r.quantity_remain = 0
        }

        // uibuilder.onChange('msg', msg => {
        //     if (msg) {
        //         if(msg.materialList && this.props.title == 'Nguyên liệu đầu vào' )
        //         {
        //             this.state.records = msg.materialList.filter(x=>x.production_order == msg.selectedProductionOrder)
        //         }
        //         if (msg.scaleData && this.props.title === 'Nguyên liệu còn lại') {
        //             var record = this.state.records.find(x=>x.id == this.state.selectedRecord)
        //             if(record)
        //             {
        //                 record.quantity_remain = msg.scaleData.kg
        //             }
        //         }
        //     }
        // })
    }

    get filteredRecords() {
        const searchLower = this.state.searchQuery.toLowerCase();
        return this.state.records.filter(record => 
            (record.display_name ? record.display_name.toLowerCase() : record.name? record.name.toLowerCase():record.product_name.toLowerCase()).includes(searchLower)
        );
    }
    

    selectRecord(recordId) {
        const index = this.state.selectedRecords.indexOf(recordId);
        if (this.props.multiSelect) {
            if (index > -1) {
                this.state.selectedRecords.splice(index, 1); // Remove if already selected
            } else {
                this.state.selectedRecords.push(recordId); // Add to selection
            }
        } else {
            if(this.props.title == "Chọn sản phẩm")
            {
                var record = this.props.records.find(x=>x.id ==recordId)
                var data = {
                    product_id: recordId,
                    quantity: this.state.quantity,
                    display_name:record.display_name,
                }
                this.props.closeSelector(data);
            }
            else{
                if(this.state.selectedRecord == recordId)
                    this.state.selectedRecord = 0
                else
                    this.state.selectedRecord = recordId
            }
            
        }
    }
    

    confirmSelection() {
        if(this.props.title == "Nguyên liệu còn lại"){
            this.props.closeSelector(this.state.records,'Nguyên liệu còn lại');
        }
        else if(this.props.title == "Chọn vị trí nguồn"){
            this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn vị trí nguồn');
        }
        else if(this.props.title == "Chọn vị trí đích"){
            this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn vị trí đích');
        }
        else if(this.props.title == "Chọn số Lô/Sê-ri"){
            this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn số Lô/Sê-ri');
        }
        else if(this.props.title == "Chọn kiện đích"){
            this.props.closeSelector(this.state.records.find(x=>x.id == this.state.selectedRecord),'Chọn kiện đích');
        }
        else
        {
            this.props.closeSelector(this.state.selectedRecords);
        } 
        
        
    }

    cancelSelection() {
        this.props.closeSelector(false);
    }
    createNew() {
        this.props.closeSelector(this.state.searchQuery,'Tạo Lô/Sê-ri');
    }
}
Selector.props = ['records', 'multiSelect?', 'closeSelector','title'];
Selector.template = 'Selector'