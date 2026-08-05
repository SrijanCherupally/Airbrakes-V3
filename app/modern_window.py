"""Polished Airbrakes V3 ground-station interface."""
import json, os, queue, threading, time, tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import coast_table_tool, data_store, firmware, serial_link

APP_DIR=os.path.join(os.path.expanduser("~"),".airbrakes_ground_station")
APP_CONFIG_PATH=os.path.join(APP_DIR,"app_config.json")
BG="#0a1017"; SIDEBAR="#101923"; SURFACE="#131e29"; SURFACE2="#192632"; FIELD="#202f3d"; HOVER="#2b4050"; CONSOLE="#08121b"; BORDER="#263847"; TEXT="#f1f7f5"; MUTED="#91a5ad"; SUBTLE="#657983"; TEAL="#48dfbb"; TEAL_DARK="#174b4c"; AMBER="#f6ca73"; RED="#f17f8b"; BLUE="#72b8ff"
FONT="Segoe UI"; MONO="Cascadia Mono"

def load_config():
    try:
        with open(APP_CONFIG_PATH,encoding="utf-8") as f:return json.load(f)
    except (OSError,ValueError):return {}
def save_config(v):
    os.makedirs(APP_DIR,exist_ok=True)
    with open(APP_CONFIG_PATH,"w",encoding="utf-8") as f:json.dump(v,f,indent=2)

