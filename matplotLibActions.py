import matplotlib.pyplot as plt
import numpy as np
from config import matplotImagePath

def createSGVPlot(sgvs, dates):
    fig, ax = plt.subplots()  # Create a figure containing a single axes.
    ax.plot(dates, sgvs)  # Plot some data on the axes.

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
    plt.savefig(matplotImagePath)