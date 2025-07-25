/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * ChartComponent: Nhận các props chartId và chartConfig (tham số hóa hoàn toàn)
 */
export class ChartComponent extends Component {
    static template = "ChartComponent1";
    static props = ["chartId", "chartConfig"];

    setup() {
        super.setup();
        this.chart = null;
        this.refs = useRef("canvas");
        // Lưu lại snapshot cấu hình chart để kiểm tra sự thay đổi
        this.prevChartConfig = JSON.stringify(this.props.chartConfig);

        onMounted(() => {
            const ctx = this.refs.el.getContext("2d");
            // Tạo chart dựa trên cấu hình truyền vào
            this.chart = new Chart(ctx, { ...this.props.chartConfig });
        });

        onPatched(() => {
            const newChartConfig = JSON.stringify(this.props.chartConfig);
            if (newChartConfig !== this.prevChartConfig) {
                // Cập nhật lại cấu hình chart nếu có thay đổi
                this.chart.config.type = this.props.chartConfig.type;
                this.chart.config.data = JSON.parse(JSON.stringify(this.props.chartConfig.data));
                this.chart.config.options = this.props.chartConfig.options;
                this.chart.update();
                this.prevChartConfig = newChartConfig;
            }
        });

        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
            }
        });
    }
}

/**
 * AllInOneDashboard: Thành phần cha quản lý dashboard
 */
export class AllInOneDashboard extends Component {
    static template = "AllInOneDashboard";
    static components = { ChartComponent };

    setup() {
        
        this.orm = useService("orm");
        this.notification = useService("notification");

        // Khởi tạo state cho dashboard
        this.state = useState({
              // Filters
              allLines: [],
              allShifts: [],
              selectedLine: "",
              selectedShift: "",
              productionDate: this._getToday(),
              dateAnalytics: "",
              view: "WorkOrder",
              search: "",
              // WorkOrder data
              steps: [],
              kpi:{},
              steps_faulty:[],
              dashboardData: [],
              faultyData: [],
              // Analytics KPI data (cũ + mới)
              analyticsData: {},
              // Charts cho KPI cũ
              chartQualityConfig: {},
              chartDefectConfig: {},
              chartProductivityConfig: {},
              chartTimeConfig: {},
              chartCompletionConfig: {},
              chartOEEConfig: {},
              // Charts cho KPI mới
              chartDowntimeConfig: {},
              chartSetupEfficiencyConfig: {},
              chartScrapRateConfig: {},
              chartYieldRateConfig: {},
              chartThroughputConfig: {},
              chartReworkConfig: {},
              chartLaborProductivityConfig: {},
              chartMachineUtilConfig: {},
              chartOnTimeDeliveryConfig: {},
              chartBottleneckConfig: {},

              autoRefreshInterval: 5,  // Mặc định 5 giây
        });
         // -------------------------
        // [THÊM MỚI]: STATE CHO AUTO REFRESH
        // -------------------------

        // Biến lưu tạm timer (setInterval)
        this.refreshTimer = null;
        this.dateResetTimer  = null;   // <─ thêm dòng này
        /* --- REF ------------------------------------------------------- */
        this.refs = useRef("progressWrapper", "faultyWrapper");

        /* --- HÀM CUỘN -------------------------------------------------- */
        const scrollBottom = () => {
            for (const k of ["progressWrapper", "faultyWrapper"]) {
                const node = this.refs[k]?.el;
                if (node) node.scrollTop = node.scrollHeight;
            }
        };
        /* -------------- lifecycle -------------------------------- */
        onMounted(() => {
            this._startAutoRefresh();
        });

        onPatched(() => {
            if (this.state.view === "WorkOrder") {
                // Đẩy xuống micro-task -> chắc chắn bản vá cuối cùng đã xong
                Promise.resolve().then(() => {
                    // Đẩy thêm 1 frame, chắn chắn layout tính xong
                    requestAnimationFrame(scrollBottom);
                });
            }
        });

        // Khi unmount, dừng auto-refresh để tránh rò rỉ bộ nhớ
        onWillUnmount(() => {
            this._stopAutoRefresh();
        });
        onWillStart(async () => {
            // Load Chart.js nếu chưa có
            await loadJS("/smartbiz_dashboard/static/src/chart.umd.min.js");
            // 1) Lấy danh sách filter options (line, shift)
            await this._fetchFilterOptions();
            // 2) Fetch dữ liệu ban đầu cho dashboard
            await this._fetchWorkOrderData();
            //await this._fetchAnalyticsData();
        });


    }
    // ==============================
    // HÀM QUẢN LÝ AUTO REFRESH
    // ==============================
    _startAutoRefresh() {
        // Dừng tất cả timer cũ trước
        this._stopAutoRefresh();
    
        /* --- interval refresh (giây) ---------------------- */
        const intervalMs = parseInt(this.state.autoRefreshInterval || 0) * 1000;
        if (intervalMs > 0) {
            this.refreshTimer = setInterval(() => {
                if (this.state.view === "WorkOrder") {
                    this._fetchWorkOrderData();
                } else {
                    this._fetchAnalyticsData();
                }
            }, intervalMs);
        }
    
        /* --- interval reset ngày (20 phút) ---------------- */
        const RESET_MS = 5 * 60 * 1000;          // 1 200 000 ms
        this.dateResetTimer = setInterval(() => {
            const today = this._getToday();       // yyyy-mm-dd
            if (this.state.productionDate !== today) {
                this.state.productionDate = today;
                if (this.state.view === "WorkOrder") {
                    this._fetchWorkOrderData();   // refresh cho đúng ngày
                }
            }
        }, RESET_MS);
    }
    _stopAutoRefresh() {
        if (this.refreshTimer)   { clearInterval(this.refreshTimer);   this.refreshTimer   = null; }
        if (this.dateResetTimer) { clearInterval(this.dateResetTimer); this.dateResetTimer = null; }
    }

