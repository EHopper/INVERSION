import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from util import define_models
from util import mineos
from util import inversion
from util import partial_derivatives
from util import weights
from util import constraints

def plot_model(model, label, ax):
    depth = np.cumsum(model.thickness)
    for ib in model.boundary_inds:
        ax.axhline(depth[ib], linestyle=':', color='#e0e0e0')
    line, = ax.plot(model.vsv, depth, '-o', markersize=2, label=label)
    ax.set_ylim([depth[-1], 0])
    ax.xaxis.set_label_position('top')
    ax.xaxis.tick_top()
    ax.set(xlabel='Vsv (km/s)', ylabel='Depth (km)')
    ax.legend()

def plot_ph_vel(periods, c, label, ax):
    line = ax.plot(periods, c, '-o', markersize=3, label=label)
    ax.set(xlabel='Period (s)', ylabel='Phase Velocity (km/s)')
    ax.legend()

def plot_rf_data_std(rf_data, std_rf_data, label, ax):
    tt = rf_data[:len(rf_data) // 2].flatten()
    dv = rf_data[len(rf_data) // 2:].flatten() * 100
    std_tt = std_rf_data[:len(rf_data) // 2].flatten()
    std_dv = std_rf_data[len(rf_data) // 2:].flatten() * 100

    ax.errorbar(tt, dv, yerr=std_dv, xerr=std_tt, linestyle='None', ecolor='k')
    ax.plot(tt, dv, 'k.', markersize=5, label=label)
    ax.set(xlabel='RF Travel Time (s)', ylabel='Estimated dVs from RF (%)')
    ax.axhline(0, linestyle=':', color='#e0e0e0')
    #ax.legend()

def plot_rf_data(rf_data, label, ax):
    tt = rf_data[:len(rf_data) // 2].flatten()
    dv = rf_data[len(rf_data) // 2:].flatten() * 100
    ax.plot(tt, dv, '.', markersize=3, label=label)
    ax.set(xlabel='RF Travel Time (s)', ylabel='Estimated dVs from RF (%)')
    #ax.legend()

def make_plot_symmetric_in_y_around_zero(ax):
    yl = max(abs(np.array(ax.get_ylim())))
    ax.set_ylim([-yl, yl])
