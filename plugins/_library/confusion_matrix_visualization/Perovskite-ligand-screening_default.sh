# ── SNIPPET: confusion_matrix_visualization/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        matplotlib | seaborn
# Tested:      ML/ML_single_model.py
# Invariants:
#   - Percentages are normalized by total sum(cf).
#   - For binary matrices, compute precision/recall/F1 from cf indices.
# Notes: Directly reusable for any binary classifier.
# ────────────────────────────────────────────────────────────

def make_confusion_matrix(cf,
                          group_names=None,
                          categories='auto',
                          count=True,
                          percent=True,
                          cbar=True,
                          xyticks=True,
                          xyplotlabels=True,
                          sum_stats=True,
                          figsize=(4,3),
                          cmap='Blues',
                          title=None,folder='./'):
    blanks = ['' for i in range(cf.size)]

    if group_names and len(group_names)==cf.size:
        group_labels = ["{}\n".format(value) for value in group_names]
    else:
        group_labels = blanks

    if count:
        group_counts = ["{0:0.0f}\n".format(value) for value in cf.flatten()]
    else:
        group_counts = blanks

    if percent:
        group_percentages = ["{0:.2%}".format(value) for value in cf.flatten()/np.sum(cf)]
    else:
        group_percentages = blanks

    box_labels = [f"{v1}{v2}{v3}".strip() for v1, v2, v3 in zip(group_labels,group_counts,group_percentages)]
    box_labels = np.asarray(box_labels).reshape(cf.shape[0],cf.shape[1])

    if sum_stats:
        accuracy  = np.trace(cf) / float(np.sum(cf))
        if len(cf)==2:
            precision = cf[1,1] / sum(cf[:,1])
            recall    = cf[1,1] / sum(cf[1,:])
            f1_score  = 2*precision*recall / (precision + recall)
            stats_text = "\n\nPrecision={:0.3f}\nRecall={:0.3f}\nF1 Score={:0.3f}".format(
                precision,recall,f1_score)
        else:
            stats_text = "\n\nAccuracy={:0.3f}".format(accuracy)
    else:
        stats_text = ""

    if xyticks==False:
        categories=False

    afont = {'fontname':'Arial','fontsize':22}
    plt.figure(figsize=figsize)
    sns.set(font_scale=2) 
    sns.heatmap(cf,annot=box_labels,fmt="",cmap=cmap,cbar=cbar,xticklabels=categories,yticklabels=categories)
    
    if xyplotlabels:
        plt.ylabel('True label',**afont)
        plt.xlabel('Predicted label' + stats_text,**afont)
    else:
        plt.xlabel(stats_text)
    
    if title:
        plt.title(title)
    pngname = '{}/metrics.png'.format(folder)
    plt.tight_layout()
    plt.savefig(pngname, dpi=300,bbox_inches='tight')
    plt.close()    
    
    return
