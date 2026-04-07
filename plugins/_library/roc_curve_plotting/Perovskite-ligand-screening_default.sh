# ── SNIPPET: roc_curve_plotting/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        matplotlib
# Tested:      ML/ML_single_model.py
# Invariants:
#   - Uses auc(fpr,tpr) and plots diagonal baseline.
# Notes: Styling is tuned for publication-like output.
# ────────────────────────────────────────────────────────────

def plot_single(x,y,auc,folder='./'):
    plt.style.use('default')
    color_list = [(0.05,0.35,0.75),(0.05,0.8,0.6),(0.9,0.3,0.05),(0.35,0.7,0.9),(0.9,0.5,0.7),(0.9,0.6,0.05),(0.95,0.9,0.25),(0.05,0.05,0.05)]*10
    fig,ax = plt.subplots(1,1,figsize=(7,5))

    ax.plot([0,1],[0,1],'k--',linewidth=3.0)
    ax.plot(x,y,markersize=0,markeredgewidth=0.0,marker='.',linestyle='-',linewidth=3.0,color=color_list[0],label='AUC = {:3.4f}'.format(auc))

    ax.tick_params(axis='both', which='major',labelsize=12,pad=10,direction='out',width=2,length=4)
    ax.tick_params(axis='both', which='minor',labelsize=12,pad=10,direction='out',width=2,length=3)
    ax.tick_params(axis='both', labelsize='24')

    [j.set_linewidth(2) for j in ax.spines.values()]
    ax.set_ylabel('True Positive Rate',fontsize=28,labelpad=10,fontname='Arial')
    ax.set_xlabel('False Positive Rate',fontsize=28,labelpad=10,fontname='Arial')

    ax.set_xlim([-0.05,1.0])
    ax.set_ylim([0.0,1.05])
    ax.grid(True)

    ax.set_yticklabels([ '{:<2.2f}'.format(_) for _ in ax.get_yticks()],fontsize=24,fontname='Arial')
    ax.set_xticklabels([ '{:<2.2f}'.format(_) for _ in ax.get_xticks()],fontsize=24,fontname='Arial')  

    handles, labels = ax.get_legend_handles_labels()
    font = font_manager.FontProperties(family='Arial',
                                   weight='normal',
                                   style='normal', size=24)
    ax.legend(handles, labels, loc='lower right',shadow=True,fancybox=True,frameon=True,prop=font,handlelength=2.5)

    pngname = '{}/ROC.png'.format(folder)
    plt.tight_layout()
    plt.savefig(pngname, dpi=300,bbox_inches='tight',transparent=False)
    plt.close(fig)
