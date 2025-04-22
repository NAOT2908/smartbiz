/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { COMMANDS } from "@barcodes/barcode_handlers";
import { registry } from "@web/core/registry";

import {
  Component,
  EventBus,
  onPatched,
  onWillStart,
  useState,
  useSubEnv,
  xml,
  useEnv,
  onWillUnmount,
  onMounted,
  useRef
} from "@odoo/owl";
import { useService, useBus, useHistory } from "@web/core/utils/hooks";
import { loadJS } from '@web/core/assets';


// Các component khác
class Production_Orders extends Component {
    static template = "Production_Orders";
}

class Machines extends Component {
    static template = "Machines";
}

class QualityIssues extends Component {
    static template = "QualityIssues";
}

class Materials extends Component {
    static template = "Materials";
}

class Workers extends Component {
    static template = "Workers";
}

// Component cho biểu đồ
class ChartComponent extends Component {
    static template = "ChartComponent";

    setup() {
        this.chartConfig = {
            type: this.props.type,
            data: this.props.data,
            options: this.props.options
        };
        this.canvas = useRef("canvas");
        this.chart = undefined;
        onWillStart(async () => {
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js")
            await loadJS("https://cdnjs.cloudflare.com/ajax/libs/jspdf/1.5.3/jspdf.min.js")
            await loadJS("https://cdn.jsdelivr.net/npm/exceljs@4.4.0/dist/exceljs.min.js")
        })
        onMounted(() => {
            this.ctx = this.canvas.el.getContext('2d');
            this.chart = new Chart(this.ctx, this.chartConfig);   
        });
        onPatched(()=>{
            this.chart.update();
        })
    }
}

// Component chính của dashboard
export class Dashboard extends Component {
    static components = { Production_Orders, Machines, QualityIssues, Materials, Workers, ChartComponent };
    static template = "Dashboard";
    static props = ["dashboardData", "faultyData", "steps"]