    // Sự kiện khi người dùng thay đổi tần số
    onChangeAutoRefresh(ev) {
        this.state.autoRefreshInterval = ev.target.value;
        this._startAutoRefresh();
    }

    // ==============================
    // Xử lý Filter (line, shift, date)
    // ==============================
    async _fetchFilterOptions() {
        try {
            const result = await this.orm.call("mrp.workorder", "get_filter_options", []);
            // Giả sử result = { lines: [...], shifts: [...] }
            this.state.allLines = result.lines || [];
            this.state.allShifts = result.shifts || [];
        } catch (error) {
            console.error(error);
            this.notification.add("Lỗi lấy filter options (line/shift)", { type: "danger" });
        }
    }

    changedashboard = (nextView) => {
        this.state.view = nextView;
        if (nextView === "WorkOrder") {
            this._fetchWorkOrderData();
        } else {
            this._fetchAnalyticsData();
        }
    }

    _getToday() {
        const now = new Date();
        const yyyy = now.getFullYear();
        const mm = String(now.getMonth() + 1).padStart(2, '0');
        const dd = String(now.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    async onLineChange(ev) {
        this.state.selectedLine = ev.target.value;
        if (this.state.view === "WorkOrder") {
            await this._fetchWorkOrderData();
        } else {
            await this._fetchAnalyticsData();
        }
    }

    async onShiftChange(ev) {
        this.state.selectedShift = ev.target.value;
        if (this.state.view === "WorkOrder") {
            await this._fetchWorkOrderData();
        } else {
            await this._fetchAnalyticsData();
        }
    }

    async onProductionDateChange(ev) {
        this.state.productionDate = ev.target.value;
        await this._fetchWorkOrderData();
    }

    async onDateAnalyticsChange(ev) {
        this.state.dateAnalytics = ev.target.value || "";
        await this._fetchAnalyticsData();
    }

    async onSearchChange(ev) {
        this.state.search = ev.target.value.toLowerCase();
        if (!this.state.search) {
            await this._fetchWorkOrderData();
            return;
        }
        this.state.dashboardData = this.state.dashboardData.filter(row => {
            return Object.values(row).some(val => (val || "").toString().toLowerCase().includes(this.state.search));
        });
    }

    // ==============================
    // FETCH WORKORDER
    // ==============================
    async _fetchWorkOrderData() {
        const line = this.state.selectedLine || "";
        const shift = this.state.selectedShift || "";
        const date = this.state.productionDate || "";
    
        const startTime1 = performance.now();
        const resp1 = await this.orm.call("mrp.workorder", "get_dashboard_data", [date, line, shift]);
        const duration1 = performance.now() - startTime1;
    
        this.state.dashboardData = resp1.data || [];
        this.state.steps = resp1.steps || [];
        this.state.kpi = resp1.kpi || {};
    
        const startTime2 = performance.now();
        const resp2 = await this.orm.call("mrp.workorder", "get_faulty_data", [date, line, shift]);
        const duration2 = performance.now() - startTime2;
    
        this.state.faultyData = resp2.data || [];
        this.state.steps_faulty = resp1.steps || [];
      
        // console.log(`Thời gian chạy get_dashboard_data: ${duration1.toFixed(2)} ms`);
        // console.log(`Thời gian chạy get_faulty_data: ${duration2.toFixed(2)} ms`);
    }
    

    onDownloadExcelWorkOrder() {
        this.notification.add("TODO: Export Excel WorkOrder", { type: "info" });
    }

    // ==============================
    // FETCH ANALYTICS
    // ==============================
    async _fetchAnalyticsData() {
        const line = this.state.selectedLine || "";
        const shift = this.state.selectedShift || "";
        const d = this.state.dateAnalytics || "";
        const startTime2 = performance.now();
        const data = await this.orm.call("mrp.workorder", "get_analytics_kpis", [d, line, shift]);
        const duration2 = performance.now() - startTime2;
        // console.log(`Thời gian chạy get_analytics_kpis: ${duration2.toFixed(2)} ms`);
        this.state.analyticsData = data;
        this._buildAllCharts();
    }

    _buildAllCharts() {
        // KPI Cũ:
        const quality_data = this.state.analyticsData.quality_data || [];
        const defect_data = this.state.analyticsData.defect_data || [];
        const productivity_data = this.state.analyticsData.productivity_data || [];
        const time_data = this.state.analyticsData.time_data || [];
        const completion_data = this.state.analyticsData.completion_data || [];
        const oee_data = this.state.analyticsData.oee_data || [];

        let totalOk = 0, totalNg = 0;
        for (const row of quality_data) {
            totalOk += (row.ok_qty || 0);
            totalNg += (row.ng_qty || 0);
        }
        this.state.chartQualityConfig = {
            type: "doughnut",
            data: {
                labels: ["OK", "NG"],
                datasets: [{
                    data: [totalOk, totalNg],
                    backgroundColor: ["rgba(75,192,192,0.7)", "rgba(255,99,132,0.7)"]
                }]
            },
            options: { plugins: { title: { display: true, text: "Chất lượng (OK vs NG)" } } }
        };

        const defLabels = [];
        const defData = [];
        for (const row of defect_data) {
            defLabels.push(`${row.workcenter} / ${row.shift}`);
            defData.push(row.ng_qty || 0);
        }
        this.state.chartDefectConfig = {
            type: "bar",
            data: {
                labels: defLabels,
                datasets: [{
                    label: "SL lỗi",
                    data: defData,
                    backgroundColor: "rgba(255,159,64,0.7)"
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                scales: { x: { beginAtZero: true } },
                plugins: { title: { display: true, text: "Lỗi theo Công đoạn & Ca" } }
            }
        };

        const prodLabels = [];
        const prodVals = [];
        for (const row of productivity_data) {
            prodLabels.push(`${row.shift} / ${row.employee}`);
            prodVals.push(row.ok_qty || 0);
        }
        this.state.chartProductivityConfig = {
            type: "bar",
            data: {
                labels: prodLabels,
                datasets: [{
                    label: "SL OK",
                    data: prodVals,
                    backgroundColor: "rgba(54,162,235,0.7)"
                }]
            },
            options: {
                responsive: true,
                scales: { y: { beginAtZero: true } },
                plugins: { title: { display: true, text: "Năng suất theo Ca & Nhân viên" } }
            }
        };

        const timeLabels = [];
        const timeVals = [];
        for (const row of time_data) {
            timeLabels.push(row.product);
            timeVals.push(row.avg_time_per_unit || 0);
        }
        this.state.chartTimeConfig = {
            type: "bar",
            data: {
                labels: timeLabels,
                datasets: [{
                    label: "Thời gian (phút/SP)",
                    data: timeVals,
                    backgroundColor: "rgba(153,102,255,0.7)"
                }]
            },
            options: {
                responsive: true,
                scales: { y: { beginAtZero: true } },
                plugins: { title: { display: true, text: "Thời gian trung bình / SP" } }
            }
        };

        const compLabels = [];
        const compData = [];
        for (const row of completion_data) {
            compLabels.push(row.production_name);
            compData.push(row.completion_rate || 0);
        }
        this.state.chartCompletionConfig = {
            type: "bar",
            data: {
                labels: compLabels,
                datasets: [{
                    label: "Tỷ lệ hoàn thành (%)",
                    data: compData,
                    backgroundColor: "rgba(255,205,86,0.7)"
                }]
            },
            options: {
                responsive: true,
                scales: { y: { beginAtZero: true, max: 100 } },
                plugins: { title: { display: true, text: "Tỷ lệ hoàn thành" } }
            }
        };

        const oeeLabels = [];
        const oeeVals = [];
        for (const row of oee_data) {
            oeeLabels.push(row.production_name);
            oeeVals.push(row.oee || 0);
        }
        this.state.chartOEEConfig = {
            type: "bar",
            data: {
                labels: oeeLabels,
                datasets: [{
                    label: "OEE (%)",
                    data: oeeVals,
                    backgroundColor: "rgba(255,99,132,0.7)"
                }]
            },
            options: {
                responsive: true,
                scales: { y: { beginAtZero: true, max: 100 } },
                plugins: { title: { display: true, text: "Phân tích OEE" } }
            }
        };

        // KPI mới:
        const downtime_rate = this.state.analyticsData.downtime_rate || 0;
        const setup_efficiency = this.state.analyticsData.setup_efficiency || 0;
        const scrap_rate = this.state.analyticsData.scrap_rate || 0;
        const yield_rate = this.state.analyticsData.yield_rate || 0;
        const throughput = this.state.analyticsData.throughput_rate || 0;
        const rework = this.state.analyticsData.rework_rate || 0;
        const labor_prod = this.state.analyticsData.labor_productivity || 0;
        const machine_util = this.state.analyticsData.machine_utilization || 0;
        const on_time = this.state.analyticsData.on_time_delivery || 0;
        const bottleneck = this.state.analyticsData.bottleneck_index || 0;

        this.state.chartDowntimeConfig = {
            type: 'doughnut',
            data: {
                labels: ["Thời gian ngừng", "Thời gian hoạt động"],
                datasets: [{
                    data: [downtime_rate, 100 - downtime_rate],
                    backgroundColor: ['#FF6384','#36A2EB']
                }]
            },
            options: { plugins: { title:{ display:true, text: "Tỷ lệ ngừng máy (%)" } } }
        };

        this.state.chartSetupEfficiencyConfig = {
            type: 'doughnut',
            data: {
                labels: ["Thiết lập", "Còn lại"],
                datasets: [{
                    data: [setup_efficiency, 100 - setup_efficiency],
                    backgroundColor: ['#FFCE56','#E7E9ED']
                }]
            },
            options: { plugins: { title:{ display:true, text: "Hiệu quả thiết lập (%)" } } }
        };

        this.state.chartScrapRateConfig = {
            type: 'doughnut',
            data: {
                labels: ["Phế liệu", "Đạt"],
                datasets: [{
                    data: [scrap_rate, 100 - scrap_rate],
                    backgroundColor: ['#FF6384','#4BC0C0']
                }]
            },
            options: { plugins: { title:{ display:true, text: "Tỷ lệ phế liệu (%)" } } }
        };

        this.state.chartYieldRateConfig = {
            type: 'doughnut',
            data: {
                labels: ["Đạt", "Lỗ"],
                datasets: [{
                    data: [yield_rate, 100 - yield_rate],
                    backgroundColor: ['#36A2EB','#FFCE56']
                }]
            },
            options: { plugins: { title:{ display:true, text: "Tỷ lệ đạt (%)" } } }
        };

        this.state.chartThroughputConfig = {
            type: 'bar',
            data: {
                labels: ["Lưu lượng"],
                datasets: [{
                    label: "SP/giờ",
                    data: [throughput],
                    backgroundColor: ['#9966FF']
                }]
            },
            options: { scales:{ y:{ beginAtZero:true } }, plugins:{ title:{ display:true, text: "Lưu lượng sản xuất" } } }
        };

        this.state.chartReworkConfig = {
            type: 'bar',
            data: {
                labels: ["Làm lại"],
                datasets: [{
                    label: "Tỷ lệ làm lại (%)",
                    data: [rework],
                    backgroundColor: ['#FF9F40']
                }]
            },
            options: { scales:{ y:{ beginAtZero:true } }, plugins:{ title:{ display:true, text: "Tỷ lệ làm lại" } } }
        };

        this.state.chartLaborProductivityConfig = {
            type: 'bar',
            data: {
                labels: ["Hiệu suất lao động"],
                datasets: [{
                    label: "Năng suất (%)",
                    data: [labor_prod],
                    backgroundColor: ['#4BC0C0']
                }]
            },
            options: { scales:{ y:{ beginAtZero:true } }, plugins:{ title:{ display:true, text: "Hiệu suất lao động" } } }
        };

        this.state.chartMachineUtilConfig = {
            type: 'doughnut',
            data: {
                labels: ["Sử dụng", "Chờ"],
                datasets: [{
                    data: [machine_util, 100-machine_util],
                    backgroundColor: ['#FF6384','#36A2EB']
                }]
            },
            options: { plugins: { title:{ display:true, text: "Tỷ lệ sử dụng máy (%)" } } }
        };

        this.state.chartOnTimeDeliveryConfig = {
            type: 'doughnut',
            data: {
                labels: ["Đúng hạn", "Trễ"],
                datasets: [{
                    data: [on_time, 100-on_time],
                    backgroundColor: ['#4BC0C0','#FFCE56']
                }]
            },
            options: { plugins: { title:{ display:true, text: "Tỷ lệ giao hàng đúng hạn (%)" } } }
        };

        this.state.chartBottleneckConfig = {
            type: 'bar',
            data: {
                labels: ["Chỉ số nút thắt"],
                datasets: [{
                    label: "Chỉ số",
                    data: [bottleneck],
                    backgroundColor: ['#9966FF']
                }]
            },
            options: { scales:{ y:{ beginAtZero:true } }, plugins:{ title:{ display:true, text: "Chỉ số nút thắt" } } }
        };
    }


    onDownloadExcelAnalytics() {
        this.notification.add("Chưa triển khai: Xuất Excel Phân tích", { type: "info" });
    }
}

// Đăng ký action cho dashboard
registry.category("actions").add("smartbiz_dashboard", AllInOneDashboard);
