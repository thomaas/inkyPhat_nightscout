import io
import matplotlib.pyplot as plt
import numpy as np


def createSGVPlot(sgvs, dates):
    fig, ax = plt.subplots()
    ax.plot(dates, sgvs)

    aspect_ratio = 212 / 104
    fig.set_size_inches(aspect_ratio * 1.5, 1.5)

    every_nth = 7
    for n, label in enumerate(ax.xaxis.get_ticklabels()):
        if n % every_nth != 0:
            label.set_visible(False)

    ax.spines['right'].set_visible(False)
    ax.spines['top'].set_visible(False)

    ax.set_ylim(ymin=50, ymax=np.max(sgvs) if np.max(sgvs) > 220 else 220)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf
