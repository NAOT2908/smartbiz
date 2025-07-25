/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService }          from "@web/core/utils/hooks";
const { DateTime } = luxon;

/* ================== helper datetime ================== */
function utcToLocalInput(utc, tz){
  return DateTime.fromISO(utc.replace(" ","T"), { zone:"utc" })
                 .setZone(tz).toFormat("yyyy-LL-dd'T'HH:mm");
}
function localInputToUtc(local, tz){
  return DateTime.fromFormat(local, "yyyy-LL-dd'T'HH:mm", { zone:tz })
                 .toUTC().toFormat("yyyy-LL-dd HH:mm:ss");
}

/* ================== constants ================== */
const PER_PAGE_SELECTOR = 10;
const PER_PAGE_MULTI    = 10;
const PER_PAGE_SINGLE   = 10;

/* ╭──────────────── DialogModal ────────────────╮ */
export class DialogModal extends Component {
  static template = "DialogModals";
  static props    = ["title","action","records","fields","closeModal","defaultValues"];

  /* ---------- setup ---------- */
  setup(){
    /* services */
    this.notification = useService("notification");
    const userSrv     = useService("user");
    this.tz           = userSrv.context.tz || DateTime.local().zoneName;

    /* form default */
    const defs = this.props.defaultValues || {};
    const form = (this.props.fields || []).reduce((acc,f)=>{
      acc[f.name] = defs[f.name] ?? (f.type==="multiselect" ? [] : "");
      return acc;
    }, {});
    if ("id" in defs) form.id = defs.id;

    /* state */
    this.state = useState({
      /* selector 1 record */
      selectedRecord : null,
      selector : { query:"", page:1 },

      /* dynamic form */
      form : form,

      /* multiselect panel */
      multi : { field:null, columns:[], temp:[], query:"", page:1 },

      /* single-select panel */
      single : { field:null, columns:[], selected:null, query:"", page:1 },
    });
  }

  /* ====================================================================== */
  /*  Selector 1 bản ghi  */
  /* ====================================================================== */
  setSelectorQuery = (e)=>{
    this.state.selector.query = e.target.value.toLowerCase();
    this.state.selector.page  = 1;
  };
  getSelectorFiltered(){
    const q = this.state.selector.query;
    return (this.props.records || []).filter(r=>{
      const name = (r.display_name || r.name || "").toLowerCase();
      return name.includes(q);
    });
  }
  getSelectorTotalPages(){ return Math.max(1, Math.ceil(this.getSelectorFiltered().length / PER_PAGE_SELECTOR)); }
  getSelectorDisplay(){
    const start = (this.state.selector.page-1) * PER_PAGE_SELECTOR;
    return this.getSelectorFiltered().slice(start, start+PER_PAGE_SELECTOR);
  }
  nextSelectorPage(){ if (this.state.selector.page < this.getSelectorTotalPages()) this.state.selector.page++; }
  prevSelectorPage(){ if (this.state.selector.page > 1) this.state.selector.page--; }
  selectRecord(id){ this.state.selectedRecord = id; }

  /* ====================================================================== */
  /*  MULTISELECT  */
  /* ====================================================================== */
  openMultiSelect(f){
    if (f.readonly) return;
    const cols = (f.columns && f.columns.length)
      ? f.columns
      : Object.keys(f.options[0] || {}).filter(k=>k!=="id").map(k=>({key:k,label:k}));
    this.state.multi = {
      field   : f,
      columns : cols,
      temp    : [...this.state.form[f.name]],
      query   : "",
      page    : 1,
    };
  }
  removeMultiValue(f,id){
    if (f.readonly) return;
    this.state.form[f.name] = this.state.form[f.name].filter(x=>x!==id);
  }
  /* search & paging */
  setMultiQuery = (e)=>{ this.state.multi.query=e.target.value.toLowerCase(); this.state.multi.page=1; };
  getMultiFiltered(){
    const q=this.state.multi.query;
    const opts=this.state.multi.field.options||[];
    if(!q) return opts;
    return opts.filter(o=>Object.values(o).some(v=>String(v).toLowerCase().includes(q)));
  }
  getMultiTotalPages(){ return Math.max(1, Math.ceil(this.getMultiFiltered().length / PER_PAGE_MULTI)); }
  getMultiDisplay(){
    const start=(this.state.multi.page-1)*PER_PAGE_MULTI;
    return this.getMultiFiltered().slice(start,start+PER_PAGE_MULTI);
  }
  nextMultiPage(){ if (this.state.multi.page < this.getMultiTotalPages()) this.state.multi.page++; }
  prevMultiPage(){ if (this.state.multi.page > 1) this.state.multi.page--; }