class App(ctk.CTk):
    def __init__(self):
        super().__init__(); ctk.set_appearance_mode("dark"); ctk.set_default_color_theme("dark-blue")
        self.title("Airbrakes V3  ·  Ground Station"); self.geometry("1320x860"); self.minsize(1020,680); self.configure(fg_color=BG); self._dark_titlebar()
        self.cfg=load_config(); self.repo_path=self.cfg.get("repo_path"); self.data_dir=self.cfg.get("data_dir",os.path.join(APP_DIR,"flight_data")); self.store=data_store.DataStore(self.data_dir)
        self.link=None; self.process=None; self._monitor_job=None; self._monitor_paused=False; self._autoscroll=True; self._flights=[]; self._selected_flight=None; self._started=None; self._last_port=None; self._operation_running=False; self._page_generation=0
        self._shell(); self._show_page("Pre-flight"); self.after(250,self._refresh_ports)
        if not self.repo_path or not os.path.isdir(self.repo_path):self.after(400,self._choose_repo)
    def _dark_titlebar(self):
        if os.name=="nt":
            try:
                import ctypes; v=ctypes.c_int(1); ctypes.windll.dwmapi.DwmSetWindowAttribute(self.winfo_id(),20,ctypes.byref(v),ctypes.sizeof(v))
            except Exception:pass
    def label(self,p,t,c=TEXT,s=12,w="normal",**kw):return ctk.CTkLabel(p,text=t,text_color=c,font=ctk.CTkFont(family=FONT,size=s,weight=w),**kw)
    def card(self,p=None):return ctk.CTkFrame(p or self.workspace,fg_color=SURFACE,bg_color=BG,border_color=BORDER,border_width=1,corner_radius=20)
    def button(self,p,t,cmd,kind="secondary",**kw):
        fg,ho,tc={"primary":(TEAL,"#32c9a6","#081713"),"secondary":(FIELD,HOVER,TEXT),"quiet":("transparent",FIELD,MUTED),"danger":("#482832","#63333f",RED)}[kind]
        # Let compact controls (status-bar Dismiss/Clear buttons) override
        # the normal 38px action height without passing duplicate kwargs.
        height=kw.pop("height",38)
        return ctk.CTkButton(p,text=t,command=cmd,height=height,corner_radius=12,fg_color=fg,hover_color=ho,text_color=tc,font=ctk.CTkFont(family=FONT,size=12,weight="bold"),**kw)
    def pill(self,p,t,c=TEAL):return ctk.CTkLabel(p,text=t,text_color=c,fg_color=TEAL_DARK if c==TEAL else "#402633",corner_radius=9,padx=8,pady=3,font=ctk.CTkFont(family=FONT,size=9,weight="bold"))
    def _shell(self):
        self.grid_columnconfigure(1,weight=1); self.grid_rowconfigure(0,weight=1); self.grid_rowconfigure(1,weight=0); self._sidebar()
        self.workspace=ctk.CTkScrollableFrame(self,fg_color=BG,bg_color=BG,scrollbar_fg_color=BG,scrollbar_button_color=FIELD,scrollbar_button_hover_color=HOVER,corner_radius=0); self.workspace.grid(row=0,column=1,sticky="nsew",padx=(0,30),pady=(24,10)); self.workspace.grid_columnconfigure(0,weight=1)
        self._global_status()
    def _global_status(self):
        self.status_host=ctk.CTkFrame(self,fg_color=BG,bg_color=BG,corner_radius=0)
        self.status_host.grid(row=1,column=1,sticky="ew",padx=(0,30),pady=(0,18));self.status_host.grid_columnconfigure(1,weight=1);self.status_host.grid_remove()
        self.status_accent=ctk.CTkFrame(self.status_host,width=5,fg_color=TEAL,bg_color=BG,corner_radius=3);self.status_accent.grid(row=0,column=0,sticky="ns",padx=(0,12),pady=2)
        body=ctk.CTkFrame(self.status_host,fg_color=SURFACE,bg_color=BG,border_color=BORDER,border_width=1,corner_radius=15);body.grid(row=0,column=1,sticky="ew");body.grid_columnconfigure(1,weight=1)
        self.status_title=self.label(body,"",TEXT,12,"bold");self.status_title.grid(row=0,column=0,sticky="w",padx=(14,6),pady=(10,0))
        self.status_detail=self.label(body,"",MUTED,10,anchor="w");self.status_detail.grid(row=1,column=0,columnspan=2,sticky="ew",padx=14,pady=(2,10))
        self.status_progress=ctk.CTkProgressBar(body,height=6,corner_radius=3,fg_color=FIELD,progress_color=TEAL);self.status_progress.grid(row=0,column=1,sticky="ew",padx=(8,14),pady=(10,0));self.status_progress.grid_remove()
        self.status_close=self.button(body,"Dismiss",self._dismiss_global_status,"quiet",height=26,width=70);self.status_close.grid(row=0,column=2,rowspan=2,padx=(0,12));self.status_close.grid_remove()
        self._status_hide_job=None
    def _show_global_status(self,title,detail="",running=True,ok=True):
        if not hasattr(self,"status_host"):return
        if self._status_hide_job:
            try:self.after_cancel(self._status_hide_job)
            except tk.TclError:pass
            self._status_hide_job=None
        self.status_host.grid();self.status_title.configure(text=title);self.status_detail.configure(text=detail)
        self.status_accent.configure(fg_color=TEAL if ok else RED)
        if running:
            self.status_progress.configure(mode="indeterminate");self.status_progress.start();self.status_progress.grid();self.status_close.grid_remove()
        else:
            self.status_progress.stop();self.status_progress.configure(mode="determinate");self.status_progress.set(1 if ok else 0);self.status_progress.grid();self.status_close.grid();self._status_hide_job=self.after(5000,self._dismiss_global_status)
    def _dismiss_global_status(self):
        if hasattr(self,"status_progress"):self.status_progress.stop()
        if hasattr(self,"status_host"):self.status_host.grid_remove()
        self._status_hide_job=None
    def _sidebar(self):
        self.sidebar=ctk.CTkFrame(self,width=244,fg_color=SIDEBAR,bg_color=BG,corner_radius=0); self.sidebar.grid(row=0,column=0,sticky="nsew"); self.sidebar.grid_propagate(False)
        b=ctk.CTkFrame(self.sidebar,fg_color="transparent",bg_color=SIDEBAR); b.pack(fill="x",padx=24,pady=(30,34)); m=ctk.CTkFrame(b,width=38,height=38,fg_color=TEAL_DARK,bg_color=SIDEBAR,corner_radius=12);m.pack(side="left",padx=(0,12));m.pack_propagate(False);self.label(m,"A",TEAL,20,"bold").place(relx=.5,rely=.48,anchor="center"); self.label(b,"AIRBRAKES",TEAL,18,"bold").pack(anchor="w");self.label(b,"V3  /  GROUND STATION",SUBTLE,9,"bold").pack(anchor="w")
        self.nav={}
        for n,g in (("Pre-flight","◈"),("Board","⌁"),("Ground test","⚙"),("History","◷")):
            x=ctk.CTkButton(self.sidebar,text=f"  {g}   {n}",anchor="w",height=46,corner_radius=13,fg_color="transparent",bg_color=SIDEBAR,hover_color=FIELD,text_color=MUTED,font=ctk.CTkFont(family=FONT,size=13,weight="bold"),command=lambda z=n:self._show_page(z));x.pack(fill="x",padx=14,pady=3);self.nav[n]=x
        ctk.CTkFrame(self.sidebar,height=1,fg_color=BORDER,bg_color=SIDEBAR).pack(fill="x",padx=24,pady=30);self.label(self.sidebar,"BOARD LINK",SUBTLE,9,"bold").pack(anchor="w",padx=26)
        q=ctk.CTkFrame(self.sidebar,fg_color=SURFACE,bg_color=SIDEBAR,corner_radius=12);q.pack(fill="x",padx=20,pady=(9,8));self.connection=self.label(q,"●  OFFLINE",RED,11,"bold");self.connection.pack(anchor="w",padx=13,pady=10);self.side_hint=self.label(self.sidebar,"Connect from the Board\npage to get started.",MUTED,11,justify="left");self.side_hint.pack(anchor="w",padx=26)
    def _show_page(self,n):
        self._page_generation+=1
        self.workspace.grid_remove()
        for x in self.workspace.winfo_children():x.destroy()
        for k,v in self.nav.items():v.configure(fg_color=TEAL_DARK if k==n else "transparent",text_color=TEXT if k==n else MUTED)
        {"Pre-flight":self._preflight,"Board":self._board,"Ground test":self._ground_test_page,"History":self._history}[n]()
        self.update_idletasks();self.workspace.grid()

    def _board(self):
        """Dedicated home for the connection and onboard file controls."""
        self._postflight()

    def _ground_test_page(self):
        """Dedicated ground-test page; connection remains available globally."""
        self._postflight()
        if hasattr(self, "flight_card"):
            self.flight_card.grid_remove()
            self._log("Ground-test controls are below the board connection.")

    def _history_row(self, parent, entry, row, color, label):
        box = ctk.CTkFrame(parent, fg_color=FIELD, bg_color=SURFACE, corner_radius=12)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=4)
        self.label(box, f"{label} {entry['flight_num']:04d}", color, 11, "bold").pack(side="left", padx=14, pady=12)
        self.label(box, f"{entry.get('downloaded_at', '?')}  ·  {entry.get('duration_s', 0):.1f}s", MUTED, 10).pack(side="left", padx=8)
        self.button(box, "Delete", lambda e=entry: self._delete_local(e), "danger", height=28, width=76).pack(side="right", padx=10)

    def _delete_local(self, entry):
        if messagebox.askyesno("Delete local data", f"Delete {entry.get('folder')} from this computer?"):
            self.store.delete_local(entry["folder"])
            self._show_page("History")

    def _delete_all_local(self):
        if messagebox.askyesno("Delete all local data", "Delete every saved flight and ground test from this computer? This does not affect the board."):
            self.store.delete_all_local()
            self._show_page("History")
    def title_block(self,e,t,s):self.label(self.workspace,e.upper(),TEAL,10,"bold").grid(row=0,column=0,sticky="w",padx=10);self.label(self.workspace,t,TEXT,30,"bold").grid(row=1,column=0,sticky="w",padx=10,pady=(4,0));self.label(self.workspace,s,MUTED,12).grid(row=2,column=0,sticky="w",padx=10,pady=(4,24))
    def _activity(self,p,row):
        a=ctk.CTkFrame(p,fg_color=SURFACE2,bg_color=SURFACE,border_color=BORDER,border_width=1,corner_radius=18);a.grid(row=row,column=0,columnspan=3,sticky="ew",padx=20,pady=(0,20));a.grid_columnconfigure(0,weight=1);h=ctk.CTkFrame(a,fg_color="transparent",bg_color=SURFACE2);h.grid(row=0,column=0,sticky="ew",padx=18,pady=(15,0));self.label(h,"LIVE ACTIVITY",TEAL,9,"bold").pack(side="left");self.activity=self.label(h,"Standing by",TEXT,12,"bold");self.activity.pack(side="right");self.detail=self.label(a,"Your next operation will appear here",MUTED,10);self.detail.grid(row=1,column=0,sticky="w",padx=18,pady=(5,0));self.progress=ctk.CTkProgressBar(a,height=9,corner_radius=5,fg_color=FIELD,progress_color=TEAL);self.progress.grid(row=2,column=0,sticky="ew",padx=18,pady=12);self.progress.set(0);f=ctk.CTkFrame(a,fg_color="transparent",bg_color=SURFACE2);f.grid(row=3,column=0,sticky="ew",padx=18,pady=(0,13));self.percent=self.label(f,"0%",SUBTLE,10,"bold");self.percent.pack(side="left");self.clock=self.label(f,"",SUBTLE,10);self.clock.pack(side="right");self.details=self.button(f,"▸  Details",self._toggle_log,"quiet",height=27,width=100);self.details.pack(side="right",padx=(0,12));self.clear_details=self.button(f,"Clear",self._clear_log,"quiet",height=27,width=65);self.clear_details.pack(side="right",padx=(0,8));self.log=ctk.CTkTextbox(a,height=125,corner_radius=13,bg_color=SURFACE2,fg_color=CONSOLE,border_color=BORDER,border_width=1,text_color="#bcebdc",font=ctk.CTkFont(family=MONO,size=10),wrap="none");self.log.grid(row=4,column=0,sticky="ew",padx=18,pady=(0,14));self.log.grid_remove();self.log.configure(state="disabled")
    def _toggle_log(self):
        if self.log.winfo_ismapped():self.log.grid_remove();self.details.configure(text="▸  Details")
        else:self.log.grid();self.details.configure(text="▾  Details")
    def _log(self,s):
        try:
            if hasattr(self,"log") and self.log.winfo_exists():self.log.configure(state="normal");self.log.insert("end",s+"\n");self.log.see("end");self.log.configure(state="disabled")
            if hasattr(self,"event_status") and self.event_status.winfo_exists():self.event_status.configure(text=str(s)[:180])
        except tk.TclError:
            pass
    def _clear_log(self):
        if hasattr(self,"log"):
            self.log.configure(state="normal");self.log.delete("1.0","end");self.log.configure(state="disabled")
    def _activity(self,s,running=False):
        self._operation_running=running
        if not hasattr(self,"activity") or not self.activity.winfo_exists():return
        self.activity.configure(text=s);self._started=time.monotonic() if running else None
        if running:self.progress.configure(mode="indeterminate");self.progress.start();self.percent.configure(text="Working");self.clock.configure(text="Live");self.detail.configure(text="Processing in the background — open Details for technical output")
        else:self.progress.stop();self.progress.configure(mode="determinate");ok="failed" not in s.lower() and "error" not in s.lower();self.progress.set(1 if ok else 0);self.percent.configure(text="Complete" if ok else "Needs attention");self.clock.configure(text="Finished");self.detail.configure(text="Operation finished" if ok else "Open Details for more information")
    def _preflight(self):
        self.title_block("Operations","Pre-flight workspace","Prepare the vehicle, generate its flight model, then build or flash when ready.");c=self.card();c.grid(row=3,column=0,sticky="ew",padx=10,pady=8);c.grid_columnconfigure(1,weight=1);self.label(c,"Vehicle setup",TEXT,17,"bold").grid(row=0,column=0,sticky="w",padx=20,pady=(19,2));self.repo_label=self.label(c,self.repo_path or "Choose a repository folder",MUTED,11,anchor="w");self.repo_label.grid(row=1,column=0,columnspan=2,sticky="ew",padx=20,pady=(0,15));self.button(c,"Choose repository",self._choose_repo,width=154).grid(row=1,column=2,padx=20,pady=(0,15));self.mass=self._field(c,"Rocket mass","mass_kg","kg",2);self.temp=self._field(c,"Temperature","temp_f","°F",3);self.humidity=self._field(c,"Humidity","humidity_pct","%",4);self.pressure=self._field(c,"Pressure","pressure_hpa","hPa",5);self.button(c,"Generate coast table",self._run_coast,"primary").grid(row=6,column=0,columnspan=3,sticky="ew",padx=20,pady=(12,20));self._load_conditions();a=self.card();a.grid(row=4,column=0,sticky="ew",padx=10,pady=8);self.label(a,"Firmware actions",TEXT,17,"bold").pack(anchor="w",padx=20,pady=(19,2));self.label(a,"Build and flash run quietly in the background. Technical output is available only when needed.",MUTED,11).pack(anchor="w",padx=20);r=ctk.CTkFrame(a,fg_color="transparent",bg_color=SURFACE);r.pack(fill="x",padx=20,pady=16);self.button(r,"Build firmware",self._run_build).pack(side="left",padx=(0,9));self.button(r,"Flash to board",self._run_upload,"primary").pack(side="left",padx=(0,9));self.button(r,"Pre-flight check",self._preflight_check).pack(side="left");self._activity(a,3)
    def _field(self,p,l,k,u,row):self.label(p,l,MUTED,11).grid(row=row,column=0,sticky="w",padx=20,pady=5);e=ctk.CTkEntry(p,height=36,corner_radius=10,bg_color=SURFACE,fg_color=FIELD,border_width=1,border_color=BORDER);e.grid(row=row,column=1,sticky="ew",padx=(20,8),pady=5);setattr(self,k,e);self.label(p,u,SUBTLE,10).grid(row=row,column=2,sticky="w",padx=(0,20));return e
    def _load_conditions(self):
        d=self.cfg.get("last_launch_conditions",{});
        for e,k in ((self.mass,"mass_kg"),(self.temp,"temp_f"),(self.humidity,"humidity_pct"),(self.pressure,"pressure_hpa")):e.insert(0,str(d.get(k,"")))
    def _choose_repo(self):
        p=filedialog.askdirectory(title="Select Airbrakes V3 repository")
        if p:self.repo_path=p;self.cfg["repo_path"]=p;save_config(self.cfg);self.repo_label.configure(text=p)
    def _run_coast(self):
        try:v=[float(x.get()) for x in (self.mass,self.temp,self.humidity,self.pressure)]
        except ValueError:return messagebox.showerror("Invalid values","All launch-condition fields must be numbers.")
        self._activity("Generating coast table",True);self._show_global_status("Generating coast table","Validating launch conditions and preparing simulation …",True);self._log("Preparing coast table inputs …")
        def on_line(line):
            self.after(0,lambda:self._line(line))
        self._async(lambda:coast_table_tool.regenerate(self.repo_path,*v,on_line=on_line),lambda r,e:self._done("Coast table generated successfully",e,summary=r))
    def _run_build(self):self._process(firmware.build_firmware,"Building firmware")
    def _run_upload(self):self._process(firmware.upload_firmware,"Flashing firmware")
    def _process(self,fac,name):
        if self._operation_running:return messagebox.showinfo("Operation in progress","Finish the current operation before starting another one.")
        if not self.repo_path:return messagebox.showwarning("Repository needed","Choose the repository first.")
        if not firmware.check_platformio_installed():return messagebox.showerror("PlatformIO unavailable","Install PlatformIO, then try again.")
        reconnect_port=self._last_port if name.startswith("Flashing") else None
        if reconnect_port and self.link:
            self._log("Closing the board connection so PlatformIO can reboot and claim the USB port …")
            self.link.close();self.link=None
            if hasattr(self,"connection") and self.connection.winfo_exists():self.connection.configure(text="●  FLASHING",text_color=AMBER)
            if hasattr(self,"side_hint") and self.side_hint.winfo_exists():self.side_hint.configure(text="Serial link released for upload.\nPlatformIO owns the port.")
        self._activity(name,True);self._show_global_status(name,"Starting PlatformIO and waiting for live output …",True);self._log("Starting "+name.lower()+" …")
        def finished(code):
            def finish_ui():
                self._done(name+(" completed successfully" if code==0 else " failed"),None if code==0 else RuntimeError(f"exit code {code}"))
                if reconnect_port:
                    self._log("Upload finished — waiting for the board to reboot …")
                    self._reconnect_after_upload(reconnect_port,attempt=0)
            self.after(0,finish_ui)
        self.process=fac(self.repo_path,on_line=lambda x:self.after(0,lambda:self._line(x)),on_exit=finished)
    def _line(self,x):
        self._log(x);l=x.lower()
        if self._operation_running:
            stage="Uploading firmware" if "upload" in l or "firmware.bin" in l else "Linking firmware" if "link" in l else "Compiling source" if "compile" in l or "building" in l else "Writing generated files" if "saved" in l or "coast_table" in l or "config.h" in l else "Reading PlatformIO output"
            self._show_global_status(self.activity.cget("text") if hasattr(self,"activity") and self.activity.winfo_exists() else "Operation in progress",stage+": "+str(x)[:130],True)
        try:
            if hasattr(self,"detail") and self.detail.winfo_exists():self.detail.configure(text="Attention required" if "error" in l or "failed" in l else "Uploading firmware" if "upload" in l else "Linking firmware" if "link" in l else "Compiling firmware" if "compile" in l else "Generating coast table" if "progress:" in l else "Writing generated files" if "saved" in l else self.detail.cget("text"))
        except tk.TclError:
            pass
    def _preflight_check(self):
        if self._operation_running:return messagebox.showinfo("Operation in progress","Finish the current operation before starting another one.")
        port=self._last_port
        if not self.link and not port:return messagebox.showinfo("Connect a board","Connect from Post-flight first, then run this check again.")
        self._activity("Checking board",True);self._show_global_status("Pre-flight check","Verifying serial link and requesting board storage information …",True);self._log("Sending INFO request to the flight computer …")
        if self.link:
            self._monitor_paused=True;self._async(self.link.get_info,lambda r,e:self._preflight_done(r,e,False))
        else:
            def open_and_check():
                temporary_link=serial_link.FlightComputerLink(port)
                try:
                    return temporary_link,temporary_link.get_info()
                except Exception:
                    temporary_link.close()
                    raise
            self._async(open_and_check,lambda r,e:self._preflight_done(r,e,True))
    def _preflight_done(self,result,error,temporary):
        if error:
            self._monitor_paused=False;self._done("Pre-flight check failed",error);return
        if temporary:
            self.link,info=result
            self._last_port=self._last_port or self._selected_port()
            summary=info
        else:
            summary=result
        self._monitor_paused=False;self._done("Pre-flight check passed",None,summary=summary)
        if hasattr(self,"connection") and self.connection.winfo_exists():self.connection.configure(text="●  CONNECTED",text_color=TEAL)
        if hasattr(self,"side_hint") and self.side_hint.winfo_exists():self.side_hint.configure(text=f"Connected on {self._last_port or 'selected port'}\nBoard verified.")
    def _done(self,msg,e,summary=None):
        self._activity(msg if not e else str(e),False);self._log(msg if not e else "Error: "+str(e))
        if summary and not e:self._log("Result: "+str(summary))
        self._show_global_status(msg,"Result: "+str(summary)[:170] if summary and not e else (str(e) if e else "Operation finished successfully"),False,not bool(e))
    def _async(self,task,done):
        q=queue.Queue()
        def w():
            try:q.put((task(),None))
            except Exception as e:q.put((None,e))
        threading.Thread(target=w,daemon=True).start()
        def poll():
            try:r,e=q.get_nowait()
            except queue.Empty:self.after(100,poll);return
            done(r,e)
        self.after(100,poll)
    def _postflight(self):
        self.title_block("Telemetry", "Post-flight workspace", "One clear home for the board connection, stored flights, and live output.")
        c=self.card(); c.grid(row=3,column=0,sticky="ew",padx=10,pady=8); c.grid_columnconfigure(0,weight=1)
        self.label(c,"Board connection",TEXT,17,"bold").grid(row=0,column=0,sticky="w",padx=20,pady=(19,12))
        self.port_var=tk.StringVar(); self.port_combo=ctk.CTkComboBox(c,variable=self.port_var,height=38,corner_radius=10,bg_color=SURFACE,fg_color=FIELD,border_width=1,border_color=BORDER,values=[]); self.port_combo.grid(row=1,column=0,sticky="ew",padx=20,pady=(0,12))
        r=ctk.CTkFrame(c,fg_color="transparent",bg_color=SURFACE); r.grid(row=2,column=0,sticky="w",padx=20,pady=(0,10)); self.refresh_button=self.button(r,"Refresh ports",self._refresh_ports).pack(side="left",padx=(0,8)); self.connect_button=self.button(r,"Connect",self._connect,"primary"); self.connect_button.pack(side="left",padx=(0,8)); self.disconnect_button=self.button(r,"Disconnect",self._disconnect); self.disconnect_button.pack(side="left")
        self.connection_progress=ctk.CTkProgressBar(c,height=7,corner_radius=4,fg_color=FIELD,progress_color=TEAL,mode="indeterminate");self.connection_progress.grid(row=3,column=0,sticky="ew",padx=20,pady=(0,6));self.connection_progress.grid_remove()
        self.event_status=self.label(c,"Ready — choose a port to connect.",MUTED,10);self.event_status.grid(row=4,column=0,sticky="w",padx=20,pady=(0,16))
        f=self.card(); f.grid(row=5,column=0,sticky="ew",padx=10,pady=8); f.grid_columnconfigure(0,weight=1); self.flight_card=f
        self.label(f,"Stored flights",TEXT,17,"bold").grid(row=0,column=0,sticky="w",padx=20,pady=(19,2)); self.flight_status=self.label(f,"Connect to view flights",MUTED,11); self.flight_status.grid(row=1,column=0,sticky="w",padx=20)
        self.flight_list=ctk.CTkFrame(f,fg_color="transparent",bg_color=SURFACE); self.flight_list.grid(row=2,column=0,sticky="ew",padx=14,pady=10)
        r=ctk.CTkFrame(f,fg_color="transparent",bg_color=SURFACE); r.grid(row=3,column=0,sticky="w",padx=20,pady=(0,19)); self.button(r,"List flights",self._list_flights).pack(side="left",padx=(0,8)); self.button(r,"Download selected",self._download).pack(side="left",padx=(0,8)); self.button(r,"Download all",self._download_all,"primary").pack(side="left")
        t=self.card();t.grid(row=6,column=0,sticky="ew",padx=10,pady=8);self.label(t,"Ground test",TEXT,17,"bold").pack(anchor="w",padx=20,pady=(17,2));self.label(t,"Arms an opt-in shake-triggered 15 s sensor log and a slow close → open → close airbrake sweep. Keep clear of the mechanism.",MUTED,10,wraplength=800,justify="left").pack(anchor="w",padx=20);tr=ctk.CTkFrame(t,fg_color="transparent",bg_color=SURFACE);tr.pack(anchor="w",padx=20,pady=(10,4));self.button(tr,"Arm ground test",self._ground_test_start,"primary").pack(side="left",padx=(0,8));self.button(tr,"Abort / close brakes",self._ground_test_abort).pack(side="left",padx=(0,8));self.button(tr,"Check status",self._ground_test_status).pack(side="left");self.button(tr,"Check DPS368",self._baro_status,"quiet").pack(side="left",padx=(8,0));self.ground_test_status=self.label(t,"Connect to arm a test.",MUTED,10);self.ground_test_status.pack(anchor="w",padx=20,pady=(0,17))
        activity=self.card();activity.grid(row=7,column=0,sticky="ew",padx=10,pady=8)
        self.label(activity,"Operation status",TEXT,17,"bold").pack(anchor="w",padx=20,pady=(17,0))
        self._activity(activity,1)
        self._monitor()
        if self.link and self._monitor_job is None:self._monitor_job=self.after(100,self._poll_monitor)
    def _monitor(self):
        m=self.card();m.grid(row=8,column=0,sticky="ew",padx=10,pady=8);m.grid_columnconfigure(0,weight=1);h=ctk.CTkFrame(m,fg_color="transparent",bg_color=SURFACE);h.grid(row=0,column=0,sticky="ew",padx=20,pady=(17,0));self.label(h,"Live serial monitor",TEXT,17,"bold").pack(side="left");self.monitor_status=self.label(h,"●  Waiting for board",MUTED,10,"bold");self.monitor_status.pack(side="right");r=ctk.CTkFrame(m,fg_color="transparent",bg_color=SURFACE);r.grid(row=1,column=0,sticky="ew",padx=20,pady=(8,10));self.monitor_lines=self.label(r,"0 lines",SUBTLE,10);self.monitor_lines.pack(side="left");self.button(r,"Clear",self._clear_monitor,"quiet",height=27,width=65).pack(side="right");self.auto_button=self.button(r,"Autoscroll  ON",self._toggle_autoscroll,"quiet",height=27,width=115);self.auto_button.pack(side="right",padx=(8,0));self.monitor=ctk.CTkTextbox(m,height=165,corner_radius=13,bg_color=SURFACE,fg_color=CONSOLE,border_color=BORDER,border_width=1,text_color="#c7eee1",font=ctk.CTkFont(family=MONO,size=10),wrap="none");self.monitor.grid(row=2,column=0,sticky="ew",padx=20,pady=(0,19))
        for tag,color in (("normal","#b9d1ce"),("warn",AMBER),("error",RED),("state",BLUE)):self.monitor.tag_config(tag,foreground=color)
    def _toggle_autoscroll(self):self._autoscroll=not self._autoscroll;self.auto_button.configure(text="Autoscroll  "+("ON" if self._autoscroll else "OFF"))
    def _clear_monitor(self):self.monitor.delete("1.0","end");self.monitor_lines.configure(text="0 lines")
    def _refresh_ports(self):
        if not hasattr(self,"port_combo"):return
        ports=serial_link.list_ports(); vals=[f"{d}  ·  {x}" for d,x in ports];self.port_combo.configure(values=vals);auto=serial_link.find_board()
        if auto:self.port_var.set(next((x for x in vals if x.startswith(auto)),auto))
        if hasattr(self,"event_status"):self.event_status.configure(text=f"{len(vals)} serial port(s) detected — select one to connect.")
    def _selected_port(self):return self.port_var.get().split()[0] if self.port_var.get() else None
    def _connect(self):
        p=self._selected_port()
        if not p:return messagebox.showwarning("No port","Choose a serial port first.")
        self.event_status.configure(text=f"Connecting to {p} … the board may take a moment to wake.",text_color=AMBER);self.connection_progress.grid();self.connection_progress.start();self.connect_button.configure(state="disabled");self._async(lambda:serial_link.FlightComputerLink(p),lambda r,e:self._connection_done(r,e,p))
    def _connection_done(self,r,e,p):
        try:
            if hasattr(self,"connection_progress") and self.connection_progress.winfo_exists():self.connection_progress.stop();self.connection_progress.grid_remove()
            if hasattr(self,"connect_button") and self.connect_button.winfo_exists():self.connect_button.configure(state="normal")
            if e:
                self.link=None
                if hasattr(self,"connection") and self.connection.winfo_exists():self.connection.configure(text="●  OFFLINE",text_color=RED)
                if hasattr(self,"event_status") and self.event_status.winfo_exists():self.event_status.configure(text=f"Connection failed: {e}",text_color=RED)
                return self._done("Connection failed",e)
            self.link=r;self._last_port=p
            if hasattr(self,"connection") and self.connection.winfo_exists():self.connection.configure(text="●  CONNECTED",text_color=TEAL)
            if hasattr(self,"side_hint") and self.side_hint.winfo_exists():self.side_hint.configure(text=f"Connected on {p}\nLive monitor active.")
            if hasattr(self,"event_status") and self.event_status.winfo_exists():self.event_status.configure(text=f"Connected to {p} — checking board response …",text_color=TEAL)
            if hasattr(self,"monitor_status") and self.monitor_status.winfo_exists():self.monitor_status.configure(text="●  Connected · waiting for output",text_color=AMBER)
            self._monitor_job=self.after(100,self._poll_monitor);self._probe_connection()
        except tk.TclError:
            # Page navigation may have rebuilt the workspace while the port
            # was opening. Keep the link and let Post-flight render it later.
            self.link=r if not e else None;self._last_port=p if not e else self._last_port

    def _probe_connection(self):
        """Perform a real protocol round-trip so a quiet monitor is not ambiguous."""
        if not self.link:return
        link=self.link;self._monitor_paused=True
        self.event_status.configure(text="Connected. Sending INFO handshake to verify the board …",text_color=AMBER)
        def done(result,error):
            self._monitor_paused=False
            if not hasattr(self,"monitor_status") or not self.monitor_status.winfo_exists():return
            if error:
                self.monitor_status.configure(text="●  Connected · no response",text_color=RED)
                self.event_status.configure(text=f"Port opened, but board did not answer INFO: {error}",text_color=RED)
                self._log("Monitor is connected but the board did not answer INFO. Check firmware/baud.")
            else:
                self.monitor_status.configure(text="●  Live · board verified",text_color=TEAL)
                self.event_status.configure(text=f"Board verified — storage: {result}. Waiting for live output …",text_color=TEAL)
                self._append_monitor("INFO handshake succeeded — serial link is healthy.","state")
                self._append_monitor("Waiting for boot or diagnostic output …","normal")
                self._log("The monitor will show boot/diagnostic lines when the board emits them.")
        self._async(link.get_info,done)

    def _reconnect_after_upload(self,port,attempt=0):
        """Re-open the monitor after PlatformIO resets the board."""
        if attempt >= 8:
            self.connection.configure(text="●  OFFLINE",text_color=RED)
            self.side_hint.configure(text="Upload finished.\nReconnect to view serial output.")
            self._log("Board did not reappear automatically. Use Connect to retry.")
            return
        self._log(f"Waiting for {port} to reappear (attempt {attempt + 1}/8) …")
        def task():
            time.sleep(1.0)
            return serial_link.FlightComputerLink(port)
        def done(result,error):
            if error:
                self.after(500,lambda:self._reconnect_after_upload(port,attempt + 1))
            else:
                self.link=result;self._last_port=port
                if hasattr(self,"connection") and self.connection.winfo_exists():self.connection.configure(text="●  CONNECTED",text_color=TEAL)
                if hasattr(self,"side_hint") and self.side_hint.winfo_exists():self.side_hint.configure(text=f"Connected on {port}\nMonitor restored after upload.")
                self._log("Board rebooted and serial monitor restored.")
                if hasattr(self,"monitor_status") and self.monitor_status.winfo_exists():self.monitor_status.configure(text="●  Live",text_color=TEAL)
                self._monitor_job=self.after(100,self._poll_monitor)
        self._async(task,done)
    def _disconnect(self):
        if self.link:self.link.close();self.link=None
        if hasattr(self,"connection_progress"):self.connection_progress.stop();self.connection_progress.grid_remove()
        if hasattr(self,"connect_button"):self.connect_button.configure(state="normal")
        self.connection.configure(text="●  OFFLINE",text_color=RED);self.side_hint.configure(text="Connect a board from\nthe Post-flight page.")
        if hasattr(self,"monitor_status"):self.monitor_status.configure(text="●  Disconnected",text_color=MUTED)
        if hasattr(self,"event_status"):self.event_status.configure(text="Disconnected — choose a port to reconnect.",text_color=MUTED)
    def _poll_monitor(self):
        self._monitor_job=None
        if self.link and not self._monitor_paused and hasattr(self,"monitor"):
            try:
                lines=self.link.read_available_lines()
                for line in lines:
                    low=line.lower();tag="error" if "error" in low or "fail" in low else "warn" if "warn" in low else "state" if "state" in low else "normal";self._append_monitor(line,tag)
                if lines:
                    count=int(self.monitor.index("end-1c").split(".")[0])-1
                    if count>500:self.monitor.delete("1.0","100.0")
                    self.monitor_lines.configure(text=f"{count:,} lines")
                    if self._autoscroll:self.monitor.see("end")
                    if hasattr(self,"monitor_status"):self.monitor_status.configure(text=f"●  Live · {len(lines)} new line(s)",text_color=TEAL)
            except Exception as error:
                if hasattr(self,"event_status"):self.event_status.configure(text=f"Serial monitor paused: {error}",text_color=RED)
        if self.link:self._monitor_job=self.after(250,self._poll_monitor)
    def _append_monitor(self,text,tag="normal"):
        if not hasattr(self,"monitor") or not self.monitor.winfo_exists():return
        self.monitor.insert("end",str(text)+"\n",tag)
    def _ground_test_start(self):
        if not self.link:return messagebox.showwarning("Not connected","Connect to the board first.")
        if not messagebox.askyesno("Arm ground test","Keep clear of the airbrakes. After you shake the rocket, it records for 15 seconds and moves the brakes close → open → close. Continue?"):return
        self._ground_test_command(self.link.ground_test_start,"Arming ground test")
    def _ground_test_abort(self):
        if not self.link:return messagebox.showwarning("Not connected","Connect to the board first.")
        self._ground_test_command(self.link.ground_test_abort,"Aborting ground test")
    def _ground_test_status(self):
        if not self.link:return messagebox.showwarning("Not connected","Connect to the board first.")
        self._ground_test_command(self.link.ground_test_status,"Checking ground-test status")
    def _baro_status(self):
        if not self.link:return messagebox.showwarning("Not connected","Connect to the board first.")
        self._monitor_paused=True;self._activity("Checking DPS368",True)
        def done(result,error):
            self._monitor_paused=False
            if error:
                self._activity("DPS368 check failed",False);self._log("DPS368 error: "+str(error));return
            self._append_monitor(result,"state");self._activity("DPS368 status received",False);self._log(result)
        self._async(self.link.baro_status,done)
    def _ground_test_command(self,command,label):
        self._monitor_paused=True;self.ground_test_status.configure(text=label+" …",text_color=AMBER);self._activity(label,True)
        def done(result,error):
            self._monitor_paused=False
            if error:
                self.ground_test_status.configure(text=str(error),text_color=RED);self._activity("Ground test command failed",False);self._log("Ground test error: "+str(error))
            else:
                self.ground_test_status.configure(text=result,text_color=TEAL);self._activity("Ground test updated",False);self._log(result)
        self._async(command,done)
    def _list_flights(self):
        if not self.link:return messagebox.showwarning("Not connected","Connect to the board first.")
        self._monitor_paused=True;self._activity("Reading flights from board",True);self._log("Sending LIST request …");self.flight_status.configure(text="Reading onboard flight files …",text_color=AMBER);self._async(self.link.list_flights,self._flights_done)
    def _flights_done(self,r,e):
        self._monitor_paused=False
        if e:self._activity("Flight list failed",False);return self.flight_status.configure(text=str(e),text_color=RED)
        self._flights=r
        for x in self.flight_list.winfo_children():x.destroy()
        for i,f in enumerate(r):
            row=ctk.CTkFrame(self.flight_list,fg_color=FIELD,bg_color=SURFACE,corner_radius=11);row.pack(fill="x",padx=6,pady=3);row.bind("<Button-1>",lambda event,index=i:self._select_flight(index));self.label(row,f"{i+1:02d}",TEAL,11,"bold",width=32).pack(side="left",padx=(12,4),pady=10);self.label(row,f["file"],TEXT,11,"bold").pack(side="left",padx=4);self.label(row,f["size"],MUTED,10).pack(side="right",padx=12)
            if f["active"]:self.pill(row,"ACTIVE").pack(side="right",padx=4)
        if not r:self.label(self.flight_list,"No flights found on the board.",MUTED,11).pack(pady=18)
        self.flight_status.configure(text=f"{len(r)} flight(s) on board",text_color=MUTED);self._activity("Flights loaded",False);self._log(f"Found {len(r)} flight(s) on the board.")
    def _select_flight(self,index):
        self._selected_flight=index
        self.flight_status.configure(text=f"Selected {self._flights[index]['file']}",text_color=TEAL)
    def _download(self):
        if not self._flights:return messagebox.showinfo("Nothing selected","List flights first.")
        if self._selected_flight is None:return messagebox.showinfo("Choose a flight","Click a flight row, then download it.")
        self._download_numbers([self._flights[self._selected_flight]["num"]],delete=False)
    def _download_numbers(self,numbers,delete=True):
        self._monitor_paused=True;self._activity("Downloading flight data",True)
        def task():
            saved=[]
            for n in numbers:
                records=self.link.download_flight(n)
                config_h=os.path.join(self.repo_path,"include","config.h") if self.repo_path else None
                category = "ground_test" if any(x.get("state_name", "").startswith("GROUND_TEST") for x in records) else "flight"
                saved.append(self.store.save_flight(n,records,config_h_path=config_h,category=category))
                if delete and not any(f["num"]==n and f["active"] for f in self._flights):self.link.delete_flight(n)
            return saved
        self._async(task,self._download_done)
    def _download_all(self):
        if not self.link or not self._flights:return messagebox.showwarning("No flights","Connect and list flights first.")
        nums=[f["num"] for f in self._flights if f["num"] is not None]
        self._download_numbers(nums)
    def _download_done(self,r,e):
        self._monitor_paused=False
        if e:
            self.flight_status.configure(text=f"Download failed: {e}",text_color=RED);self._activity("Download failed",False)
        else:
            self.flight_status.configure(text=f"Saved {len(r)} flight(s) to {self.data_dir}",text_color=TEAL);self._activity("Download complete",False)
    def _history(self):
        self.title_block("Analysis","Flight history","All saved sessions in one place. Select a session to inspect it, or remove local copies here.");c=self.card();c.grid(row=3,column=0,sticky="ew",padx=10,pady=8);c.grid_columnconfigure(0,weight=1);self.label(c,"Saved sessions",TEXT,17,"bold").grid(row=0,column=0,sticky="w",padx=20,pady=(19,5));self.button(c,"Delete all local data",self._delete_all_local,"danger",height=32).grid(row=0,column=1,padx=20,pady=(15,5));entries=self.store.list_by_category("flight")
        tests=self.store.list_by_category("ground_test")
        if entries:
            for i,e in enumerate(entries,1):
                self._history_row(c,e,i,TEAL,"FLIGHT")
            if tests:
                self.label(c,"Ground tests",TEXT,17,"bold").grid(row=len(entries)+1,column=0,sticky="w",padx=20,pady=(22,5))
                for j,e in enumerate(tests, len(entries)+2):
                    self._history_row(c,e,j,AMBER,"GROUND TEST")
        elif tests:
            self.label(c,"Ground tests",TEXT,17,"bold").grid(row=0,column=0,sticky="w",padx=20,pady=(19,5))
            for j,e in enumerate(tests, 1):
                self._history_row(c,e,j,AMBER,"GROUND TEST")
        else:
            x=ctk.CTkFrame(c,fg_color="transparent",bg_color=SURFACE);x.grid(row=1,column=0,sticky="ew",pady=70);self.label(x,"◌",TEAL,34).pack();self.label(x,"No saved flights yet",TEXT,15,"bold").pack(pady=(7,3));self.label(x,"Download a flight from Post-flight to see it here.",MUTED,11).pack()

if __name__=="__main__":App().mainloop()
