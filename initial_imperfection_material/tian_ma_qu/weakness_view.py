"""Scientific figures and an offline, dependency-free weakness result viewer."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import numpy as np


def color(member):
    if member["ever_buckled"]:
        return "#d83f4b"
    if member["max_compression_force_ratio"]>=.9:
        return "#e77716"
    if member["max_compression_force_ratio"]>=.5:
        return "#c8a122"
    return "#a7b7c5"


def save(fig,output,name):
    for extension in ("svg","png","pdf"):
        fig.savefig(Path(output)/f"{name}.{extension}",dpi=170,bbox_inches="tight")
    plt.close(fig)


def publish(output,summary,main,extended,panels):
    output=Path(output)
    plt.rcParams.update({"axes.grid":True,"grid.alpha":.16,"font.size":10})
    members=list(extended["members"].values())
    fig=plt.figure(figsize=(15,8))
    ax=fig.add_subplot(1,3,1,projection="3d")
    ax.add_collection3d(Line3DCollection([[m["start"],m["end"]] for m in members],
        colors=[color(m) for m in members],linewidths=[2.5 if m["ever_buckled"] or m["max_compression_force_ratio"]>=.9 else .55 for m in members]))
    ax.set(xlim=(-20,20),ylim=(-4,4),zlim=(0,40),xlabel="X (m)",ylabel="Y (m)",zlabel="Z (m)",title="All 1528 members")
    ax.set_box_aspect((40,8,40))
    ax.view_init(elev=17,azim=-65)
    plan=[m for m in members if abs(m["z_min"]-33)<1e-6 and abs(m["z_max"]-33)<1e-6]
    for i,limit,title in ((2,20,"z = 33 m horizontal members"),(3,2.3,"Central body: first softening location")):
        ax=fig.add_subplot(1,3,i)
        ax.add_collection(LineCollection([[m["start"][:2],m["end"][:2]] for m in plan],colors=[color(m) for m in plan],
                                         linewidths=[3 if m["ever_buckled"] or m["max_compression_force_ratio"]>=.9 else .7 for m in plan]))
        ax.set(xlim=(-limit,limit),ylim=(-2.4,2.4),xlabel="X (m)",ylabel="Y (m)",title=title)
        ax.set_aspect("equal",adjustable="box")
        for m in plan:
            if m["ever_buckled"] and i==3 or m["max_compression_force_ratio"]>=.9 and not m["ever_buckled"] and i==2:
                x=(m["start"][0]+m["end"][0])/2
                y=(m["start"][1]+m["end"][1])/2
                ax.annotate(str(m["element_tag"]),(x,y),xytext=(0,15 if y>=0 else -18),textcoords="offset points",ha="center",color=color(m),fontsize=11,fontweight="bold")
    legend=[Line2D([0],[0],color=c,lw=3,label=label) for c,label in (
        ("#d83f4b","Historically entered buckling softening"),("#e77716","Not buckled; compression ratio >= 0.9"),
        ("#c8a122","Not buckled; compression ratio 0.5–0.9"),("#a7b7c5","Other members"))]
    fig.legend(handles=legend,loc="lower center",ncol=2,fontsize=9)
    fig.suptitle("Spatial weakness screening | extended PARTIAL path | event history + INITIAL-limit demand",fontsize=15)
    fig.subplots_adjust(top=.9,bottom=.14,wspace=.28)
    save(fig,output,"weakness_locations")

    fig,axes=plt.subplots(1,3,figsize=(15,7))
    env=summary["panel_envelopes"]
    heights=[.5*(r["z_lower"]+r["z_upper"]) for r in env]
    levels=sorted({r["amplitude_drift"] for r in summary["amplitude_envelopes"]})
    for amplitude in levels:
        data=[r for r in summary["amplitude_envelopes"] if r["amplitude_drift"]==amplitude]
        axes[0].plot([r["isdr_y_abs_max"]*100 for r in data],heights,"o-",ms=3,label=f"+/-{amplitude*100:g}% control drift")
    axes[0].set(title="Corrected Y ISDR by amplitude block",xlabel="max |ISDR Y| (%)",ylabel="Panel midpoint height (m)")
    axes[0].legend(fontsize=8)
    for key,label,style in (("raw_y_abs_max","Uncorrected","--"),("isdr_y_abs_max","Mean nodal rotation","-"),
                            ("geometric_isdr_y_abs_max","Vertical-displacement plane fit",":")):
        axes[1].plot([r[key]*100 for r in env],heights,style,marker="o",ms=3,label=label)
    axes[1].set(title="Rotation-estimator sensitivity",xlabel="Full-protocol maximum absolute (%)",ylabel="Panel midpoint height (m)")
    axes[1].legend(fontsize=8)
    axes[2].plot([r["isdr_x_abs_max"]*100 for r in env],heights,"o-",label="X direction (secondary)")
    axes[2].plot([r["isdr_y_abs_max"]*100 for r in env],heights,"o-",label="Y direction (loading)")
    axes[2].set(title="Orthogonal directions",xlabel="max |ISDR| (%)",ylabel="Panel midpoint height (m)")
    axes[2].legend(fontsize=8)
    for ax in axes:
        for s in summary["sections"]:
            ax.axhline(s["height_m"],lw=.5,c="#bbb",alpha=.6)
    fig.suptitle("Luo Eq. 2.2 adapted to quasi-static reversed loading | 11 declared BODY panels",fontsize=15)
    fig.tight_layout(rect=(0,.04,1,.95))
    fig.text(.5,.012,"Rotations measured relative to gravity equilibrium. No transfer of the thesis 2% collapse threshold. Crossarm tips excluded from body section groups.",ha="center",fontsize=8)
    save(fig,output,"isdr_profiles")

    fig,axes=plt.subplots(1,2,figsize=(13,5))
    x=[r["drift_ratio"]*100 for r in main["history"]]
    y=[r["base_shear_N"]/1000 for r in main["history"]]
    axes[0].plot(x,y,lw=1)
    events={e["step"]:e for e in main["events"]}
    for step,event in events.items():
        axes[0].scatter(x[step],y[step],color="#d83f4b",zorder=3)
        tags=[str(e["element_tag"]) for e in main["events"] if e["step"]==step]
        axes[0].annotate("/".join(tags)+f" step {step}",(x[step],y[step]),xytext=(10,-25),textcoords="offset points",fontsize=8)
    axes[0].set(xlabel="Control drift (%)",ylabel="Base shear (kN)",title="First OBSERVED softening events; not exact onset")
    primary=summary["primary_max_isdr_y"]["panel"]
    rr=[r for r in panels if r["panel"]==primary]
    axes[1].plot([r["isdr_y"]*100 for r in rr],[r["base_shear_N"]/1000 for r in rr],lw=1)
    axes[1].set(xlabel=f"Panel {primary} signed corrected Y ISDR (%)",ylabel="WHOLE-TOWER base shear (kN)",
                title="Response linkage (NOT local panel shear capacity)")
    fig.tight_layout()
    save(fig,output,"event_sequence")

    payload=dict(summary=summary,runs={})
    for name,screen in (("bounded",main),("extended",extended)):
        payload["runs"][name]={k:screen[k] for k in ("members","ranking","selected_histories","run")}
    template=Path(__file__).with_name("weakness_viewer.html").read_text(encoding="utf-8")
    (output/"index.html").write_text(template.replace("__PAYLOAD__",json.dumps(payload,ensure_ascii=False,allow_nan=False).replace("</","<\\/")),encoding="utf-8")