  /* chọn / bỏ chọn */
  toggleOne(id){
    const tmp=[...this.state.multi.temp];
    const idx=tmp.indexOf(id);
    idx===-1 ? tmp.push(id) : tmp.splice(idx,1);
    this.state.multi.temp=tmp;
  }
  toggleAll(ev){
    this.state.multi.temp = ev.target.checked
      ? this.state.multi.field.options.map(o=>o.id)
      : [];
  }
  closeMulti(){ this.state.multi.field=null; }
  confirmMulti(){
    const f=this.state.multi.field;
    this.state.form[f.name]=[...this.state.multi.temp];
    this.closeMulti();
  }

  /* ====================================================================== */
  /*  SINGLE-SELECT  */
  /* ====================================================================== */
  openSingleSelect(f){
    if (f.readonly) return;
    const cols = (f.columns && f.columns.length)
      ? f.columns
      : Object.keys(f.options[0] || {}).filter(k=>k!=="id").map(k=>({key:k,label:k}));
    this.state.single = {
      field    : f,
      columns  : cols,
      selected : this.state.form[f.name] || null,
      query    : "",
      page     : 1,
    };
  }
  clearSingleValue(f){ 
    if (f.readonly) return;
    this.state.form[f.name]=""; 
}

  /* search + paging */
  setSingleQuery = (e)=>{ this.state.single.query=e.target.value.toLowerCase(); this.state.single.page=1; };
  getSingleFiltered(){
    const q=this.state.single.query;
    const opts=this.state.single.field.options||[];
    if(!q) return opts;
    return opts.filter(o=>Object.values(o).some(v=>String(v).toLowerCase().includes(q)));
  }
  getSingleTotalPages(){ return Math.max(1, Math.ceil(this.getSingleFiltered().length / PER_PAGE_SINGLE)); }
  getSingleDisplay(){
    const start=(this.state.single.page-1)*PER_PAGE_SINGLE;
    return this.getSingleFiltered().slice(start,start+PER_PAGE_SINGLE);
  }
  nextSinglePage(){ if (this.state.single.page < this.getSingleTotalPages()) this.state.single.page++; }
  prevSinglePage(){ if (this.state.single.page > 1) this.state.single.page--; }

  /* chọn hàng */
  selectSingleRow(id){ this.state.single.selected=id; }
  closeSingle(){ this.state.single.field=null; }
  confirmSingle(){
    if(this.state.single.selected===null){
      this.notification.add("Bạn chưa chọn bản ghi!",{type:"warning"});
      return;
    }
    const f=this.state.single.field;
    this.state.form[f.name]=this.state.single.selected;
    this.closeSingle();
  }