    setup() {
        this.state = useState({
            chartColors: [],
            chartBorderColors: [],
            data : [],
            stage: '',
            faultyData: this.props.faultyData,
            dashboardData: this.props.dashboardData,
            steps: this.props.steps,
            colorMap: {},
            theme: 'light',
            productionOrders: [
                { id: 1, name: 'Order 1', status: 'In Progress', progress: 50, dueDate: '2024-06-01' },
                { id: 2, name: 'Order 2', status: 'Completed', progress: 100, dueDate: '2024-05-15' },
                { id: 3, name: 'Order 3', status: 'Delayed', progress: 30, dueDate: '2024-06-10' },
            ],
            machines: [
                { id: 1, name: 'Machine 1', status: 'Operating', lastMaintenance: '2024-05-01' },
                { id: 2, name: 'Machine 2', status: 'Stopped', lastMaintenance: '2024-04-20' },
                { id: 3, name: 'Machine 3', status: 'Maintenance Required', lastMaintenance: '2024-04-10' },
            ],
            qualityIssues: [
                { id: 1, product: 'Product A', issue: 'Defect', resolution: 'Reworked', time: '2024-05-18' },
                { id: 2, product: 'Product B', issue: 'Damage', resolution: 'Scrapped', time: '2024-05-17' },
            ],
            materials: [
                { id: 1, name: 'Material 1', quantity: 100, status: 'Sufficient' },
                { id: 2, name: 'Material 2', quantity: 20, status: 'Low' },
            ],
            workers: [
                { id: 1, name: 'Worker 1', hoursWorked: 40 },
                { id: 2, name: 'Worker 2', hoursWorked: 35 },
            ],
            charts: {
                productionProgress: {
                    type: 'line',
                    data: {
                        labels: ['January', 'February', 'March', 'April', 'May', 'June', 'July'],
                        datasets: [{
                            label: 'Production Progress',
                            data: [65, 59, 80, 81, 56, 55, 40],
                            borderColor: 'rgba(75, 192, 192, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        scales: {
                            x: {
                                title: {
                                    color: 'red',
                                    display: true,
                                    text: 'Lệnh sản xuất'
                                },
                                ticks: {
                                    color: 'blue'
                                }
                            },
                            y: {
                                beginAtZero: true
                            }
                        }
                    }
                },
                qualityIssues: {
                    type: 'bar',
                    data: {
                        labels: ['Product A', 'Product B', 'Product C'],
                        datasets: [{
                            label: 'Quality Issues',
                            data: [12, 19, 3],
                            backgroundColor: [
                                'rgba(255, 99, 132, 0.2)',
                                'rgba(54, 162, 235, 0.2)',
                                'rgba(75, 192, 192, 0.2)'
                            ],
                            borderColor: [
                                'rgba(255, 99, 132, 1)',
                                'rgba(54, 162, 235, 1)',
                                'rgba(75, 192, 192, 1)'
                            ],
                            borderWidth: 2
                        }]
                    },
                    options: {
                        scales: {
                            x: {
                                title: {
                                    color: 'red',
                                    display: true,
                                    text: 'Lệnh sản xuất'
                                },
                                ticks: {
                                    color: 'blue',
                                }
                            },
                            y: {
                                beginAtZero: true
                            }
                        }
                    }
                },
                doughnut: {
                    type: 'doughnut',
                    data: {
                        labels: ['Product A', 'Product B', 'Product C'],
                        datasets: [{
                            label: 'Quality Issues',
                            data: [12, 19, 3],
                            backgroundColor: [
                                'rgba(255, 99, 132, 0.2)',
                                'rgba(54, 162, 235, 0.2)',
                                'rgba(75, 192, 192, 0.2)'
                            ],
                            borderColor: [
                                'rgba(255, 99, 132, 1)',
                                'rgba(54, 162, 235, 1)',
                                'rgba(75, 192, 192, 1)'
                            ],
                            hoverOffset: 4
                        }]
                    },

                    options: {
                    }
                },
                polarArea: {
                    type: 'polarArea',
                    data: {
                        labels: ['Product A', 'Product B', 'Product C'],
                        datasets: [{
                            label: 'Quality Issues',
                            data: [12, 19, 3],
                            backgroundColor: [
                                'rgb(255, 99, 132)',
                                'rgb(75, 192, 192)',
                                'rgb(255, 205, 86)',
                                'rgb(201, 203, 207)',
                                'rgb(54, 162, 235)'
                            ]
                        }]
                    },
                    options: {
                        
                    }
                }
            }
        });
        console.log(this.props.steps)
        onMounted(() => {
            //setInterval(() => this.updateProductionProgress(), 3000);    
            this.updateCharts();
        });
    }

    toggleTheme = () => {
        this.state.theme = this.state.theme === 'light' ? 'dark' : 'light';
    };
    getRandomColor() {
        const r = Math.floor(Math.random() * 255);
        const g = Math.floor(Math.random() * 255);
        const b = Math.floor(Math.random() * 255);
        const a = 0.5; // alpha cho backgroundColor (độ trong suốt)
        return `rgba(${r}, ${g}, ${b}, ${a})`;
    }
    getRandomBorderColor() {
        const r = Math.floor(Math.random() * 255);
        const g = Math.floor(Math.random() * 255);
        const b = Math.floor(Math.random() * 255);
        const a = 1; // alpha cho borderColor (không trong suốt)
        return `rgba(${r}, ${g}, ${b}, ${a})`;
    }
    // Hàm cập nhật giá trị ngẫu nhiên cho dữ liệu 
    updateProductionProgress(){
        var newData = [];
        for (var i = 0; i < this.state.charts.productionProgress.data.datasets[0].data.length; i++) {
            newData.push(Math.floor(Math.random() * 100)); // giá trị ngẫu nhiên từ 0 đến 99
        }
        this.state.charts.productionProgress.data.datasets[0].data = newData;
        var newData = [];
        for (var i = 0; i < this.state.charts.qualityIssues.data.datasets[0].data.length; i++) {
            newData.push(Math.floor(Math.random() * 100)); // giá trị ngẫu nhiên từ 0 đến 99
        }
        this.state.charts.qualityIssues.data.datasets[0].data = newData;
    }
    updateChartOnChange(event) {
        this.state.stage = event.target.value; // Giá trị đã chọn
        console.log(this.state.stage, this.state.dashboardData);
        if (this.state.stage) {
            this.updateCharts(this.state.stage);
        }
    }
    initializeColors() {
        this.state.chartColors = this.state.dashboardData.map(() => this.getRandomColor());
        this.state.chartBorderColors = this.state.dashboardData.map(() => this.getRandomBorderColor());

        
    }
    updateCharts() {
        if (!this.state.chartColors.length) {
            this.initializeColors(); // Chỉ cần gọi một lần
        }
        const randomColors = this.state.dashboardData.map(() => this.getRandomColor());
        const randomBorderColors = this.state.dashboardData.map(() => this.getRandomBorderColor());
        if (this.state.stage){
            // Cập nhật dữ liệu cho biểu đồ Quality Issues
            this.state.charts.qualityIssues.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.qualityIssues.data.datasets[0].data = this.state.dashboardData.map(item => item[this.state.stage]);
            this.state.charts.qualityIssues.data.datasets[0].backgroundColor = this.state.chartColors;
            this.state.charts.qualityIssues.data.datasets[0].borderColor = this.state.chartBorderColors;

            console.log(this.state.charts.qualityIssues.data.datasets[0].data)

            // Cập nhật các biểu đồ khác tương tự...
            this.state.charts.doughnut.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.doughnut.data.datasets[0].data = this.state.dashboardData.map(item => item[this.state.stage]);
            this.state.charts.doughnut.data.datasets[0].backgroundColor = this.state.chartColors;
            this.state.charts.doughnut.data.datasets[0].borderColor = this.state.chartBorderColors;

            this.state.charts.polarArea.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.polarArea.data.datasets[0].data = this.state.dashboardData.map(item => item[this.state.stage]);
            this.state.charts.polarArea.data.datasets[0].backgroundColor = this.state.chartColors;
            this.state.charts.polarArea.data.datasets[0].borderColor = this.state.chartBorderColors;

            this.state.charts.productionProgress.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.productionProgress.data.datasets[0].data = this.state.dashboardData.map(item => item[this.state.stage]);
            this.state.charts.productionProgress.data.datasets[0].backgroundColor = this.state.chartColors;
            this.state.charts.productionProgress.data.datasets[0].borderColor = this.state.chartBorderColors;
        } else {
            // Random màu nhấp nháy :))

            // Cập nhật dữ liệu biểu đồ Quality Issues khi có dashboardData
            this.state.charts.qualityIssues.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.qualityIssues.data.datasets[0].data = this.state.dashboardData.map(item => item.so_luong);
            this.state.charts.qualityIssues.data.datasets[0].backgroundColor = randomColors;
            this.state.charts.qualityIssues.data.datasets[0].borderColor = randomBorderColors;
            
            
            // Cập nhật dữ liệu biểu đồ Doughnut khi có dashboardData
            this.state.charts.doughnut.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.doughnut.data.datasets[0].data = this.state.dashboardData.map(item => item.so_luong);
            this.state.charts.doughnut.data.datasets[0].backgroundColor = randomColors;
            this.state.charts.doughnut.data.datasets[0].borderColor = randomBorderColors;

            // Cập nhật dữ liệu biểu đồ polarArea khi có dashboardData
            this.state.charts.polarArea.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.polarArea.data.datasets[0].data = this.state.dashboardData.map(item => item.so_luong);
            this.state.charts.polarArea.data.datasets[0].backgroundColor = randomColors;
            this.state.charts.polarArea.data.datasets[0].borderColor = randomBorderColors;
            
            // Cập nhật dữ liệu biểu đồ productionProgress khi có dashboardData
            this.state.charts.productionProgress.data.labels = this.state.dashboardData.map(item => item.lot);
            this.state.charts.productionProgress.data.datasets[0].data = this.state.dashboardData.map(item => item.thoi_gian_thuc_te);
            this.state.charts.productionProgress.data.datasets[0].backgroundColor = randomColors;
            this.state.charts.productionProgress.data.datasets[0].borderColor = randomBorderColors;
        }
    }

}