  /* ====================================================================== */
  /*  INPUT helpers + utilities */
  /* ====================================================================== */
  getOptionName(f,id){
    const rec=f.options.find(o=>o.id==id);
    //console.log("getOptionName",f,id,rec);
    return rec ? (rec.display_name||rec.name||id) : id;

  }
  isSelectDialog(f){
    return f.type==="select" && (f.dialog || (f.options?.length>30));
  }
  getInputValue(field) {
    const val = this.state.form[field.name];
    if ((field.type === "datetime-local" || field.type === "date") && val) {
      const dt = DateTime.fromISO(val.replace(" ", "T"), {
        zone: "utc",
      }).setZone(this.tz);
      return field.type === "date"
        ? dt.toFormat("yyyy-LL-dd") // chỉ ngày
        : dt.toFormat("yyyy-LL-dd'T'HH:mm"); // datetime-local
    }
    if (field.type === "select") {
      return val === null || val === undefined ? "" : String(val);
    }
    return val ?? "";
  }
  _onInput(name, ev) {
    let val = ev.target.value;
    if (
      (ev.target.type === "datetime-local" || ev.target.type === "date") &&
      val
    ) {
      const fmt =
        ev.target.type === "date" ? "yyyy-LL-dd" : "yyyy-LL-dd'T'HH:mm";

      val = DateTime.fromFormat(val, fmt, { zone: this.tz })
        .toUTC()
        .toFormat("yyyy-LL-dd HH:mm:ss");
    } else if (ev.target.type === "number" && val !== "") {
      val = Number(val);
    } else if (ev.target.tagName === "SELECT" && /^\d+$/.test(val)) {
      val = Number(val);
    }
    this.state.form[name] = val;
    this._onAfterInput(name);
  }
    /* ========================= ẨN / HIỆN ========================== */
    isFieldVisible(f) {
        // Không cấu hình -> luôn hiển thị
        if (!f.visible_if) return true;
    
        const { field, operator = "=", value } = f.visible_if;
        const v = this.state.form[field];
    
        switch (operator) {
        case "=":      return v == value;
        case "!=":     return v != value;
        case ">":      return v >  value;
        case "<":      return v <  value;
        case ">=":     return v >= value;
        case "<=":     return v <= value;
        case "in":     return Array.isArray(value) && value.includes(v);
        case "notin":  return Array.isArray(value) && !value.includes(v);
        default:       return true;
        }
    }
    
    getVisibleFields() {
        return (this.props.fields || []).filter((f) => this.isFieldVisible(f));
    }

      _onAfterInput(changedField) {
    const form = this.state.form;

    // Tính duration (chỉ khi đang ở màn overtime)
    if (
      "start_date" in form &&
      "end_date" in form &&
      form.start_date &&
      form.end_date
    ) {
      const start = DateTime.fromFormat(
        form.start_date,
        "yyyy-LL-dd HH:mm:ss",
        { zone: "utc" }
      );
      const end = DateTime.fromFormat(form.end_date, "yyyy-LL-dd HH:mm:ss", {
        zone: "utc",
      });
      const duration = end.diff(start, "hours").hours;

      // chỉ update nếu hợp lệ
      if (!isNaN(duration) && duration >= 0) {
        form.duration = Math.round(duration * 100) / 100;
      } else {
        form.duration = 0;
      }
    }

    // Tính number_of_days (chỉ khi ở leave_data)
    if (
      "date_from" in form &&
      "date_to" in form &&
      form.date_from &&
      form.date_to
    ) {
      const from = DateTime.fromFormat(form.date_from, "yyyy-LL-dd HH:mm:ss", {
        zone: "utc",
      });
      const to = DateTime.fromFormat(form.date_to, "yyyy-LL-dd HH:mm:ss", {
        zone: "utc",
      });

      const days = to.diff(from, "days").days;
      if (!isNaN(days) && days >= 0) {
        form.number_of_days = Math.round((days + 1) * 100) / 100; // +1 nếu tính cả 2 ngày
      } else {
        form.number_of_days = 0;
      }
    }
  }
  /* ====================================================================== */
  /*  Confirm / Cancel  */
  /* ====================================================================== */
  confirmEdit(){
    /* validate required */
    if(this.props.fields){
        const visible = this.getVisibleFields();
        const invalid = visible.find(f => {
          if (!f.required) return false;
          const v = this.state.form[f.name];
          return f.type === "multiselect" ? v.length === 0 : !v;
        });
      if(invalid){
        this.notification.add(`Trường "${invalid.label}" là bắt buộc`,{type:"danger"});
        return;
      }
      this.props.closeModal(this.props.title,this.state.form,this.props.action);
    }else{
      const rec=this.props.records.find(r=>r.id===this.state.selectedRecord);
      this.props.closeModal(this.props.title,rec||false);
    }
  }
  cancel(){ this.props.closeModal(this.props.title,false); }
}
/* ╰──────────────────────────────────────────────────────╯ */